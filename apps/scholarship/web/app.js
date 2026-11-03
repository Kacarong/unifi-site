const API = '/api/scholarship';
const $ = (id) => document.getElementById(id);
const PAGE = 30;

const state = { view: 'open', offset: 0, options: null, profile: null, seq: 0 };

const VIEW_HINT = {
  open: '지금 신청할 수 있는 장학금입니다. 마감이 가까운 순서.',
  soon: '작년 이맘때 모집했는데 올해 공고는 아직 목록에 없는 장학금입니다. 날짜는 작년 일정 기준 예상이라 ☆ 해 두면 실제 모집이 올라올 때 알려 드립니다.',
  starred: '관심 표시한 장학금입니다. 내 조건과 상관없이 늘 보입니다.',
  all: '받아 둔 장학금 전부입니다(지난 회차 포함). 최근에 모집한 순서.',
};

async function api(path, options) {
  const res = await fetch(API + path, options);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* 본문이 JSON 이 아님 */ }
    throw new Error(msg);
  }
  return res.json();
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

const md = (iso) => (iso ? `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}` : '?');
const fmtTs = (ts) => (ts ? new Date(ts * 1000).toLocaleString('ko-KR', { hour12: false }) : '아직 없음');

function fillSelect(sel, values) {
  for (const v of values) sel.append(new Option(v, v));
}

// ---------------- 상태 ----------------
async function loadStatus() {
  try {
    const s = await api('/status');
    const when = s.meta?.name?.match(/_(\d{8})$/)?.[1];
    const basis = when ? `${when.slice(0, 4)}.${when.slice(4, 6)}.${when.slice(6)} 자료` : '자료';
    let text = s.count
      ? `${basis} · 장학금 ${s.count.toLocaleString()}건 · 지금 신청 가능 ${s.open}건 · 마지막 확인 ${fmtTs(s.last_sync_at)}`
      : '아직 원본을 받지 못했습니다. 잠시 뒤 새로고침하거나 아래 "지금 원본 다시 받기"를 눌러 주세요.';
    if (s.last_error) text += ` · ⚠️ 갱신 실패: ${s.last_error}`;
    if (s.notify_error) text += ` · ⚠️ 알림 실패: ${s.notify_error}`;
    $('status').textContent = text;
  } catch (e) {
    $('status').textContent = '상태를 불러오지 못했습니다: ' + e.message;
  }
}

// ---------------- 내 조건 ----------------
const PURPOSE_LABEL = { living: '생활비만', no_tuition: '등록금 전용 제외' };

function profileSummary(p) {
  const parts = [p.regions ? `${p.regions}+전국` : '', p.level, p.school, p.field,
    PURPOSE_LABEL[p.purpose] || '', p.exclude_loans ? '대출 제외' : ''].filter(Boolean);
  return parts.length ? parts.join(' · ') : '아직 안 정했어요 — 정하면 맞는 것만 보여 드립니다';
}

async function loadProfile() {
  const p = await api('/profile');
  state.profile = p;
  $('p_regions').value = p.regions || '';
  $('p_level').value = p.level || '';
  $('p_school').value = p.school || '';
  $('p_field').value = p.field || '';
  $('p_purpose').value = p.purpose || '';
  $('p_noloan').checked = p.exclude_loans !== false;
  $('profileSummary').textContent = profileSummary(p);
  if (!p.regions && !p.level && !p.school && !p.field) $('profileBox').open = true;
}

async function saveProfile() {
  const btn = $('profileSave');
  btn.disabled = true;
  try {
    const p = await api('/profile', json('PATCH', {
      regions: $('p_regions').value,
      level: $('p_level').value,
      school: $('p_school').value,
      field: $('p_field').value,
      purpose: $('p_purpose').value,
      exclude_loans: $('p_noloan').checked,
    }));
    state.profile = p;
    $('profileSummary').textContent = profileSummary(p);
    $('profileBox').open = false;
    reload();
  } catch (e) {
    alert('저장하지 못했습니다: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------------- 목록 ----------------
function statusBadge(it) {
  if (it.expected_start) {
    const now = new Date().toLocaleDateString('sv-SE'); // 내 기기 날짜 YYYY-MM-DD
    return it.expected_start <= now
      ? el('span', 'badge warn', `작년엔 ${md(it.expected_start)}~${md(it.expected_end)} 모집`)
      : el('span', 'badge', `${md(it.expected_start)}쯤 열릴 듯`);
  }
  if (it.status === 'open') {
    if (it.dday === 0) return el('span', 'badge hot', '오늘 마감');
    return el('span', `badge ${it.dday <= 3 ? 'hot' : 'ok'}`, `D-${it.dday} · ${md(it.end)} 마감`);
  }
  if (it.status === 'upcoming') return el('span', 'badge', `${md(it.start)} 모집 시작`);
  return el('span', 'badge off', `마감 (${it.start.slice(0, 4)}년 ${md(it.start)}~${md(it.end)})`);
}

function starButton(it) {
  const b = el('button', `star${it.starred ? ' on' : ''}`, it.starred ? '★' : '☆');
  b.title = it.starred ? '관심 해제' : '관심 표시 — 마감 임박·다음 모집을 알려 드립니다';
  b.setAttribute('aria-label', b.title);
  b.addEventListener('click', async (ev) => {
    ev.stopPropagation();
    const on = !b.classList.contains('on');
    b.disabled = true;
    try {
      await api(`/stars/${it.series}`, json('PUT', { on }));
      b.classList.toggle('on', on);
      b.textContent = on ? '★' : '☆';
      loadCounts();
    } catch (e) {
      alert(e.message);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}

const DETAIL_SECTIONS = [
  ['support', '지원 내용'],
  ['grade_req', '성적 기준'],
  ['income', '소득 기준'],
  ['special', '특정 자격'],
  ['region', '지역 조건'],
  ['restriction', '자격 제한'],
  ['selection', '선발 방법'],
  ['quota', '선발 인원'],
  ['recommend', '추천 필요'],
  ['documents', '제출 서류'],
];

// 원본은 '대학2학기, 대학3학기, … 공학계열, 교육계열, …' 처럼 값을 전부 늘어놓는다.
// 칩 서른 개로 그리면 읽을 수가 없어서 세 줄로 줄인다.
const NO_LIMIT = (list, all) => list.includes('제한없음') || list.length >= all;

function gradeText(grades) {
  if (grades.includes('제한없음')) return '제한 없음';
  const parts = [];
  if (grades.includes('대학신입생')) parts.push('신입생');
  const sems = grades.map((g) => g.match(/^대학(\d)학기/)?.[1]).filter(Boolean).map(Number);
  if (sems.length) parts.push(Math.min(...sems) <= 2 ? '재학생' : `재학생(${Math.min(...sems)}학기 이상)`);
  if (grades.some((g) => g.startsWith('석사') || g === '박사과정')) parts.push('대학원생');
  if (grades.includes('연령제한')) parts.push('나이 제한 있음');
  return parts.join(', ');
}

function targetLines(d) {
  const clean = (list) => (list || []).filter((t) => t !== '해당없음');
  const schools = clean(d.schools);
  const grades = clean(d.grades);
  const fields = clean(d.fields);
  const lines = [];
  if (schools.length) lines.push(`학교: ${NO_LIMIT(schools, 8) ? '제한 없음' : schools.join(', ')}`);
  if (grades.length) lines.push(`과정: ${gradeText(grades)}`);
  if (fields.length) lines.push(`계열: ${NO_LIMIT(fields, 7) ? '제한 없음' : fields.join(', ')}`);
  return lines.join('\n');
}

async function toggleDetail(card, it) {
  const open = card.querySelector('.detail');
  if (open) { open.remove(); card.classList.remove('expanded'); return; }
  card.classList.add('expanded');
  const box = el('div', 'detail', '불러오는 중…');
  card.append(box);
  try {
    const d = await api(`/items/${it.id}`);
    box.textContent = '';
    const meta = el('p', 'tiny muted', [d.org_type, d.category, d.product].filter(Boolean).join(' · '));
    box.append(meta);
    const target = targetLines(d);
    if (target) {
      const sec = el('div', 'sec');
      sec.append(el('h3', null, '대상'), el('p', null, target));
      box.append(sec);
    }
    for (const [key, label] of DETAIL_SECTIONS) {
      const text = (d[key] || '').trim();
      if (!text || text === '해당없음') continue;
      const sec = el('div', 'sec');
      sec.append(el('h3', null, label), el('p', null, text));
      box.append(sec);
    }
    if (d.rounds?.length > 1) {
      const sec = el('div', 'sec');
      sec.append(el('h3', null, '모집 기록'),
        el('p', null, d.rounds.map((r) => `${r.start} ~ ${r.end}`).join('\n')));
      box.append(sec);
    }
    if (d.url) {
      const a = el('a', 'btn small', '기관 홈페이지 열기 ↗');
      a.href = d.url; a.target = '_blank'; a.rel = 'noopener';
      a.addEventListener('click', (ev) => ev.stopPropagation());
      box.append(a);
    }
  } catch (e) {
    box.textContent = '자세한 내용을 불러오지 못했습니다: ' + e.message;
  }
}

function card(it) {
  const c = el('article', 'item');
  const head = el('div', 'head');
  const title = el('div', 'title');
  title.append(el('span', 'org', it.org), el('strong', null, it.name));
  head.append(title, starButton(it));
  const badges = el('div', 'tags');
  badges.append(statusBadge(it));
  if (it.category && it.category !== '해당없음') badges.append(el('span', 'chip', it.category));
  if (it.region_check) badges.append(el('span', 'chip warn', '지역 확인 필요'));
  else if (it.regional) badges.append(el('span', 'chip', '지역'));
  if (it.loan) badges.append(el('span', 'chip', '대출'));
  else if (it.purpose === 'living') badges.append(el('span', 'chip ok', '생활비'));
  else if (it.purpose === 'tuition') badges.append(el('span', 'chip', '등록금'));
  if (!it.mine) badges.append(el('span', 'chip dim', '조건 밖'));
  c.append(head, badges);
  if (it.support) c.append(el('p', 'support', it.support));
  c.addEventListener('click', (ev) => {
    if (ev.target.closest('.detail')) return; // 펼친 내용 안을 눌러 글자 고르기
    toggleDetail(c, it);
  });
  return c;
}

function query(extra = {}) {
  const p = new URLSearchParams({
    view: state.view,
    mine: $('mine').checked ? 'true' : 'false',
    q: $('q').value.trim(),
    category: $('category').value,
    offset: state.offset,
    limit: PAGE,
    ...extra,
  });
  return `/items?${p}`;
}

function showCounts(counts) {
  for (const tab of document.querySelectorAll('.tab')) {
    tab.querySelector('b').textContent = counts[tab.dataset.view] ?? '';
    tab.classList.toggle('active', tab.dataset.view === state.view);
  }
}

async function loadCounts() {
  try { showCounts((await api(query({ limit: 1, offset: 0 }))).counts); } catch { /* 숫자만 못 고침 */ }
}

async function load(append) {
  const seq = ++state.seq;
  const list = $('list');
  if (!append) {
    state.offset = 0;
    list.innerHTML = '';
    for (let i = 0; i < 3; i++) list.append(el('div', 'item skeleton'));
  }
  $('viewHint').textContent = VIEW_HINT[state.view];
  try {
    const data = await api(query());
    if (seq !== state.seq) return; // 그새 다른 탭·검색으로 바뀜
    if (!append) list.innerHTML = '';
    showCounts(data.counts);
    for (const it of data.items) list.append(card(it));
    state.offset += data.items.length;
    $('more').hidden = state.offset >= data.total;
    if (!data.total) {
      const empty = el('p', 'empty muted');
      empty.textContent = state.view === 'starred'
        ? '아직 관심 표시한 장학금이 없습니다. 목록에서 ☆ 를 눌러 보세요.'
        : $('mine').checked
          ? '내 조건에 맞는 장학금이 없습니다. "내 조건만" 을 끄면 전부 볼 수 있어요.'
          : '해당하는 장학금이 없습니다.';
      list.append(empty);
    }
    window.unifiUI?.observeReveals();
  } catch (e) {
    if (seq === state.seq) list.textContent = '목록을 불러오지 못했습니다: ' + e.message;
  }
}

const reload = () => load(false);

// ---------------- 알림 설정 ----------------
function notifySummary(s) {
  if (!s.discord_webhook_set) return '꺼짐 — 웹훅을 넣으면 켜집니다';
  return `켜짐 · 마감 ${(s.reminder_days || []).map((d) => `D-${d}`).join('/') || '알림 없음'}`;
}

async function loadSettings() {
  const s = await api('/settings');
  $('s_webhook').value = '';
  $('s_webhook').placeholder = s.discord_webhook_set
    ? '저장돼 있음 — 바꿀 때만 새 주소를 넣으세요'
    : 'https://discord.com/api/webhooks/…';
  $('s_mention').value = s.discord_mention || '';
  $('s_days').value = (s.reminder_days || []).join(', ');
  $('s_new').checked = !!s.notify_new;
  $('s_starred').checked = !!s.notify_starred;
  $('notifySummary').textContent = notifySummary(s);
}

async function saveSettings() {
  const body = {
    discord_mention: $('s_mention').value.trim(),
    notify_new: $('s_new').checked,
    notify_starred: $('s_starred').checked,
    reminder_days: $('s_days').value.split(/[^0-9]+/).filter(Boolean).map(Number),
  };
  const hook = $('s_webhook').value.trim();
  if (hook) body.discord_webhook_url = hook;
  try {
    await api('/settings', json('PATCH', body));
    await loadSettings();
    $('notifyMsg').textContent = '저장했습니다.';
  } catch (e) {
    $('notifyMsg').textContent = '⚠️ ' + e.message;
  }
}

async function testNotify() {
  $('notifyMsg').textContent = '보내는 중…';
  try {
    await api('/settings/test', { method: 'POST' });
    $('notifyMsg').textContent = '보냈습니다. 디스코드를 확인해 보세요.';
  } catch (e) {
    $('notifyMsg').textContent = '⚠️ ' + e.message;
  }
}

async function forceSync() {
  const b = $('syncBtn');
  b.disabled = true;
  b.textContent = '받는 중…';
  try {
    await api('/sync', { method: 'POST' });
    await Promise.all([loadStatus(), loadOptions()]);
    reload();
    b.textContent = '다시 받았습니다';
  } catch (e) {
    b.textContent = '실패: ' + e.message;
  } finally {
    b.disabled = false;
  }
}

async function loadOptions() {
  const o = await api('/options');
  const cat = $('category');
  const keep = cat.value;
  cat.length = 1;
  fillSelect(cat, o.categories);
  cat.value = keep;
  if (!state.options) {
    fillSelect($('p_level'), o.levels);
    fillSelect($('p_school'), o.schools);
    fillSelect($('p_field'), o.fields);
  }
  state.options = o;
}

// ---------------- 시작 ----------------
function bind() {
  for (const tab of document.querySelectorAll('.tab')) {
    tab.addEventListener('click', () => { state.view = tab.dataset.view; reload(); });
  }
  let t;
  $('q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(reload, 250); });
  $('category').addEventListener('change', reload);
  $('mine').addEventListener('change', reload);
  $('more').addEventListener('click', () => load(true));
  $('profileSave').addEventListener('click', saveProfile);
  $('notifySave').addEventListener('click', saveSettings);
  $('notifyTest').addEventListener('click', testNotify);
  $('syncBtn').addEventListener('click', forceSync);
}

(async function init() {
  bind();
  loadStatus();
  try {
    await loadOptions();
    await loadProfile();
  } catch (e) {
    $('status').textContent = '불러오지 못했습니다: ' + e.message;
  }
  loadSettings().catch(() => {});
  reload();
})();
