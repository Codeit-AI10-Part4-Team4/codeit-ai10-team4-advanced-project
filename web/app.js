/* 동네 광고 만들기 — 화면.
 *
 * 지금은 목업으로 돈다. 백엔드가 서면 API_BASE 한 줄만 채우면 실제 API 를 부른다.
 * 화면 코드는 그대로 두려고 데이터 접근을 api() 하나로 모았다.
 */

const API_BASE = ''; // 예: 'https://동네광고-api.onrender.com'

async function api(path, fallback) {
  if (!API_BASE) return fallback;
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

const M = window.MOCK;
const RESIST = window.RESISTANCE_LABEL;

// ── 도구 ─────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);

/** 사장님이 쓴 값은 화면에 그대로 나가므로 태그를 막는다. */
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

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
          <button class="btn--ghost" style="border:0;background:none;cursor:pointer;font-weight:600;padding:4px" data-go="stores">가입하기</button>
        </p>
        <!-- 로그인 화면엔 상단 바가 없어서 화면 목록으로 갈 길이 여기밖에 없다 -->
        <p class="muted rule" style="text-align:center">
          <button class="btn--ghost" style="border:0;background:none;cursor:pointer;padding:6px;color:var(--ink-3)" data-drawer>전체 화면 목록 보기</button>
        </p>
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
          ${M.stores.map((s) => `
            <button class="card card--tap" data-go="chat">
              <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">
                <strong style="font-size:16px">${esc(s.name)}</strong>
                <span class="tag">${esc(s.industry)}</span>
              </div>
              <span class="muted">${esc(s.address)}</span>
            </button>`).join('')}
        </div>
        <button class="btn btn--line" data-go="chat">새 가게 등록하기</button>
      </div>`,
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
            <dt>말투</dt><dd>${esc(M.brief.tone)}</dd>
          </dl>
        </div>

        <div class="chat">
          ${M.turns.map((t) => `<div class="bubble bubble--${t.who}">${esc(t.text)}</div>`).join('')}
        </div>

        <div class="chips">
          ${M.toneChips.map((c) => `<button class="chip">${esc(c)}</button>`).join('')}
        </div>

        <div class="compose">
          <div class="field" style="flex:1"><input placeholder="직접 입력" aria-label="답변 입력"></div>
          <button class="btn" style="width:auto;padding:12px 20px">전송</button>
        </div>

        <div class="rule stack--s">
          <button class="btn btn--line" data-go="photos">📷 사진 넣기 — 선택</button>
          <button class="btn" data-go="panel">동네 손님들에게 보여주기</button>
          <p class="muted" style="text-align:center">손님 12명이 문구 후보 셋을 봅니다. 1분쯤 걸립니다.</p>
        </div>
      </div>`,
  },

  photos: {
    title: '사진 넣기',
    bar: true, back: 'chat',
    render: () => `
      <div class="stack">
        <div class="note">세 칸 모두 선택입니다. 안 올려도 광고는 만들어집니다.</div>

        <div class="slot">
          <div><strong style="font-size:15px">제품 사진</strong>
            <p class="muted" style="margin:2px 0 0">광고할 제품이 잘 보이도록 찍어주세요</p></div>
          <div class="slot__shot">올린 사진</div>
          <p class="muted">AI가 읽은 내용 — ${esc(M.photos.product.note)}</p>
          <button class="btn btn--line btn--sm" style="width:auto;align-self:flex-start">빼기</button>
        </div>

        <div class="rule stack">
          <div class="slot">
            <div><strong style="font-size:15px">레퍼런스</strong>
              <p class="muted" style="margin:2px 0 0">이런 분위기로 만들어주세요</p></div>
            <button class="slot__drop"><span>＋</span><span>사진 올리기</span></button>
          </div>
          <div class="slot">
            <div><strong style="font-size:15px">스케치</strong>
              <p class="muted" style="margin:2px 0 0">이런 배치·구도로 만들어주세요</p></div>
            <button class="slot__drop"><span>＋</span><span>사진 올리기</span></button>
          </div>
        </div>

        <p class="muted rule">제품 사진만 AI가 읽어 문구에 반영합니다.
          레퍼런스·스케치는 “어떻게 그릴지”에 대한 지시라 읽지 않습니다.</p>
        <button class="btn" data-go="chat">다 넣었어요</button>
      </div>`,
  },

  panel: {
    title: '손님 반응',
    bar: true, back: 'chat',
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
          <h2 class="h2">동네 숫자와 견줘보면</h2>
          <ul class="facts">
            ${r.contrast_notes.map((n) => `
              <li class="${n.fit !== null && n.fit < 0.5 ? 'off' : ''}">${n.text}
                <span class="src">${esc(n.src)}</span></li>`).join('')}
          </ul>
        </section>

        <section class="rule">
          <h2 class="h2">이렇게 해보시면 어떨까요</h2>
          <ul class="facts" style="gap:11px">
            ${r.suggestions.map((s) => `<li style="border-left-color:var(--accent-soft)">${s}</li>`).join('')}
          </ul>
          <button class="btn" style="margin-top:16px" data-go="chat">제안 반영해 다시 만들기</button>
        </section>

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
          ${M.images.map((im) => `
            <div class="card">
              <strong style="font-size:15px">${esc(im.label)}</strong>
              <div class="shot"><span class="muted">광고 이미지</span><span class="data">1080 × 1080</span></div>
              <div class="btn-row">
                <button class="btn ${im.saved ? 'btn--done' : 'btn--line'} btn--sm" ${im.saved ? 'disabled' : ''}>
                  ${im.saved ? '저장됨' : '저장'}</button>
                <button class="btn btn--line btn--sm">다운로드</button>
              </div>
            </div>`).join('')}
        </div>

        <p class="muted">GPU를 찾지 못해 CPU로 만들었습니다. 장당 18초쯤 걸립니다.</p>
        <button class="btn btn--line" data-make>사진만 다시 만들기</button>
        <p class="muted rule">문구를 바꾸려면 손님 반응 화면에서 다른 것을 고르세요 —
          사진은 그대로 두고 글자만 다시 얹습니다.</p>
      </div>`,
  },
};

const ORDER = [
  ['login',  '로그인'],
  ['stores', '내 가게'],
  ['chat',   '대화 — 광고 만들기'],
  ['photos', '사진 넣기'],
  ['panel',  '손님 반응'],
  ['image',  '광고 이미지'],
];

// ── 라우팅 ───────────────────────────────────────────────────

function route() {
  const name = location.hash.slice(2) || 'login';
  const screen = SCREENS[name] || SCREENS.login;

  const bar = $('#bar');
  bar.hidden = !screen.bar;
  $('#bar-title').textContent = screen.title;
  $('[data-back]').hidden = !screen.back;
  bar.dataset.back = screen.back || '';

  const main = $('#main');
  main.innerHTML = screen.render();
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);

  document.title = screen.title ? `${screen.title} · 동네 광고 만들기` : '동네 광고 만들기';
  drawList(name);
}

const go = (name) => { location.hash = `#/${name}`; };

// ── 이벤트 ───────────────────────────────────────────────────

document.addEventListener('click', (e) => {
  const goEl = e.target.closest('[data-go]');
  if (goEl) { go(goEl.dataset.go); return; }

  if (e.target.closest('[data-back]')) { go($('#bar').dataset.back || 'stores'); return; }

  if (e.target.closest('[data-drawer]')) { openDrawer(true); return; }
  if (e.target.closest('[data-drawer-close]') || e.target.id === 'drawer') { openDrawer(false); return; }

  // 이미지 생성은 서버에서 18초 걸린다. 그동안 화면이 멈춘 것처럼 보이지 않게 한다.
  const make = e.target.closest('[data-make]');
  if (make) fakeMake(make);
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#drawer').hidden) openDrawer(false);
});

function openDrawer(open) {
  $('#drawer').hidden = !open;
  $('[data-drawer]').setAttribute('aria-expanded', String(open));
  if (open) $('#drawer-list').querySelector('button')?.focus();
}

function drawList(current) {
  $('#drawer-list').innerHTML = ORDER.map(([key, label], i) => `
    <button class="drawer__item" data-go="${key}" ${key === current ? 'aria-current="true"' : ''}>
      <span class="drawer__num">${i + 1}</span>${label}
    </button>`).join('');
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

window.addEventListener('hashchange', route);
$('#drawer-list').addEventListener('click', () => openDrawer(false));

route();
