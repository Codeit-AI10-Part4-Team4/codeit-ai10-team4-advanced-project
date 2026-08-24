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

/** 로그인 토큰.
 *
 * 서버를 다시 띄우면 서명 비밀이 새로 만들어져서 들고 있던 토큰이 401 이 된다.
 * 그때 그냥 두면 "내 가게"가 이유 없이 빈 화면으로 보인다 — 지우고 로그인으로 보낸다. */
const TOKEN = {
  get: () => localStorage.getItem('token'),
  set: (t) => localStorage.setItem('token', t),
  clear: () => localStorage.removeItem('token'),
};

/** 서버 호출 한 곳. body 를 주면 POST 다.
 *
 * 실패하면 서버가 준 detail 을 그대로 던진다 — 사장님께 보여줄 문장으로 쓰여 있다.
 * 다만 422(형식 오류)의 detail 은 배열이라 그대로는 못 보여준다. */
async function api(path, body) {
  const token = TOKEN.get();
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method: body ? 'POST' : 'GET',
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    // 서버가 꺼져 있거나 CORS 로 막히면 fetch 가 통째로 던진다.
    // 브라우저가 주는 말은 "Failed to fetch" 라서 사장님 화면에 그대로 못 쓴다.
    throw new Error('서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해주세요.');
  }
  if (res.ok) return res.json();

  if (res.status === 401 && token) { TOKEN.clear(); S.stores = []; S.store = null; }
  const d = await res.json().catch(() => null);
  const err = new Error(detailText(d, path, res.status));
  err.status = res.status;
  throw err;
}

/** 서버 오류를 사장님이 읽을 문장으로 바꾼다.
 *
 * 400·401·404·409 의 detail 은 문자열이라 그대로 쓴다. 422 만 배열인데, 그 안에서
 * `type: 'value_error'` 인 것만 고른다 — 그건 app_core 의 검증기가 한국어로 쓴
 * 문장("지금은 서울 주소만 지원합니다")이고, 나머지(형식·길이)는 pydantic 이 만든
 * 영어 문장이라 화면에 그대로 내보낼 수 없다. */
function detailText(d, path, status) {
  if (typeof d?.detail === 'string') return d.detail;
  const v = Array.isArray(d?.detail) && d.detail.find((e) => e.type === 'value_error');
  // pydantic 이 앞에 "Value error, " 를 붙여준다
  if (v) return String(v.msg).replace(/^Value error,\s*/, '');
  return `${path} → ${status}`;
}

// 화면이 읽는 데이터 한 벌. 기본은 목업이고, API_BASE 가 채워지면 boot() 이 갈아끼운다.
// const 로 두면 갈아끼울 수가 없어서 let 이다 — 화면은 그릴 때 값을 읽으므로 그대로 반영된다.
let M = window.MOCK;
const RESIST = window.RESISTANCE_LABEL;

/** 상권 숫자가 서버 실측인가. 화면에 표시한다 —
 *  목업과 실측을 구분 못 하면 데모에서 오해가 생긴다. */
let LIVE = false;

/** 목업 결과의 원본. loadTradeArea() 가 M.result 를 실측으로 덮어쓰기 때문에,
 *  가게를 바꿨다가 상권 조회가 실패하면 앞 가게 숫자가 남는다 — 그때 되돌릴 자리다. */
const MOCK_RESULT = JSON.stringify(window.MOCK.result);

/** 화면을 다시 그려도 남아야 하는 값. 서버가 서면 이 자리가 세션으로 바뀐다. */
const S = {
  said: [],          // 사장님이 새로 말한 것
  tone: null,        // 고른 말투
  shots: {},         // { 칸: objectURL } — 올린 사진
  saved: {},         // { 형태: true } — 저장한 이미지
  stores: [],        // 내 가게 목록 (로그인했으면 서버에서 받은 것)
  store: null,       // 고른 가게 — 상권 조회·이미지 요청이 이걸 쓴다

  // ── 서버에서 온 것 ─────────────────────────────────────────
  // 전부 null 이면 화면은 목업으로 그린다. 서버가 없어도(Pages 시연) 흐름은
  // 보여야 해서, 붙이는 게 아니라 **덮어쓰는** 방식으로 둔다.
  draft: null,       // 주문서 — /chat 이 갱신해서 돌려준다. 서버는 상태를 안 든다
  turns: [],         // { who, text } — 사장님과 챗봇이 주고받은 것
  options: [],       // 챗봇이 준 이번 턴의 선택지
  copies: null,      // /ads/copies 결과
  adId: null,        // 그 문구들이 저장된 광고 번호 — /ads/review 가 쓴다
  result: null,      // /ads/review 결과 중 1위 후보의 평가
  margin: null,      // clear_margin — "1등이 낫다"고 말할 기준
  work: {},          // { 이름: 'running'|'failed' } — 진행 중인 서버 작업
  revised: null,     // 마지막으로 고쳐달라고 한 말
  //: { 형태: { status, jobId, error, url, sec } } — 서버에 맡긴 이미지 작업
  jobs: {},
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

// ── 광고 이미지 ──────────────────────────────────────────────
// 한 장에 첫 번째는 54초, 그다음부터는 20초다(실측, GPU 없는 노트북).
// 그동안 화면이 죽은 것처럼 보이지 않게 경과 시간을 세어 보여준다.

/** 형태 한 칸. 아직 안 만들었으면 빈 자리, 도는 중이면 진행, 끝나면 이미지. */
function imageCard(im) {
  const j = S.jobs[im.style];
  const saved = S.saved[im.style] ?? (j ? false : im.saved);

  let body;
  if (j?.status === 'queued' || j?.status === 'running') {
    // 한 번에 하나씩 만든다 — 확산 파이프라인이 스레드 안전하지 않아서다.
    // 줄 서 있는 걸 "만드는 중"이라고 하면 화면이 거짓말을 하게 된다.
    const label = j.status === 'queued' ? '차례를 기다리는 중' : '만드는 중';
    body = `<div class="shot"><span class="muted">${label}</span>
              <span class="data">${j.sec}초</span></div>
            <div class="progress"><i></i></div>`;
  } else if (j?.status === 'failed') {
    // 한 형태가 실패해도 다른 형태는 남는다 — 실패한 칸에만 안내를 띄운다.
    body = `<div class="note note--flag">${esc(im.label)}을(를) 만들지 못했습니다.
              <br><span style="font-size:12px">${esc(j.error || '')}</span></div>`;
  } else if (j?.status === 'done') {
    // API_BASE 를 빼면 화면 오리진(8899)으로 붙어서 이미지가 안 뜬다.
    body = `<img src="${API_BASE}${j.url}" alt="${esc(im.label)} 광고 이미지"
                 style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:var(--r-sm)">`;
  } else {
    body = `<div class="shot"><span class="muted">광고 이미지</span>
              <span class="data">1080 × 1080</span></div>`;
  }

  const canSave = !j || j.status === 'done';
  return `
    <div class="card">
      <strong style="font-size:15px">${esc(im.label)}</strong>
      ${body}
      ${j?.status === 'failed' ? '' : `
        <div class="btn-row">
          <button class="btn ${saved ? 'btn--done' : 'btn--line'} btn--sm"
                  data-save="${im.style}" ${saved || !canSave ? 'disabled' : ''}>${saved ? '저장됨' : '저장'}</button>
          ${j?.status === 'done'
            ? `<a class="btn btn--line btn--sm" style="text-decoration:none"
                  href="${API_BASE}${j.url}" download="${esc(im.label)}.png">다운로드</a>`
            : '<button class="btn btn--line btn--sm" data-download disabled>다운로드</button>'}
        </div>`}
    </div>`;
}

/** 두 형태를 한꺼번에 맡기고 각각 물어본다. 서버가 2개까지 동시에 돌린다. */
async function startImages() {
  const store = picked();
  const body = {
    store_name: store.name,
    // 목업 가게는 industryId, 서버에서 받은 가게는 industry 가 id 다.
    industry: store.industryId || store.industry,
    product: M.brief.product,
    price: Number(String(M.brief.price).replace(/[^\d]/g, '')) || 0,
    headline: copies()[0].headline,
    sub: copies()[0].sub,
    situation: M.brief.situation,
    tone: S.tone || M.brief.tone,
    // '기타' 업종은 이게 없으면 서버가 Store 를 못 만든다
    industry_note: store.industry_note || '',
  };

  for (const im of M.images) {
    S.jobs[im.style] = { status: 'queued', sec: 0 };
    try {
      const res = await fetch(`${API_BASE}/ads/image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, style: im.style }),
      });
      if (!res.ok) throw new Error(`등록 실패 ${res.status}`);
      const { job_id: jobId } = await res.json();
      S.jobs[im.style].jobId = jobId;
      pollJob(im.style, jobId);
    } catch (e) {
      S.jobs[im.style] = { status: 'failed', error: String(e.message || e) };
    }
  }
  route();
}

const busy = (j) => j?.status === 'queued' || j?.status === 'running';

/** 끝날 때까지 2초마다 물어본다. 서버를 재시작하면 404 가 오므로 거기서 멈춘다. */
async function pollJob(style, jobId) {
  const idx = M.images.findIndex((i) => i.style === style) + 1;

  // 1초마다 초만 고쳐 쓴다. 통째로 다시 그리면 옆 칸 이미지가 깜빡인다.
  const tick = setInterval(() => {
    const j = S.jobs[style];
    if (!busy(j)) { clearInterval(tick); return; }
    j.sec += 1;
    const el = document.querySelector(`#shots .card:nth-child(${idx}) .data`);
    if (el) el.textContent = `${j.sec}초`;
  }, 1000);

  while (busy(S.jobs[style])) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const res = await fetch(`${API_BASE}/jobs/${jobId}`);
      if (res.status === 404) throw new Error('작업이 사라졌습니다. 다시 만들어주세요.');
      const st = await res.json();
      const j = S.jobs[style];
      if (st.status === 'done') {
        S.jobs[style] = { status: 'done', url: st.image_url, sec: Math.round(st.elapsed_ms / 1000) };
        route();
      } else if (st.status === 'failed') {
        S.jobs[style] = { status: 'failed', error: st.error };
        route();
      } else if (st.status !== j.status) {
        // 줄에서 빠져나와 실제로 돌기 시작했다 — 문구가 바뀌어야 한다
        j.status = st.status;
        route();
      }
    } catch (e) {
      S.jobs[style] = { status: 'failed', error: String(e.message || e) };
      route();
    }
  }
  clearInterval(tick);
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
        <!-- 서버가 아이디를 이메일로 강제하지 않는다. type="email" 로 두면
             이메일이 아닌 아이디로는 폼이 아예 안 넘어간다. -->
        <form class="stack" data-login>
          <div class="stack--s">
            <div class="field"><label for="em">아이디</label>
              <input id="em" name="username" autocomplete="username" placeholder="sajang@example.com" required></div>
            <div class="field"><label for="pw">비밀번호</label>
              <input id="pw" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required></div>
          </div>
          <button class="btn">로그인</button>
        </form>
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
        <form class="stack" data-signup>
          <div class="stack--s">
            <div class="field"><label for="su-em">아이디</label>
              <input id="su-em" name="username" autocomplete="username" placeholder="sajang@example.com" required></div>
            <div class="field"><label for="su-pw">비밀번호</label>
              <input id="su-pw" name="password" type="password" autocomplete="new-password" placeholder="8자 이상" required></div>
            <div class="field"><label for="su-pw2">비밀번호 확인</label>
              <input id="su-pw2" name="password2" type="password" autocomplete="new-password" required></div>
          </div>
          <button class="btn">가입하고 가게 등록하기</button>
        </form>
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
          ${storeList().length ? storeList().map((s, i) => `
            <button class="card card--tap" data-store="${i}">
              <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">
                <strong style="font-size:16px">${esc(s.name)}</strong>
                <!-- '기타'면 사장님이 직접 적은 이름을 보여준다. 서버의
                     StoreInput.industry_label 이 같은 일을 하지만 @property 라
                     JSON 에 안 실린다 — 그대로 두면 '반찬가게'가 '기타'로 보인다. -->
                <span class="tag">${esc(s.industry_note || indLabel(s.industry))}</span>
              </div>
              <span class="muted">${esc(s.address)}</span>
            </button>`).join('')
            : '<p class="muted">아직 등록한 가게가 없습니다. 아래에서 가게를 등록해주세요.</p>'}
        </div>
        <button class="btn btn--line" data-go="storeNew">새 가게 등록하기</button>

        <!-- 최근 광고는 목업이다. 실제 계정으로 로그인했을 때까지 보여주면
             내가 만든 적 없는 광고가 내 기록처럼 보인다 — 서버에 목록 API 가
             생기기 전까진 로그인 안 했을 때만 띄운다. -->
        ${TOKEN.get() ? '' : `
        <section class="rule">
          <h2 class="h2">최근에 만든 광고</h2>
          <div class="stack--s">
            ${M.recent.map((a) => `
              <div class="card" style="gap:4px">
                <span class="data">${esc(a.at)} · ${esc(a.product)}</span>
                <strong style="font-size:15px;font-weight:600">${esc(a.headline)}</strong>
              </div>`).join('')}
          </div>
        </section>`}
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
            ${M.industries.map((i) => `<option value="${esc(i.id)}">${i.emoji} ${esc(i.label)}</option>`).join('')}
          </select>
          <!-- 업종은 손님 패널이 그 동네 같은 업종 매출을 찾는 열쇠다.
               맞는 업종이 없으면 동네 전체 평균으로 떨어져 객단가가 통째로 달라진다. -->
          <p class="muted">고른 업종으로 그 동네 <b>같은 업종 손님</b>을 찾습니다.
            맞는 게 없으면 동네 전체 평균으로 봅니다.</p>
        </div>

        <!-- '기타'는 서버(StoreInput._other_needs_note)가 industry_note 없이는
             거절한다. 이 칸이 없으면 '기타 (직접 입력)'을 고른 사장님은 무엇을
             고쳐야 하는지도 모른 채 등록에 계속 실패한다. -->
        <div class="field" data-other hidden>
          <label for="sn-note">업종을 직접 적어주세요</label>
          <input id="sn-note" name="industry_note" placeholder="예: 반찬가게">
        </div>

        <div class="field"><label for="sn-addr">주소</label>
          <input id="sn-addr" name="address" placeholder="서울 마포구 망원로 87" required>
          <p class="muted">주소로 상권을 찾습니다. 지번·도로명 다 되고,
            상권 데이터가 서울 기준이라 <b>지금은 서울만</b> 됩니다.</p></div>

        <div class="field"><label for="sn-tel">연락처</label>
          <input id="sn-tel" name="phone" type="tel" inputmode="tel" placeholder="02-000-0000"></div>

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
            <!-- 어느 가게 이야기인지 여기 말고는 나오는 데가 없었다.
                 가게를 잘못 고른 것을 알아챌 방법이 화면에 있어야 한다. -->
            <dt>가게</dt><dd>${esc(picked().name)}</dd>
            <dt>홍보 대상</dt><dd>${esc(slip('product', M.brief.product))}</dd>
            <dt>가격</dt><dd>${esc(slip('price', M.brief.price))}</dd>
            <dt>상황</dt><dd>${esc(slip('situation', M.brief.situation))}</dd>
            <dt>말투</dt><dd>${esc(slip('tone', S.tone || M.brief.tone))}</dd>
          </dl>
        </div>

        <div class="chat">
          ${turns().map((t) => `<div class="bubble bubble--${t.who}">${esc(t.text)}</div>`).join('')}
          ${S.work.chat === 'running' ? '<div class="bubble bubble--bot"><span class="data">…</span></div>' : ''}
        </div>

        <div class="chips">
          ${chips().map((c) => `<button class="chip"${S.tone === c ? ' aria-pressed="true"' : ''} data-say="${esc(c)}">${esc(c)}</button>`).join('')}
        </div>

        <form class="compose" data-send>
          <div class="field" style="flex:1"><input name="say" placeholder="직접 입력" aria-label="답변 입력" autocomplete="off"></div>
          <button class="btn" style="width:auto;padding:12px 20px">전송</button>
        </form>

        <div class="rule stack--s">
          <button class="btn btn--line" data-go="photos">
            📷 사진 넣기 ${Object.keys(S.shots).length ? `— ${Object.keys(S.shots).length}장 넣음` : '— 선택'}
          </button>
          <button class="btn" data-make-copies ${S.work.copies === 'running' ? 'disabled' : ''}>
            ${S.work.copies === 'running' ? '만드는 중…' : '광고 문구 만들기'}</button>
          ${S.work.copies === 'failed' ? `<div class="note note--flag">${esc(S.work.copiesError || '')}</div>` : ''}
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
          ${copies().map((c) => `
            <div class="card">
              <strong style="font-size:18px;letter-spacing:-.02em;line-height:1.35">${esc(c.headline)}</strong>
              <span class="muted" style="font-size:14px">${esc(c.sub)}</span>
              ${(c.defects || []).map((d) => `<div class="note note--flag" style="font-size:13px">⚠ ${esc(d)}</div>`).join('')}
              <button class="btn btn--line btn--sm" data-go="image">이걸로 할게요</button>
            </div>`).join('')}
        </div>

        <div class="rule stack--s">
          <button class="btn" data-review ${S.work.review === 'running' ? 'disabled' : ''}>
            ${S.work.review === 'running' ? '손님들이 보는 중…' : '동네 손님들에게 셋 다 보여주기'}</button>
          <p class="muted" style="text-align:center">손님 12명이 셋을 다 봅니다. 1분쯤 걸립니다.</p>
          ${S.work.review === 'failed' ? `<div class="note note--flag">${esc(S.work.reviewError || '')}</div>` : ''}
        </div>

        ${revise()}
      </div>`,
  },

  panel: {
    title: '손님 반응',
    bar: true, back: 'copy',
    render: () => {
      const r = result();
      const people = r.persona_comments;
      const total = people.length + r.excluded_cnt;
      // 방문의향은 절대값으로 못 쓰고 차이는 쓸 수 있다 (재실행 잡음 최대 1.8점).
      // 기준은 서버가 준 clear_margin 을 쓴다 — 양쪽에 숫자를 따로 두면 다르게 늙는다.
      const cs = copies();
      const gap = (cs[0]?.intent ?? 0) - (cs[1]?.intent ?? 0);
      const margin = S.margin ?? 2;

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

        <p class="eyebrow" style="margin:0"><b>${esc(picked().name)}</b> · ${esc(picked().address)}</p>
        ${band(people)}
        <!-- 무엇이 실측이고 무엇이 예시인지 화면이 정확히 말해야 한다.
             손님 평가까지 돌았으면 이 화면에 예시가 하나도 없다 — 그때도
             "아직 예시입니다"라고 하면 화면이 거짓말을 하는 셈이다. -->
        ${S.result ? `<div class="note">
          <b>전부 실측입니다.</b> 동네 숫자는 서울시 상권 데이터에서, 손님 코멘트와
          점수는 이 동네 손님 ${people.length}명에게 실제로 물어 받은 것입니다.
        </div>` : LIVE ? `<div class="note">
          <b>동네 숫자는 서울시 실측</b>입니다 — 상권·객단가·시간대·점포 수.
          손님 코멘트와 점수, 문구 후보는 모델을 불러야 해서 <b>아직 예시</b>입니다.
        </div>` : ''}
        ${badges}

        <div class="note note--accent">
          ${gap >= margin
            ? `손님들은 <b>1위 문구</b>에 가장 마음이 움직였습니다. 2위와 ${gap.toFixed(0)}점 차 — 다시 돌려도 뒤집히지 않는 차이입니다.`
            : '손님 반응은 셋이 비슷했습니다. 아래 지적사항이 없는 쪽을 고르시면 됩니다.'}
        </div>

        <section class="rule">
          <h2 class="h2">문구 후보 셋</h2>
          <div class="stack--s">
            ${cs.map((c, i) => `
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
                <span class="src">${esc(n.evidence)}</span></li>`).join('')}
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
        <div class="note note--accent">고른 문구 — <b>${esc(copies()[0].headline)}</b></div>

        <div class="stack--s">
          <button class="btn" data-make>광고 이미지 만들기</button>
          <!-- 실측(GPU 없는 노트북): 첫 장 53.8초 · 두 번째 20.1초.
               첫 장이 오래 걸리는 건 모델을 메모리에 올리기 때문이다. -->
          <p class="muted" style="text-align:center">첫 장은 1분쯤, 그다음부터는 20초쯤 걸립니다</p>
        </div>

        <div id="shots" class="stack--s rule">
          ${M.images.map((im) => imageCard(im)).join('')}
        </div>

        <p class="muted">GPU를 찾지 못해 CPU로 만들었습니다. GPU가 있으면 훨씬 빠릅니다.</p>
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

  // 고른 가게가 상권 조회·이미지 요청의 기준이 된다
  const card = e.target.closest('[data-store]');
  if (card) {
    S.store = storeList()[Number(card.dataset.store)];
    rememberStore(S.store);
    // 하던 대화·문구·평가는 앞 가게 것이다. 그대로 두면 다른 가게 화면에
    // 남의 문구가 붙어 있는다.
    Object.assign(S, { draft: null, turns: [], options: [], copies: null,
                       adId: null, result: null, margin: null, tone: null });
    forget();
    go('chat');
    refreshPanel();
    return;
  }

  if (e.target.closest('[data-logout]')) {
    TOKEN.clear();
    S.stores = [];
    S.store = null;
    rememberStore(null);
    Object.assign(S, { draft: null, turns: [], options: [], copies: null,
                       adId: null, result: null, margin: null, tone: null });
    forget();
    openDrawer(false);
    go('login');
    toast('로그아웃했습니다');
    refreshPanel();
    return;
  }

  if (e.target.closest('[data-drawer]')) { openDrawer(true); return; }
  if (e.target.closest('[data-drawer-close]') || e.target.id === 'drawer') { openDrawer(false); return; }

  // 말투 칩 — 고른 말투가 주문서에 바로 반영된다
  const chip = e.target.closest('[data-say]');
  if (chip) {
    // 말투 칩은 주문서의 말투를 정하고, 서버가 준 선택지는 그냥 답변이다.
    if (M.toneChips.includes(chip.dataset.say)) S.tone = chip.dataset.say;
    say(chip.dataset.say);
    return;
  }

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

  if (e.target.closest('[data-make-copies]')) { makeCopies(); return; }
  if (e.target.closest('[data-review]')) { reviewCopies(); return; }

  const make = e.target.closest('[data-make]');
  if (make) {
    if (!API_BASE) { toast('서버가 없어 이미지를 만들 수 없습니다'); return; }
    if (Object.values(S.jobs).some(busy)) return;   // 두 번 눌러도 한 번만
    startImages();
  }
});

document.addEventListener('change', (e) => {
  const ind = e.target.closest('#sn-ind');
  if (ind) {
    const note = $('[data-other]');
    note.hidden = ind.value !== 'other';
    // hidden 인 채로 required 를 두면 브라우저가 "focusable 하지 않다"며 제출을 막는다
    note.querySelector('input').required = !note.hidden;
    return;
  }

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
    form.say.value = '';
    say(text).then(() => {
      // 다시 그리면 방금 쓰던 입력칸이 사라져 포커스가 body 로 떨어진다.
      // 그대로 두면 한 마디 보낼 때마다 입력칸을 다시 눌러야 한다.
      $('[data-send] input')?.focus();
    });
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

  if (form.matches('[data-login]') || form.matches('[data-signup]')) { submitAuth(form); return; }

  if (form.matches('[data-store-new]')) { addStore(form); }
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
    </button>`).join('') + (TOKEN.get() ? `
    <button class="drawer__item" data-logout><span class="drawer__num">↩</span>로그아웃</button>` : '');
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

$('#drawer-list').addEventListener('click', () => openDrawer(false));

/** 시간대 코드 → 사장님이 읽는 말. 서울시 원본의 구간 그대로다. */
const TIME_LABEL = {
  '00-06': '새벽(0–6시)', '06-11': '아침(6–11시)', '11-14': '점심(11–14시)',
  '14-17': '오후(14–17시)', '17-21': '저녁(17–21시)', '21-24': '심야(21–24시)',
};

const won = (n) => n.toLocaleString('ko-KR');

/** 업종 id → 사장님이 읽는 이름. 서버는 id 만 준다(korean_food).
 *  목업 가게는 이미 라벨을 들고 있어서 못 찾으면 받은 값을 그대로 쓴다. */
const indLabel = (v) => M.industries.find((i) => i.id === v)?.label || v;

/** 화면에 보여줄 가게 목록.
 *  로그인해서 서버에서 받아왔으면 **그것만** — 목업 가게를 섞으면 등록한 적 없는
 *  가게가 내 목록에 있는 것처럼 보인다. */
const storeList = () => (TOKEN.get() ? S.stores : [...M.stores, ...S.stores]);

/** 지금 광고를 만들고 있는 가게. 아직 안 골랐으면 목업 첫 가게로 화면을 채운다. */
const picked = () => S.store || M.stores[0];

// 서버에서 받은 게 있으면 그것을, 없으면 목업을 쓴다. 화면 코드가 둘을 구분하지
// 않도록 여기서만 갈라둔다 — 화면마다 삼항 연산자를 흩어두면 한 곳을 빠뜨린다.
const copies = () => S.copies || M.copies;
const result = () => S.result || M.result;
const turns = () => (S.turns.length ? S.turns : [...M.turns, ...S.said]);
const chips = () => (S.options.length ? S.options : M.toneChips);

/** 주문서 한 줄. 서버 주문서(AdBriefDraft)는 아직 안 채워진 칸이 null 이다. */
const slip = (key, fallback) => {
  const v = S.draft ? S.draft[key] : fallback;
  return v === null || v === undefined || v === '' ? '아직' : String(v);
};

/** 고른 가게를 새로고침 뒤에도 기억한다.
 *
 * 안 그러면 손님 반응 화면에서 새로고침한 순간 목업 첫 가게로 조용히 되돌아가서,
 * **다른 가게의 동네 숫자**를 이 가게 것처럼 보여준다. 가게 하나를 통째로 넣는다 —
 * id 만 넣으면 목업 가게(1,2,3)와 서버 가게(1,2)의 번호가 겹친다. */
const rememberStore = (s) => {
  if (s) localStorage.setItem('store', JSON.stringify(s));
  else localStorage.removeItem('store');
};

/** 새로고침해도 하던 작업이 남아야 하는 값들.
 *
 * 손님 평가 한 번이 1분이다. 시연 중에 새로고침 한 번으로 그게 날아가면
 * 다시 1분을 기다려야 한다. 서버가 주는 것만 담는다 — 목업은 어차피 코드에 있다. */
const KEEP = ['draft', 'turns', 'options', 'copies', 'adId', 'result', 'margin', 'tone'];

const keep = () => {
  const box = {};
  for (const k of KEEP) box[k] = S[k];
  localStorage.setItem('work', JSON.stringify(box));
};

const forget = () => localStorage.removeItem('work');

function restore() {
  let box;
  try { box = JSON.parse(localStorage.getItem('work')); } catch { return; }
  if (!box) return;
  for (const k of KEEP) if (box[k] !== undefined && box[k] !== null) S[k] = box[k];
  // 평가까지 받아뒀으면 동네 숫자도 실측이다 — 배지가 "예시"로 돌아가면 안 된다.
  if (S.result) LIVE = true;
}

/** 상권 실측을 받아 화면 문장으로 바꾼다.
 *
 * 여기서 만드는 세 문장은 **LLM 을 거치지 않는다.** 전부 서울시 원본에서
 * 뺄셈·나눗셈으로 나오므로 같은 입력이면 항상 같은 문장이다. 손님 평가가
 * 흔들려도 이 줄들은 흔들리지 않는다 — 화면에서 신뢰의 바닥을 깔아준다. */
async function loadTradeArea() {
  const s = picked();
  const q = new URLSearchParams({ address: s.address, industry: s.industryId || s.industry });
  // 좌표를 알면 같이 보낸다 — 카카오 지오코딩(그리고 키)을 건너뛰는 통로다.
  // 사장님이 직접 등록한 가게는 좌표가 없어서 서버가 주소를 찍어봐야 한다.
  if (s.lat != null && s.lon != null) { q.set('lat', s.lat); q.set('lon', s.lon); }
  const t = await api(`/trade-area?${q}`);

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
      // 업종 폴백이면 이 숫자는 '전체 업종' 평균이라 그 가게와 견줄 값이 아니다.
      // 그냥 "이 동네 결제 평균"이라고만 하면 반찬가게 객단가가 17만원인 줄 안다.
      text: `광고에 적힌 <b>${won(price)}원</b>은 이 동네 ` +
            `<b>${esc(t.category_nm)}</b> 결제 평균 ` +
            `<b>${won(t.avg_ticket)}원</b>보다 ${cheaper ? '낮습니다' : '높습니다'}.`,
      evidence: `${src} · ${t.category_nm} 객단가`,
    },
    {
      kind: 'timing',
      fit: 0.3,
      text: `이 동네는 <b>${TIME_LABEL[t.peak_time] || t.peak_time}</b>에 가장 많이 팔립니다 ` +
            `— 매출의 ${Math.round(t.peak_share * 100)}%.`,
      evidence: `${src} · 시간대별 매출`,
    },
    {
      kind: 'competition',
      fit: null,
      text: `같은 업종 가게가 <b>${t.competitor_cnt}곳</b>, 이번 분기에 ` +
            `<b>${t.open_cnt}곳 열고 ${t.close_cnt}곳 닫았습니다.</b>`,
      evidence: `${src} · 점포 수`,
    },
  ].filter(Boolean);

  // 제안은 원래 LLM 몫이라 아직 목업이다. 그런데 시간대 제안은 "점심에 가장 많이
  // 팔린다"고 적혀 있어서, 실측 피크가 저녁인 동네에서는 바로 옆 문장과 어긋난다.
  // 어긋나는 한 줄만 실측에서 다시 만든다.
  const peak = TIME_LABEL[t.peak_time] || t.peak_time;
  r.suggestions[0] =
    `이 동네는 <b>${peak}</b>에 가장 많이 팔립니다. 광고에서 그 시간대를 말해보시는 건 어떨까요.`;
}

/** 고른 가게로 상권 문장을 다시 만든다.
 *
 *  실패하면 목업 원본으로 되돌린다 — loadTradeArea 가 M.result 를 제자리에서
 *  덮어쓰기 때문에, 그냥 두면 앞 가게의 동네 숫자가 이 가게 것처럼 남는다. */
async function refreshTradeArea() {
  if (!API_BASE) return;
  // 손님 평가를 이미 받아뒀으면 그 안에 contrast_notes 가 들어 있다.
  // 여기서 다시 받아 LIVE 를 내렸다가 실패하면, 실측 화면에 "예시 값" 배지가 붙는다.
  if (S.result) return;
  LIVE = false;
  try {
    await loadTradeArea();
    LIVE = true;
  } catch (e) {
    M.result = JSON.parse(MOCK_RESULT);
    console.warn('서버에서 상권을 못 받아 목업으로 그립니다.', e);
  }
}

/** 상권을 다시 받아오고, **손님 반응 화면일 때만** 다시 그린다.
 *
 * M.result·LIVE 를 읽는 화면이 거기 하나뿐이다. 그냥 route() 를 부르면 조회가
 * 끝나는 1~2초 뒤에 지금 화면이 통째로 다시 그려지는데, 가게를 고르고 대화
 * 화면에서 답을 쓰고 있었다면 **쓰던 말이 날아가고 포커스도 잃는다.** */
const refreshPanel = () => refreshTradeArea().then(() => {
  if (location.hash === '#/panel') route();
});

/** 서버가 붙어 있고 로그인했나. 셋 다 이걸 먼저 본다. */
const live = () => Boolean(API_BASE && TOKEN.get());

/** 오래 걸리는 작업 하나를 등록하고 끝날 때까지 물어본다.
 *
 *  이미지 폴링(pollJob)과 나뉘어 있는 이유: 저쪽은 두 형태를 동시에 돌리며
 *  초 단위로 화면을 고쳐 쓰지만, 여기는 결과 한 덩어리만 받으면 된다. */
async function runJob(name, path, body) {
  S.work[name] = 'running';
  delete S.work[name + 'Error'];
  route();
  try {
    const { job_id: id, poll_after_ms: every } = await api(path, body);
    for (;;) {
      await new Promise((r) => setTimeout(r, every || 2000));
      const st = await api(`/jobs/${id}`);
      if (st.status === 'done') { S.work[name] = 'done'; return st.result; }
      if (st.status === 'failed') throw new Error(st.error || '실패했습니다');
    }
  } catch (e) {
    S.work[name] = 'failed';
    S.work[name + 'Error'] = e.message;
    route();
    return null;
  }
}

/** 사장님 말 한 마디를 서버에 보내고 주문서를 갱신한다.
 *  서버가 대화 상태를 안 들기 때문에 주문서를 우리가 들고 다닌다. */
async function say(text) {
  // 서버가 없으면 목업 대화 뒤에 덧붙이기만 한다. S.turns 에 넣으면 turns() 가
  // 그쪽을 택해서 **예시 대화가 통째로 사라진다.**
  if (!live()) { S.said.push({ who: 'me', text }); route(); return; }

  S.turns.push({ who: 'me', text });

  S.work.chat = 'running';
  S.options = [];
  route();
  try {
    const turn = await api('/chat', {
      store_id: picked().id, utterance: text, draft: S.draft || undefined,
    });
    S.draft = turn.draft;
    S.options = turn.options || [];
    S.turns.push({ who: 'bot', text: turn.message });
  } catch (e) {
    toast(e.message);
  }
  S.work.chat = 'done';
  keep();
  route();
}

/** 주문서를 문구 후보 셋으로. 끝나면 문구 화면으로 넘어간다. */
async function makeCopies() {
  if (!live()) { go('copy'); return; }
  const d = S.draft;
  if (!d?.product) { toast('무엇을 홍보할지부터 말씀해주세요'); return; }

  const out = await runJob('copies', '/ads/copies', {
    store_id: picked().id,
    product: d.product,
    price: d.price ?? 0,
    situation: d.situation || '',
    tone: S.tone || d.tone || '',
    extra: d.extra || '',
  });
  if (!out) return;               // 실패 문구는 화면에 이미 떠 있다
  S.copies = out.copies;
  S.adId = out.ad_id;
  S.result = null;                // 문구가 갈렸으니 이전 평가는 더 이상 이 문구의 것이 아니다
  keep();
  go('copy');
}

/** 후보 셋을 동네 손님들에게 보여준다. 1분쯤 걸린다. */
async function reviewCopies() {
  if (!live() || !S.adId) { go('panel'); return; }
  const d = S.draft || {};
  const st = picked();

  const out = await runJob('review', '/ads/review', {
    store_id: st.id,
    ad_id: S.adId,
    product: d.product,
    price: d.price ?? 0,
    situation: d.situation || '',
    tone: S.tone || d.tone || '',
    ...(st.lat != null && st.lon != null ? { lat: st.lat, lon: st.lon } : {}),
  });
  if (!out) return;

  S.margin = out.clear_margin;
  // 후보는 좋은 순으로 온다. 화면의 "동네 숫자"는 1위 후보의 평가를 쓴다 —
  // app.py 도 같다. 셋의 평가를 섞으면 어느 문구 이야기인지 알 수 없다.
  S.copies = out.ranked.map((r) => ({
    ...r.copy,
    defects: r.defects.map((x) => x.text ?? String(x)),
    intent: r.result.scores?.intent ?? 0,
  }));
  S.result = out.ranked[0]?.result || null;
  LIVE = true;
  keep();
  go('panel');
}

/** 서버에서 내 가게를 받아온다. 토큰이 없거나 서버가 없으면 할 일이 없다. */
async function loadStores() {
  if (!API_BASE || !TOKEN.get()) return;
  S.stores = await api('/stores');
}

/** 로그인·가입. 서버가 없으면 화면만 넘긴다 — 목업으로도 흐름은 보여야 한다. */
async function submitAuth(form) {
  const isSignup = form.matches('[data-signup]');
  if (!API_BASE) { go(isSignup ? 'storeNew' : 'stores'); return; }

  const username = form.username.value.trim();
  const password = form.password.value;
  // 서버도 8자를 검사하지만 그건 422 로 오고 detail 이 배열이라 보여줄 문장이 없다.
  if (isSignup && password.length < 8) { toast('비밀번호는 8자 이상이어야 합니다'); return; }
  if (isSignup && password !== form.password2.value) { toast('비밀번호가 서로 다릅니다'); return; }

  try {
    const ses = await api(isSignup ? '/auth/signup' : '/auth/login', { username, password });
    TOKEN.set(ses.token);
    S.store = null;
    rememberStore(null);
    S.stores = [];
    await loadStores();
  } catch (e) {
    toast(e.message);
    return;
  }
  go(isSignup ? 'storeNew' : 'stores');
  toast(isSignup ? '가입했습니다' : '로그인했습니다');
}

/** 가게 등록. 로그인해서 서버에 저장하거나, 서버가 없으면 화면 안에만 담는다. */
async function addStore(form) {
  const body = {
    name: form.name.value.trim(),
    industry: form.industry.value,        // id 다. 서버가 registry 로 검사한다.
    address: form.address.value.trim(),
    phone: form.phone.value.trim(),
    industry_note: form.industry_note.value.trim(),
  };

  if (!API_BASE || !TOKEN.get()) {
    S.stores.push(body);
    S.store = body;
  } else {
    try {
      S.store = await api('/stores', body);
      await loadStores();
    } catch (e) { toast(e.message); return; }
  }
  rememberStore(S.store);

  go('chat');
  toast('가게를 등록했습니다');
  // 상권은 늦게 와도 된다. 기다렸다 넘어가면 등록 버튼이 몇 초 멈춘 것처럼 보인다.
  refreshPanel();
}

/** 서버가 있으면 서버 값으로, 없거나 실패하면 목업으로 그린다.
 *  화면이 아예 안 뜨는 것보다 목업이라도 뜨는 편이 낫다 — 실패는 콘솔에만 남긴다. */
async function boot() {
  try { S.store = JSON.parse(localStorage.getItem('store')); } catch { S.store = null; }
  restore();
  if (API_BASE && TOKEN.get()) {
    // 토큰이 만료·위조로 걸리면 api() 가 알아서 지운다.
    try { await loadStores(); } catch (e) { console.warn('내 가게를 못 받았습니다.', e); }
  }
  await refreshTradeArea();
  // 이미 로그인해 둔 사람에게 로그인 화면부터 보여줄 이유가 없다.
  if (!location.hash && TOKEN.get()) location.hash = '#/stores';
  window.addEventListener('hashchange', route);
  route();
}

boot();
