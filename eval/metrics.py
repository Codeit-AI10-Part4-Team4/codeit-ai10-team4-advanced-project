"""NLU 슬롯 추출 정확도.

순수 함수만 둔다 — (예측, 정답)만 받는다. chat.py 구현이 바뀌거나 모델을
갈아끼워도 이 파일은 그대로 재사용한다.

**슬롯마다 채점 방식이 다르다.**

  product·price   값이 정확히 같아야 한다
  situation·tone  자유 텍스트라 완전일치가 불가능하다.
                  "판매 부진"과 "판매량 늘리기"는 둘 다 맞는 답이다.
                  그래서 **채워졌는지 여부**만 본다.

자유 슬롯을 완전일치로 채점하면 프롬프트를 고칠 때마다 표현이 조금씩 달라져
점수가 요동친다. 그러면 개선인지 잡음인지 구분할 수 없다.
값의 품질은 리포트에 원문을 같이 찍어 사람이 눈으로 본다.
"""

from __future__ import annotations

#: 값이 정확히 같아야 하는 슬롯
EXACT_SLOTS = ("product", "price")

#: 채워졌는지 여부만 보는 슬롯 (자유 텍스트)
FILLED_SLOTS = ("situation", "tone")

SLOTS = EXACT_SLOTS + FILLED_SLOTS


def _check_same_length(predictions: list[dict], expectations: list[dict]) -> None:
    if len(predictions) != len(expectations):
        raise ValueError("예측과 정답 개수가 다릅니다")


def slot_hit(slot: str, predicted: object, expected: object) -> bool:
    """슬롯 하나가 맞았는가.

    자유 슬롯은 값이 달라도 "채워져야 할 때 채워졌으면" 맞은 것으로 센다.
    """
    if slot in FILLED_SLOTS:
        return bool(predicted) == bool(expected)
    return predicted == expected


def slot_accuracy(predictions: list[dict], expectations: list[dict]) -> dict[str, float]:
    """슬롯별 정확도."""
    _check_same_length(predictions, expectations)
    if not predictions:
        return dict.fromkeys(SLOTS, 0.0)
    return {
        slot: sum(
            1
            for p, e in zip(predictions, expectations, strict=True)
            if slot_hit(slot, p.get(slot), e.get(slot))
        )
        / len(predictions)
        for slot in SLOTS
    }


def overall_accuracy(predictions: list[dict], expectations: list[dict]) -> float:
    """모든 슬롯이 전부 맞은 비율 — 부분 점수 없음."""
    _check_same_length(predictions, expectations)
    if not predictions:
        return 0.0
    correct = sum(
        1
        for p, e in zip(predictions, expectations, strict=True)
        if all(slot_hit(slot, p.get(slot), e.get(slot)) for slot in SLOTS)
    )
    return correct / len(predictions)


def failures(
    predictions: list[dict], expectations: list[dict]
) -> list[tuple[int, dict[str, tuple[object, object]]]]:
    """틀린 것만 추린다 — (몇 번째, {슬롯: (뽑은 값, 정답)}).

    점수만 보면 무엇이 왜 틀렸는지 알 수 없다. 프롬프트를 고칠 단서는 여기에 있다.
    """
    _check_same_length(predictions, expectations)
    out = []
    for i, (p, e) in enumerate(zip(predictions, expectations, strict=True)):
        wrong = {
            slot: (p.get(slot), e.get(slot))
            for slot in SLOTS
            if not slot_hit(slot, p.get(slot), e.get(slot))
        }
        if wrong:
            out.append((i, wrong))
    return out
