const API = '/api/cgvmacro';
const $ = (id) => document.getElementById(id);

const KIND_LABEL = {
  open: '🎬 상영 오픈',
  available: '🟢 잔여석',
  cancel: '🎟️ 취소표',
  stage_event: '🎤 무대인사',
  seat_held: '🪑 선점 완료',
  grab_error: '⚠️ 선점 실패',
};

const JOB_LABEL = {
  queued: '대기 중',
  claimed: '로컬 PC가 가져감',
  running: '선점 진행 중',
  done: '완료',
  error: '실패',
};

async function api(path, options) {
  const res = await fetch(API + path, options);
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.status === 204 ? null : res.json();
}

function jsonBody(body) {
  return { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function fmtTime(ts) {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString('ko-KR', { hour12: false });
}

// ---------------- 상태 ----------------
async function refreshStatus() {
  try {
    const s = await api('/monitor/status');
    const agents = (s.agents || []).filter((a) => a.online);
    $('status').innerHTML =
      `감시: <span class="${s.running ? 'on' : 'off'}">${s.running ? '동작 중' : '멈춤'}</span>` +
      ` · 대상 ${s.targets_enabled}/${s.targets_total}개` +
      ` · 마지막 확인 ${fmtTime(s.last_poll_at)}` +
      ` · 로컬 에이전트 ${agents.length ? `연결됨(${agents.length})` : '없음'}` +
      (s.last_error ? `<br /><span style="color:var(--warn)">최근 오류: ${s.last_error}</span>` : '');
  } catch (e) {
    $('status').textContent = '상태를 불러오지 못했습니다: ' + e.message;
  }
}

// ---------------- 감시 대상 ----------------
function targetItem(t) {
  const node = el('div', `item${t.enabled ? '' : ' off'}`);
  const left = el('div');
  left.append(el('div', 'main', t.name));
  const parts = [t.movie, t.theater, t.date];
  if (t.time_from || t.time_to) parts.push(`${t.time_from || '00:00'}~${t.time_to || '23:59'}`);
  if (t.screen_type) parts.push(t.screen_type);
  left.append(el('div', 'meta', parts.filter(Boolean).join(' · ')));
  node.append(left);

  const right = el('div', 'btns');
  right.style.marginTop = '0';
  if (t.auto_grab) right.append(el('span', 'tag auto', '자동 선점'));

  const toggle = el('button', 'btn small', t.enabled ? '끄기' : '켜기');
  toggle.onclick = async () => {
    await api(`/targets/${t.id}`, { method: 'PATCH', ...jsonBody({ enabled: !t.enabled }) });
    refreshTargets();
  };
  right.append(toggle);

  const grab = el('button', 'btn small', '지금 선점');
  grab.onclick = async () => {
    await api('/jobs', { method: 'POST', ...jsonBody({ target_id: t.id, showtime: {} }) });
    refreshJobs();
  };
  right.append(grab);

  const del = el('button', 'btn small', '삭제');
  del.onclick = async () => {
    if (!confirm(`'${t.name}' 을(를) 삭제할까요?`)) return;
    await api(`/targets/${t.id}`, { method: 'DELETE' });
    refreshTargets();
  };
  right.append(del);

  node.append(right);
  return node;
}

async function refreshTargets() {
  const box = $('targets');
  const targets = await api('/targets');
  box.innerHTML = '';
  if (!targets.length) {
    box.textContent = '아직 없습니다.';
    return;
  }
  targets.forEach((t) => box.append(targetItem(t)));
  refreshStatus();
}

async function refreshEvents() {
  const box = $('events');
  const events = await api('/events?limit=20');
  box.innerHTML = '';
  if (!events.length) {
    box.textContent = '아직 없습니다.';
    return;
  }
  events.forEach((e) => {
    const node = el('div', 'item');
    const left = el('div');
    left.append(el('div', 'main', `${KIND_LABEL[e.kind] || e.kind} ${e.target_name}`));
    left.append(el('div', 'meta',
      [e.movie, e.theater, `${e.date} ${e.time}`, e.screen, e.status_text].filter(Boolean).join(' · ')));
    node.append(left);
    node.append(el('span', 'tag', fmtTime(e.at)));
    box.append(node);
  });
}

async function refreshJobs() {
  const box = $('jobs');
  const jobs = await api('/jobs?limit=15');
  box.innerHTML = '';
  if (!jobs.length) {
    box.textContent = '아직 없습니다.';
    return;
  }
  jobs.forEach((j) => {
    const node = el('div', 'item');
    const left = el('div');
    left.append(el('div', 'main', `${j.target_name} · ${(j.showtime || {}).time || '회차 자동'}`));
    const last = (j.messages || []).slice(-1)[0];
    left.append(el('div', 'meta',
      [JOB_LABEL[j.status] || j.status, j.error, last && last.text].filter(Boolean).join(' · ')));
    node.append(left);
    node.append(el('span', 'tag', fmtTime(j.created_at)));
    box.append(node);
  });
}

// ---------------- 설정 ----------------
async function loadSettings() {
  const s = await api('/settings');
  $('s_webhook').value = s.discord_webhook_url || '';
  $('s_mention').value = s.discord_mention || '';
  $('s_interval').value = s.poll_interval_seconds;
  $('s_jitter').value = s.jitter_seconds;
  $('s_token').placeholder = s.agent_token_set ? '설정됨 (바꾸려면 입력)' : '비우면 인증 없음';
}

async function saveSettings() {
  const patch = {
    discord_webhook_url: $('s_webhook').value.trim(),
    discord_mention: $('s_mention').value.trim(),
    poll_interval_seconds: Number($('s_interval').value),
    jitter_seconds: Number($('s_jitter').value),
  };
  const token = $('s_token').value.trim();
  if (token) patch.agent_token = token;
  await api('/settings', { method: 'PATCH', ...jsonBody(patch) });
  $('s_token').value = '';
  loadSettings();
  alert('저장했습니다.');
}

// ---------------- 폼 ----------------
function formTarget() {
  return {
    name: $('f_name').value.trim() || $('f_movie').value.trim(),
    movie: $('f_movie').value.trim(),
    theater: $('f_theater').value.trim(),
    date: $('f_date').value,
    time_from: $('f_from').value,
    time_to: $('f_to').value,
    screen_type: $('f_screen').value.trim(),
    auto_grab: $('f_auto').checked,
    alerts: { min_remaining_seats: Number($('f_min').value) || 1 },
    grab: {
      general: Number($('f_gen').value) || 0,
      teen: Number($('f_teen').value) || 0,
      senior: Number($('f_senior').value) || 0,
      seats: $('f_seats').value.trim(),
    },
  };
}

async function addTarget() {
  const body = formTarget();
  if (!body.movie || !body.theater || !body.date) {
    alert('영화 · 극장 · 날짜는 필수입니다.');
    return;
  }
  await api('/targets', { method: 'POST', ...jsonBody(body) });
  $('f_name').value = '';
  refreshTargets();
}

async function preview() {
  const box = $('preview');
  const t = formTarget();
  box.classList.remove('hidden');
  box.textContent = '조회 중…';
  try {
    const params = new URLSearchParams({ movie: t.movie, theater: t.theater, date: t.date });
    const rows = await api(`/showtimes?${params}`);
    box.textContent = rows.length
      ? rows.map((r) =>
          `${r.time}  ${r.screen}  ${r.fmt}  ${r.controlled ? '판매통제' : r.soldout ? '매진' : `잔여 ${r.remaining}/${r.total}`}`
        ).join('\n')
      : '해당 날짜에 열린 회차가 없습니다.';
  } catch (e) {
    box.textContent = '조회 실패: ' + e.message;
  }
}

// 영화·극장 칸은 셸의 공용 자동완성을 쓴다. 브라우저 기본 datalist 는
// CSS 가 전혀 안 먹어서 사이트 톤과 따로 놀았다.
const movieBox = window.unifiUI?.combobox($('f_movie'), { emptyText: '그런 영화가 없습니다' });
const theaterBox = window.unifiUI?.combobox($('f_theater'), { emptyText: '그런 극장이 없습니다' });

async function loadLists() {
  try {
    const [movies, theaters] = await Promise.all([api('/movies'), api('/theaters')]);
    movieBox?.setOptions(movies.map((m) => m.name));
    theaterBox?.setOptions(theaters.map((t) => t.name));
  } catch (e) {
    /* 목록은 없어도 직접 입력하면 된다 */
  }
}

// ---------------- 초기화 ----------------
$('startBtn').onclick = async () => { await api('/monitor/start', { method: 'POST' }); refreshStatus(); };
$('stopBtn').onclick = async () => { await api('/monitor/stop', { method: 'POST' }); refreshStatus(); };
$('addBtn').onclick = addTarget;
$('previewBtn').onclick = preview;
$('saveSettings').onclick = saveSettings;

function refreshAll() {
  refreshStatus();
  refreshTargets().catch(() => {});
  refreshEvents().catch(() => {});
  refreshJobs().catch(() => {});
}

loadSettings().catch(() => {});
loadLists();
refreshAll();
setInterval(refreshAll, 10000);
