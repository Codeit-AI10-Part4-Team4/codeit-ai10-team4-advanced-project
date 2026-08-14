"""패널 점수와 사람 평가의 일치도 지표.

`(예측, 정답) -> 점수` 형태의 순수 함수만 둔다. 외부 의존성 없음.

AI 패널이 실제 사람 평가를 얼마나 따라가는지 재는 데 쓴다.
팀원이 광고 시안을 블라인드로 평가한 값을 정답으로 놓고 상관을 보면,
"이 평가를 믿어도 되나"에 대한 유일한 외부 근거가 된다.
"""

from __future__ import annotations

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

#: 코멘트가 가격을 **문제가 아니라고** 말할 때 쓰는 표현.
#: 실측에서 12명이 하나같이 이렇게 말하면서 걸림돌은 `price` 를 골랐다.
PRICE_PRAISE: Final = ("괜찮", "적당", "저렴", "매력적", "합리적", "나쁘지 않")


def price_contradictions(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """가격을 칭찬하면서 걸림돌이 `price` 인 코멘트를 모은다.

    `pairs` 는 `(코멘트, 걸림돌 라벨)`.

    "걸림돌이 price 로 쏠린다"는 그 자체로는 결함이 아니다 — 정말 비싼 광고면
    맞는 답이다. 결함인 것은 **가격이 괜찮다고 말하면서 가격을 걸림돌로 고르는
    것**이고, 그건 광고가 아니라 프롬프트를 보고 답했다는 뜻이다.

    느낌으로 "이상하다"를 판단하다가 여러 번 헛짚어서, 세는 것으로 바꾼다.
    낱말 맞추기라 완벽하진 않다. **판정이 아니라 계기판으로 쓴다.**
    """
    return [
        comment
        for comment, label in pairs
        if label == "price" and any(word in comment for word in PRICE_PRAISE)
    ]
