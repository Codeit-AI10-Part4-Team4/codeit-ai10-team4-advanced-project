"""동네 매장 광고 만들기 — Streamlit 프로토타입.

기능 범위를 눈으로 확인하기 위한 클릭 가능한 프로토타입.

  실제 동작  레이아웃 합성(PIL) · 금칙어 룰 엔진 · 적용 법령 패널 · 레지스트리
  스텁      이미지 생성(색보정) · 문구 생성(템플릿)
            → src/image_gen.py, src/copy_gen.py 의 '교체할 지점' 주석 참조

실행: streamlit run app.py
"""

from __future__ import annotations

import io

import streamlit as st
from PIL import Image

from src import compliance, copy_gen, image_gen, layout, registry

st.set_page_config(page_title="동네 매장 광고 만들기", page_icon="🏪", layout="wide")

INDUSTRIES = registry.industries()
STYLES = registry.styles()
FORMATS = registry.formats()


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _label(item: dict, beta: bool = False) -> str:
    tag = "  🅑 베타" if beta and item.get("status") == "beta" else ""
    return f"{item.get('emoji', '')} {item['label']}{tag}"


def _render(bg: Image.Image, fmt: dict, style: dict, headline: str, sub: str) -> Image.Image:
    return layout.render(
        bg, fmt, style, headline, sub,
        items=st.session_state.get("items", []),
        badge=st.session_state.get("badge", ""),
    )


def _replace_term(field_key: str, start: int, end: int, alt: str) -> None:
    """금칙 표현 원클릭 교체. 콜백에서 실행돼 위젯 값 갱신이 안전하다.

    레이아웃 단계가 분리돼 있어 GPU 재실행 없이 즉시 반영된다.
    """
    cur = st.session_state.get(field_key, "")
    st.session_state[field_key] = cur[:start] + alt + cur[end:]


def _findings_block(field_key: str, field_label: str, text: str, tags: set[str]) -> list:
    findings = compliance.scan(text, tags)
    for i, f in enumerate(findings):
        icon = {"high": "🚫", "medium": "⚠️", "info": "ℹ️"}[f.severity]
        with st.container(border=True):
            st.markdown(
                f"{icon} **{f.label}** · `{f.matched}` — {field_label}  \n"
                f"<small>{f.law_name} {f.law_article} · {f.severity_label}</small>",
                unsafe_allow_html=True,
            )
            st.caption(f.reason)
            if f.alternatives:
                cols = st.columns(len(f.alternatives))
                for c, alt in zip(cols, f.alternatives):
                    c.button(
                        f"→ {alt}",
                        key=f"fix_{field_key}_{i}_{alt}",
                        on_click=_replace_term,
                        args=(field_key, f.start, f.end, alt),
                        use_container_width=True,
                    )
    return findings


# ──────────────────────────────────────────────────────────────
# 좌측 — 입력
# ──────────────────────────────────────────────────────────────

st.title("🏪 동네 매장 광고 만들기")
st.caption("사진 한 장으로 바로 쓸 수 있는 광고물을 만듭니다 · 프로토타입")

left, right = st.columns([0.36, 0.64], gap="large")

with left:
    st.subheader("1. 우리 가게")
    industry = st.selectbox(
        "업종", INDUSTRIES, format_func=lambda x: _label(x, beta=True),
        help="업종에 따라 배경 프롬프트·문구 톤·적용 법령이 달라집니다",
    )
    if industry.get("status") == "beta":
        st.caption("🅑 베타 — 결과 품질을 아직 검증하지 못한 업종입니다.")

    st.subheader("2. 사진")
    no_photo = st.checkbox(
        "사진이 없어요 (배경만 만들기)",
        value=not industry.get("needs_photo", True),
        help="학원·공부방처럼 쓸 사진이 없을 때. 제품을 사칭하지 않는 배경만 생성합니다.",
    )
    photo = None
    if not no_photo:
        up = st.file_uploader("제품 사진", type=["jpg", "jpeg", "png", "webp"])
        if up:
            photo = Image.open(io.BytesIO(up.read()))
            st.image(photo, caption="원본 — 이 제품은 그대로 보존됩니다", use_container_width=True)
        else:
            st.info("사진을 올리면 제품은 그대로 두고 배경·조명만 바꿉니다.")

    reference = None
    with st.expander("🎨 레퍼런스 이미지 (선택)"):
        st.caption("“이런 느낌으로 만들어주세요” — 분위기·색조만 가져옵니다. 제품은 위 사진 그대로입니다.")
        ref_up = st.file_uploader("레퍼런스", type=["jpg", "jpeg", "png", "webp"], key="ref")
        if ref_up:
            reference = Image.open(io.BytesIO(ref_up.read()))
            st.image(reference, use_container_width=True)

    mode = image_gen.resolve_mode(photo, reference)
    st.caption(f"▸ **{image_gen.MODE_LABEL[mode]}**")

    st.subheader("3. 어디에 쓸 건가요")
    fmt = st.selectbox("규격", FORMATS, format_func=_label)
    st.caption(f"{fmt['size'][0]}×{fmt['size'][1]}px · 배치 `{fmt['layout']}`")

    style = st.radio(
        "스타일", STYLES, format_func=_label, horizontal=True,
        help="색감과 문구 어조가 함께 바뀝니다",
    )

    st.subheader("4. 내용")
    product = st.text_input(
        "상품명", placeholder="예: 크로플, 삼겹살, 여름 특강",
        help="VLM 을 붙이면 사진에서 자동으로 채워집니다 (현재는 직접 입력)",
    )
    badge = st.text_input("뱃지 (선택)", placeholder="예: 오늘의 특가", key="badge")

    st.markdown("**가격·조건**")
    st.caption("AI 가 지어내면 안 되는 정보라 직접 입력받습니다.")
    items = st.data_editor(
        st.session_state.get("items") or [{"name": "", "price": ""}],
        column_config={
            "name": st.column_config.TextColumn("항목", width="medium"),
            "price": st.column_config.TextColumn("가격/조건", width="small"),
        },
        num_rows="dynamic", hide_index=True, use_container_width=True, key="items_editor",
    )
    st.session_state["items"] = [dict(i) for i in items]

    with st.expander("⚙️ 고급 — 직접 요청하기"):
        st.caption("비워두셔도 됩니다. 업종·스타일만으로 알아서 만듭니다.")
        request = st.text_input("이미지 요청사항", placeholder="예: 나무 테이블 위에, 창가 햇빛")

    go = st.button("✨ 광고 만들기", type="primary", use_container_width=True)

tags = registry.legal_tags_for(industry, fmt)

# ──────────────────────────────────────────────────────────────
# 생성
# ──────────────────────────────────────────────────────────────

if go:
    cands = copy_gen.generate(product, industry, style, fmt, tags, n=3)
    st.session_state["results"] = [
        {
            "bg": image_gen.generate(
                photo, industry, style, tuple(fmt["size"]), seed=i, reference=reference
            ),
            "cand": c,
        }
        for i, c in enumerate(cands)
    ]
    st.session_state["ctx"] = {
        "fmt": fmt, "style": style, "industry": industry,
        "mode": mode, "request": request, "product": product,
    }
    st.session_state["sel"] = None
    st.session_state.pop("hl", None)
    st.session_state.pop("sb", None)

# ──────────────────────────────────────────────────────────────
# 우측 — 결과
# ──────────────────────────────────────────────────────────────

with right:
    results = st.session_state.get("results")

    if not results:
        st.subheader("결과")
        st.info("왼쪽에서 설정을 고르고 **광고 만들기**를 눌러보세요.")
        with st.container(border=True):
            st.markdown("**이 조건에 적용될 법령**")
            for law in compliance.applicable_laws(tags):
                st.markdown(f"- **{law['name']}** {law['article']} — {law['applies_when']}")
        st.stop()

    ctx = st.session_state["ctx"]
    r_fmt, r_style = ctx["fmt"], ctx["style"]

    st.subheader("결과 — 마음에 드는 안을 고르세요")
    cols = st.columns(3)
    for i, (col, res) in enumerate(zip(cols, results)):
        with col:
            img = _render(res["bg"], r_fmt, r_style, res["cand"].headline, res["cand"].sub)
            st.image(img, use_container_width=True)
            st.caption(f"**{res['cand'].headline}**")
            if st.button(f"{i + 1}안 선택", key=f"sel_{i}", use_container_width=True):
                st.session_state["sel"] = i
                st.session_state["hl"] = res["cand"].headline
                st.session_state["sb"] = res["cand"].sub
                st.rerun()

    sel = st.session_state.get("sel")
    if sel is None:
        st.stop()

    st.divider()
    res = results[sel]
    detail_l, detail_r = st.columns([0.55, 0.45], gap="large")

    with detail_r:
        st.markdown("#### ✏️ 문구 수정")
        st.caption("이미지는 다시 만들지 않습니다 — 글자만 즉시 다시 얹습니다.")
        st.text_input("헤드라인", key="hl", max_chars=r_fmt["max_headline_chars"])
        st.text_input("서브카피", key="sb", max_chars=r_fmt["max_sub_chars"])
        st.caption(" ".join(res["cand"].hashtags))

    headline = st.session_state.get("hl", "")
    sub = st.session_state.get("sb", "")
    final = _render(res["bg"], r_fmt, r_style, headline, sub)

    with detail_l:
        st.image(final, use_container_width=True)
        st.download_button(
            "⬇️ 다운로드 (PNG)",
            data=layout.to_png_bytes(final),
            file_name=f"{ctx['industry']['id']}_{r_fmt['id']}.png",
            mime="image/png",
            use_container_width=True,
        )

    with detail_r:
        all_findings = compliance.scan(headline, tags) + compliance.scan(sub, tags)
        blocking = compliance.has_blocking(all_findings)
        if all_findings:
            st.warning(f"확인이 필요한 표현 {len(all_findings)}건 — 아래 법적 검토를 확인하세요.")

        with st.expander(
            "⚖️ 이 광고, 법적으로 괜찮나요?", expanded=bool(blocking)
        ):
            st.markdown("##### ✅ 적용되는 규정")
            for law in compliance.applicable_laws(tags):
                st.markdown(
                    f"**{law['name']}** `{law['article']}`  \n"
                    f"▸ 왜 적용되나 — {law['applies_when']}  \n"
                    f"▸ 무엇을 금지하나 — {law['summary']}  \n"
                    f"▸ 어떻게 지켰나 — {law['we_did']}  \n"
                    f"[조문 원문 보기]({law['url']})"
                )
                st.markdown("")

            st.markdown("##### ⚠️ 확인이 필요한 표현")
            found = _findings_block("hl", "헤드라인", headline, tags)
            found += _findings_block("sb", "서브카피", sub, tags)
            if not found:
                st.success("금칙 표현이 발견되지 않았습니다.")

            st.caption(
                "본 검토는 참고용이며 법률 자문이 아닙니다. 최종 책임은 광고주에게 있습니다. "
                "법령·조문은 원문 대조 전 초안입니다."
            )

    with st.expander("🔧 개발자 보기 — 생성 모드와 실제 모델에 보낼 프롬프트"):
        r_mode = ctx["mode"]
        st.markdown(
            f"**생성 모드** `{r_mode}` — {image_gen.MODE_LABEL[r_mode]}  \n"
            f"프로젝트 요구사항 대응: **{image_gen.MODE_REQUIREMENT[r_mode]}**"
        )
        st.caption("현재는 스텁이 동작 중입니다. 아래 프롬프트가 실제 모델에 그대로 전달됩니다.")
        st.markdown("**이미지 프롬프트**")
        st.code(
            image_gen.build_prompt(ctx["industry"], r_style, r_mode, request=ctx["request"]),
            language="text",
        )
        st.code(f"negative: {image_gen.NEGATIVE_PROMPT}", language="text")
        st.markdown("**문구 프롬프트 (금지 규칙 주입 = Stage A)**")
        st.code(
            copy_gen.build_prompt(ctx["product"], ctx["industry"], r_style, r_fmt, tags),
            language="text",
        )
