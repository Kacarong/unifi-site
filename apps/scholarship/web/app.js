const API = '/api/scholarship';
const $ = (id) => document.getElementById(id);
const PAGE = 30;

const state = { view: 'open', offset: 0, options: null, profile: null, seq: 0 };

const VIEW_HINT = {
  open: '지금 신청할 수 있는 장학금입니다(마감이 가까운 순서). 그 아래는 공고가 나왔고 곧 접수를 시작하는 것입니다. 학교 추천을 거치는 장학금은 학교 마감이 더 빠를 수 있습니다.',
  year_round: '공고 기간이 1년 가까이 잡힌 사업입니다. 국가근로·멘토링 장학금처럼 실제 신청은 학기마다 짧게 따로 받는 경우가 많아서, 지금 신청할 수 있는지는 기관 공고에서 꼭 확인하세요.',
  soon: '작년 일정으로 본 장학금인데 올해 공고는 아직 목록에 없습니다. 위쪽은 작년엔 두 달 안에 시작했던 것, 아래쪽(\'확인 필요\')은 작년 기준이면 이미 모집을 시작했을 것입니다. 일정이 당겨져 이미 끝났을 수도, 아직 받고 있을 수도 있으니 기관·학교 공지에서 꼭 확인하세요. ☆ 해 두면 올해 모집이 목록에 올라올 때 알려 드립니다.',
  closed: '최근 6개월 안에 마감된 회차입니다. 지난 공고도 지우지 않고 남겨 둡니다 — 내년 일정을 가늠하거나 놓친 장학금의 다음 모집을 ☆ 해 둘 때 쓰세요.',
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
    if (s.extra_count) text += ` · 포털·공고 게시판에서 더 찾은 것 ${s.extra_count}건 (${fmtTs(s.last_extra_at)})`;
    if (s.last_error) text += ` · ⚠️ 갱신 실패: ${s.last_error}`;
    if (s.extra_error) text += ` · ⚠️ 추가 출처 실패: ${s.extra_error}`;
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
  if (it.expected_start && it.started) {
    return el('span', 'badge warn', `작년 ${md(it.start)}~${md(it.end)} 모집 · 작년 기준이면 이미 시작 · 올해 공고 확인 필요`);
  }
  if (it.expected_start) {
    return el('span', 'badge warn', `작년 ${md(it.start)}~${md(it.end)} 모집 · 올해 모집 미확인`);
  }
  if (it.status === 'open') {
    if (it.dday == null) return el('span', 'badge warn', `${md(it.start)} 공고 · 마감일은 공고 원문 확인`);
    if (it.dday === 0) return el('span', 'badge hot', '오늘 마감');
    return el('span', `badge ${it.dday <= 3 ? 'hot' : 'ok'}`, `D-${it.dday} · ${md(it.end)} 마감`);
  }
  if (it.status === 'upcoming') return el('span', 'badge', `${md(it.start)} 접수 시작 · ${md(it.end)} 마감`);
  if (it.status === 'year_round') {
    return el('span', 'badge warn', `연중 사업 (~${it.end.slice(0, 4)}년 ${md(it.end)}) · 신청 시기 확인`);
  }
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
    if (d.notice_title) {
      const where = d.period_from ? ` — 신청 기간은 ${d.period_from}에서 읽었습니다` : '';
      box.append(el('p', 'tiny muted', `공고: ${d.notice_title}${d.posted ? ` (${d.posted} 게시)` : ''}${where}. 자동으로 읽은 날짜라 원문으로 한 번 더 확인해 주세요.`));
    }
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
    const links = [];
    if (d.notice_url) links.push([d.notice_url, '공고 원문 열기 ↗']);
    if (d.url) links.push([d.url, d.notice_title && !d.notice_url ? '공고 원문 열기 ↗' : '기관 홈페이지 열기 ↗']);
    for (const [href, label] of links) {
      const a = el('a', 'btn small', label);
      a.href = href; a.target = '_blank'; a.rel = 'noopener';
      a.addEventListener('click', (ev) => ev.stopPropagation());
      box.append(a, ' ');
    }
  } catch (e) {
    box.textContent = '자세한 내용을 불러오지 못했습니다: ' + e.message;
  }
}

function card(it) {
  const c = el('article', 'item');
  const head = el('div', 'head');
  const title = el('div', 'title');
  title.append(el('span', 'org', it.org), el('strong', null, it.notice_title || it.name));
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
  if (it.source) badges.append(el('span', 'chip', it.source === '한국장학재단 포털' ? '새로 올라옴 · 포털' : it.source));
  if ((it.period_from || '').startsWith('첨부')) badges.append(el('span', 'chip ok', '일정은 첨부 공고문에서 읽음'));
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

// ---------------- 공고 게시판 출처 ----------------
function sourceStat(st) {
  if (!st) return '아직 안 읽음';
  if (st.error) return `⚠️ 못 읽음: ${st.error}`;
  return `글 ${st.posts}개 · 장학 글 ${st.picked}개 열어 봄 · 목록에 ${st.items}건`;
}

function renderSources(list) {
  const box = $('sourceList');
  box.textContent = '';
  for (const src of list) {
    const row = el('div', 'source');
    const lab = el('label', 'check');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = src.enabled;
    cb.addEventListener('change', async () => {
      try {
        renderSources((await api(`/sources/${src.id}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: cb.checked }),
        })).sources);
        $('srcMsg').textContent = '바꿨습니다. "지금 다시 모으기"를 누르면 목록에 바로 반영됩니다.';
      } catch (e) { cb.checked = !cb.checked; alert(e.message); }
    });
    const a = el('a', null, src.label);
    a.href = src.url; a.target = '_blank'; a.rel = 'noopener';
    lab.append(cb, ' ', a);
    row.append(lab, el('span', 'tiny muted', ' ' + sourceStat(src.stat)));
    if (!src.builtin) {
      const del = el('button', 'linkish', '지우기');
      del.addEventListener('click', async () => {
        if (!confirm(`'${src.label}' 출처를 지울까요?`)) return;
        try { renderSources((await api(`/sources/${src.id}`, { method: 'DELETE' })).sources); } catch (e) { alert(e.message); }
      });
      row.append(' ', del);
    }
    box.append(row);
  }
  $('sourcesSummary').textContent = `켜진 게시판 ${list.filter((s) => s.enabled).length}곳`;
}

async function loadSources() {
  renderSources((await api('/sources')).sources);
}

async function addSource() {
  const url = $('src_url').value.trim();
  if (!url) { $('srcMsg').textContent = '게시판 주소를 넣어 주세요.'; return; }
  const btn = $('srcAdd');
  btn.disabled = true;
  $('srcMsg').textContent = '게시판을 읽어 보는 중…';
  try {
    const r = await api('/sources', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, label: $('src_label').value.trim() }),
    });
    renderSources(r.sources);
    const sample = r.probe.scholarship.length ? ` 예: ${r.probe.scholarship.slice(0, 3).join(' / ')}` : ' 최근 장학 글은 아직 없습니다.';
    $('srcMsg').textContent = `더했습니다. 글 ${r.probe.posts}개를 찾았습니다.${sample} "지금 다시 모으기"를 누르면 바로 반영됩니다.`;
    $('src_url').value = ''; $('src_label').value = '';
  } catch (e) {
    $('srcMsg').textContent = '더하지 못했습니다: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function refreshSources() {
  const btn = $('srcRefresh');
  btn.disabled = true;
  $('srcMsg').textContent = '포털과 게시판을 다시 읽는 중… (1분쯤 걸립니다)';
  try {
    const r = await api('/sources/refresh', { method: 'POST' });
    renderSources(r.sources);
    $('srcMsg').textContent = `다시 모았습니다. 포털 ${r.portal}건, 게시판 ${r.boards}건.` + (r.errors?.length ? ` ⚠️ ${r.errors.join(' / ')}` : '');
    loadStatus();
    reload();
  } catch (e) {
    $('srcMsg').textContent = '다시 모으지 못했습니다: ' + e.message;
  } finally {
    btn.disabled = false;
  }
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
  $('srcAdd').addEventListener('click', addSource);
  $('srcRefresh').addEventListener('click', refreshSources);
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
  loadSources().catch(() => {});
  reload();
})();
