"""사진 갈래 판정 부품 — 받은 사진을 어떻게 쓸지 정한다.

골든셋 측정(2026-08-13)에서 15장 중 10장이 잘못된 길로 갔다 —
좋은 사진을 해체하거나(원본 살리기감 7장), 흩어진 물건을 억지로 오렸다(3장).
그래서 오리기 전에 갈래부터 정한다.

  keep      사진이 이미 광고 배경감 — 그대로 배경으로 쓰고 글자만 얹는다
  cutout    제품은 좋은데 배경이 별로 — 제품만 오려 새 배경에 얹는다 (기존 방식)
  generate  오릴 대상이 없다 — 사진은 참고만 하고 배경을 새로 그린다
"""

from typing import Literal, NamedTuple

from PIL import Image

Route = Literal["keep", "cutout", "generate"]

#: 마스크 분석용 축소 크기 — 조각 세기는 대략이면 충분하고, 작아야 빠르다
_GRID = 64
#: 이보다 작은 조각은 부스러기로 보고 조각 수에 안 센다 (화면의 1%)
_CRUMB = 0.01

#: 갈래 문턱값 — 골든셋 15장 라벨(eval/run_photo_router.py)로 맞춘 값
_TOO_SMALL = 0.05  #: 전경이 5% 미만 — 누끼가 빈손이라 cutout 불가
_TOO_BIG = 0.75  #: 전경이 75% 이상 — 전경/배경 구분 실패
_SCATTERED = 3  #: 조각이 셋 이상 — 물건이 흩어져 있다


class MaskStats(NamedTuple):
    area: float  #: 전경이 화면에서 차지하는 비율 0~1
    pieces: int  #: 부스러기를 뺀 조각 수
    largest: float  #: 가장 큰 조각이 전경 전체에서 차지하는 비율 0~1


def mask_stats(cut: Image.Image) -> MaskStats:
    """누끼 결과(RGBA)의 알파 채널을 읽어 전경의 모양새를 잰다."""
    alpha = cut.getchannel("A").resize((_GRID, _GRID), Image.Resampling.NEAREST)
    raw = alpha.tobytes()
    on = [[raw[y * _GRID + x] > 127 for x in range(_GRID)] for y in range(_GRID)]
    total = sum(map(sum, on))
    if total == 0:
        return MaskStats(0.0, 0, 0.0)

    sizes = []
    seen = [[False] * _GRID for _ in range(_GRID)]
    for y in range(_GRID):
        for x in range(_GRID):
            if not on[y][x] or seen[y][x]:
                continue
            size, queue = 0, [(x, y)]
            seen[y][x] = True
            while queue:
                cx, cy = queue.pop()
                size += 1
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < _GRID and 0 <= ny < _GRID and on[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            sizes.append(size)

    cells = _GRID * _GRID
    big = [s for s in sizes if s / cells >= _CRUMB]
    return MaskStats(total / cells, len(big), max(sizes) / total)


def route_by_mask(stats: MaskStats) -> Route | None:
    """마스크만으로 확실한 수 있는 갈래. 애매하면 None ─ 비전 판정(judge_photo)의 몫

    골든셋 실측(2026-08-13)에서 조각 수로는 흩어짐을 못 잡았다 ─ 흩어진 물건도
    마스크에선 한 덩어리로 붙어 나온다. 흩어짐은 사진을 직접 보는 2층이 판단하고,
    여기는 마스크만 아는 사실(전경 과다 = 오릴 게 화면 전부)만 말한다.
    """
    if stats.area > _TOO_BIG:
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


def judge_photo(data: bytes, mime: str) -> Route:
    """사진을 직접 보고 갈래를 정한다 — 마스크로는 못 하는 미적 판단.

    업로드 때 vision.describe 가 이미 사진을 한 번 보므로, 서비스에선 그 콜에
    합쳐 공짜로 만들 수 있다. 지금은 부품 단독으로도 돌게 따로 둔다.
    """
    import base64
    import json

    from openai import OpenAI  # CI에는 llm extra가 없어 지연 import

    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    rsp = OpenAI().chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]},
        ],
    )

    try:
        out = json.loads(rsp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        out = {}
    route = out.get("route") if isinstance(out, dict) else None
    return route if route in ("keep", "cutout", "generate") else "cutout"


def route_photo(data: bytes, mime: str, cut: Image.Image) -> Route:
    """갈래 최종 판정 — 1층(마스크 규칙)이 확신하면 그걸로, 아니면 2층(비전)."""
    stats = mask_stats(cut)
    if (verdict := route_by_mask(stats)) is not None:
        return verdict
    route = judge_photo(data, mime)
    if route == "cutout" and stats.area < _TOO_SMALL:
        return "keep"  # 오리라는데 누끼가 빈손이다 — 원본이라도 살리는 쪽이 안전하다
    return route


def keep_largest(cut: Image.Image, grid: int = 256) -> Image.Image:
    """누끼 결과에서 가장 큰 덩어리만 남긴다 — 딸려온 조각(책·대리석 등) 청소.

    골든셋 실측에서 나온 처방: 꽃집_밝음(책 더미), 분식_밝음(대리석 조각).
    조각 구분은 축소판(256)에서 빠르게 하고, 지우는 것만 원본 해상도에 적용한다
    — 주인공의 가장자리 품질은 원본 알파가 그대로 지킨다.
    """
    from PIL import ImageChops

    alpha = cut.getchannel("A")
    raw = alpha.resize((grid, grid), Image.Resampling.NEAREST).tobytes()
    on = [b > 127 for b in raw]

    best: list[int] = []
    seen = [False] * (grid * grid)
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
        if len(comp) > len(best):
            best = comp

    if not best:
        return cut

    chosen = set(best)
    keep = Image.frombytes(
        "L", (grid, grid), bytes(255 if i in chosen else 0 for i in range(grid * grid))
    )
    out = cut.copy()
    out.putalpha(ImageChops.multiply(alpha, keep.resize(cut.size, Image.Resampling.NEAREST)))
    return out
