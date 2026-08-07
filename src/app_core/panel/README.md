# src/app_core/panel/

**현재 버전 V1** · 최종 수정 2026-08-06
담당: 이아인(데이터·패널) · 이수호(평가·집계)

AI 손님 패널 — 상권 데이터로 구성한 가상 손님이 완성된 광고물을 평가하는 모듈.
기획은 [05](../../../docs/05_AI손님패널_기획.md), 기술계획은 [06](../../../docs/06_기술계획서_품질검증.md).

## 경계

기본 파이프라인(`generation`) 코드를 **import 하지 않는다.** 계약은 아래 하나뿐이다.

```
evaluate(image, headline, sub, items, context) -> EvaluationResult
                                                       └─(suggestions)─> 재생성
```

반대 방향도 함수 하나로만 부른다. 이 경계가 흐려지면 두 파트가 서로를 기다리게 된다.

내부 경계는 `build_features(address, category) -> TradeAreaFeatures` 하나다.
이 함수 앞이 아인님, 뒤가 수호님이다.

| 파일 | 담당 | 비고 |
|---|---|---|
| `schemas.py` | **공동** | 변경은 PR로. 고치기 전에 상대에게 알릴 것 |
| `features.py` | 아인 | `build_features()` |
| `panel_builder.py` | 아인 | 세그먼트 룰·서사·가중치 |
| `evidence.py` | 수호 | 근거 대조 |
| `aggregate.py` | 수호 | 가중 집계·분산 체크 |
| `evaluator.py` | 수호 | LLM 호출·검증 (예정) |

## 설계 결정 — 코드만 봐서는 안 보이는 것

**정량은 코드, LLM은 서사만.** 세그먼트·가중치·집계·근거 대조는 전부 결정적 코드다.
LLM은 `narrative`와 평가 문장만 만든다. 신뢰 판단의 근거는 모델의 자기보고가 아니라
코드 검증 결과여야 하기 때문이다. `evidence.py`가 그 집행 지점이다.

**경계 페르소나는 점수에서 빼고 코멘트·저항 요인에는 남긴다.**
06 §7.1의 "점수 기여가 아니라 저항 요인·코멘트 다양성 목적"을 그대로 구현했다.
뺀 만큼 가중치를 재정규화한다. `include_boundary_in_scores=True`로 뒤집을 수 있게
열어둔 것은 비교 실험용이다.

**`axes.time` enum이 3종이 아니라 5종이다.**
06 §7.1 초안은 `weekday_lunch / evening / weekend`인데 실제 산출(역삼 샘플)에
`morning`·`afternoon`이 나왔다. 카페 상권에서 오전·오후는 다른 손님이라 넓혔다.
`Persona.axes`를 `dict[str, str]`이 아니라 모델로 고정한 덕에 발견한 불일치다.

**`is_fallback` / `match_distance_m`은 06 스키마에 없는 추가 필드다.**
05 §5.1이 "서울 평균 폴백 시 결과 화면에 배지"를 요구하는데 그 플래그가 없었다.
폴백이면 분산과 무관하게 `confidence="low"`로 떨어뜨린다.
기본값이 있어 A쪽이 아직 안 채워도 파싱은 된다.

## 규칙

- `schemas.py`는 둘 다 건드린다. 변경 전 공유, PR로만.
- `configs/*.yaml`·`flow.yaml`은 기본 파이프라인 소유다. 업종 추가가 필요하면 PR 전에 공유.
- 외부 API 호출은 테스트에서 mock. 실 호출은 비용·비결정성으로 금지.
- 파일을 추가·변경하면 **아래 표에 한 줄 추가하고 상단 버전을 올린다.**

## 변경 이력

| 버전 | 날짜 | 변경 | 이유 |
|---|---|---|---|
| **V1** | 2026-08-06 | `schemas.py`·`evidence.py`·`aggregate.py` 최초 추가 | F0 계약을 먼저 고정해 A·B 병렬 착수. LLM 호출 없이 결정적 로직만 올려 CI 통과 확보 |
