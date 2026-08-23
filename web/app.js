/* 동네 광고 만들기 — 화면.
 *
 * 지금은 목업으로 돈다. 백엔드가 서면 API_BASE 한 줄만 채우면 실제 API 를 부른다.
 * 화면 코드는 그대로 두려고 데이터 접근을 api() 하나로 모았다.
 */

/* 서버 주소.
 *
 * 같은 기계에서 열면(로컬 개발) 8000 번의 API 를 찾아보고, 아니면 비워 둔다.
 * 배포된 화면에 서버를 붙일 때는 ?api=https://... 로 한 번 넘겨주면
 * localStorage 에 남아 다음부터 그대로 쓴다 — 주소를 코드에 박지 않기 위해서다. */
const API_BASE = (() => {
  const q = new URLSearchParams(location.search).get('api');
  if (q !== null) {
    if (q) localStorage.setItem('apiBase', q);
    else localStorage.removeItem('apiBase');
  }
  const saved = localStorage.getItem('apiBase');
  if (saved) return saved;
  return location.hostname === 'localhost' || location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000'
    : '';
})();

async function api(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

// 화면이 읽는 데이터 한 벌. 기본은 목업이고, API_BASE 가 채워지면 boot() 이 갈아끼운다.
// const 로 두면 갈아끼울 수가 없어서 let 이다 — 화면은 그릴 때 값을 읽으므로 그대로 반영된다.
let M = window.MOCK;
const RESIST = window.RESISTANCE_LABEL;

/** 상권 숫자가 서버 실측인가. 화면에 표시한다 —
 *  목업과 실측을 구분 못 하면 데모에서 오해가 생긴다. */
let LIVE = false;

/** 화면을 다시 그려도 남아야 하는 값. 서버가 서면 이 자리가 세션으로 바뀐다. */
const S = {
  said: [],          // 사장님이 새로 말한 것
  tone: null,        // 고른 말투
  shots: {},         // { 칸: objectURL } — 올린 사진
  saved: {},         // { 형태: true } — 저장한 이미지
  stores: [],        // 새로 등록한 가게
  revised: null,     // 마지막으로 고쳐달라고 한 말
};

// ── 도구 ─────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);

/** 사장님이 쓴 값은 화면에 그대로 나가므로 태그를 막는다. */
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/** 강조만 살리고 나머지는 막는다.
 *
 * suggestions 는 _summarize() 가 **LLM 에게 받아온 문장**이고 contrast_notes 도
 * 서버가 준 값이다. 그대로 innerHTML 에 꽂으면 API_BASE 를 채우는 순간
 * 모델 출력이 곧 스크립트가 된다. 전부 escape 한 뒤 <b> 만 되살린다. */
const rich = (s) => esc(s).replace(/&lt;b&gt;([\s\S]*?)&lt;\/b&gt;/g, '<b>$1</b>');

/** "20261" → "2026년 1분기" */
const quarter = (q) => (q.length === 5 ? `${q.slice(0, 4)}년 ${q.slice(4)}분기` : q);

const pct = (n) => Math.round(n * 100);

// ── 시그니처: 손님 띠 ────────────────────────────────────────
// 점 하나 = 손님 한 명. 지름은 weight(매출 비중), 색은 걸림돌 유무.
// 지어낸 장식이 아니라 Persona.weight 를 그대로 그린 것이다.

function band(people, { legend = true } = {}) {
  const dots = people.map((p, i) => {
    const size = Math.round(10 + p.weight * 90); // 0.06→15px, 0.14→23px
    const kind = p.is_boundary ? ' band__dot--edge' : p.resistance === 'none' ? '' : ' band__dot--flag';
    return `<span class="band__dot${kind}" style="width:${size}px;height:${size}px;animation-delay:${i * 35}ms"></span>`;
  }).join('');

  const keys = legend ? `
    <div class="band__legend">
      <span class="band__key"><i></i>걸리는 것 없음</span>
      <span class="band__key band__key--flag"><i></i>걸린 게 있음</span>
      <span class="band__key band__key--edge"><i></i>지나가는 손님</span>
    </div>` : '';

  return `<div class="band"><div class="band__dots" role="img"
      aria-label="손님 ${people.length}명. 점 크기는 매출 비중입니다.">${dots}</div>${keys}</div>`;
}

// ── 다시 만들기 ──────────────────────────────────────────────
// 사장님이 "뭘 원하세요"엔 답을 못 해도 "이거 어때요"엔 답한다.
// 그래서 한 번에 맞히려 하지 않고 고쳐가는 길을 둔다 (revise_view).
// 문구 화면과 손님 반응 화면 둘 다에 붙는다 — 두 벌로 만들면 서로 다르게 늙는다.

function revise({ suggestions = null } = {}) {
  return `
    <section class="rule">
      <h2 class="h2">마음에 안 드시면 고쳐드릴게요</h2>
      <div class="chips">
        ${M.revisionOptions.map((o) => `<button class="chip" data-revise="${esc(o)}">${esc(o)}</button>`).join('')}
      </div>
      <form class="compose" data-revise-form style="margin-top:12px">
        <div class="field" style="flex:1">
          <input name="say" placeholder="예: 좀 더 밝게" aria-label="어떻게 고칠지" autocomplete="off">
        </div>
        <button class="btn" style="width:auto;padding:12px 20px">보내기</button>
      </form>
      ${suggestions ? `
        <div class="rule" style="margin-top:20px">
          <p class="eyebrow">손님들의 제안</p>
          <ul class="facts" style="gap:11px">
            ${suggestions.map((s) => `<li style="border-left-color:var(--accent-soft)">${rich(s)}</li>`).join('')}
          </ul>
          <button class="btn" style="margin-top:16px" data-revise="제안 반영">제안 반영해 다시 만들기</button>
        </div>` : ''}
    </section>`;
}

// ── 화면 ─────────────────────────────────────────────────────

const SCREENS = {

  login: {
    title: '',
    bar: false,
    render: () => `
      <div class="stack" style="padding-top:56px">
        <div>
          <p class="eyebrow">동네 광고 만들기</p>
          <h2 class="h1">우리 동네 손님들이<br>먼저 봐드립니다.</h2>
          <p class="lead">광고를 붙이기 전에, 이 동네에서 실제로 사 먹는 사람들이
            뭐라고 할지 들어보세요.</p>
        </div>
        <div class="stack--s">
          <div class="field"><label for="em">이메일</label>
            <input id="em" type="email" inputmode="email" autocomplete="email" placeholder="sajang@example.com"></div>
          <div class="field"><label for="pw">비밀번호</label>
            <input id="pw" type="password" autocomplete="current-password" placeholder="••••••••"></div>
        </div>
        <button class="btn" data-go="stores">로그인</button>
        <p class="muted" style="text-align:center">
          아직 계정이 없으신가요?
          <button class="btn--ghost" data-go="signup">가입하기</button>
        </p>
        <!-- 로그인 화면엔 상단 바가 없어서 화면 목록으로 갈 길이 여기밖에 없다 -->
        <p class="muted rule" style="text-align:center">
          <button class="btn--ghost" style="color:var(--ink-3);font-weight:400" data-drawer>전체 화면 목록 보기</button>
        </p>
      </div>`,
  },

  signup: {
    title: '가입하기',
    bar: true, back: 'login',
    render: () => `
      <div class="stack">
        <div>
          <h2 class="h2" style="font-size:21px">가게 하나만 있으면 시작할 수 있어요</h2>
          <p class="muted">가게는 가입한 뒤에 등록합니다.</p>
        </div>
        <div class="stack--s">
          <div class="field"><label for="su-em">이메일</label>
            <input id="su-em" type="email" inputmode="email" autocomplete="email" placeholder="sajang@example.com"></div>
          <div class="field"><label for="su-pw">비밀번호</label>
            <input id="su-pw" type="password" autocomplete="new-password" placeholder="8자 이상"></div>
          <div class="field"><label for="su-pw2">비밀번호 확인</label>
            <input id="su-pw2" type="password" autocomplete="new-password"></div>
        </div>
        <button class="btn" data-go="storeNew">가입하고 가게 등록하기</button>
      </div>`,
  },

  stores: {
    title: '내 가게',
    bar: true, back: null,
    render: () => `
      <div class="stack">
        <div>
          <h2 class="h2" style="margin-bottom:2px">광고를 만들 가게를 골라주세요</h2>
          <p class="muted">가게 주소로 그 동네 손님을 부릅니다.</p>
        </div>
        <div class="stack--s">
          ${[...M.stores, ...S.stores].map((s) => `
            <button class="card card--tap" data-go="chat">
              <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">
                <strong style="font-size:16px">${esc(s.name)}</strong>
                <span class="tag">${esc(s.industry)}</span>
              </div>
              <span class="muted">${esc(s.address)}</span>
            </button>`).join('')}
        </div>
        <button class="btn btn--line" data-go="storeNew">새 가게 등록하기</button>

        <section class="rule">
          <h2 class="h2">최근에 만든 광고</h2>
          <div class="stack--s">
            ${M.recent.map((a) => `
              <div class="card" style="gap:4px">
                <span class="data">${esc(a.at)} · ${esc(a.product)}</span>
                <strong style="font-size:15px;font-weight:600">${esc(a.headline)}</strong>
              </div>`).join('')}
          </div>
        </section>
      </div>`,
  },

  storeNew: {
    title: '새 가게 등록',
    bar: true, back: 'stores',
    render: () => `
      <form class="stack" data-store-new>
        <div class="field"><label for="sn-name">상호</label>
          <input id="sn-name" name="name" placeholder="행복한 순대국" required></div>

        <div class="field">
          <label for="sn-ind">업종</label>
          <select id="sn-ind" name="industry" required>
            <option value="" disabled selected>골라주세요</option>
            ${M.industries.map((i) => `<option value="${esc(i.label)}">${i.emoji} ${esc(i.label)}</option>`).join('')}
          </select>
          <!-- 업종은 손님 패널이 그 동네 같은 업종 매출을 찾는 열쇠다.
               맞는 업종이 없으면 동네 전체 평균으로 떨어져 객단가가 통째로 달라진다. -->
          <p class="muted">고른 업종으로 그 동네 <b>같은 업종 손님</b>을 찾습니다.
            맞는 게 없으면 동네 전체 평균으로 봅니다.</p>
        </div>

        <div class="field"><label for="sn-addr">주소</label>
          <input id="sn-addr" name="address" placeholder="서울시 마포구 망원동 123-4" required>
          <p class="muted">주소로 상권을 찾습니다. 지번·도로명 다 됩니다.</p></div>

        <div class="field"><label for="sn-tel">연락처</label>
          <input id="sn-tel" name="tel" type="tel" inputmode="tel" placeholder="02-000-0000"></div>

        <button class="btn">등록하고 광고 만들기</button>
      </form>`,
  },

  chat: {
    title: '광고 만들기',
    bar: true, back: 'stores',
    render: () => `
      <div class="stack">
        <div class="card" style="gap:12px">
          <p class="eyebrow" style="margin:0">주문서</p>
          <dl class="slip">
            <dt>홍보 대상</dt><dd>${esc(M.brief.product)}</dd>
            <dt>가격</dt><dd>${esc(M.brief.price)}</dd>
            <dt>상황</dt><dd>${esc(M.brief.situation)}</dd>
            <dt>말투</dt><dd>${esc(S.tone || M.brief.tone)}</dd>
          </dl>
        </div>

        <div class="chat">
          ${[...M.turns, ...S.said].map((t) => `<div class="bubble bubble--${t.who}">${esc(t.text)}</div>`).join('')}
        </div>

        <div class="chips">
          ${M.toneChips.map((c) => `<button class="chip"${S.tone === c ? ' aria-pressed="true"' : ''} data-say="${esc(c)}">${esc(c)}</button>`).join('')}
        </div>

        <form class="compose" data-send>
          <div class="field" style="flex:1"><input name="say" placeholder="직접 입력" aria-label="답변 입력" autocomplete="off"></div>
          <button class="btn" style="width:auto;padding:12px 20px">전송</button>
        </form>

        <div class="rule stack--s">
          <button class="btn btn--line" data-go="photos">
            📷 사진 넣기 ${Object.keys(S.shots).length ? `— ${Object.keys(S.shots).length}장 넣음` : '— 선택'}
          </button>
          <button class="btn" data-go="copy">광고 문구 만들기</button>
        </div>
      </div>`,
  },

  photos: {
    title: '사진 넣기',
    bar: true, back: 'chat',
    render: () => {
      // PHOTO_SLOTS 그대로. read=true 인 제품 사진만 AI 가 읽는다.
      const slots = [
        ['product', '제품 사진', '광고할 제품이 잘 보이도록 찍어주세요', true],
        ['ref',     '레퍼런스',  '이런 분위기로 만들어주세요',           false],
        ['sketch',  '스케치',    '이런 배치·구도로 만들어주세요',        false],
      ];
      const slot = ([key, label, hint, read]) => {
        const url = S.shots[key];
        const body = url
          ? `<img src="${url}" alt="${esc(label)} 미리보기"
                  style="width:100%;height:200px;object-fit:cover;border-radius:var(--r);border:1px solid var(--line)">
             ${read ? `<p class="muted">AI가 읽은 내용 — ${esc(M.photos.product.note)}</p>` : ''}
             <button class="btn btn--line btn--sm" style="width:auto;align-self:flex-start"
                     data-drop="${key}">빼기</button>`
          // hidden 이 아니라 sr-only 다 — hidden 이면 키보드로 닿지 못한다
          : `<label class="slot__drop"><span aria-hidden="true">＋</span><span>${esc(label)} 올리기</span>
               <input type="file" accept="image/png,image/jpeg,image/webp"
                      class="sr-only" data-pick="${key}" aria-label="${esc(label)} 올리기"></label>`;
        return `<div class="slot">
            <div><strong style="font-size:15px">${esc(label)}</strong>
              <p class="muted" style="margin:2px 0 0">${esc(hint)}</p></div>
            ${body}
          </div>`;
      };

      return `
      <div class="stack">
        <div class="note">세 칸 모두 선택입니다. 안 올려도 광고는 만들어집니다.</div>
        ${slot(slots[0])}
        <div class="rule stack">${slot(slots[1])}${slot(slots[2])}</div>
        <p class="muted rule">제품 사진만 AI가 읽어 문구에 반영합니다.
          레퍼런스·스케치는 “어떻게 그릴지”에 대한 지시라 읽지 않습니다.</p>
        <button class="btn" data-go="chat">다 넣었어요</button>
      </div>`;
    },
  },

  // 문구 만들기와 손님 평가는 실제로도 두 단계다 — 평가가 비싸기 때문이다.
  // 후보 1건당 손님 12명을 부르니 셋이면 36콜. 문구만 보고 마음에 안 들면
  // 평가 없이 여기서 바로 다시 만들 수 있어야 한다.
  copy: {
    title: '문구 후보',
    bar: true, back: 'chat',
    render: () => `
      <div class="stack">
        ${S.revised ? `<div class="note note--accent">“${esc(S.revised)}”로 다시 만들었습니다.</div>` : ''}
        <div>
          <h2 class="h2" style="margin-bottom:2px">셋 중에 눈에 들어오는 게 있나요?</h2>
          <p class="muted">고르기 전에 동네 손님들 반응을 먼저 들어보실 수 있습니다.</p>
        </div>

        <div class="stack--s">
          ${M.copies.map((c) => `
            <div class="card">
              <strong style="font-size:18px;letter-spacing:-.02em;line-height:1.35">${esc(c.headline)}</strong>
              <span class="muted" style="font-size:14px">${esc(c.sub)}</span>
              ${c.defects.map((d) => `<div class="note note--flag" style="font-size:13px">⚠ ${esc(d)}</div>`).join('')}
              <button class="btn btn--line btn--sm" data-go="image">이걸로 할게요</button>
            </div>`).join('')}
        </div>

        <div class="rule stack--s">
          <button class="btn" data-go="panel">동네 손님들에게 셋 다 보여주기</button>
          <p class="muted" style="text-align:center">손님 12명이 셋을 다 봅니다. 1분쯤 걸립니다.</p>
        </div>

        ${revise()}
      </div>`,
  },

  panel: {
    title: '손님 반응',
    bar: true, back: 'copy',
    render: () => {
      const r = M.result;
      const people = r.persona_comments;
      const total = people.length + r.excluded_cnt;
      const gap = M.copies[0].intent - M.copies[1].intent;

      const badges = [
        r.is_fallback
          ? '<div class="note note--flag">이 주소로 동네를 찾지 못해 <b>서울 평균</b>으로 봤습니다.</div>' : '',
        r.is_category_fallback
          ? '<div class="note">이 동네에 같은 업종 데이터가 적어 <b>동네 전체 손님 기준</b>으로 봤습니다.</div>' : '',
        r.confidence === 'low'
          ? `<div class="note note--flag"><span>이 평가는 <b>참고만</b> 해주세요.
               <ul>${r.confidence_reasons.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></span></div>` : '',
      ].join('');

      const resist = Object.entries(r.resistance_share)
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `
          <div class="bars__row">
            <span class="bars__name">${esc(RESIST[k] || k)}</span>
            <span class="bars__track"><i class="bars__fill" style="width:${pct(v)}%"></i></span>
            <span class="bars__pct">${pct(v)}%</span>
          </div>`).join('');

      return `
      <div class="stack">
        <!-- 출처를 먼저 밝히고 결론을 말한다. 순서가 바뀌면 근거가 각주가 된다. -->
        <div>
          <p class="data">${esc(r.area_nm)} 상권 · ${quarter(r.quarter)} 실측 · 손님 ${total}명</p>
          ${r.excluded_cnt ? `<p class="muted">근거를 못 댄 ${r.excluded_cnt}명은 빼고 셈했습니다.</p>` : ''}
        </div>

        ${band(people)}
        ${LIVE ? `<div class="note">
          <b>동네 숫자는 서울시 실측</b>입니다 — 상권·객단가·시간대·점포 수.
          손님 코멘트와 점수, 문구 후보는 모델을 불러야 해서 <b>아직 예시</b>입니다.
        </div>` : ''}
        ${badges}

        <div class="note note--accent">
          ${gap >= 2
            ? `손님들은 <b>1위 문구</b>에 가장 마음이 움직였습니다. 2위와 ${gap.toFixed(0)}점 차 — 다시 돌려도 뒤집히지 않는 차이입니다.`
            : '손님 반응은 셋이 비슷했습니다. 아래 지적사항이 없는 쪽을 고르시면 됩니다.'}
        </div>

        <section class="rule">
          <h2 class="h2">문구 후보 셋</h2>
          <div class="stack--s">
            ${M.copies.map((c, i) => `
              <div class="card${i === 0 ? ' card--pick' : ''}">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                  <strong class="data" style="color:${i === 0 ? 'var(--accent)' : 'var(--ink-2)'};font-weight:700">${i + 1}위</strong>
                  <span class="data">방문의향 ${c.intent}</span>
                </div>
                <strong style="font-size:18px;letter-spacing:-.02em;line-height:1.35">${esc(c.headline)}</strong>
                <span class="muted" style="font-size:14px">${esc(c.sub)}</span>
                ${c.defects.map((d) => `<div class="note note--flag" style="font-size:13px">⚠ ${esc(d)}</div>`).join('')}
                <button class="btn ${i === 0 ? '' : 'btn--line'} btn--sm" data-go="image">이걸로 할게요</button>
              </div>`).join('')}
          </div>
        </section>

        <section class="rule">
          <h2 class="h2">무엇이 걸렸나</h2>
          <div class="bars">${resist}</div>
          <p class="muted" style="margin-top:12px">가겠다고 한 손님이 말한 흠은 빼고 셈했습니다.
            합이 100%가 아닌 이유입니다.</p>
        </section>

        <section class="rule">
          <h2 class="h2">손님들이 남긴 말</h2>
          ${people.map((p) => `
            <div class="voice">
              <div class="voice__who">
                <div class="voice__demo">${esc(p.demo)}</div>
                <div class="voice__w">${p.is_boundary ? '지나가는 손님' : `비중 ${pct(p.weight)}%`}</div>
              </div>
              <div class="voice__say">
                ${p.is_boundary ? '<span class="tag tag--edge">점수에는 안 넣음</span> ' : ''}
                <span class="tag${p.resistance === 'none' ? ' tag--ok' : ''}">${esc(RESIST[p.resistance] || p.resistance)}</span>
                <p>${esc(p.comment)}</p>
              </div>
            </div>`).join('')}
        </section>

        <section class="rule">
          <h2 class="h2">동네 숫자와 견줘보면
            <span class="tag${LIVE ? ' tag--ok' : ' tag--edge'}" style="margin-left:6px;font-weight:500">
              ${LIVE ? '서울시 실측' : '예시 값'}</span>
          </h2>
          <ul class="facts">
            ${r.contrast_notes.map((n) => `
              <li class="${n.fit !== null && n.fit < 0.5 ? 'off' : ''}">${rich(n.text)}
                <span class="src">${esc(n.src)}</span></li>`).join('')}
          </ul>
        </section>

        ${revise({ suggestions: r.suggestions })}

        <p class="muted rule">
          손님 ${total}명 중 ${r.excluded_cnt}명은 근거를 대지 못해 셈에서 뺐습니다.<br>
          지나가는 손님 ${people.filter((p) => p.is_boundary).length}명은 코멘트만 싣고 점수에서 뺐습니다.<br>
          평가에 걸린 시간 ${(r.elapsed_ms / 1000).toFixed(1)}초
        </p>
      </div>`;
    },
  },

  image: {
    title: '광고 이미지',
    bar: true, back: 'panel',
    render: () => `
      <div class="stack">
        <div class="note note--accent">고른 문구 — <b>${esc(M.copies[0].headline)}</b></div>

        <div class="stack--s">
          <button class="btn" data-make>광고 이미지 만들기</button>
          <p class="muted" style="text-align:center">20~30초 걸립니다</p>
        </div>

        <div id="shots" class="stack--s rule">
          ${M.images.map((im) => {
            const saved = S.saved[im.style] ?? im.saved;
            return `
            <div class="card">
              <strong style="font-size:15px">${esc(im.label)}</strong>
              <div class="shot"><span class="muted">광고 이미지</span><span class="data">1080 × 1080</span></div>
              <div class="btn-row">
                <button class="btn ${saved ? 'btn--done' : 'btn--line'} btn--sm"
                        data-save="${im.style}" ${saved ? 'disabled' : ''}>${saved ? '저장됨' : '저장'}</button>
                <button class="btn btn--line btn--sm" data-download>다운로드</button>
              </div>
            </div>`;
          }).join('')}
        </div>

        <p class="muted">GPU를 찾지 못해 CPU로 만들었습니다. 장당 18초쯤 걸립니다.</p>
        <button class="btn btn--line" data-make>사진만 다시 만들기</button>
        <p class="muted rule">문구를 바꾸려면 손님 반응 화면에서 다른 것을 고르세요 —
          사진은 그대로 두고 글자만 다시 얹습니다.</p>
      </div>`,
  },
};

const ORDER = [
  ['login',    '로그인'],
  ['signup',   '가입하기'],
  ['stores',   '내 가게'],
  ['storeNew', '새 가게 등록'],
  ['chat',     '대화 — 광고 만들기'],
  ['photos',   '사진 넣기'],
  ['copy',     '문구 후보'],
  ['panel',    '손님 반응'],
  ['image',    '광고 이미지'],
];

// ── 라우팅 ───────────────────────────────────────────────────

function route() {
  const name = location.hash.slice(2) || 'login';
  const screen = SCREENS[name] || SCREENS.login;

  const bar = $('#bar');
  bar.hidden = !screen.bar;
  $('#bar-title').textContent = screen.title;
  $('[data-back]').hidden = !screen.back;
  // ⚠ data-back 으로 두면 안 된다 — 바 자신이 [data-back] 에 걸려서
  //   $('[data-back]') 가 뒤로가기 버튼 대신 바를 잡고, 바가 통째로 숨는다.
  //   클릭도 마찬가지로 바 안 아무 데나 누르면 뒤로 가버린다.
  bar.dataset.backto = screen.back || '';

  const main = $('#main');
  main.innerHTML = screen.render();

  // 화면이 바뀔 때만 맨 위로. 같은 화면을 다시 그리는 것(대화 전송·사진 추가)까지
  // 위로 올려버리면 방금 쓴 말이 화면 밖으로 사라진다.
  if (name !== route.last) {
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    route.last = name;
  }

  document.title = screen.title ? `${screen.title} · 동네 광고 만들기` : '동네 광고 만들기';
  drawList(name);
}

/** 같은 화면으로 가려 하면 hashchange 가 안 떠서 다시 그려지지 않는다 —
 *  문구 화면에서 "다시 만들기"를 누르면 아무 일도 안 일어나던 이유다. */
const go = (name) => {
  const next = `#/${name}`;
  if (location.hash !== next) { location.hash = next; return; }
  // 같은 화면이면 hashchange 가 안 뜬다. 직접 다시 그리고, 눌렀던 버튼이
  // 사라지며 포커스가 body 로 떨어지므로 본문으로 되돌린다.
  route();
  $('#main').focus({ preventScroll: true });
};

// ── 이벤트 ───────────────────────────────────────────────────

document.addEventListener('click', (e) => {
  const goEl = e.target.closest('[data-go]');
  if (goEl) { go(goEl.dataset.go); return; }

  if (e.target.closest('[data-back]')) { go($('#bar').dataset.backto || 'stores'); return; }

  if (e.target.closest('[data-drawer]')) { openDrawer(true); return; }
  if (e.target.closest('[data-drawer-close]') || e.target.id === 'drawer') { openDrawer(false); return; }

  // 말투 칩 — 고른 말투가 주문서에 바로 반영된다
  const say = e.target.closest('[data-say]');
  if (say) { S.tone = say.dataset.say; S.said.push({ who: 'me', text: say.dataset.say }); route(); return; }

  const drop = e.target.closest('[data-drop]');
  if (drop) {
    URL.revokeObjectURL(S.shots[drop.dataset.drop]);   // 안 풀면 탭이 닫힐 때까지 메모리에 남는다
    delete S.shots[drop.dataset.drop];
    route(); return;
  }

  // 다시 만들기 — 문구를 새로 뽑아 문구 화면으로 되돌린다
  const rev = e.target.closest('[data-revise]');
  if (rev) { S.revised = rev.dataset.revise; go('copy'); toast('다시 만들었습니다'); return; }

  const save = e.target.closest('[data-save]');
  if (save) { S.saved[save.dataset.save] = true; route(); toast('저장했습니다'); return; }

  if (e.target.closest('[data-download]')) { toast('목업이라 아직 내려받을 이미지가 없습니다'); return; }

  // 이미지 생성은 서버에서 18초 걸린다. 그동안 화면이 멈춘 것처럼 보이지 않게 한다.
  const make = e.target.closest('[data-make]');
  if (make) fakeMake(make);
});

document.addEventListener('change', (e) => {
  const pick = e.target.closest('[data-pick]');
  if (!pick || !pick.files[0]) return;
  S.shots[pick.dataset.pick] = URL.createObjectURL(pick.files[0]);
  route();
});

document.addEventListener('submit', (e) => {
  const form = e.target.closest('form');
  if (!form) return;
  e.preventDefault();                       // 새로고침되면 쓰던 게 다 날아간다

  if (form.matches('[data-send]')) {
    const text = form.say.value.trim();
    if (!text) return;
    S.said.push({ who: 'me', text });
    route();
    // 다시 그리면 방금 쓰던 입력칸이 사라져 포커스가 body 로 떨어진다.
    // 그대로 두면 한 마디 보낼 때마다 입력칸을 다시 눌러야 한다.
    $('[data-send] input')?.focus();
    return;
  }

  if (form.matches('[data-revise-form]')) {
    const text = form.say.value.trim();
    if (!text) return;
    S.revised = text;
    go('copy');
    toast('다시 만들었습니다');
    return;
  }

  if (form.matches('[data-store-new]')) {
    S.stores.push({
      name: form.name.value.trim(),
      industry: form.industry.value,
      address: form.address.value.trim(),
    });
    go('chat');
    toast('가게를 등록했습니다');
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#drawer').hidden) openDrawer(false);
});

let drawerOpener = null;

function openDrawer(open) {
  $('#drawer').hidden = !open;
  // 시트가 떠 있는 동안 뒤쪽이 탭으로 잡히면 안 보이는 곳으로 포커스가 샌다
  $('.shell').inert = open;
  document.querySelectorAll('[data-drawer]').forEach((b) => b.setAttribute('aria-expanded', String(open)));
  if (open) {
    drawerOpener = document.activeElement;
    $('#drawer-list').querySelector('button')?.focus();
  } else {
    drawerOpener?.focus?.();   // 열었던 자리로 돌려준다
    drawerOpener = null;
  }
}

function drawList(current) {
  $('#drawer-list').innerHTML = ORDER.map(([key, label], i) => `
    <button class="drawer__item" data-go="${key}" ${key === current ? 'aria-current="true"' : ''}>
      <span class="drawer__num">${i + 1}</span>${label}
    </button>`).join('');
}

/** 눌렀는데 아무 일도 안 일어나면 고장으로 읽힌다. 한 줄로 결과를 말한다. */
let toastTimer;
function toast(text) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.className = 'toast';
    el.setAttribute('role', 'status');
    document.body.append(el);
  }
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2000);
}

/** 목업이라 실제로 만들지는 않는다. 기다림이 어떻게 보이는지만 보여준다. */
function fakeMake(btn) {
  const shots = $('#shots');
  if (!shots || btn.dataset.busy) return;
  btn.dataset.busy = '1';
  const label = btn.textContent.trim();
  btn.textContent = '만드는 중...';
  shots.insertAdjacentHTML('beforebegin', '<div class="progress" id="prog"><i></i></div>');
  setTimeout(() => {
    $('#prog')?.remove();
    btn.textContent = label;
    delete btn.dataset.busy;
  }, 2200);
}

$('#drawer-list').addEventListener('click', () => openDrawer(false));

/** 시간대 코드 → 사장님이 읽는 말. 서울시 원본의 구간 그대로다. */
const TIME_LABEL = {
  '00-06': '새벽(0–6시)', '06-11': '아침(6–11시)', '11-14': '점심(11–14시)',
  '14-17': '오후(14–17시)', '17-21': '저녁(17–21시)', '21-24': '심야(21–24시)',
};

const won = (n) => n.toLocaleString('ko-KR');

/** 상권 실측을 받아 화면 문장으로 바꾼다.
 *
 * 여기서 만드는 세 문장은 **LLM 을 거치지 않는다.** 전부 서울시 원본에서
 * 뺄셈·나눗셈으로 나오므로 같은 입력이면 항상 같은 문장이다. 손님 평가가
 * 흔들려도 이 줄들은 흔들리지 않는다 — 화면에서 신뢰의 바닥을 깔아준다. */
async function loadTradeArea() {
  const s = M.stores[0];
  const t = await api(
    `/trade-area?address=${encodeURIComponent(s.address)}` +
    `&industry=${encodeURIComponent(s.industryId)}&lat=${s.lat}&lon=${s.lon}`,
  );

  const r = M.result;
  r.area_nm = t.area_nm;
  r.quarter = t.quarter;
  r.is_fallback = t.is_fallback;
  r.is_category_fallback = t.is_category_fallback;

  const src = `서울시 ${quarter(t.quarter)}`;
  const price = Number(String(M.brief.price).replace(/[^\d]/g, ''));
  const cheaper = price && price < t.avg_ticket;

  r.contrast_notes = [
    price && {
      kind: 'price',
      fit: cheaper ? 0.8 : 0.3,
      text: `광고에 적힌 <b>${won(price)}원</b>은 이 동네 결제 평균 ` +
            `<b>${won(t.avg_ticket)}원</b>보다 ${cheaper ? '낮습니다' : '높습니다'}.`,
      src: `${src} · 객단가`,
    },
    {
      kind: 'timing',
      fit: 0.3,
      text: `이 동네는 <b>${TIME_LABEL[t.peak_time] || t.peak_time}</b>에 가장 많이 팔립니다 ` +
            `— 매출의 ${Math.round(t.peak_share * 100)}%.`,
      src: `${src} · 시간대별 매출`,
    },
    {
      kind: 'competition',
      fit: null,
      text: `같은 업종 가게가 <b>${t.competitor_cnt}곳</b>, 이번 분기에 ` +
            `<b>${t.open_cnt}곳 열고 ${t.close_cnt}곳 닫았습니다.</b>`,
      src: `${src} · 점포 수`,
    },
  ].filter(Boolean);

  // 제안은 원래 LLM 몫이라 아직 목업이다. 그런데 시간대 제안은 "점심에 가장 많이
  // 팔린다"고 적혀 있어서, 실측 피크가 저녁인 동네에서는 바로 옆 문장과 어긋난다.
  // 어긋나는 한 줄만 실측에서 다시 만든다.
  const peak = TIME_LABEL[t.peak_time] || t.peak_time;
  r.suggestions[0] =
    `이 동네는 <b>${peak}</b>에 가장 많이 팔립니다. 광고에서 그 시간대를 말해보시는 건 어떨까요.`;
}

/** 서버가 있으면 서버 값으로, 없거나 실패하면 목업으로 그린다.
 *  화면이 아예 안 뜨는 것보다 목업이라도 뜨는 편이 낫다 — 실패는 콘솔에만 남긴다. */
async function boot() {
  if (API_BASE) {
    try {
      await loadTradeArea();
      LIVE = true;
    } catch (e) {
      console.warn('서버에서 상권을 못 받아 목업으로 그립니다.', e);
    }
  }
  window.addEventListener('hashchange', route);
  route();
}

boot();
