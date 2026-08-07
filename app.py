"""Streamlit 화면 — 개발·검증용.

화면만 그린다. 대화 로직·주문서·LLM 호출은 전부 app_core 에 있고 여기서는
부르기만 한다. 그래야 나중에 React 로 바꿔도 app_core 를 그대로 쓴다.

실행: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from app_core import ads, auth, chat, config, copy_gen, registry, stores
from app_core.schema import AdBriefDraft, Store, StoreInput

# DB·API 키 설정을 읽는다. app_core 를 쓰기 전에 해야 한다.
config.load_env()

st.set_page_config(page_title="동네 광고 만들기", page_icon="🏪", layout="wide")

GOALS = {"image": "🖼️ 광고 이미지 만들기", "copy": "✍️ 광고 문구 만들기"}
PLACEHOLDER = "예: 크로플 신메뉴 나왔어요, 인스타에 올릴 사진 만들어줘"


def _reset_chat() -> None:
    st.session_state.pop("draft", None)
    st.session_state.pop("history", None)
    st.session_state.pop("copies", None)


# ── 로그인 ────────────────────────────────────────────────


def login_view() -> None:
    st.title("🏪 동네 광고 만들기")
    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login, st.form("login"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        if st.form_submit_button("로그인"):
            user_id = auth.login(username, password)
            if user_id is None:
                st.error("아이디나 비밀번호가 맞지 않습니다")
            else:
                st.session_state.user_id = user_id
                st.rerun()

    with tab_signup, st.form("signup"):
        username = st.text_input("아이디", key="su_id")
        password = st.text_input("비밀번호 (8자 이상)", type="password", key="su_pw")
        if st.form_submit_button("가입하기"):
            try:
                st.session_state.user_id = auth.signup(username, password)
                st.rerun()
            except ValueError as e:
                st.error(str(e))


# ── 가게 목록 ──────────────────────────────────────────────


def store_form(user_id: int) -> None:
    options = registry.industry_options()
    labels = {o["id"]: f"{o['emoji']} {o['label']}" for o in options}

    with st.form("add_store"):
        st.subheader("가게 추가")
        industry = st.selectbox("업종", [o["id"] for o in options], format_func=lambda i: labels[i])
        # 목록에 없는 업종을 고른 경우에만 쓰인다. 폼 안이라 선택에 따라
        # 감출 수 없어서 항상 띄우고 안내 문구로 구분한다.
        industry_note = st.text_input("업종 직접 입력", placeholder="'기타'를 고르셨을 때만")
        name = st.text_input("상호")
        address = st.text_input("주소", placeholder="서울시 마포구 연남동 ...")
        phone = st.text_input("연락처", placeholder="02-000-0000")
        if st.form_submit_button("등록"):
            try:
                stores.add(
                    user_id,
                    StoreInput(
                        industry=industry,
                        name=name,
                        address=address or "서울",
                        phone=phone,
                        industry_note=industry_note,
                    ),
                )
                st.rerun()
            except ValidationError as e:
                st.error(e.errors()[0]["msg"])


def store_list_view(user_id: int) -> None:
    st.title("내 가게")
    my_stores = stores.list_stores(user_id)

    for store in my_stores:
        col_info, col_btn = st.columns([4, 1])
        col_info.markdown(f"**{store.name}** — {store.industry_label}  \n{store.address}")
        if col_btn.button("광고 만들기", key=f"pick{store.id}"):
            st.session_state.store_id = store.id
            _reset_chat()
            st.rerun()
        st.divider()

    if not my_stores:
        st.info("등록된 가게가 없습니다. 아래에서 추가해주세요.")
    store_form(user_id)


# ── 챗봇 ──────────────────────────────────────────────────


def brief_panel(draft: AdBriefDraft) -> None:
    """개발용 — LLM 이 제대로 알아들었는지 눈으로 보려고 띄운다. 배포 시 뺀다."""
    st.subheader("주문서")
    st.caption("개발 확인용")
    st.json(draft.model_dump())
    missing = draft.missing()
    if missing:
        st.warning(f"아직 안 찬 것: {', '.join(missing)}")
    else:
        st.success("다 찼습니다")


def copy_view(store: Store, draft: AdBriefDraft) -> None:
    brief = draft.to_brief()
    # 필수만 차면 바로 뜬다. 봇이 느낌·상황을 더 묻고 있어도 사장님은
    # 언제든 여기서 끊고 만들 수 있다.
    if draft.next_slot():
        st.caption("더 안 알려주셔도 지금 바로 만들 수 있습니다")
    if st.button("문구 만들기", type="primary"):
        with st.spinner("만드는 중..."):
            st.session_state.copies = copy_gen.generate(brief, store, ads.recent(store.id))
            st.session_state.ad_id = ads.save(store.id, brief, st.session_state.copies)

    for i, candidate in enumerate(st.session_state.get("copies") or [], start=1):
        with st.container(border=True):
            st.markdown(f"### {candidate.headline}")
            if candidate.sub:
                st.write(candidate.sub)
            if st.button("이걸로 할게요", key=f"pick_copy{i}"):
                ads.choose_copy(st.session_state.ad_id, candidate.headline)
                st.success("선택했습니다")


def chat_view(store: Store) -> None:
    st.title(f"{store.name} 사장님, 어떤 광고를 만들까요?")

    draft: AdBriefDraft = st.session_state.setdefault("draft", AdBriefDraft())
    history: list[tuple[str, str]] = st.session_state.setdefault("history", [])

    if draft.goal is None:
        cols = st.columns(len(GOALS))
        for col, (goal, label) in zip(cols, GOALS.items(), strict=True):
            if col.button(label, use_container_width=True):
                st.session_state.draft = draft.model_copy(update={"goal": goal})
                st.rerun()
        return

    col_chat, col_brief = st.columns([3, 2])

    with col_chat:
        for role, text in history:
            st.chat_message(role).write(text)

        # 가로로 늘어놓는다. 세로로 쌓으면 화면을 다 잡아먹는다.
        options = st.session_state.get("options") or []
        if options:
            for col, option in zip(st.columns(len(options)), options, strict=True):
                if col.button(option, key=f"opt_{option}", use_container_width=True):
                    st.session_state.pending = option
                    st.rerun()

        typed = st.chat_input(PLACEHOLDER)
        utterance = st.session_state.pop("pending", None) or typed
        if utterance:
            history.append(("user", utterance))
            turn = chat.respond(draft, utterance, store)
            history.append(("assistant", turn.message))
            st.session_state.draft = turn.draft
            st.session_state.options = turn.options
            st.rerun()

    with col_brief:
        brief_panel(draft)
        if not draft.missing():
            copy_view(store, draft)


# ── 라우팅 ────────────────────────────────────────────────


def main() -> None:
    if "user_id" not in st.session_state:
        login_view()
        return

    user_id = st.session_state.user_id
    store_id = st.session_state.get("store_id")

    with st.sidebar:
        if store_id and st.button("← 가게 목록"):
            st.session_state.pop("store_id")
            _reset_chat()
            st.rerun()
        if st.button("로그아웃"):
            st.session_state.clear()
            st.rerun()

    if store_id is None:
        store_list_view(user_id)
        return

    store = stores.get(user_id, store_id)
    if store is None:
        st.session_state.pop("store_id")
        st.rerun()
    else:
        chat_view(store)


main()
