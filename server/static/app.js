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

function card(app) {
  const clickable = app.status === 'ready' && app.url;
  const node = el(clickable ? 'a' : 'div', `card reveal${clickable ? '' : ' disabled'}`);
  if (clickable) node.href = app.url;

  const head = el('div', 'row');
  head.append(el('span', 'card-icon', app.icon || '🧩'));
  head.append(el('span', `badge ${app.status}`, STATUS_LABEL[app.status] || app.status));
  node.append(head);

  node.append(el('h3', null, app.name));
  node.append(el('p', 'muted card-desc', app.description || ''));

  if (app.tags && app.tags.length) {
    const tags = el('div', 'tags');
    app.tags.forEach((t) => tags.append(el('span', 'chip', t)));
    node.append(tags);
  }

  const note = app.notes || NOTE_BY_STATUS[app.status];
  if (note) node.append(el('div', 'note', note));

  if (clickable) node.append(el('div', 'card-go', '열기 →'));
  return node;
}

/* 로딩 중에는 빈 화면 대신 카드 모양을 먼저 깔아 둔다 */
function skeletons(grid, n = 3) {
  grid.innerHTML = '';
  for (let i = 0; i < n; i += 1) {
    const s = el('div', 'skeleton');
    s.style.height = '188px';
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
