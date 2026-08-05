"""대화 흐름 엔진 (상태 머신).

질문 트리는 configs/flow.yaml 에 있고 이 모듈은 그것을 해석만 한다.
Streamlit 에 의존하지 않으므로 UI 를 바꿔도 그대로 재사용된다.

━━ 정보 수집 방식 (기술계획서 4장) ━━━━━━━━━━━━━━━━━━━━━━━━━━━
경로를 고르게 하지 않는다. 매 질문마다 **선택지와 자유 입력을 함께** 제시하고,
사용자가 어느 쪽을 쓰든 같은 슬롯을 채운다.

자유 입력이 들어오면:
  ① 현재 질문의 선택지와 먼저 대조   ← "카페요" 같은 짧은 답. LLM 호출 절약
  ② 실패하면 NLU 로 슬롯 추출         ← 여러 슬롯을 한 번에 채울 수 있다
  ③ 레지스트리에 없는 값은 버린다     ← 환각 방어
  ④ 채워진 질문은 건너뛴다
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import nlu, registry

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
_EMPTY = (None, "", [], {})
_EMOJI = re.compile(r"[^\w가-힣·\s]", re.UNICODE)


@lru_cache(maxsize=None)
def load() -> dict[str, dict]:
    with (CONFIG_DIR / "flow.yaml").open(encoding="utf-8") as f:
        return {n["id"]: n for n in yaml.safe_load(f)}


def steps() -> list[dict]:
    nodes = [n for n in load().values() if not n.get("hidden") and n.get("step")]
    return sorted(nodes, key=lambda n: n["step"])


def start() -> dict[str, Any]:
    return {
        "_node": "root",
        "_history": [],
        "_auto": {},      # 자연어에서 자동으로 채운 슬롯 → 근거 표현
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
        if nd.get("nl_fillable") and nd.get("store") and _filled(state, nd["store"]):
            node_id = nd["next"]
            continue
        return node_id


def _snapshot(state: dict) -> dict:
    return {k: v for k, v in state.items() if k != "_history"}


def advance(state: dict, value: Any, label: str, next_id: str, filled: dict | None = None) -> None:
    """답을 저장하고 다음 질문으로. 되돌아가기용 스냅샷을 함께 남긴다."""
    nd = node(state)
    state["_history"].append(
        {
            "node": state["_node"],
            "ask": ask_text(nd, state),
            "label": label,
            "filled": filled or {},
            "snapshot": _snapshot(state),
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


# ── 자유 입력 처리 ─────────────────────────────────────────────

def _tokens(label: str) -> set[str]:
    core = _EMOJI.sub(" ", label or "").split("베타")[0]
    return {w for w in re.split(r"[\s·]+", core) if len(w) >= 2}


def match_option(nd: dict, text: str) -> dict | None:
    """현재 질문의 선택지와 대조한다. LLM 을 부르기 전에 먼저 시도.

    "카페요" → ☕ 카페·디저트,  "이미지요" → 🖼️ 광고 이미지 만들기

    ⚠️ 선택지들이 공유하는 단어는 판별에 쓸 수 없다.
       "광고 문구 만들기" / "광고 이미지 만들기" 에서 '광고'·'만들기'로는 구분이 안 된다.
       → 여러 선택지에 나오는 토큰은 제외하고, **유일하게 맞는 하나**일 때만 채택한다.
    """
    opts = options(nd)
    if not opts or len(_EMOJI.sub("", text or "").strip()) < 2:
        return None

    token_sets = [_tokens(o["label"]) for o in opts]
    shared = {t for i, a in enumerate(token_sets) for j, b in enumerate(token_sets) if i != j for t in a & b}

    hits = [o for o, ts in zip(opts, token_sets) if any(t in text for t in ts - shared)]
    return hits[0] if len(hits) == 1 else None


_VALIDATORS = {
    "industry": lambda v: any(i["id"] == v for i in registry.industries()),
    "format": lambda v: any(f["id"] == v for f in registry.formats()),
    "style": lambda v: any(s["id"] == v for s in registry.styles()),
    "goal": lambda v: v in ("copy", "image"),
}


def _valid(slot: str, value: Any) -> bool:
    """레지스트리에 없는 값은 버린다 — LLM 환각 방어."""
    check = _VALIDATORS.get(slot)
    return check(value) if check else bool(value)


def submit_free_text(state: dict, text: str) -> dict:
    """자유 입력 한 건을 처리한다.

    Returns:
        {"kind": "option", "label": ...}  현재 질문에 답한 것으로 처리
        {"kind": "nlu", "filled": {...}}  슬롯을 채움 (여러 개 가능)
        {"kind": "none"}                  아무것도 못 알아들음
    """
    nd = node(state)

    # ① 선택지 먼저 — LLM 호출 절약
    opt = match_option(nd, text)
    if opt:
        advance(state, opt["value"], opt["label"], opt["next"])
        return {"kind": "option", "label": opt["label"]}

    # ② NLU → ③ 검증
    slots = {k: s for k, s in nlu.extract(text).items() if _valid(k, s.value)}
    if not slots:
        return {"kind": "none"}

    state["_history"].append(
        {
            "node": state["_node"],
            "ask": ask_text(nd, state),
            "label": text,
            "filled": {k: (s.value, s.evidence) for k, s in slots.items()},
            "snapshot": _snapshot(state),
        }
    )
    for name, slot in slots.items():
        state[name] = slot.value
        state["_auto"][name] = slot.evidence

    # ④ 채워진 질문은 건너뛴다 (현재 노드부터 다시 해석)
    state["_node"] = _resolve(state["_node"], state)
    return {"kind": "nlu", "filled": slots}


def missing_slots(state: dict) -> list[str]:
    """아직 비어 있는 필수 슬롯."""
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
    """현재 갈래에서 실제로 거치는 단계만."""
    goal = state.get("goal")
    return [s for s in steps() if not s.get("only") or not goal or s["only"] == goal]


def progress(state: dict) -> tuple[int, int]:
    visible = visible_steps(state)
    auto = {s["id"] for s in visible if s.get("store") in state["_auto"]}
    done = len({h["node"] for h in state["_history"]} | auto)
    total = len(visible)
    return min(done, total), total
