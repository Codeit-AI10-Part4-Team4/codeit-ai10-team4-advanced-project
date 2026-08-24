"""Streamlit 화면 — 개발·검증용.

화면만 그린다. 대화 로직·주문서·LLM 호출은 전부 app_core 에 있고 여기서는
부르기만 한다. 그래야 나중에 React 로 바꿔도 app_core 를 그대로 쓴다.

실행: streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

import streamlit as st
from PIL import Image
from pydantic import ValidationError

from app_core import (
    ads,
    auth,
    chat,
    config,
    copy_gen,
    image_backend,
    llm,
    photo_store,
    registry,
    result_store,
    stores,
    vision,
)
from app_core.panel.aggregate import AggregationError
from app_core.panel.features import NoTradeAreaError
from app_core.panel.review import Ranked, has_clear_winner, rank
from app_core.panel.schemas import EvaluationResult
from app_core.schema import AdBrief, AdBriefDraft, CopyCandidate, Feedback, Store, StoreInput

if TYPE_CHECKING:
    from app_core.pipeline import Style

# DB·API 키 설정을 읽는다. app_core 를 쓰기 전에 해야 한다.
config.load_env()

st.set_page_config(page_title="동네 광고 만들기", page_icon="🏪", layout="wide")

GOALS = {"image": "🖼️ 광고 이미지 만들기", "copy": "✍️ 광고 문구 만들기"}
PLACEHOLDER = "예: 크로플 신메뉴 나왔어요, 인스타에 올릴 사진 만들어줘"
PHOTO_TYPES = ["png", "jpg", "jpeg", "webp"]
STYLES: tuple[tuple[Style, str], ...] = (("simple", "감성 피드형"), ("poster", "정보 포스터형"))


class OutputCard(NamedTuple):
    """STEP 1 에서 사장님이 고르는 결과물 카드 하나."""

    value: str  #: pipeline.OutputType
    title: str
    blurb: str  #: 무엇에 좋은지 한 줄
    steps: str  #: 이 유형을 고르면 이후 단계가 어떻게 되는지


#: 결과물 3종 — **대화보다 먼저** 고른다 (PDF STEP 1).
#:
#: 카드 그림은 매번 생성하는 것이 아니라 **고정 예시**다. 여기서 진짜를 만들면
#: 고르기도 전에 돈과 시간이 나간다.
OUTPUT_CARDS = (
    OutputCard(
        "emotional_no_text",
        "감성 사진 · 글자 없음",
        "문구 없이 사진에 집중",
        "문구·손님 반응을 건너뜁니다",
    ),
    OutputCard(
        "emotional_text",
        "감성 사진 · 글자 있음",
        "짧은 문구로 분위기 전달",
        "문구 3개 + 손님 반응을 봅니다",
    ),
    OutputCard(
        "poster",
        "포스터형 · 글자 필수",
        "상품과 가격을 명확하게",
        "문구 3개 + 손님 반응을 봅니다",
    ),
)


class PhotoSlot(NamedTuple):
    field: str  #: AdBriefDraft 의 어느 칸에 번호를 넣을지
    label: str
    hint: str  #: 사장님에게 "이 칸에 뭘 넣는 건지" 알려주는 한 줄
    read: bool  #: 비전 모델로 읽어서 문구에 반영할지


#: 사진 칸 셋. 용도가 달라서 받는 쪽이 하는 일이 다르다 (schema.AdBrief 참고).
PHOTO_SLOTS = (
    # 찍는 법을 안내한다 — 여러 물건이 흩어진 사진은 누끼에서 상품이 지워지거나
    # 조각으로 딸려온다(#22). 사장님이 찍기 전에 아는 것이 사후 보정보다 낫다.
    PhotoSlot(
        "photo_id",
        "제품 사진",
        "광고할 제품이 잘 보이도록 가능하면 광고할 제품 위주로 찍어주세요",
        read=True,
    ),
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
    st.session_state.pop("ranked", None)
    st.session_state.pop("picked", None)
    st.session_state.pop("images", None)
    st.session_state.pop("materials", None)
    st.session_state.pop("materials_brief", None)
    st.session_state.pop("mat_errors", None)
    st.session_state.pop("backend_notes", None)
    st.session_state.pop("saved", None)
    # STEP 1·2 선택도 지운다 — 안 지우면 "다시 고르기" 가 대화만 지우고 같은
    # 유형으로 되돌아와서, 사장님은 버튼이 안 먹은 줄 안다.
    st.session_state.pop("output_type", None)
    st.session_state.pop("has_photo", None)
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
    """사진 칸 — **사진 유무 갈래에 맞는 것만** 보여준다 (PDF STEP 2).

    제품 사진만 비전 모델로 읽어서 문구에 반영한다. 그 사진이 곧 홍보 대상이라
    생김새·분위기가 문구의 근거가 되기 때문이다. 레퍼런스·스케치는 "어떻게
    그릴지"에 대한 지시라 문구와 상관없어서 읽지 않는다 — 호출비만 든다.

    읽는 건 올릴 때 한 번뿐이다. 다시 만들 때마다 부르면 같은 답에 돈만 든다.

    셋을 한꺼번에 늘어놓지 않는 이유: 레퍼런스는 **실물 사진을 다듬는** 지시고
    스케치는 **없는 장면을 그리는** 지시라, 사장님이 고른 갈래에 안 맞는 칸은
    올려도 쓸 데가 없다. 화면에 있으면 올리게 되고, 올리면 반영될 줄 안다.
    """
    slots = _slots_for(_has_photo(draft))
    filled = [s.label for s in slots if getattr(draft, s.field) is not None]
    title = "📷 사진 — " + (", ".join(filled) if filled else "선택")

    with st.expander(title, expanded=not filled):
        for col, slot in zip(st.columns(len(slots)), slots, strict=True):
            with col:
                _photo_slot(draft, slot)


def _has_photo(draft: AdBriefDraft) -> bool:
    """사장님이 STEP 2 에서 "사진 있어요" 를 골랐는지."""
    return bool(st.session_state.get("has_photo"))


def _slots_for(has_photo: bool) -> tuple[PhotoSlot, ...]:
    """그 갈래에서 열어줄 사진 칸.

    사진 있음   제품 사진(3번) + 레퍼런스(2번)   실물을 살리고 분위기를 얹는다
    사진 없음   스케치(4번)                     안 올리면 통생성(1번)
    """
    by_field = {s.field: s for s in PHOTO_SLOTS}
    if has_photo:
        return (by_field["photo_id"], by_field["ref_id"])
    return (by_field["sketch_id"],)


def brief_panel(draft: AdBriefDraft) -> None:
    """개발용 — LLM 이 제대로 알아들었는지 눈으로 보려고 띄운다. 배포 시 뺀다.

    **접어 둔다.** 펼친 채로 두면 화면 오른쪽 2/5 를 개발용 JSON 이 차지해서,
    사장님 화면에서 제일 큰 것이 개발 부산물이 된다 (2026-08-14 클릭 검증).
    정작 필요한 "다 찼나"는 접힌 제목에 남겨서 한눈에 보인다.
    """
    missing = draft.missing()
    state = f"아직 안 찬 것: {', '.join(missing)}" if missing else "다 찼습니다"
    with st.expander(f"🧾 주문서 (개발 확인용) — {state}", expanded=False):
        st.json(draft.model_dump())


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

    st.session_state.brief = brief
    st.session_state.ad_id = ad_id = ads.save(store.id, brief, copies, parent_id=parent_id)
    # DB가 붙인 id를 실어 다시 꺼낸다 ─ 선택이 문자열이 아니라 id로 짚게 (docs/08 §2-2)
    st.session_state.copies = ads.copies_of(store.id, ad_id)
    # 문구가 갈렸으니 이전 순위·이전 선택은 더 이상 화면의 것이 아니다. 안 지우면
    # 사라진 문구의 평가와 선택이 새 문구 밑에 그대로 붙어 있는다.
    st.session_state.pop("ranked", None)
    st.session_state.pop("picked", None)
    return True


def _rank_copies(store: Store, brief: AdBrief, copies: list[CopyCandidate]) -> bool:
    """후보 전부를 손님들에게 보여주고 순위를 담는다. **성공하면 True.**

    한 건만 평가하던 것을 셋으로 늘렸다. 콜이 3배지만, 한 건만 물어서 얻은 것은
    "가격이 걸린다"는 한 단어뿐이었고 그건 사장님이 손댈 수 없는 답이다
    (재생성은 가격 슬롯을 안 바꾼다). 셋을 물으면 **어느 걸 쓸지**가 나온다.

    **성공 여부를 돌려주는 이유** — 부르는 쪽이 실패했을 때 `st.rerun()` 을
    건너뛰어야 안내문이 화면에 남는다. 안 그러면 사장님 눈에는 버튼을 눌러도
    아무 일도 안 일어나는 것으로 보인다 (귀한님이 통합 스모크에서 발견,
    2026-08-19). `_make_copies` 는 #20 에서 같은 이유로 이미 bool 이었는데
    바로 아래 이 버튼만 안 고쳐져 있었다 — 규칙을 주석으로 적어두는 것만으로는
    안 지켜진다.
    """
    try:
        with st.spinner("동네 손님들에게 후보를 보여주는 중... (1분쯤 걸립니다)"):
            st.session_state.ranked = rank(
                store, brief, copies, ad_id=str(st.session_state.get("ad_id", ""))
            )
    except NoTradeAreaError as exc:
        # 원문을 그대로 띄우면 사장님이 "coord 를 직접 넘기세요" 같은 개발자
        # 문장을 읽게 된다(카카오 키가 없을 때 실제로 그 문장이 온다).
        # 사장님이 할 수 있는 말만 화면에 두고 원문은 접어서 남긴다.
        st.warning("이 주소로는 동네 손님을 불러오지 못했습니다.", icon="📍")
        with st.expander("왜 안 됐는지 (개발용)"):
            st.code(str(exc))
        return False
    except AggregationError as exc:
        st.error(f"손님 반응을 모으지 못했습니다. 다시 눌러주세요. ({exc})")
        return False
    return True


def _panel_source(result: EvaluationResult) -> None:
    """무엇을 근거로 한 평가인지 화면에 남긴다.

    집계 결과는 신뢰도 필드를 아홉 개 실어 보내는데(`is_category_fallback` ·
    `excluded_cnt` · `confidence_reasons` …) 화면은 `scores` · `suggestions` ·
    `top_resistance` 셋만 쓰고 있었다. `schemas.py` 가 **"결과 화면에 배지를
    띄운다"** 고 적어둔 그 배지가 어디에도 없었다 (06 §6 도 같은 요구).

    "동네 손님 12명" 이라고 말하려면 **어느 동네의 언제 데이터인지**, 그리고
    **정말 그 인원인지** 를 같이 말해야 한다. 인원은 12명 고정이 아니다 —
    매출이 0 인 연령대는 `build_panel` 이 빼므로 10명일 수 있다. 그래서 버튼·
    스피너에서 숫자를 뺐고 여기서 `total` 로 실제 수를 말한다. 업종 폴백도 그렇다 —
    객단가가 통째로 바뀌는데(실측 2026-08-17: 관악 분식이 업종 9,546원대가
    아니라 동네 전 업종 평균 40,141원) 화면에는 아무 표시가 없었다.
    """
    total = len(result.persona_comments) + result.excluded_cnt
    quarter = (
        f"{result.quarter[:4]}년 {result.quarter[4:]}분기"
        if len(result.quarter) == 5
        else result.quarter
    )
    parts = [f"{result.area_nm} 상권", f"{quarter} 실측", f"손님 {total}명"]
    if result.excluded_cnt:
        parts.append(f"근거를 못 댄 {result.excluded_cnt}명은 빼고 셈")
    st.caption("📍 " + "  ·  ".join(parts))

    if result.is_fallback:
        st.warning("이 주소로 동네를 찾지 못해 **서울 평균**으로 평가했습니다.", icon="📍")
    elif result.is_category_fallback:
        st.info(
            "이 동네에 같은 업종 데이터가 적어 **동네 전체 손님 기준**으로 봤습니다.",
            icon="ℹ️",
        )

    if result.confidence == "low":
        why = "".join(f"\n- {reason}" for reason in result.confidence_reasons)
        st.warning(f"이 평가는 **참고만** 해주세요.{why}", icon="⚠️")


def _rank_caption(position: int, ranked: list[Ranked]) -> str:
    """절대 점수 없이 순위와 근거 있는 추천만 보여준다."""
    label = f"**{position}위**"
    if position == 1 and has_clear_winner(ranked):
        return f"{label} · 🏆 손님들이 가장 반응한 문구"
    return label


def _rank_summary(ranked: list[Ranked]) -> None:
    """1등을 권하되 **차이가 잡음보다 클 때만** 권한다.

    절대 점수는 해석할 수 없다 — 실측(2026-08-13)에서 방문의향이 49.7~54.0 사이에만
    머물러서 "52점"이 좋은지 나쁜지 말할 수 없다. 반면 후보끼리의 차이는 재실행
    흔들림(0.7)의 3~8배라 순위는 믿을 수 있다. 그래서 점수를 크게 띄우지 않고
    **어느 것을 쓸지**만 말한다.
    """
    if len(ranked) < 2:
        return
    if has_clear_winner(ranked):
        st.success(
            "손님들은 **1위 문구**에 가장 마음이 움직였습니다.",
            icon="🧑‍🤝‍🧑",
        )
    else:
        st.info(
            "손님 반응은 셋이 비슷했습니다. 아래 지적사항이 없는 쪽을 고르시면 됩니다.",
            icon="🧑‍🤝‍🧑",
        )


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

    # ③ AI 손님 패널 평가 — 고른 문구에 대한 손님들의 개선 제안
    #
    # 여기서 다시 평가하지 않는다. 위(`copy_view`)에서 후보 전부를 이미 평가했고,
    # 고른 것의 결과가 그 안에 들어 있다. 또 부르면 같은 답에 20콜을 더 쓴다.
    picked = st.session_state.get("picked")
    scored = next(
        (r for r in st.session_state.get("ranked") or [] if r.copy == picked),
        None,
    )
    if scored is None:
        st.caption("🧑‍🤝‍🧑 위에서 손님 반응을 보고 문구를 하나 고르시면 제안을 드립니다")
        return

    for line in scored.result.suggestions:
        st.write(f"- {line}")
    if scored.result.suggestions and st.button("제안 반영해 다시 만들기", key="panel_again"):
        # 손님 반응을 그대로 재생성 입력으로 넘긴다. 이전 순위 정리는 `_make_copies` 가 한다.
        again(
            Feedback(
                source="panel",
                notes=scored.result.suggestions,
                resistance=scored.result.top_resistance,
            )
        )


def copy_view(store: Store, draft: AdBriefDraft) -> None:
    copies = st.session_state.get("copies") or []
    ranked: list[Ranked] = st.session_state.get("ranked") or []

    # **아직 안 만들었을 때만 띄운다.** 결과가 나온 뒤에도 이 빨간 버튼이 맨 위에
    # 남으면 화면에서 제일 눈에 띄는 것이 "누르면 순위가 날아가는 버튼"이 된다
    # (_make_copies 가 ranked 를 지운다). 2026-08-14 클릭 검증에서 눈으로 봤다.
    # 다시 만들기는 아래 revise_view 가 맡는다.
    if not copies:
        # 필수만 차면 바로 뜬다. 봇이 느낌·상황을 더 묻고 있어도 사장님은
        # 언제든 여기서 끊고 만들 수 있다.
        if draft.next_slot():
            st.caption("더 안 알려주셔도 지금 바로 만들 수 있습니다")
        # copies 를 위에서 읽었으므로 rerun 없이는 방금 만든 문구가 이번 화면에
        # 안 나온다. 실패했을 때는 그대로 둬야 에러 문구가 남는다.
        if st.button("문구 만들기", type="primary") and _make_copies(store, draft.to_brief()):
            st.rerun()

    # 위 "문구 만들기"와 같은 규칙이다 — **성공했을 때만** rerun 한다.
    # 무조건 돌리면 `_rank_copies` 가 띄운 안내문이 그 자리에서 지워져,
    # 사장님 눈에는 버튼을 눌러도 아무 일도 안 일어난 것처럼 보인다.
    if (
        copies
        and not ranked
        and st.button("🧑‍🤝‍🧑 동네 손님들에게 셋 다 보여주기")
        and _rank_copies(store, st.session_state.brief, copies)
    ):
        st.rerun()

    if ranked:
        # 출처를 먼저 밝히고 결론을 말한다 — 순서가 바뀌면 근거가 각주가 된다.
        _panel_source(ranked[0].result)
        _rank_summary(ranked)

    # 순위가 나왔으면 그 순서로 보여준다 — 사장님이 위에서부터 읽으면 된다.
    shown = [(r.copy, r) for r in ranked] or [(c, None) for c in copies]
    for i, (candidate, scored) in enumerate(shown, start=1):
        with st.container(border=True):
            if scored is not None:
                st.caption(_rank_caption(i, ranked))
            st.markdown(f"### {candidate.headline}")
            if candidate.sub:
                st.write(candidate.sub)
            for note in scored.defects if scored else []:
                st.warning(note.text, icon="⚠️")
            if st.button("이걸로 할게요", key=f"pick_copy{i}") and candidate.id is not None:
                # store.id 는 소유권 검사용(내 쪽), picked 는 손님 패널이 평가할 대상(아인님 쪽)
                # 둘 다 필요해서 합쳤다.
                # id로 짚는다 ─ 제목이 같은 후보가 나와도 고른 한 건만 선택된다 (docs/08 §2-2)
                if ads.choose_copy(store.id, st.session_state.ad_id, candidate.id):
                    st.session_state.picked = candidate
                    # 이전 문구로 만든 이미지는 더 이상 화면의 것이 아니다
                    st.session_state.pop("images", None)
                    st.success("선택했습니다")
                else:
                    st.error("문구를 선택하지 못했습니다. 다시 만들어주세요.")

    if copies:
        revise_view(store)


# ── 광고 이미지 ────────────────────────────────────────────


def _prepare_materials(store: Store, brief: AdBrief) -> bool:
    """비싼 재료(사진 분석·배경 생성·포스터 기획)를 형태별로 준비해 세션에 담는다.

    한 형태가 실패해도 다른 형태는 진행한다 — 실패는 mat_errors 로 남겨 화면이
    형태별로 안내한다 (docs/08 §7-1). 성공한 쪽을 남의 실패로 날리지 않는다.
    """
    # 확산 모델 의존이라 지연 import ─ 문구만 쓰는 환경에서도 앱이 뜨게 한다
    from app_core import pipeline

    output_type = st.session_state.output_type
    label = next(c.title for c in OUTPUT_CARDS if c.value == output_type)
    materials: dict[str, pipeline.AdMaterials] = {}
    errors: dict[str, str] = {}
    # 사장님이 고른 **한 형태만** 만든다. 전에는 감성형·포스터형을 늘 둘 다
    # 만들어서, 안 고른 쪽에 GPU·API 비용과 20~30초가 그대로 나갔다.
    try:
        with st.spinner(f"{label} 재료 준비 중... (20~30초)"):
            materials[output_type] = pipeline.prepare_output(brief, store, output_type)
    except (OSError, ValueError, RuntimeError, ImportError) as e:
        errors[output_type] = str(e)
    st.session_state.materials = materials
    st.session_state.mat_errors = errors
    st.session_state.materials_brief = brief
    st.session_state.backend_notes = image_backend.pop_notices()
    if not materials and llm.profile() == "stub":
        st.caption("⚠️ MODEL_PROFILE 이 stub 이라 기획 단계에서 멈춥니다 — .env 를 확인하세요.")
    return bool(materials)


def _render_images(picked: CopyCandidate | None) -> None:
    """준비된 재료를 결과물 유형에 맞게 마무리한다 — 싼 단계라 문구만 바꿔도 여기만 돈다.

    글자 없는 유형은 `picked` 가 None 이다. 문구를 고르는 화면 자체를 안 거친다.
    """
    from app_core import pipeline

    output_type = st.session_state.output_type
    images = {}
    materials = st.session_state.materials.get(output_type)
    if materials is not None:  # None 이면 재료 단계에서 실패 — mat_errors 가 안내한다
        try:
            images[output_type] = pipeline.render_output(materials, output_type, picked)
        except (OSError, ValueError, RuntimeError, TypeError) as e:
            st.session_state.mat_errors[output_type] = str(e)
    st.session_state.images = images
    # 새로 조판했으니 이전 저장 표시는 더 이상 이 이미지의 것이 아니다
    st.session_state.pop("saved", None)


def _make_images(store: Store, brief: AdBrief) -> bool:
    """고른 결과물 유형으로 이미지 한 장을 만들어 화면 상태에 담는다.

    재료 준비(비쌈)와 조판(쌈)이 나뉘어 있어(#37), 같은 주문서면 재료를 재사용하고
    조판만 다시 한다 — 문구를 바꿔 다시 눌러도 20~30초를 다시 기다리지 않는다.
    """
    from app_core import pipeline

    picked: CopyCandidate | None = st.session_state.get("picked")
    if pipeline.needs_copy(st.session_state.output_type) and picked is None:
        st.info("먼저 문구를 하나 골라주세요 — 위 후보에서 '이걸로 할게요'를 누르면 됩니다.")
        return False

    stale = st.session_state.get("materials_brief") != brief
    if (stale or not st.session_state.get("materials")) and not _prepare_materials(store, brief):
        return False
    _render_images(picked)
    st.session_state.brief = brief
    return bool(st.session_state.images)


def _save_and_download(
    store: Store, product: str, style: str, label: str, img: Image.Image
) -> None:
    """완성 광고를 남기는 두 길 — 서버 저장(DB 기록)과 즉시 다운로드는 서로 독립이다.

    저장이 실패해도 다운로드는 살아 있어야 한다 (docs/08 §7) — 1분 걸려 만든
    이미지를 저장 실패로 날리지 않는다. 저장 성공은 버튼을 "저장됨"으로 바꿔
    중복 저장을 막는다.
    """
    saved: dict[str, str] = st.session_state.setdefault("saved", {})
    col_save, col_dl = st.columns(2)
    if style in saved:
        col_save.button("저장됨 ✓", key=f"save_{style}", disabled=True)
    elif col_save.button("저장", key=f"save_{style}"):
        ad_id = st.session_state.get("ad_id")
        if ad_id is None:
            st.error("광고 번호가 없어 저장할 수 없습니다. 문구를 다시 만들어주세요.")
        else:
            try:
                path = result_store.save_result(img)
                recorded = ads.add_image(store.id, ad_id, path)
            except OSError as e:
                st.error(f"저장에 실패했습니다 ({e}). 다운로드는 가능합니다.")
            else:
                if recorded:
                    saved[style] = path
                    st.rerun()
                else:
                    st.error("저장 기록에 실패했습니다. 다운로드는 가능합니다.")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    col_dl.download_button(
        "다운로드",
        data=buf.getvalue(),
        file_name=f"{store.name}_{product}_{label}_{datetime.now(ZoneInfo('Asia/Seoul')):%Y%m%d}.png",
        mime="image/png",
        key=f"dl_{style}",
    )


def image_view(store: Store, draft: AdBriefDraft) -> None:
    """광고 이미지 ─ 사장님이 고른 결과물 **한 형태만** 만든다.

    문구가 필요한 유형은 문구 후보·패널·선택을 문구 갈래와 **같은 부품**(copy_view)
    으로 거친다 ─ 따로 만들면 두 화면이 서로 다르게 늙는다 (docs/08 §2 ③④).

    글자 없는 유형은 그 단계를 통째로 건너뛴다 (PDF STEP 3). 고른 문구가 결과에
    한 글자도 안 나오는데 문구를 고르게 하면 사장님을 헛수고시키는 것이다.
    """
    from app_core import pipeline

    output_type = st.session_state.output_type
    label = next(c.title for c in OUTPUT_CARDS if c.value == output_type)
    wants_copy = pipeline.needs_copy(output_type)

    if wants_copy:
        copy_view(store, draft)
        if st.session_state.get("picked") is None:
            return  # 고르기 전엔 이미지 버튼도 안 보인다 ─ 누르고 안내받는 것보다 낫다
    picked: CopyCandidate | None = st.session_state.get("picked") if wants_copy else None

    # 문구만 바꾼 경우 — 재료가 있으면 조판만 자동으로 다시 한다 (1~2초).
    # 다른 문구의 "이걸로 할게요"를 누르는 순간 이미지가 그 문구로 바뀐다.
    same_brief = st.session_state.get("materials_brief") == draft.to_brief()
    if same_brief and st.session_state.get("materials") and not st.session_state.get("images"):
        _render_images(picked)

    if st.button(f"{label} 만들기", type="primary"):
        _make_images(store, draft.to_brief())

    images = st.session_state.get("images") or {}
    errors = st.session_state.get("mat_errors") or {}
    if not images and not errors:
        return

    img = images.get(output_type)
    with st.container(border=True):
        st.markdown(f"**{label}**")
        if img is None:
            st.error(f"{label}을(를) 만들지 못했습니다. {errors.get(output_type, '')}")
        else:
            st.image(img, use_container_width=True)
            _save_and_download(store, draft.product or "광고", output_type, label, img)

    for note in st.session_state.get("backend_notes") or []:
        st.caption(f"ℹ️ {note}")

    if img is not None and st.button("사진만 다시 만들기"):
        # 문구는 그대로 두고 재료(배경·상품)만 새로 뽑는다 — 생성은 매번 다르게 나온다
        if _prepare_materials(store, draft.to_brief()):
            _render_images(picked)
            st.rerun()
        else:
            st.error("새 사진을 만들지 못했습니다. 이전 결과를 유지합니다.")
    if wants_copy:
        st.caption(
            "문구를 바꾸려면 위 후보에서 다른 것을 고르세요 — "
            "사진은 그대로 두고 글자만 다시 얹습니다."
        )


def _chosen_banner() -> None:
    """고른 것을 계속 보여주고 되돌아갈 길을 준다.

    안 보이면 사장님이 무엇을 고른 채 대화 중인지 잊는다 — 특히 글자 없는 유형은
    문구 화면이 안 나와서 "왜 문구를 안 물어보지" 가 된다.
    """
    card = next(c for c in OUTPUT_CARDS if c.value == st.session_state.output_type)
    photo = "사진 있음" if st.session_state.has_photo else "사진 없음"
    left, right = st.columns([4, 1])
    left.caption(f"**{card.title}** · {photo}")
    if right.button("다시 고르기", use_container_width=True):
        _reset_chat()
        st.rerun()


def output_type_view() -> None:
    """STEP 1 — 만들고 싶은 결과를 **눈으로** 먼저 고른다.

    카드 그림은 고정 예시다. 여기서 진짜를 만들면 고르기도 전에 돈과 시간이 나간다.
    """
    st.subheader("어떤 결과물을 만들까요?")
    st.caption("먼저 만들고 싶은 형태를 고르시면, 그에 필요한 것만 여쭤봅니다.")
    for col, card in zip(st.columns(len(OUTPUT_CARDS)), OUTPUT_CARDS, strict=True):
        with col, st.container(border=True):
            st.markdown(f"**{card.title}**")
            st.caption(card.blurb)
            st.caption(f"→ {card.steps}")
            if st.button("이걸로 만들기", key=f"out_{card.value}", use_container_width=True):
                st.session_state.output_type = card.value
                st.rerun()


def photo_choice_view() -> None:
    """STEP 2 — 상품 사진이 있는지만 묻는다. 같은 결과물이어도 생성 경로가 갈린다."""
    st.subheader("상품 사진이 있나요?")
    st.caption("실제 상품 사진은 0장 또는 1장이면 됩니다 — 여러 장은 필요 없습니다.")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**사진이 있어요**")
        st.caption("실제 상품의 형태와 용기를 유지하고 조명·색감·배경만 자연스럽게 개선합니다.")
        if st.button("사진 올릴게요", key="has_photo_yes", use_container_width=True):
            st.session_state.has_photo = True
            st.rerun()
    with right, st.container(border=True):
        st.markdown("**사진이 없어요**")
        st.caption("대화에서 받은 상품 정보로 AI가 장면을 새로 연출하고 표시를 붙입니다.")
        if st.button("사진 없이 만들게요", key="has_photo_no", use_container_width=True):
            st.session_state.has_photo = False
            st.rerun()


def chat_view(store: Store) -> None:
    st.title(f"{store.name} 사장님, 어떤 광고를 만들까요?")

    # 입구가 셋이다 — 결과물 선택 → 사진 유무 → 대화 (PDF STEP 1~3).
    #
    # 순서가 중요하다. 결과물을 먼저 골라야 **문구·손님 반응을 거칠지**가 정해지고,
    # 사진 유무를 먼저 물어야 **어느 사진 칸을 열지**가 정해진다. 대화를 먼저 시키면
    # 다 끝난 뒤에 "사실 이건 글자 없는 거였어요" 가 되어 문구 고른 게 버려진다.
    #
    # goal 필드와 ads.goal 컬럼은 그대로 둔다 ─ NLU·DB 계약 정리는 별건.
    draft: AdBriefDraft = st.session_state.setdefault("draft", AdBriefDraft(goal="image"))
    history: list[tuple[str, str]] = st.session_state.setdefault("history", [])

    if st.session_state.get("output_type") is None:
        output_type_view()
        return
    if st.session_state.get("has_photo") is None:
        photo_choice_view()
        return

    _chosen_banner()
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
        if draft.goal == "image":
            image_view(store, draft)
        else:
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


# streamlit 은 스크립트를 `__main__` 으로 실행하므로 화면 동작은 그대로다.
# 가드가 없으면 import 하는 순간 앱이 통째로 돌아서 이 파일에 테스트를 붙일 수 없었다.
if __name__ == "__main__":
    main()
