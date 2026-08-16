"""사진 갈래 판정 부품 — 받은 사진을 어떻게 쓸지 정한다.

골든셋 측정(2026-08-13)에서 15장 중 10장이 잘못된 길로 갔다 —
좋은 사진을 해체하거나(원본 살리기감 7장), 흩어진 물건을 억지로 오렸다(3장).
그래서 오리기 전에 갈래부터 정한다.

  keep      사진이 이미 광고 배경감 — 그대로 배경으로 쓰고 글자만 얹는다
  cutout    제품은 좋은데 배경이 별로 — 제품만 오려 새 배경에 얹는다 (기존 방식)
  generate  오릴 대상이 없다 — 사진은 참고만 하고 배경을 새로 그린다
"""

from typing import Literal

from PIL import Image

from app_core import llm

Route = Literal["keep", "cutout", "generate"]

#: 마스크 분석용 축소 크기 — 조각 세기는 대략이면 충분하고, 작아야 빠르다
_GRID = 64


#: 갈래 문턱값 — 골든셋 15장 라벨(eval/run_photo_router.py)로 맞춘 값
_TOO_SMALL = 0.05  #: 전경이 5% 미만 — 누끼가 빈손이라 cutout 불가
_TOO_BIG = 0.75  #: 전경이 75% 이상 — 전경/배경 구분 실패
_PIECE_GRID = 256  #: 조각 분석 격자 — 작은 상품도 보이게 마스크 격자보다 촘촘히
#: 이 미만은 부스러기. 폰 사진 3장 실측(2026-08-16): 부스러기 최대 0.23% / 가장 작은 실제 상품 2.57%.
#: 표본 3장의 임시 실측값이며 일반 기준이 아니다 — 근거: data/component_study/조각면적.csv
_CRUMB = 0.01


def mask_area(cut: Image.Image) -> float:
    """누끼 결과(RGBA)에서 전경이 화면에서 차지하는 비율(0~1)을 잰다.

    조각 수·최대 조각 계산은 뺐다 — 골든셋 실측(2026-08-13)에서 흩어진 물건도
    마스크에선 한 덩어리로 나와, 그 신호로는 아무것도 판정하지 못했다.
    """
    alpha = cut.getchannel("A").resize((_GRID, _GRID), Image.Resampling.NEAREST)
    return sum(b > 127 for b in alpha.tobytes()) / (_GRID * _GRID)


def route_by_mask(area: float) -> Route | None:
    """마스크만으로 확신할 수 있는 갈래. 애매하면 None — 비전 판정(judge_photo)의 몫."""
    if area > _TOO_BIG:
        return "generate"
    return None


_JUDGE_SYSTEM = """너는 동네 가게 광고 제작자다. 사장님이 올린 제품 사진 위에 흰 글자
문구를 얹어 인스타그램 광고 한 장을 만든다. 이 사진을 어떻게 쓸지 딱 하나 고른다.

keep      사진을 통째로 배경으로 쓴다
cutout    주인공만 오려내 새 배경에 얹는다
generate  사진은 버리고 배경을 새로 그린다

판단 기준 — 예쁜 사진인지가 아니라 광고 재료로 문제가 없는지를 본다:
- 주인공(팔려는 것)이 또렷하고 배경에 아래 문제가 없을 때만 keep 이다.
- 배경에 문제가 있으면 cutout 이다: 모르는 사람이 찍혔다 · 팔려는 것과 상관없는
  물건(책·소품·남의 상품)이 같이 나온다 · 어수선해서 글자가 묻힌다.
- 팔려는 것 하나를 짚을 수 없으면 generate 다: 물건이 잔뜩 깔린 진열대 · 매대 ·
  여러 접시가 흩어진 상. 단, 가게 풍경 전체가 정돈된 무드라 그대로 배경이 되면 keep.
- 전문가가 찍은 듯 예뻐도 위 문제가 있으면 keep 이 아니다. "분위기가 좋다"는
  이유만으로 keep 을 고르지 마라.

JSON 만 출력한다: {"route": "keep|cutout|generate", "reason": "한 문장"}"""


def judge_photo(data: bytes, mime: str, client: llm.VisionClient | None = None) -> Route:
    """사진을 직접 보고 갈래를 정한다 — 마스크로는 못 하는 미적 판단.

    클라이언트는 팀 공용 llm 부품에서 받는다 — stub 프로필이면 빈 답이 와서
    cutout 으로 물러난다. 외부 호출이 실패해도 같은 곳으로 물러난다:
    갈래 판정 하나 때문에 광고 생성 전체를 죽일 이유가 없다.
    """
    try:
        out = (client or llm.get_vision_client()).read_image(_JUDGE_SYSTEM, data, mime)
    except Exception:  # noqa: BLE001 — 선택적 사진 판정 실패가 광고 생성을 막으면 안 된다
        return "cutout"
    route = out.get("route") if isinstance(out, dict) else None
    return route if route in ("keep", "cutout", "generate") else "cutout"


def route_photo(data: bytes, mime: str, cut: Image.Image) -> Route:
    """갈래 최종 판정 — `cut` 은 **청소 전** 누끼여야 한다(조각을 모두 봐야 하므로).

    1층(마스크 규칙)이 확신하면 그걸로, 아니면 2층(비전). 마지막에 안전장치 둘 —
      - 의미 있는 조각이 여럿이면 **판정 전에** keep: cutout 은 상품을 지우고
        generate 는 새로 그린다 (실측 2026-08-16: 2.6% 조각이 삭제됨)
      - 누끼가 빈손이면 cutout 금지: 오릴 게 없다
    둘 다 keep 으로 물러난다. generate 는 상품을 새로 그려 모양이 바뀌므로 보존 경로가 아니다.
    """
    if significant_pieces(cut) >= 2:
        return "keep"
    area = mask_area(cut)
    if (verdict := route_by_mask(area)) is not None:
        return verdict
    route = judge_photo(data, mime)
    if route == "cutout" and area < _TOO_SMALL:
        return "keep"
    return route


def _components(cut: Image.Image, grid: int) -> tuple[list[list[int]], int]:
    """알파 마스크의 연결 성분 목록(격자 칸 번호)과 전체 칸 수."""
    alpha = cut.getchannel("A")
    raw = alpha.resize((grid, grid), Image.Resampling.NEAREST).tobytes()
    on = [b > 127 for b in raw]
    seen = [False] * (grid * grid)
    comps: list[list[int]] = []
    for start in range(grid * grid):
        if not on[start] or seen[start]:
            continue
        comp, queue = [], [start]
        seen[start] = True
        while queue:
            i = queue.pop()
            comp.append(i)
            x, y = i % grid, i // grid
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < grid and 0 <= ny < grid:
                    j = ny * grid + nx
                    if on[j] and not seen[j]:
                        seen[j] = True
                        queue.append(j)
        comps.append(comp)
    return comps, grid * grid


def piece_areas(cut: Image.Image, grid: int = _PIECE_GRID) -> list[float]:
    """누끼 조각들의 면적비(화면 대비), 큰 것부터."""
    comps, cells = _components(cut, grid)
    return sorted((len(c) / cells for c in comps), reverse=True)


def significant_pieces(cut: Image.Image) -> int:
    """부스러기를 뺀 조각 수 — 2 이상이면 상품이 여럿이라는 뜻이다."""
    return sum(1 for a in piece_areas(cut) if a >= _CRUMB)


def remove_crumbs(cut: Image.Image, grid: int = _PIECE_GRID) -> Image.Image:
    """부스러기(_CRUMB 미만 조각)만 지우고 의미 있는 조각은 모두 남긴다.

    v1 의 `keep_largest` 는 가장 큰 조각 하나만 남겼는데, 실측에서 그 규칙이 두 번째
    상품(2.6%)을 통째로 지웠다. 상품이 사라지면 허위 광고가 되므로 계약을 바꿨다.
    """
    from PIL import ImageChops

    comps, cells = _components(cut, grid)
    keep = {i for c in comps if len(c) / cells >= _CRUMB for i in c}
    if not keep:
        return cut
    mask = Image.frombytes("L", (grid, grid), bytes(255 if i in keep else 0 for i in range(cells)))
    out = cut.copy()
    out.putalpha(
        ImageChops.multiply(cut.getchannel("A"), mask.resize(cut.size, Image.Resampling.NEAREST))
    )
    return out
