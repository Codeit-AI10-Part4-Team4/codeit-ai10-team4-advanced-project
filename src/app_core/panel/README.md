# src/app_core/panel/

**현재 버전 V2** · 최종 수정 2026-08-07
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
| `schemas.py` | **수호 단독** | 07 §12 확정(`a0c931f`). 아인님은 변경 요청 |
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

**성별과 연령이 한 축이 아니라 두 축이다.**
서울시 원본에 성별×연령 교차 데이터가 없다(07 §4.4①). "30대 여성 매출"이라는
값 자체가 존재하지 않아 두 축을 따로 두고 페르소나에서 곱한다. 그래서 `evidence`도
곱한 값이 아니라 원본 두 값을 각각 인용해야 대조가 1:1로 맞는다.

**시간대는 유동인구가 아니라 매출 기준이다.**
지나다니는 사람과 사는 사람이 다르다(07 §4.4③). 유동인구는 `foot_age_share`,
동네 주민은 `back_age_share`로 남겨 경계 페르소나 근거로 쓴다.
`back_age_share`는 골목상권에만 있어 발달상권(역삼역)에서는 `None`이다 —
매핑이 `None`일 수 있으므로 `resolve()`에 방어가 들어 있다.

**상권 성격은 추론이 아니라 실측이다.**
`motive` 판정이 "점심에 팔리니 직장인 상권"이라는 추론에서 `work_ratio` 실측으로
바뀌었다(07 §7.1). `worker_pop`·`resident_pop`·`apt_avg_price` 등을 스키마에
두지 않으면 Pydantic이 조용히 버려서 평가 프롬프트에 넣을 수가 없다.

**`axes.time` enum이 5종이다.**
`morning / weekday_lunch / afternoon / evening / weekend`. `weekend`는
`weekend_ratio > 0.4`일 때만 나온다(역삼역 0.138이라 없음).
`Persona.axes`를 `dict[str, str]`이 아니라 모델로 고정했기 때문에 값이 검증된다.

**`is_fallback` / `match_distance_m`은 07 §6에 없는 추가 필드다.**
06 §5가 "서울 평균 폴백 시 결과 화면에 배지"를 요구하는데 그 플래그가 없었다.
기본값이 있어 A쪽이 안 채워도 파싱은 된다.

**신뢰도를 떨어뜨리는 사유가 셋이고, 화면 문구가 달라야 한다.**
폴백(동네 데이터 없음) · `demo_coverage < 0.5`(미상 매출 과다, 07 §4.4②) ·
분산 초과(손님별 평가가 갈림). 셋을 한 플래그로 뭉치면 사장님에게 무엇이
문제인지 못 알려주므로 `confidence_reasons`에 사유를 따로 남긴다.
**업종 폴백은 여기 넣지 않는다** — 정밀도만 낮아질 뿐 "우리 동네" 그라운딩은
유지되고(07 §4.5), `realestate`처럼 커버리지 1%인 업종은 폴백이 기본이라
항상 "신뢰도 낮음"이 뜨면 배지가 무의미해진다.

**매칭·데이터 품질 지표는 근거로 인용할 수 없다.**
`match_distance_m` · `demo_coverage`. 상권 특성이 아닐뿐더러, 이런 수치로도
근거 요건이 충족되면 LLM이 실제 인구·행동 데이터를 보지 않고 검증 게이트를
통과한다 — 게이트의 목적이 무너진다. 실패 사유는 `unknown_path`가 아니라
`not_citable`로 구분해 로그에서 오타와 정책 위반을 가른다.

**`aggregate()`는 `suggestions`를 만들지 않는다.**
개선 제안은 집계가 아니라 요약 콜의 산출물이라(07 §7.3) 인자로 받아 실어 나르기만
한다. 그런데 07 §7은 "패널 모듈 LLM 콜은 서사 1콜 + 평가 ≤20콜 둘뿐"이라 했고
제안을 만들 콜이 명세에 없다 — F5에서 요약 1콜을 제안했다.

## 규칙

- `schemas.py`는 수호 단독 소유다(07 §12). 아인님 요청은 받되 편집은 수호가 한다.
- `docs/`·픽스처·`features.py`·`panel_builder.py`는 아인님 소유다. 고치지 말고 요청한다.
- `configs/*.yaml`·`flow.yaml`은 기본 파이프라인 소유다. 업종 추가가 필요하면 PR 전에 공유.
- 외부 API 호출은 테스트에서 mock. 실 호출은 비용·비결정성으로 금지.
- 파일을 추가·변경하면 **아래 표에 한 줄 추가하고 상단 버전을 올린다.**

## 변경 이력

| 버전 | 날짜 | 변경 | 이유 |
|---|---|---|---|
| **V1** | 2026-08-06 | `schemas.py`·`evidence.py`·`aggregate.py` 최초 추가 | F0 계약을 먼저 고정해 A·B 병렬 착수. LLM 호출 없이 결정적 로직만 올려 CI 통과 확보 |
| **V2** | 2026-08-07 | ① CSV 실물 검수(07 §4.4) 반영 — `sales_share`·`time_traffic` 폐기, `gender_share`·`age_share`·`demo_coverage`·`time_share`·`foot_age_share`·`avg_ticket_pct`·`category_cds`·`is_category_fallback` 도입 ② 배후지·직장인구·아파트 7필드 추가 ③ `match_distance_m`·`demo_coverage` 인용 금지 ④ `ad_id`·`suggestions`·`confidence_reasons` 추가 ⑤ 단수 `category_cd` 한시 변환기 제거 | 원본에 성별×연령 교차가 없고 주문서 구조가 05로 바뀜. 신규 피처는 스키마에 없으면 Pydantic이 버려서 평가 프롬프트에 못 넣는다. 인용 금지는 아인님 지적(`match_distance_m`)에 같은 성격인 `demo_coverage`를 더한 것 |
