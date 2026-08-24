"""광고 생성 총괄 부품 — 주문서를 받아 부품들을 순서대로 돌려 완성 광고를 만든다.

주문서(AdBrief)는 "무엇을 원하는가", 가게(Store)는 "어떤 가게인가",
문구(CopyCandidate)는 "이미지에 얹을 글"이다. 셋이 모여야 광고 한 장이 나온다.

형태는 두 가지다.
  simple  업로드 사진 AI 재촬영/안전 보정 또는 사진 없는 AI 생성 + 문구 — 분위기가 주인공
  poster  광고 사진 카드 + 종이 정보 블록 — 정보가 주인공
"""

from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageOps

from app_core import photo_store, ref_style, sketch_gen
from app_core.background import remove_background
from app_core.compose import compose_ad, compose_no_text
from app_core.gen_background import generate_background
from app_core.image_backend import generate_scene, restage_photo
from app_core.image_backend import profile as image_profile
from app_core.photo_enhance import enhance_uploaded_photo
from app_core.photo_router import mask_area, remove_crumbs
from app_core.poster import generate_poster, generate_uploaded_photo_poster
from app_core.poster_plan import PosterPlan, plan_poster
from app_core.prompt_builder import build_bg_prompt, build_hero_prompt, build_scene_prompt
from app_core.schema import AdBrief, CopyCandidate, Store

Style = Literal["simple", "poster"]

#: 사장님이 **대화보다 먼저** 고르는 결과물 유형 (화면 STEP 1).
#:
#: 이 값이 정하는 것은 딱 하나 — **글자를 얹느냐**다. 어떤 이미지 기능(1~4번)이
#: 도는지는 별개로 "사진을 올렸나 / 레퍼런스를 올렸나 / 스케치를 올렸나" 가 정한다.
#: 둘은 서로 독립이라 3×4 조합이 전부 성립한다.
OutputType = Literal["emotional_no_text", "emotional_text", "poster"]

#: 결과물 유형 → 조판 형태. 글자 없는 유형은 조판 자체를 안 하므로 감성형 재료를 쓴다.
_OUTPUT_STYLE: dict[str, Style] = {
    "emotional_no_text": "simple",
    "emotional_text": "simple",
    "poster": "poster",
}


def needs_copy(output_type: OutputType) -> bool:
    """문구·손님 패널 단계를 거쳐야 하는 유형인가.

    화면이 이 함수로 단계를 건너뛸지 정한다 — 글자가 없는 결과물에 문구를 고르게
    하면 사장님이 고른 문구가 **어디에도 안 나오는** 흐름이 된다 (PDF STEP 3).
    """
    return output_type != "emotional_no_text"


def style_of(output_type: OutputType) -> Style:
    """결과물 유형이 쓰는 조판 형태."""
    return _OUTPUT_STYLE[output_type]


@dataclass(frozen=True)
class SimpleMaterials:
    """감성 피드형 재료 — 문구를 얹기 전까지의 전부."""

    product: Image.Image | None  #: 누끼. 실사진 보정·통생성이면 None
    background: Image.Image  #: 안전 보정 실사진 또는 생성 배경
    shop: str = ""  #: 실사진 전용 조판에 표시할 상호
    preserved_photo: bool = False  #: 누끼 없는 사진 전체에 고정 상단 조판을 쓸지
    staged: bool = False  #: 상품 이미지를 AI 가 그렸는지 → "연출된 이미지" 표기


@dataclass(frozen=True)
class PosterMaterials:
    """정보 포스터형 재료 — 기획(LLM)까지 끝난 상태."""

    product: Image.Image | None  #: 누끼 또는 생성된 주인공
    plan: PosterPlan  #: 포스터 기획 결과
    shop: str  #: 가게 이름
    info: str  #: 하단 한 줄 (주소·전화)
    staged: bool = False  #: 상품 이미지를 AI 가 그렸는지 → "연출된 이미지" 표기


@dataclass(frozen=True)
class UploadedPhotoPosterMaterials:
    """업로드 사진 포스터 재료 — 재촬영 또는 안전 보정한 사진 전체를 쓴다."""

    photo: Image.Image
    shop: str
    info: str
    product_name: str
    staged: bool = False


#: 문구를 모르는 재료 상자 — 문구가 바뀌어도 이건 재사용하고 조판만 다시 한다
AdMaterials = SimpleMaterials | PosterMaterials | UploadedPhotoPosterMaterials


def _info_line(store: Store) -> str:
    """포스터 하단 한 줄 — 없는 항목은 빼고 이어 붙인다."""
    return "  ·  ".join(part for part in (store.address, store.phone) if part)


def _safe_uploaded_photo(photo: Image.Image) -> Image.Image:
    """생성 모델 없이 픽셀 좌표를 유지한 채 색감만 보수적으로 다듬는다."""
    try:
        return enhance_uploaded_photo(photo)
    except (OSError, ValueError):
        return photo.convert("RGB")


def _uploaded_ad_photo(
    photo: Image.Image,
    brief: AdBrief,
    store: Store,
    style: Style,
) -> tuple[Image.Image, bool]:
    """OpenAI면 스타일별 광고 재촬영, 로컬이면 비용 없는 안전 보정.

    레퍼런스를 같이 올렸으면 그 분위기까지 재촬영 지시에 얹는다 — 사진 보존(3번)과
    레퍼런스(2번)는 서로를 끄지 않는다.
    """
    if image_profile() == "openai":
        result = restage_photo(
            photo,
            product=brief.product,
            industry=store.industry_label,
            situation=brief.situation,
            tone=brief.tone,
            extra=brief.extra,
            transcript=brief.raw_utterance,
            style=style,
            size=(1080, 1080) if style == "simple" else (1080, 720),
            reference=_reference_mood(brief),
        )
        return result.image, result.staged
    return _safe_uploaded_photo(photo), False


def _keeps_photo(brief: AdBrief) -> bool:
    """올린 사진을 통째로 살리는 경로로 갈지.

    레퍼런스를 같이 올렸다면 **그 분위기를 반영할 수 있을 때만** 사진을 통째로
    쓴다. openai 는 재촬영 지시에 얹을 수 있고(3번+2번), local 은 안전 색보정뿐이라
    얹을 자리가 없어서 누끼+생성 배경으로 내려가야 레퍼런스가 살아난다.
    """
    return brief.ref_id is None or image_profile() == "openai"


def _reference_mood(brief: AdBrief) -> str:
    """레퍼런스에서 읽은 분위기 구절. 없거나 못 읽으면 빈 문자열 — 광고는 만든다."""
    if brief.ref_id is None:
        return ""
    loaded = photo_store.load(brief.ref_id)
    return ref_style.describe_style(*loaded) if loaded else ""


def _with_reference(brief: AdBrief, prompt: str) -> str:
    """레퍼런스가 있으면 그 분위기를 프롬프트 뒤에 얹는다 (이미지 2번).

    이미지를 확산 모델에 직접 넣는 길(IP-Adapter·img2img)은 둘 다 막혀서
    말로 바꿔 넣는다 — 자세한 근거는 ref_style 참고.
    """
    return ref_style.apply_to(prompt, _reference_mood(brief))


def _background(brief: AdBrief, prompt: str) -> Image.Image:
    """배경 한 장. 스케치가 있으면 그 구도를 따라 그린다 (이미지 4번).

    스케치가 없으면 이미지 백엔드가 그린다 — IMAGE_PROFILE 이 openai 면 GPT,
    아니면 sd-turbo. 스케치 갈래는 로컬 전용이라 그대로다 (docs/09 v1).
    """
    if brief.sketch_id is None:
        return generate_scene(prompt)

    path = photo_store.path_of(brief.sketch_id)
    if path is None:
        return generate_scene(prompt)

    with Image.open(path) as sketch:
        return sketch_gen.generate_from_sketch(sketch.copy(), prompt)


def _simple_materials(brief: AdBrief, store: Store, product: Image.Image | None) -> SimpleMaterials:
    """제품 누끼가 있으면 빈 무대 배경에 얹고, 없으면 제품이 든 장면을 통째로 그린다.

    빈 무대 프롬프트(_BASE)는 누끼를 얹으려고 제품을 일부러 뺀 캔버스다. 그 위에
    올릴 게 없으면 광고 대상이 사라진다 — generate 갈래·사진 없는 주문이 그 경우다.

    **스케치는 여기서 갈래를 바꾸지 않는다.** 각 입력의 뜻이 그대로 유지된다 —

      제품 사진 있음 + 스케치   빈 무대를 스케치 구도로 그리고 그 위에 누끼를 얹는다
                               (사진 = 이 상품을 살린다 · 스케치 = 이 배치로)
      제품 사진 없음 + 스케치   product 가 None 이라 hero 로 간다. 스케치가 상품을 그린다

    ⚠️ 전에 `or brief.sketch_id is not None` 을 달았다가 뺐다. 스케치 기능을
    만들 때는 이 함수에 `product is None` 분기가 없어서 필요했는데, #22 가
    들어오면서 그쪽이 이미 같은 경우를 덮었다. 남겨두니 **사진과 스케치를 같이
    올렸을 때 배경에도 제품이 그려지고 누끼도 얹혀 제품이 둘로** 나왔다.
    """
    if product is None:
        if brief.sketch_id is not None:
            # 스케치 생성(sd-turbo+ControlNet)은 CLIP 입력이 짧다 — 긴 촬영 기획
            # 프롬프트는 잘려서 구도 지시가 약해진다. 스케치 주문은 짧은 주인공
            # 프롬프트를 유지한다 (제품이 들어 있어 "흐릿한 덩어리"도 안 된다).
            prompt = build_hero_prompt(store.industry_label, brief.product, brief.tone)
        else:
            prompt = build_scene_prompt(
                shop=store.name,
                location=store.address,
                industry=store.industry_label,
                product=brief.product,
                situation=brief.situation,
                tone=brief.tone,
                extra=brief.extra,
                transcript=brief.raw_utterance,
            )
    else:
        prompt = build_bg_prompt(store.industry_label, brief.situation, brief.tone)

    prompt = _with_reference(brief, prompt)
    # product 가 없으면 상품까지 AI 가 그린 것이다 → "연출된 이미지" 표기.
    return SimpleMaterials(
        product=product,
        background=_background(brief, prompt),
        shop=store.name,
        preserved_photo=False,
        staged=product is None,
    )


def _poster_materials(brief: AdBrief, store: Store, product: Image.Image | None) -> PosterMaterials:
    """포스터에 들어갈 내용(태그라인·특징·이벤트·색)은 기획 부품이 정한다.

    사장님에게 특징 3개를 직접 쓰게 하면 서비스가 아니라 양식 작성이 된다.
    """
    # ⚠️ product 는 아래에서 덮어써지므로 **지금** 판단해야 한다.
    # 덮어쓴 뒤에 보면 항상 사진이 있는 것처럼 보여 표기가 영영 안 붙는다.
    staged = product is None

    if product is None:
        # 사진이 없으면 주인공 이미지를 생성해 그 자리를 채운다 (사진 카드처럼 얹힌다)
        hero_prompt = build_hero_prompt(store.industry_label, brief.product, brief.tone)
        # 레퍼런스는 여기에도 얹는다 — 배경만 분위기를 따르고 주인공은 안 따르면
        # 한 장 안에서 두 느낌이 부딪힌다.
        product = generate_background(_with_reference(brief, hero_prompt)).convert("RGBA")

    plan = plan_poster(
        shop=store.name,
        industry=store.industry_label,
        product=brief.product,
        situation=brief.situation,
        tone=brief.tone,
        extra=brief.extra,
        transcript=brief.raw_utterance,
    )
    return PosterMaterials(
        product=product,
        plan=plan,
        shop=store.name,
        info=_info_line(store),
        staged=staged,
    )


def prepare_materials(
    brief: AdBrief,
    store: Store,
    style: Style = "simple",
) -> AdMaterials:
    """비싼 단계 전부 ─ 사진 보정·배경 생성·포스터 기획. **문구를 모른다.**

    일반 업로드 사진은 IMAGE_PROFILE=openai일 때 감성형·포스터형 목적에 맞춰 각각
    광고 촬영본으로 재연출한다. 실패하거나 local 프로필이면 좌표를 유지한 안전
    색보정으로 끝낸다. 레퍼런스·스케치를 명시한 감성형은 기존 누끼 계약을 지킨다.
    """
    photo = cut = None
    if brief.photo_id is not None:
        path = photo_store.path_of(brief.photo_id)
        if path is None:
            raise FileNotFoundError(f"보관함에 {brief.photo_id}번 사진이 없습니다")
        with Image.open(path) as f:
            photo = ImageOps.exif_transpose(f).copy()

    # 사진을 올렸으면 **사진 보존(3번)이 기본 경로**다. 레퍼런스를 같이 올려도
    # 끄지 않는다 — 분위기는 재촬영 지시에 얹혀서 함께 반영된다(_uploaded_ad_photo).
    #
    # 🪤 전에는 `ref_id is None` 까지 걸려 있어서, 레퍼런스를 같이 올리면 3번이
    #    통째로 꺼지고 옛날 누끼 합성으로 빠졌다. 사장님은 "사진 있음 + 이런 느낌"
    #    을 고른 건데 실제로는 상품이 오려져 나갔다.
    #
    # 스케치는 남긴다 — **사진 없음 갈래의 입력**이라 사진과 같이 오면 구도 지시가
    # 우선이고, 실제 상품 누끼를 그 구도 위에 얹어야 한다.
    #
    # 🪤 local 프로필에서는 레퍼런스가 있으면 이 경로로 오면 안 된다. 로컬은 재촬영을
    #    못 해서 안전 색보정만 하는데, 거기엔 분위기를 얹을 자리가 없다 — 사장님이
    #    올린 레퍼런스가 **아무 일도 안 하고 사라진다.** 그때는 누끼+생성 배경으로
    #    내려가야 분위기가 배경 프롬프트에 실제로 반영된다.
    if style == "simple" and photo is not None and brief.sketch_id is None and _keeps_photo(brief):
        background, staged = _uploaded_ad_photo(photo, brief, store, "simple")
        return SimpleMaterials(
            product=None,
            background=background,
            shop=store.name,
            preserved_photo=True,
            staged=staged,
        )

    if style == "poster" and photo is not None:
        poster_photo, staged = _uploaded_ad_photo(photo, brief, store, "poster")
        return UploadedPhotoPosterMaterials(
            photo=poster_photo,
            shop=store.name,
            info=_info_line(store),
            product_name=brief.product,
            staged=staged,
        )

    if photo is not None:
        # 레퍼런스·스케치는 실제 상품을 따로 얹어야 하므로 이때만 누끼를 딴다.
        cut = remove_crumbs(remove_background(photo))

    if style == "poster":
        # 누끼가 빈손(전경 5% 미만)이면 없는 셈 친다 — 실오라기가 제품 자리에 앉는 것 방지
        product = cut if cut is not None and mask_area(cut) >= 0.05 else None
        return _poster_materials(brief, store, product)

    if photo is not None:
        # 레퍼런스·스케치를 함께 준 경우에는 실제 상품 누끼를 보존하고, 명시한
        # 분위기·구도만 배경 생성에 반영한다. 누끼가 비면 생성 주인공으로 폴백한다.
        product = cut if cut is not None and mask_area(cut) >= 0.05 else None
        return _simple_materials(brief, store, product)

    return _simple_materials(brief, store, None)


def render_no_text_ad(materials: SimpleMaterials) -> Image.Image:
    """감성형 재료를 광고 문구 없이 사진 한 장으로 완성한다.

    사진 전체나 통생성 장면은 이미 상품을 포함하므로 그대로 규격만 맞춘다.
    레퍼런스·스케치 주문처럼 상품 누끼와 배경이 분리된 경우에는 글자 없는
    전용 합성기로 상품을 얹어 사라지지 않게 한다.
    """
    return compose_no_text(
        materials.product,
        background=materials.background,
        staged=materials.staged,
    )


def generate_no_text_ad(brief: AdBrief, store: Store) -> Image.Image:
    """주문서와 가게를 받아 글자 없는 감성 사진 한 장을 돌려준다."""
    materials = prepare_materials(brief, store, "simple")
    if not isinstance(materials, SimpleMaterials):
        raise TypeError("글자 없는 결과물은 감성형 재료만 사용할 수 있습니다")
    return render_no_text_ad(materials)


def render_ad(materials: AdMaterials, copy: CopyCandidate) -> Image.Image:
    """재료에 문구를 얹는다 — **문구가 처음 쓰이는 곳.**

    싼 단계(글자 그리기)만 있다. 문구를 바꾸면 여기만 다시 부르면 되고,
    비싼 재료(GPU 배경·LLM 기획·비전 판정)는 그대로 재사용된다 (광고완성흐름 §4-1).
    """
    if isinstance(materials, UploadedPhotoPosterMaterials):
        return generate_uploaded_photo_poster(
            materials.photo,
            materials.shop,
            headline=copy.headline,
            product_name=materials.product_name,
            sub=copy.sub,
            info=materials.info,
            staged=materials.staged,
        )
    if isinstance(materials, PosterMaterials):
        plan = materials.plan
        return generate_poster(
            materials.product,
            materials.shop,
            tagline=plan.tagline,
            badge=plan.badge,
            date_line=plan.date_line,
            features=plan.features,
            event=plan.event,
            headline=copy.headline,
            info=materials.info,
            palette=plan.palette,
            staged=materials.staged,
        )
    return compose_ad(
        materials.product,
        copy.headline,
        copy.sub,
        background=materials.background,
        staged=materials.staged,
        shop=materials.shop,
        preserved_photo=materials.preserved_photo,
    )


def generate_ad(
    brief: AdBrief,
    store: Store,
    copy: CopyCandidate,
    style: Style = "simple",
) -> Image.Image:
    """주문서·가게·문구를 받아 완성 광고 한 장을 돌려준다 — 기존 호출부 호환용.

    안은 재료 준비와 조판 두 단계다. 문구만 바꿀 때는 이걸 다시 부르지 말고
    prepare_materials 결과를 들고 render_ad 만 다시 부른다.
    """
    return render_ad(prepare_materials(brief, store, style), copy)


def render_output(
    materials: AdMaterials,
    output_type: OutputType,
    copy: CopyCandidate | None = None,
) -> Image.Image:
    """재료에 결과물 유형에 맞는 마무리를 한다 — **싼 단계만.**

    사진만 다시 만들 때는 prepare_output 을, 문구만 바꿀 때는 이 함수만 다시
    부른다 (PDF STEP 5). 비싼 재료(GPT 재촬영·확산 배경·포스터 기획)는 재사용된다.
    """
    if output_type == "emotional_no_text":
        if not isinstance(materials, SimpleMaterials):
            raise TypeError("글자 없는 결과물은 감성형 재료만 사용할 수 있습니다")
        return render_no_text_ad(materials)
    if copy is None:
        raise ValueError(f"{output_type} 은 문구가 있어야 만들 수 있습니다")
    return render_ad(materials, copy)


def prepare_output(brief: AdBrief, store: Store, output_type: OutputType) -> AdMaterials:
    """결과물 유형에 맞는 재료를 준비한다 — **비싼 단계 전부, 문구는 모른다.**"""
    return prepare_materials(brief, store, style_of(output_type))


def generate_output(
    brief: AdBrief,
    store: Store,
    output_type: OutputType,
    copy: CopyCandidate | None = None,
) -> Image.Image:
    """결과물 유형 하나로 광고 한 장을 만든다 — 화면이 부르는 단일 진입점.

    어떤 이미지 기능이 도는지는 여기서 정하지 않는다. 주문서에 무엇이 담겼는지가
    정한다 (prepare_materials) —

        사진 있음 + 레퍼런스   3번 보존 + 2번 분위기   (둘 다 반영)
        사진 있음             3번 보존
        사진 없음 + 스케치     4번 스케치 구도
        사진 없음             1번 통생성

    output_type 은 그 위에 **글자를 얹을지**만 정한다.
    """
    return render_output(prepare_output(brief, store, output_type), output_type, copy)
