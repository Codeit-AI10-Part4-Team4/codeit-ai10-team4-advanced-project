"""동네 매장 광고 만들기 — 챗봇 흐름 설계 데모.

⚠️ **동작하는 서비스가 아니라 설계를 보여주는 데모**입니다.
   실제 이미지 생성은 하지 않습니다.

보여주려는 것 (기술계획서 4장):
  1. 경로를 고르게 하지 않는다 — 매 질문에 **선택지 + 자유 입력이 함께** 있다
  2. 자유 입력은 아무 슬롯이나 채우고, 채워진 질문은 건너뛴다
  3. 무엇을 알아들었는지 **근거와 함께** 보여준다
  4. 사진 × 레퍼런스 조합으로 생성 모드가 자동 결정된다
  5. 두 갈래(문구·이미지)가 끝에서 다시 합류한다

실행: streamlit run app_chat.py
"""

from __future__ import annotations

import io

import streamlit as st
from PIL import Image

from src import compliance, copy_gen, flow, nlu, registry

st.set_page_config(page_title="광고 만들기 — 흐름 설계 데모", page_icon="💬", layout="wide")

TREE = """
                        ┌───────────────────┐
                        │ ① 무엇을 만들까?   │ ★분기
                        └────┬─────────┬────┘
                     📝 문구 │         │ 🖼️ 이미지
                   ┌─────────▼──┐ ┌────▼───────────┐
                   │ ② 어떤 가게?│ │ ② 어떤 가게?    │
                   ├────────────┤ ├────────────────┤
                   │ ③ 제품 사진?│ │ ③ 제품 사진?    │ ★분기
                   └─────────┬──┘ ├────────────────┤
                             │    │ ④ 참고 이미지?  │ ★분기
                             │    │   → 생성 모드 확정│
                             │    └────┬───────────┘
                   ┌─────────▼──┐ ┌────▼───────────┐
                   │ ⑤ 무엇을 홍보│ │ ⑤ 무엇을 홍보   │
                   │ ⑥ 어디에 쓸까│ │ ⑥ 어디에 쓸까   │
                   │ ⑦ 어떤 느낌 │ │ ⑦ 어떤 느낌     │
                   └─────────┬──┘ ├────────────────┤
                             │    │ ⑧ 글자도 넣을까?│ ★분기
                             │    └──┬──────────┬──┘
                             │  글자넣기│        │이미지만
                   ┌─────────▼────────▼──┐      │
                   │ ⑨ 가격·조건  ⇄ 합류  │      │
                   └──────────┬──────────┘      │
                              └────────┬────────┘
                                  ┌────▼────┐
                                  │  결과   │
                                  └─────────┘

  ※ 모든 질문에서 선택지를 누르거나, 아래 입력창에 말로 하거나 — 둘 다 됩니다.
    한 문장에 여러 개를 말하면 해당 질문들을 건너뜁니다.
"""


def _init() -> dict:
    if "chat_state" not in st.session_state:
        st.session_state.chat_state = flow.start()
    return st.session_state.chat_state


def _go(value, label: str, next_id: str) -> None:
    flow.advance(st.session_state.chat_state, value, label, next_id)
    st.rerun()


def _summary(filled: dict) -> str:
    """자연어에서 채운 슬롯을 한 줄로."""
    parts = []
    for slot, val in filled.items():
        value = val[0] if isinstance(val, tuple) else val.value
        parts.append(nlu.describe(slot, value))
    return " · ".join(parts)


state = _init()

# ──────────────────────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🌳 진행 상황")

    done_nodes = {h["node"] for h in state["_history"]}
    answers = {h["node"]: h["label"] for h in state["_history"]}
    current, goal, auto = state["_node"], state.get("goal"), state["_auto"]

    for s in flow.steps():
        store = s.get("store")
        skipped = s.get("only") and goal and s["only"] != goal

        if store and store in auto:
            st.markdown(f"✨ ~~{s['step']}. {s['short']}~~")
            st.caption(f"　　→ {nlu.describe(store, state[store])}")
            st.caption(f"　　💬 “{auto[store]}” 에서")
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
        if s["id"] in answers and s["id"] not in (current,):
            st.caption(f"　　→ {answers[s['id']]}")

    if auto:
        st.info(f"💬 말씀으로 **{len(auto)}개 질문**을 건너뛰었습니다.")

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
    "선택지를 누르셔도 되고, 아래 입력창에 말로 하셔도 됩니다."
)

with st.expander("🌳 전체 분기 구조 한눈에 보기", expanded=not state["_history"]):
    st.code(TREE, language="text")
    st.markdown(
        "- **경로를 고르게 하지 않습니다.** 매 질문에 선택지와 자유 입력이 함께 있습니다.\n"
        "- 선택지는 **힌트** 역할을 합니다 — 뭘 물어보는지 보고 말로 풀어 쓸 수 있습니다.\n"
        "- **★분기** — 답에 따라 이후 경로가 갈라지는 질문\n"
        "- **⇄합류** — 문구 갈래와 이미지 갈래가 다시 만나는 지점\n"
        "- 질문 순서는 코드가 아니라 `configs/flow.yaml` 에 있어 "
        "순서 변경·질문 추가가 YAML 수정만으로 됩니다."
    )

done, total = flow.progress(state)
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
        if h.get("filled"):
            st.caption(f"✅ {_summary(h['filled'])} — 이렇게 이해했어요")

# ── 현재 질문 ─────────────────────────────────────────────────

nd = flow.node(state)
kind = nd.get("kind")

if kind != "result":
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
            st.caption(f"💬 아래 입력창에 적어주세요 — {nd.get('placeholder', '')}")

        elif kind == "items":
            rows = st.data_editor(
                [{"항목": "", "가격/조건": ""}],
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"it_{nd['id']}",
            )
            filled_rows = [r for r in rows if r.get("항목")]
            c1, c2 = st.columns(2)
            if c1.button("다음 →", key=f"next_{nd['id']}", type="primary"):
                label = " · ".join(f"{r['항목']} {r['가격/조건']}" for r in filled_rows) or "입력함"
                _go(filled_rows, label, nd["next"])
            if c2.button("없어요", key=f"skip_{nd['id']}"):
                _go([], "없어요", nd["next"])

    # ── 자유 입력 — 항상 열려 있다 ────────────────────────────
    if text := st.chat_input("말로 하셔도 돼요.  예: 카페 크로플 인스타 사진 감성적으로"):
        res = flow.submit_free_text(st.session_state.chat_state, text)

        if res["kind"] != "none":
            st.rerun()
        elif kind == "text":
            # 이 질문은 입력 자체가 답이다 (상품명 등)
            _go(text, text, nd["next"])
        else:
            # 못 알아들었을 때는 rerun 하지 않고 그 자리에서 알린다
            st.warning(
                f"“{text}” 를 잘 못 알아들었어요. "
                "위 선택지에서 골라주시거나 다시 말씀해 주세요."
            )
            st.caption("ℹ️ 지금은 키워드 매칭 스텁입니다. LLM 을 붙이면 훨씬 잘 알아듣습니다.")

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
