const STATUS_LABEL = {
  ready: '사용 가능',
  needs_build: '빌드 필요',
  error: '오류',
  disabled: '꺼짐',
};

const NOTE_BY_STATUS = {
  needs_build: '프론트엔드가 아직 빌드되지 않았습니다. `python scripts/build.py <id>` 를 실행하세요.',
  error: '앱 로드 중 오류가 났습니다. 서버 로그를 확인하세요.',
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/* 카드 겉면에는 아이콘·이름·한 줄·상태만 둔다. 긴 설명과 태그, 주의사항은
 * '자세히' 를 눌렀을 때 펼쳐진다. */
function card(app) {
  const open = app.status === 'ready' && app.url;
  const node = el('article', `card reveal${open ? '' : ' card-off'}`);
  if (app.accent) node.style.setProperty('--accent', app.accent);
  // 카드를 누르면 앱 화면으로 이어지듯 넘어가게 하는 이름표
  node.style.setProperty('view-transition-name', `app-${app.id}`);

  const head = el('div', 'card-head');
  head.append(el('span', 'card-icon', app.icon || '🧩'));

  const titles = el('div', 'card-titles');
  titles.append(el('h3', null, app.name));
  const tagline = app.tagline || '';
  if (tagline) titles.append(el('p', 'card-tagline', tagline));
  head.append(titles);
  node.append(head);

  const foot = el('div', 'card-foot');
  foot.append(el('span', `badge ${app.status}`, STATUS_LABEL[app.status] || app.status));

  const more = el('button', 'btn ghost card-more');
  more.type = 'button';
  more.append(el('span', null, '자세히'));
  more.append(el('span', 'chev', '▾'));
  foot.append(more);

  if (open) {
    const go = el('a', 'btn primary card-open', '열기');
    go.href = app.url;
    foot.append(go);
  }
  node.append(foot);

  // 펼쳐지는 부분 — 높이 애니메이션을 위해 grid 한 겹을 덧댄다
  const wrap = el('div', 'card-detail');
  const inner = el('div', 'card-detail-inner');
  if (app.description) inner.append(el('p', 'muted', app.description));

  if (app.tags && app.tags.length) {
    const tags = el('div', 'tags');
    app.tags.forEach((t) => tags.append(el('span', 'chip', t)));
    inner.append(tags);
  }

  const note = app.notes || NOTE_BY_STATUS[app.status];
  if (note) inner.append(el('div', 'note', note));

  wrap.append(inner);
  node.append(wrap);

  more.addEventListener('click', () => {
    const nowOpen = node.classList.toggle('expanded');
    more.setAttribute('aria-expanded', String(nowOpen));
    more.firstChild.textContent = nowOpen ? '접기' : '자세히';
  });
  more.setAttribute('aria-expanded', 'false');

  return node;
}

/* 로딩 중에는 빈 화면 대신 카드 모양을 먼저 깔아 둔다 */
function skeletons(grid, n = 3) {
  grid.innerHTML = '';
  for (let i = 0; i < n; i += 1) {
    const s = el('div', 'skeleton');
    s.style.height = '150px';
    grid.append(s);
  }
}

async function load() {
  const grid = document.getElementById('grid');
  skeletons(grid);
  try {
    const res = await fetch('/api/_apps');
    const apps = await res.json();
    grid.innerHTML = '';
    if (!apps.length) {
      grid.append(el('div', 'muted', '등록된 앱이 없습니다. apps/ 폴더에 앱을 추가하세요.'));
      return;
    }
    apps.forEach((a) => grid.append(card(a)));
    window.unifiUI?.observeReveals();
  } catch (e) {
    grid.innerHTML = '';
    grid.append(el('div', 'muted', `앱 목록을 불러오지 못했습니다: ${e}`));
  }
}

load();
