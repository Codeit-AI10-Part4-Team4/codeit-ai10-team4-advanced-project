"""대화 흐름 엔진 (상태 머신).

질문 트리는 configs/flow.yaml 에 있고 이 모듈은 그것을 해석만 한다.
Streamlit 에 의존하지 않으므로 UI 를 바꿔도 그대로 재사용된다.

입구가 두 개다.
  ① 자연어  — nlu 가 뽑아낸 슬롯은 질문을 건너뛴다
  ② 선택형  — 처음부터 하나씩 묻는다
어느 쪽이든 채우는 슬롯은 같으므로, 뒤쪽 로직은 완전히 공유된다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import nlu, registry

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
_EMPTY = (None, "", [], {})


@lru_cache(maxsize=None)
def load() -> dict[str, dict]:
    with (CONFIG_DIR / "flow.yaml").open(encoding="utf-8") as f:
        return {n["id"]: n for n in yaml.safe_load(f)}


def steps() -> list[dict]:
    nodes = [n for n in load().values() if not n.get("hidden") and n.get("step")]
    return sorted(nodes, key=lambda n: n["step"])


def start() -> dict[str, Any]:
    return {
        "_node": "welcome",
        "_history": [],
        "_auto": {},      # 자연어에서 자동으로 채운 슬롯 → 근거 표현
        "entry": None,    # nl | guided
        "photo": None,
        "reference": None,
        "product": "",
        "items": [],
        "with_text": True,
    }


def node(state: dict) -> dict:
    return load()[state["_node"]]


def ask_text(nd: dict, state: dict) -> str:
    ask = nd.get("ask", "")
    if isinstance(ask, dict):
        return ask.get(state.get("goal"), ask.get("_default", ""))
    return ask


def _registry_label(item: dict) -> str:
    beta = "  ·  베타" if item.get("status") == "beta" else ""
    return f"{item.get('emoji', '')} {item['label']}{beta}"


def options(nd: dict) -> list[dict]:
    """선택지. source 가 있으면 레지스트리에서 자동 생성한다.

    → 업종을 추가해도 flow.yaml 을 고칠 필요가 없다.
    """
    if nd.get("source"):
        items = getattr(registry, nd["source"])()
        return [
            {"label": _registry_label(i), "value": i["id"], "next": nd["next"]} for i in items
        ]
    return nd.get("options", [])


def _filled(state: dict, key: str) -> bool:
    return state.get(key) not in _EMPTY


def _resolve(node_id: str, state: dict) -> str:
    """route 를 따라가고, 이미 채워진 슬롯의 질문은 건너뛴다."""
    flow = load()
    while True:
        nd = flow[node_id]
        if nd.get("kind") == "route":
            for rule in nd["route"]:
                when = rule.get("when")
                if when is None or all(state.get(k) == v for k, v in when.items()):
                    node_id = rule["then"]
                    break
            continue
        # 자연어에서 이미 알아낸 항목은 다시 묻지 않는다
        if nd.get("nl_fillable") and nd.get("store") and _filled(state, nd["store"]):
            node_id = nd["next"]
            continue
        return node_id


def advance(state: dict, value: Any, label: str, next_id: str) -> None:
    """답을 저장하고 다음 질문으로. 되돌아가기용 스냅샷을 함께 남긴다."""
    nd = node(state)
    state["_history"].append(
        {
            "node": state["_node"],
            "ask": ask_text(nd, state),
            "label": label,
            "snapshot": {k: v for k, v in state.items() if k != "_history"},
        }
    )
    if nd.get("store"):
        state[nd["store"]] = value
    state["_node"] = _resolve(next_id, state)


def rewind(state: dict, index: int) -> dict:
    entry = state["_history"][index]
    restored = dict(entry["snapshot"])
    restored["_history"] = state["_history"][:index]
    return restored


# ── 자연어 입구 ────────────────────────────────────────────────

def apply_nlu(state: dict, text: str) -> dict[str, nlu.Slot]:
    """자연어에서 슬롯을 뽑아 상태에 채운다. 못 알아들은 것은 비워둔다."""
    slots = nlu.extract(text)
    state["entry"] = "nl"
    state["_utterance"] = text
    for name, slot in slots.items():
        state[name] = slot.value
        state["_auto"][name] = slot.evidence
    return slots


def clear_auto(state: dict) -> None:
    """자동 인식 결과를 버리고 처음부터 물어본다."""
    for name in list(state["_auto"]):
        state[name] = "" if name == "product" else None
    state["_auto"] = {}


def missing_slots(state: dict) -> list[str]:
    """자연어로 채우지 못해 되물어야 하는 항목."""
    return [
        nd["store"]
        for nd in steps()
        if nd.get("nl_fillable") and nd.get("store") and not _filled(state, nd["store"])
    ]


# ── 데모용 보조 ────────────────────────────────────────────────

MODES = {
    (True, True): ("preserve_ref", "제품 보존 + 레퍼런스 분위기", "SDXL Inpainting + IP-Adapter"),
    (True, False): ("preserve", "제품 보존 — 배경·조명만 교체", "SDXL Inpainting"),
    (False, True): ("reference", "레퍼런스 기반 배경 생성", "SDXL + IP-Adapter"),
    (False, False): ("scene", "텍스트만으로 배경 생성", "SDXL text-to-image"),
}


def resolved_mode(state: dict) -> tuple[str, str, str] | None:
    """사진·레퍼런스 답변이 끝나면 확정되는 생성 모드.

    사용자는 모드를 고르지 않는다. 무엇을 올렸는지로 자동 결정된다.
    """
    if state.get("goal") != "image":
        return None
    if "has_photo" not in state or "has_reference" not in state:
        return None
    return MODES[(bool(state["has_photo"]), bool(state["has_reference"]))]


def visible_steps(state: dict) -> list[dict]:
    """현재 갈래·입구에서 실제로 거치는 단계만."""
    goal, entry = state.get("goal"), state.get("entry")
    out = []
    for s in steps():
        if s.get("only") and goal and s["only"] != goal:
            continue
        if s.get("only_path") and entry and s["only_path"] != entry:
            continue
        out.append(s)
    return out


def progress(state: dict) -> tuple[int, int]:
    visible = visible_steps(state)
    auto = {s["id"] for s in visible if s.get("store") in state["_auto"]}
    done = len({h["node"] for h in state["_history"]} | auto)
    total = len(visible)
    return min(done, total), total
