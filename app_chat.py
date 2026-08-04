"""동네 매장 광고 만들기 — 챗봇 흐름 설계 데모.

⚠️ **동작하는 서비스가 아니라 설계를 보여주는 데모**입니다.
   실제 이미지 생성은 하지 않습니다. "이런 흐름으로 만들려는데 어떠세요?"를
   팀원에게 보여주는 것이 목적입니다.

보여주려는 것:
  1. 자연어로 말하는 것이 기본 동선, 선택형은 보조 경로
  2. 말에서 알아들은 항목은 건너뛰고 **모자란 것만 되묻는다**
  3. 각 질문이 무엇을 결정하는지
  4. 사진 × 레퍼런스 조합으로 생성 모드 4가지가 자동 결정된다
  5. 두 갈래가 끝에서 다시 합류한다

실행: streamlit run app_chat.py
"""

from __future__ import annotations

import io

import streamlit as st
from PIL import Image

from src import compliance, copy_gen, flow, nlu, registry

st.set_page_config(page_title="광고 만들기 — 흐름 설계 데모", page_icon="💬", layout="wide")

TREE = """
              ┌──────────────────────────────────────┐
              │  ① 어떻게 시작할까?          ★분기    │
              └────────┬────────────────────┬────────┘
            💬 말로 하기 (기본)       🔘 골라서 만들기 (보조)
              ┌────────▼────────┐            │
              │ ② 이해한 내용    │            │
              │    확인          │            │   말로 설명하기
              │  알아들은 항목은  │            │   어려운 분을 위한
              │  질문을 건너뜀 ✨ │            │   경로
              └────────┬────────┘            │
                       └──────────┬──────────┘
                        ┌─────────▼─────────┐
                        │ ③ 무엇을 만들까?   │ ★분기
                        └────┬─────────┬────┘
                     📝 문구 │         │ 🖼️ 이미지
                   ┌─────────▼──┐ ┌────▼───────────┐
                   │ ④ 어떤 가게?│ │ ④ 어떤 가게?    │
                   ├────────────┤ ├────────────────┤
                   │ ⑤ 제품 사진?│ │ ⑤ 제품 사진?    │ ★분기
                   └─────────┬──┘ ├────────────────┤
                             │    │ ⑥ 참고 이미지?  │ ★분기
                             │    │   → 생성 모드 확정│
                             │    └────┬───────────┘
                   ┌─────────▼──┐ ┌────▼───────────┐
                   │ ⑦ 무엇을 홍보│ │ ⑦ 무엇을 홍보   │
                   │ ⑧ 어디에 쓸까│ │ ⑧ 어디에 쓸까   │
                   │ ⑨ 어떤 느낌 │ │ ⑨ 어떤 느낌     │
                   └─────────┬──┘ ├────────────────┤
                             │    │ ⑩ 글자도 넣을까?│ ★분기
                             │    └──┬──────────┬──┘
                             │  글자넣기│        │이미지만
                   ┌─────────▼────────▼──┐      │
                   │ ⑪ 가격·조건  ⇄ 합류  │      │
                   └──────────┬──────────┘      │
                              └────────┬────────┘
                                  ┌────▼────┐
                                  │  결과   │
                                  └─────────┘
"""


def _init() -> dict:
    if "chat_state" not in st.session_state:
        st.session_state.chat_state = flow.start()
    return st.session_state.chat_state


def _go(value, label: str, next_id: str) -> None:
    flow.advance(st.session_state.chat_state, value, label, next_id)
    st.rerun()


state = _init()

# ──────────────────────────────────────────────────────────────
# 사이드바 — 분기와 자동 인식이 눈에 보이게
# ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🌳 진행 상황")

    done_nodes = {h["node"] for h in state["_history"]}
    answers = {h["node"]: h["label"] for h in state["_history"]}
    current, goal, entry = state["_node"], state.get("goal"), state.get("entry")
    auto = state["_auto"]

    for s in flow.steps():
        store = s.get("store")
        skipped = (s.get("only") and goal and s["only"] != goal) or (
            s.get("only_path") and entry and s["only_path"] != entry
        )

        if store and store in auto:
            st.markdown(f"✨ ~~{s['step']}. {s['short']}~~")
            st.caption(f"　　→ {nlu.describe(store, state[store])}")
            st.caption(f"　　💬 “{auto[store]}” 에서 자동 인식")
            continue

        if s["id"] in done_nodes:
            icon, wrap = "✅", ""
        elif s["id"] == current:
            icon, wrap = "▶️", "**"
        elif skipped:
            icon, wrap = "⤫", "~~"
        else:
            icon, wrap = "⬜", ""

        mark = " `★분기`" if s.get("branch") else (" `⇄합류`" if s.get("merge") else "")
        st.markdown(f"{icon} {wrap}{s['step']}. {s['short']}{wrap}{mark}")
        if s["id"] in answers:
            st.caption(f"　　→ {answers[s['id']]}")

    if auto:
        st.info(f"💬 말씀 한 번으로 **{len(auto)}개 질문**을 건너뛰었습니다.")

    st.divider()
    mode = flow.resolved_mode(state)
    if mode:
        st.markdown("### 🎯 확정된 생성 모드")
        st.success(f"**`{mode[0]}`**\n\n{mode[1]}")
        st.caption(f"붙일 모델: {mode[2]}")
        st.caption("사용자는 모드를 고르지 않습니다. 무엇을 올렸는지로 자동 결정됩니다.")

    st.divider()
    if st.button("🔄 처음부터", width="stretch"):
        st.session_state.chat_state = flow.start()
        st.rerun()

# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────

st.title("💬 광고 만들기 — 챗봇 흐름 설계")
st.caption(
    "**설계를 보여주는 데모입니다.** 실제 이미지 생성은 하지 않습니다. "
    "질문 흐름과 분기 구조를 확인해 주세요."
)

with st.expander("🌳 전체 분기 구조 한눈에 보기", expanded=not state["_history"]):
    st.code(TREE, language="text")
    st.markdown(
        "- **💬 말로 하기가 기본 동선**입니다. 말에서 알아들은 항목(✨)은 질문을 건너뜁니다.\n"
        "- **🔘 골라서 만들기**는 말로 설명하기 어려운 분을 위한 보조 경로입니다. "
        "어느 쪽으로 들어와도 **채우는 항목은 같습니다.**\n"
        "- **★분기** — 답에 따라 이후 경로가 갈라지는 질문\n"
        "- **⇄합류** — 문구 갈래와 이미지 갈래가 다시 만나는 지점\n"
        "- 질문 순서는 코드가 아니라 `configs/flow.yaml` 에 있어 "
        "순서 변경·질문 추가가 YAML 수정만으로 됩니다."
    )

done, total = flow.progress(state)
if state.get("entry"):
    st.progress(done / total, text=f"{done} / {total} 단계")

st.divider()

# ── 지나온 대화 ────────────────────────────────────────────────

for i, h in enumerate(state["_history"]):
    with st.chat_message("assistant"):
        st.markdown(h["ask"])
    with st.chat_message("user"):
        c1, c2 = st.columns([0.75, 0.25])
        c1.markdown(f"**{h['label']}**")
        if c2.button("✏️ 수정", key=f"rw_{i}", width="stretch"):
            st.session_state.chat_state = flow.rewind(st.session_state.chat_state, i)
            st.rerun()

# ── 현재 질문 ─────────────────────────────────────────────────

nd = flow.node(state)
kind = nd.get("kind")

if kind == "nl_entry":
    with st.chat_message("assistant"):
        st.markdown(flow.ask_text(nd, state))
        text = st.text_area(
            "말씀해 주세요", placeholder=nd.get("placeholder", ""), height=90, key="nl_text"
        )
        c1, c2 = st.columns([0.5, 0.5])
        if c1.button("💬 이렇게 만들어줘", type="primary", width="stretch", disabled=not text):
            flow.apply_nlu(st.session_state.chat_state, text)
            flow.advance(st.session_state.chat_state, text, f"“{text}”", nd["next"])
            st.rerun()
        if c2.button(nd["fallback_label"], width="stretch"):
            st.session_state.chat_state["entry"] = "guided"
            flow.advance(st.session_state.chat_state, None, "골라서 만들기", nd["fallback"])
            st.rerun()
        st.caption(
            "🔧 이 답이 결정하는 것 — " + nd["decides"] + "  \n"
            "ℹ️ 지금은 키워드 매칭 스텁입니다. LLM 을 붙이면 이 자리가 교체됩니다."
        )

elif kind == "confirm":
    with st.chat_message("assistant"):
        st.markdown(flow.ask_text(nd, state))

        got = state["_auto"]
        if got:
            for slot, evidence in got.items():
                st.markdown(
                    f"✅ **{nlu.LABELS[slot]}** — {nlu.describe(slot, state[slot])}　"
                    f"<small style='color:#888'>“{evidence}” 에서</small>",
                    unsafe_allow_html=True,
                )
        else:
            st.warning("말씀에서 알아들은 항목이 없어요. 하나씩 여쭤볼게요.")

        missing = flow.missing_slots(state)
        if missing:
            st.caption(
                "❓ 아직 모르는 것 — "
                + ", ".join(nlu.LABELS[m] for m in missing)
                + " · 이건 이따 여쭤볼게요"
            )

        c1, c2 = st.columns(2)
        if c1.button("👍 네, 맞아요", type="primary", width="stretch"):
            _go(None, "네, 맞아요", nd["next"])
        if c2.button("🔘 아니요, 골라서 할게요", width="stretch"):
            flow.clear_auto(st.session_state.chat_state)
            st.session_state.chat_state["entry"] = "guided"
            flow.advance(st.session_state.chat_state, None, "골라서 할게요", nd["next"])
            st.rerun()

elif kind != "result":
    with st.chat_message("assistant"):
        st.markdown(flow.ask_text(nd, state))
        if nd.get("decides"):
            st.caption(f"🔧 이 답이 결정하는 것 — {nd['decides']}")
        if nd.get("note"):
            st.caption(f"ℹ️ {nd['note']}")

        if kind == "choice":
            opts = flow.options(nd)
            cols = st.columns(min(len(opts), 4))
            for j, opt in enumerate(opts):
                if cols[j % len(cols)].button(
                    opt["label"], key=f"opt_{nd['id']}_{j}", width="stretch"
                ):
                    _go(opt["value"], opt["label"], opt["next"])

        elif kind == "upload":
            up = st.file_uploader(
                "이미지 선택", type=["jpg", "jpeg", "png", "webp"], key=f"up_{nd['id']}"
            )
            img = Image.open(io.BytesIO(up.read())) if up else None
            if img:
                st.image(img, width=220)
            if st.button("다음 →", key=f"next_{nd['id']}", type="primary"):
                _go(img, "사진 첨부함" if img else "(데모 — 첨부 생략)", nd["next"])

        elif kind == "text":
            val = st.text_input("입력", placeholder=nd.get("placeholder", ""), key=f"tx_{nd['id']}")
            if st.button("다음 →", key=f"next_{nd['id']}", type="primary", disabled=not val):
                _go(val, val, nd["next"])

        elif kind == "items":
            rows = st.data_editor(
                [{"항목": "", "가격/조건": ""}],
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"it_{nd['id']}",
            )
            filled = [r for r in rows if r.get("항목")]
            c1, c2 = st.columns(2)
            if c1.button("다음 →", key=f"next_{nd['id']}", type="primary"):
                label = " · ".join(f"{r['항목']} {r['가격/조건']}" for r in filled) or "입력함"
                _go(filled, label, nd["next"])
            if c2.button("없어요", key=f"skip_{nd['id']}"):
                _go([], "없어요", nd["next"])

# ── 결과 (목업) ────────────────────────────────────────────────

else:
    industry = registry.by_id(registry.industries(), state["industry"])
    fmt = registry.by_id(registry.formats(), state["format"])
    style = registry.by_id(registry.styles(), state["style"])
    tags = registry.legal_tags_for(industry, fmt)

    with st.chat_message("assistant"):
        st.markdown("다 됐습니다! 이런 광고를 만들어 드릴게요 👇")

    st.info(
        "아래는 **실제 생성 결과가 아니라 목업**입니다. "
        "모델을 붙이면 이 자리에 진짜 결과가 들어갑니다."
    )

    left, right = st.columns([0.55, 0.45], gap="large")

    with left:
        st.markdown("#### 🖼️ 이미지")
        if state.get("goal") == "image":
            mode = flow.resolved_mode(state)
            w, h = fmt["size"]
            st.markdown(
                f"""
<div style="border:2px dashed #999;border-radius:12px;padding:48px 16px;
text-align:center;color:#888;line-height:1.9">
<div style="font-size:42px">🖼️</div>
<b>{fmt['label']}</b> · {w}×{h}px<br>
배치 <code>{fmt['layout']}</code><br>
생성 모드 <code>{mode[0] if mode else '-'}</code><br>
<small>{mode[2] if mode else ''}</small>
</div>""",
                unsafe_allow_html=True,
            )
            if not state.get("with_text", True):
                st.caption("글자 없이 이미지만 — 문구 갈래로 합류하지 않았습니다.")
        else:
            st.caption("문구 갈래로 시작하셨습니다. 이미지는 만들지 않습니다.")

    with right:
        st.markdown("#### 📝 문구 3안")
        st.caption("현재는 템플릿 스텁입니다. LLM 을 붙이면 여기가 교체됩니다.")
        if state.get("goal") == "copy" or state.get("with_text", True):
            for i, c in enumerate(
                copy_gen.generate(state.get("product", ""), industry, style, fmt, tags), 1
            ):
                with st.container(border=True):
                    st.markdown(f"**{i}안 · {c.headline}**")
                    st.caption(c.sub)
                    st.caption(" ".join(c.hashtags))
        else:
            st.caption("이미지만 요청하셔서 문구는 만들지 않았습니다.")

    st.divider()
    st.markdown("#### ⚖️ 이 광고에 적용되는 규정")
    st.caption(
        f"업종(`{industry['id']}`) × 규격(`{fmt['id']}`) 조합으로 자동 판별됩니다. "
        "— 규격을 바꾸면 적용 법령도 바뀝니다."
    )
    for law in compliance.applicable_laws(tags):
        st.markdown(f"- **{law['name']}** `{law['article']}` — {law['applies_when']}")

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.button("🔁 다시 만들기 (다른 안)", width="stretch", disabled=True)
    c2.button("⬇️ 다운로드", width="stretch", disabled=True)
    if state.get("goal") == "copy":
        if c3.button("🖼️ 이미지에도 얹어보기", width="stretch"):
            st.session_state.chat_state["goal"] = "image"
            st.rerun()
    else:
        c3.button("✏️ 문구 수정", width="stretch", disabled=True)
    st.caption("비활성 버튼은 실제 기능 연결 전 자리표시입니다.")
