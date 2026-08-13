"""Streamlit 화면 — 개발·검증용.

화면만 그린다. 대화 로직·주문서·LLM 호출은 전부 app_core 에 있고 여기서는
부르기만 한다. 그래야 나중에 React 로 바꿔도 app_core 를 그대로 쓴다.

실행: streamlit run app.py
"""

from __future__ import annotations

from typing import NamedTuple

import streamlit as st
from pydantic import ValidationError

from app_core import (
    ads,
    auth,
    chat,
    config,
    copy_gen,
    llm,
    photo_store,
    registry,
    stores,
    vision,
)
from app_core.schema import AdBrief, AdBriefDraft, Feedback, Store, StoreInput

# DB·API 키 설정을 읽는다. app_core 를 쓰기 전에 해야 한다.
config.load_env()

st.set_page_config(page_title="동네 광고 만들기", page_icon="🏪", layout="wide")

GOALS = {"image": "🖼️ 광고 이미지 만들기", "copy": "✍️ 광고 문구 만들기"}
PLACEHOLDER = "예: 크로플 신메뉴 나왔어요, 인스타에 올릴 사진 만들어줘"
PHOTO_TYPES = ["png", "jpg", "jpeg", "webp"]


class PhotoSlot(NamedTuple):
    field: str  #: AdBriefDraft 의 어느 칸에 번호를 넣을지
    label: str
    hint: str  #: 사장님에게 "이 칸에 뭘 넣는 건지" 알려주는 한 줄
    read: bool  #: 비전 모델로 읽어서 문구에 반영할지


#: 사진 칸 셋. 용도가 달라서 받는 쪽이 하는 일이 다르다 (schema.AdBrief 참고).
PHOTO_SLOTS = (
    PhotoSlot("photo_id", "제품 사진", "이 상품을 그대로 살립니다", read=True),
    PhotoSlot("ref_id", "레퍼런스", "이런 분위기로 만들어주세요", read=False),
    PhotoSlot("sketch_id", "스케치", "이런 배치·구도로 만들어주세요", read=False),
)


def _clear_uploader(field: str) -> None:
    """올린 파일을 비운다.

    st.file_uploader 는 key 가 같으면 rerun 뒤에도 파일을 계속 물고 있어서,
    "빼기"를 눌러도 다음 rerun 에 같은 파일이 또 올라온다.
    key 를 바꾸면 새 위젯으로 취급돼 빈 상태로 그려진다.
    """
    st.session_state[f"slot_{field}"] = st.session_state.get(f"slot_{field}", 0) + 1
    st.session_state.pop(f"key_{field}", None)


def _reset_chat() -> None:
    st.session_state.pop("draft", None)
    st.session_state.pop("history", None)
    st.session_state.pop("copies", None)
    st.session_state.pop("brief", None)
    st.session_state.pop("ad_id", None)
    for slot in PHOTO_SLOTS:
        _clear_uploader(slot.field)


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


def _photo_slot(draft: AdBriefDraft, slot: PhotoSlot) -> None:
    """사진 칸 하나. 이미 있으면 보여주고, 없으면 받는다."""
    st.markdown(f"**{slot.label}**")
    st.caption(slot.hint)

    # ① 이미 올린 경우 — 무엇으로 읽었는지 보여준다. 엉뚱하면 빼면 된다.
    if (photo_id := getattr(draft, slot.field)) is not None:
        if path := photo_store.path_of(photo_id):
            st.image(str(path), use_container_width=True)
        if slot.read:
            st.caption(draft.photo_note or "사진은 저장했지만 내용은 읽지 못했습니다")
        if st.button("빼기", key=f"drop_{slot.field}", use_container_width=True):
            blank = {slot.field: None} | ({"photo_note": ""} if slot.read else {})
            st.session_state.draft = draft.model_copy(update=blank)
            _clear_uploader(slot.field)
            st.rerun()
        return

    # ② 아직 없는 경우
    uploaded = st.file_uploader(
        slot.label,
        type=PHOTO_TYPES,
        label_visibility="collapsed",
        key=f"up_{slot.field}{st.session_state.get(f'slot_{slot.field}', 0)}",
    )
    if uploaded is None:
        return

    # 같은 파일이 그대로 있으면 rerun 마다 다시 올라온다 — 저장도 비전 호출도 한 번만.
    key = (uploaded.name, uploaded.size)
    if st.session_state.get(f"key_{slot.field}") == key:
        return
    st.session_state[f"key_{slot.field}"] = key

    try:
        photo_id = photo_store.save(uploaded.getvalue(), uploaded.name)
    except (ValueError, OSError) as e:
        st.error(str(e))
        return

    update: dict = {slot.field: photo_id}
    if slot.read:
        with st.spinner("사진 보는 중..."):
            data, mime = photo_store.load(photo_id) or (b"", "")
            update["photo_note"] = vision.describe(data, mime) if data else ""

    st.session_state.draft = draft.model_copy(update=update)
    st.rerun()


def photo_panel(draft: AdBriefDraft) -> None:
    """사진 칸 셋 — 전부 선택이다.

    제품 사진만 비전 모델로 읽어서 문구에 반영한다. 그 사진이 곧 홍보 대상이라
    생김새·분위기가 문구의 근거가 되기 때문이다. 레퍼런스·스케치는 "어떻게
    그릴지"에 대한 지시라 문구와 상관없어서 읽지 않는다 — 호출비만 든다.

    읽는 건 올릴 때 한 번뿐이다. 다시 만들 때마다 부르면 같은 답에 돈만 든다.
    """
    filled = [s.label for s in PHOTO_SLOTS if getattr(draft, s.field) is not None]
    title = "📷 사진 — " + (", ".join(filled) if filled else "선택")

    with st.expander(title, expanded=not filled):
        for col, slot in zip(st.columns(len(PHOTO_SLOTS)), PHOTO_SLOTS, strict=True):
            with col:
                _photo_slot(draft, slot)


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


def _make_copies(store: Store, brief: AdBrief, parent_id: int | None = None) -> bool:
    """문구를 만들어 화면 상태에 담는다. 처음 만들 때도 다시 만들 때도 같은 길이다.

    만들어진 게 없으면 **저장하지 않고 알린다.** 빈 목록은 화면에서 조용히
    사라져서 "고장인지 느린 건지" 알 수가 없고, 사장님이 버튼을 다시 누를수록
    후보 0개짜리 광고 행만 쌓인다.

    빈 목록이 나오는 길은 셋이고 증상이 똑같다 —
    MODEL_PROFILE 이 stub / LLM 이 candidates 를 빠뜨림 / 후보 전부가 검증 탈락.
    """
    with st.spinner("만드는 중..."):
        copies = copy_gen.generate(brief, store, ads.recent(store.id))

    if not copies:
        st.error("문구를 만들지 못했습니다. 다시 눌러주세요.")
        if llm.profile() == "stub":
            st.caption("⚠️ MODEL_PROFILE 이 stub 이라 항상 빈 결과입니다 — .env 를 확인하세요.")
        return False

    st.session_state.copies = copies
    st.session_state.brief = brief
    st.session_state.ad_id = ads.save(store.id, brief, copies, parent_id=parent_id)
    return True


def revise_view(store: Store) -> None:
    """다시 만들기 — 경로 셋이 같은 함수로 모인다.

    사장님이 "뭘 원하세요"엔 답을 못 해도 "이거 어때요"엔 답한다.
    그래서 한 번에 맞히려 하지 않고 고쳐가는 길을 둔다.
    """
    brief: AdBrief = st.session_state.brief
    st.divider()
    st.caption("마음에 안 드시면 고쳐서 다시 만들어드릴게요")

    def again(feedback: Feedback) -> None:
        # 실패했으면 rerun 하지 않는다 — 다시 그리면 방금 띄운 에러가 지워져서
        # 또 아무 일도 안 일어난 것처럼 보인다.
        if _make_copies(
            store,
            brief.revised(feedback, st.session_state.copies),
            parent_id=st.session_state.ad_id,
        ):
            st.rerun()

    # ① 선택지 — 말로 설명하기 어려울 때
    cols = st.columns(len(copy_gen.REVISION_OPTIONS))
    for col, option in zip(cols, copy_gen.REVISION_OPTIONS, strict=True):
        if col.button(option, key=f"rev_{option}", use_container_width=True):
            again(Feedback(source="option", notes=[option]))

    # ② 자연어 — 하고 싶은 말이 따로 있을 때
    if said := st.chat_input("어떻게 고쳐드릴까요? 예: 좀 더 밝게", key="revise_in"):
        again(Feedback(source="typed", notes=[said]))

    # ③ AI 손님 패널 평가 — 담당자 기능이 붙으면 여기로 들어온다
    st.caption("🧑‍🤝‍🧑 손님 패널 평가는 담당자 기능 연결 후 활성화됩니다")


def copy_view(store: Store, draft: AdBriefDraft) -> None:
    # 필수만 차면 바로 뜬다. 봇이 느낌·상황을 더 묻고 있어도 사장님은
    # 언제든 여기서 끊고 만들 수 있다.
    if draft.next_slot():
        st.caption("더 안 알려주셔도 지금 바로 만들 수 있습니다")
    if st.button("문구 만들기", type="primary"):
        _make_copies(store, draft.to_brief())

    copies = st.session_state.get("copies") or []
    for i, candidate in enumerate(copies, start=1):
        with st.container(border=True):
            st.markdown(f"### {candidate.headline}")
            if candidate.sub:
                st.write(candidate.sub)
            if st.button("이걸로 할게요", key=f"pick_copy{i}"):
                ads.choose_copy(store.id, st.session_state.ad_id, candidate.headline)
                st.success("선택했습니다")

    if copies:
        revise_view(store)


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
        photo_panel(draft)
        for role, text in history:
            st.chat_message(role).write(text)

        # 가로로 늘어놓는다. 세로로 쌓으면 화면을 다 잡아먹는다.
        options = st.session_state.get("options") or []
        if options:
            for col, option in zip(st.columns(len(options)), options, strict=True):
                if col.button(option, key=f"opt_{option}", use_container_width=True):
                    st.session_state.pending = option
                    st.rerun()

        typed = st.chat_input(PLACEHOLDER, key="chat_in")
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

    # 결과는 **전체 폭**으로 아래에 둔다. 오른쪽 칸(2/5)에 넣으면 재생성 버튼이
    # 3~4줄로 접히고, 손님 패널 결과(대조 3 + 점수 3 + 코멘트 12)는 더 심하다.
    # 위쪽 좁은 칸에는 개발 확인용 주문서만 남긴다.
    if not draft.missing():
        st.divider()
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
