/* 목업 데이터.
 *
 * 모양은 src/app_core/panel/schemas.py 의 EvaluationResult 를 그대로 따른다.
 * 백엔드가 서면 app.js 의 API_BASE 만 채우면 이 파일은 안 쓰인다 —
 * 그때 필드 이름이 어긋나지 않게 여기서부터 실제 스키마를 지킨다.
 *
 * 값은 전부 합성이다. 실제 매장·손님 데이터가 아니다. */

window.MOCK = {

  stores: [
    { id: 1, name: '행복한 순대국', industry: '한식', address: '서울시 은평구 불광동 56-7' },
    { id: 2, name: '홍길동 분식',   industry: '분식', address: '서울시 마포구 망원동 123-4' },
    { id: 3, name: '마포 커피숍',   industry: '카페', address: '서울시 마포구 합정동 88-2' },
  ],

  // 대화 화면 — chat.respond 가 돌려주는 턴을 흉내낸다
  turns: [
    { who: 'ai', text: '어떤 메뉴를 알리고 싶으세요?' },
    { who: 'me', text: '순대국이요. 한 그릇 8,000원이에요.' },
    { who: 'ai', text: '가격을 광고 문구에 넣을까요?' },
    { who: 'me', text: '네, 8,000원 넣어주세요.' },
    { who: 'ai', text: '어떤 상황에 쓰실 광고인가요?' },
    { who: 'me', text: '퇴근길 사람들한테 알리고 싶어요.' },
    { who: 'ai', text: '말투는 어떻게 할까요?' },
  ],
  toneChips: ['친근하게', '따뜻하게', '활기차게', '담백하게'],

  brief: {
    product: '순대국',
    price: '8,000원',
    situation: '퇴근길 직장인 대상',
    tone: '친근하고 따뜻하게',
  },

  photos: {
    // 제품 사진만 vision.describe 로 읽는다. 레퍼런스·스케치는 "어떻게 그릴지"라 안 읽는다.
    product: { filled: true, note: '접시에 담긴 순대국 한 그릇, 김이 오르는 상태, 나무 테이블 위' },
    ref:     { filled: false },
    sketch:  { filled: false },
  },

  copies: [
    { id: 'c1', headline: '퇴근길, 뜨끈한 국물 한 그릇', sub: '순대국 8,000원 · 저녁 6시부터', intent: 54, defects: [] },
    { id: 'c2', headline: '합리적인 가격의 정통 순대국', sub: '불광동에서 20년, 변함없는 맛',   intent: 51, defects: ['금액이 문구에 없습니다'] },
    { id: 'c3', headline: '가성비 최고! 든든한 한 끼',   sub: '지금 바로 방문하세요',           intent: 50, defects: ['금액이 문구에 없습니다'] },
  ],

  // ── EvaluationResult ────────────────────────────────────────
  result: {
    ad_id: 'ad#0',
    area_nm: '불광역',
    quarter: '20261',
    is_fallback: false,
    is_category_fallback: true,
    demo_coverage: 0.91,
    confidence: 'low',
    confidence_reasons: ['지표가 손님마다 크게 갈렸습니다'],
    scores: { attention: 63.8, message: 75.9, intent: 54.0 },
    // 합이 1 이 아니다 — none 을 뺀 값이고, 가겠다고 한 손님의 흠도 뺀다
    resistance_share: { price: 0.42, alternative: 0.25, relevance: 0.18 },
    excluded_cnt: 2,
    elapsed_ms: 24600,
    suggestions: [
      '점심에 가장 많이 팔리는 동네라, 저녁 대신 <b>점심</b>을 말해보시는 건 어떨까요.',
      '가격이 가장 많이 걸렸습니다. 동네 평균보다 싼 편이니 <b>얼마나 싼지</b>를 같이 적어보시죠.',
      '단골집이 있다는 손님이 넷이었습니다. <b>처음 오시는 분께 드리는 것</b>이 있다면 넣어보세요.',
    ],
    persona_comments: [
      { persona_id: 'p1',  demo: '30대 여성', weight: 0.14, is_boundary: false, resistance: 'price',       comment: '8,000원이면 요즘 점심값이랑 비슷해서 크게 끌리진 않네요.' },
      { persona_id: 'p2',  demo: '40대 남성', weight: 0.12, is_boundary: false, resistance: 'none',        comment: '퇴근길이라는 말이 딱 제 얘기라 한번 가보고 싶어요.' },
      { persona_id: 'p3',  demo: '50대 남성', weight: 0.11, is_boundary: false, resistance: 'alternative', comment: '근처에 늘 가던 국밥집이 있어서요.' },
      { persona_id: 'p4',  demo: '40대 여성', weight: 0.10, is_boundary: false, resistance: 'none',        comment: '국물 사진이 따뜻해 보여서 눈이 갔어요.' },
      { persona_id: 'p5',  demo: '50대 여성', weight: 0.09, is_boundary: false, resistance: 'price',       comment: '둘이 가면 16,000원이라 좀 망설여져요.' },
      { persona_id: 'p6',  demo: '30대 남성', weight: 0.09, is_boundary: false, resistance: 'none',        comment: '야근하고 나오면 딱 생각날 것 같아요.' },
      { persona_id: 'p7',  demo: '60대 남성', weight: 0.08, is_boundary: false, resistance: 'alternative', comment: '20년 다닌 데가 있어서 옮기진 않을 것 같아요.' },
      { persona_id: 'p8',  demo: '20대 남성', weight: 0.08, is_boundary: false, resistance: 'relevance',   comment: '저녁은 주로 집에서 먹어서요.' },
      { persona_id: 'p9',  demo: '60대 여성', weight: 0.07, is_boundary: false, resistance: 'price',       comment: '가격이 적혀 있는 건 좋은데 조금 부담돼요.' },
      { persona_id: 'p10', demo: '20대 여성', weight: 0.06, is_boundary: true,  resistance: 'relevance',   comment: '저녁에 이 길을 지나가긴 하는데 국밥을 잘 안 먹어요.' },
    ],
    contrast_notes: [
      { kind: 'price',       fit: 0.8,  text: '광고에 적힌 <b>8,000원</b>은 이 동네 결제 평균 <b>9,546원</b>보다 낮습니다.', src: '서울시 2026년 1분기 · 객단가' },
      { kind: 'timing',      fit: 0.21, text: '광고는 <b>저녁</b>을 말하는데, 이 동네는 <b>점심(11–14시)</b>에 가장 많이 팔립니다 — 매출의 42%.', src: '서울시 2026년 1분기 · 시간대별 매출' },
      { kind: 'competition', fit: null, text: '같은 업종 가게가 <b>34곳</b>, 이번 분기에 <b>3곳 열고 5곳 닫았습니다.</b>', src: '서울시 2026년 1분기 · 점포 수' },
    ],
  },

  images: [
    { style: 'simple', label: '감성 피드형',  saved: false },
    { style: 'poster', label: '정보 포스터형', saved: true  },
  ],
};

/* 걸림돌 한글 이름.
 * 코드에는 price·message·visual·relevance·alternative·none 영문만 있고
 * 대응표가 없다. 여기 둔 것은 제안이고, 팀 확인 뒤 서버로 옮겨야 한다. */
window.RESISTANCE_LABEL = {
  price:       '가격',
  message:     '무슨 말인지 모르겠음',
  visual:      '눈에 안 들어옴',
  relevance:   '나랑 상관없음',
  alternative: '가던 데가 있음',
  none:        '걸리는 것 없음',
};
