"""패널 점수와 사람 평가의 일치도 지표.

`(예측, 정답) -> 점수` 형태의 순수 함수만 둔다. 외부 의존성 없음.

AI 패널이 실제 사람 평가를 얼마나 따라가는지 재는 데 쓴다.
팀원이 광고 시안을 블라인드로 평가한 값을 정답으로 놓고 상관을 보면,
"이 평가를 믿어도 되나"에 대한 유일한 외부 근거가 된다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from math import sqrt
from typing import Final


def _check(pred: Sequence[float], truth: Sequence[float]) -> None:
    if len(pred) != len(truth):
        raise ValueError(f"길이가 다릅니다 (pred {len(pred)}, truth {len(truth)})")
    if len(pred) < 2:
        raise ValueError("표본이 2개 미만입니다")


def pearson(pred: Sequence[float], truth: Sequence[float]) -> float:
    """피어슨 상관계수. 분산이 0이면 0.0을 돌려준다."""
    _check(pred, truth)
    n = len(pred)
    mx = sum(pred) / n
    my = sum(truth) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(pred, truth, strict=True))
    vx = sqrt(sum((x - mx) ** 2 for x in pred))
    vy = sqrt(sum((y - my) ** 2 for y in truth))
    if vx == 0.0 or vy == 0.0:
        return 0.0
    return cov / (vx * vy)


def _average_ranks(values: Sequence[float]) -> list[float]:
    """동점은 평균 순위를 준다."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(pred: Sequence[float], truth: Sequence[float]) -> float:
    """스피어만 순위 상관계수. 점수 자체보다 순위가 중요할 때 쓴다."""
    _check(pred, truth)
    return pearson(_average_ranks(pred), _average_ranks(truth))


def mean_absolute_error(pred: Sequence[float], truth: Sequence[float]) -> float:
    """평균 절대 오차. 0~100 스케일에서 몇 점이나 빗나가는지."""
    _check(pred, truth)
    return sum(abs(x - y) for x, y in zip(pred, truth, strict=True)) / len(pred)


# --- 걸림돌 라벨의 자기모순 (2026-08-14) ------------------------------------

#: 코멘트가 가격을 **문제가 아니라고 단정**할 때 쓰는 표현.
#:
#: 낱말 줄기(`"적당"`)만 보면 안 된다 — 어미가 뜻을 뒤집는다.
#:
#:     "가격이 적당하지만"    값이 괜찮다고 **단정**했다   → 모순 후보
#:     "가격이 적당한지 고민"  괜찮은지 **모르겠다**       → 그냥 불만
#:     "가격이 저렴해서"      싸다고 단정                 → 모순 후보
#:     "더 저렴했으면"        비싸다는 뜻                 → 그냥 불만
#:
#: 첫 판(줄기 매칭)은 실측에서 5건을 잡았는데 **5건 다 오탐**이었다.
#: 그래서 단정형 어미까지 붙여 놓는다. 늘리기 전에 아래 테스트의 실측
#: 코멘트로 반드시 확인할 것.
PRICE_OK: Final = (
    "괜찮지만",
    "괜찮은데",
    "괜찮고",
    "괜찮아서",
    "적당하지만",
    "적당한데",
    "적당해",
    "적당하고",
    "저렴해서",
    "저렴하지만",
    "저렴한데",
    "저렴하고",
    "매력적이지만",
    "매력적이긴",
    "매력적인데",
    "매력적이라",
    "합리적이지만",
    "합리적인데",
    "싸지만",
    "싼데",
    "부담 없",
    "부담스럽지 않",
)


def price_contradictions(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """가격이 괜찮다고 **단정**하면서 걸림돌은 `price` 인 코멘트를 모은다.

    `pairs` 는 `(코멘트, 걸림돌 라벨)`.

    "걸림돌이 price 로 쏠린다"는 그 자체로 결함이 아니다 — 정말 비싼 광고면
    맞는 답이고, 광고에 가격 말고 구체적인 게 없으면 손님이 반응할 것도
    가격뿐이다. 결함인 것은 **가격이 괜찮다고 말해 놓고 가격을 걸림돌로
    고르는 것**이다. 그건 광고가 아니라 프롬프트를 보고 답했다는 뜻이다.

    ⚠️ **칭찬이 무엇을 가리키는지 본다.** 어미만 보면 상품 칭찬을 가격
    칭찬으로 오독한다 (실측 2026-08-21, 2건):

        "평양냉면이 매력적이긴 한데, 가격이 너무 높아서 고민이 됩니다"
         └─ 매력적인 것은 냉면이지 가격이 아니다

    그래서 절을 나눠 **같은 절 안에 가격 말과 칭찬이 함께 있을 때만** 센다.

    낱말 맞추기라 완벽하지 않다. **판정이 아니라 계기판으로 쓴다** —
    놓치는 쪽으로 기울여 두었다. 잘못 울리는 계기판은 안 울리는 것보다 나쁘다.
    """
    return [comment for comment, label in pairs if label == "price" and _praises_price(comment)]


#: 절을 가르는 자리. "A 는 좋은데, B 가 걸린다" 의 쉼표·역접이다.
_CLAUSE: Final = re.compile(r"[,·]|(?<=지만)|(?<=한데)|(?<=는데)|(?<=아서)|(?<=어서)")

#: 가격을 가리키는 말. 이 말이 없는 절의 칭찬은 상품 칭찬이다.
PRICE_WORDS: Final = ("가격", "값", "원")


def _praises_price(comment: str) -> bool:
    """가격을 가리키면서 괜찮다고 단정한 절이 있는가."""
    for clause in _CLAUSE.split(comment):
        if not clause:
            continue
        if any(p in clause for p in PRICE_WORDS) and any(w in clause for w in PRICE_OK):
            return True
    return False
