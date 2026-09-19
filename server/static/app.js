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
  const node = el(clickable ? 'a' : 'div', `card${clickable ? '' : ' disabled'}`);
  if (clickable) node.href = app.url;

  const head = el('div', 'row');
  head.append(el('span', 'icon', app.icon || '🧩'));
  head.append(el('span', `badge ${app.status}`, STATUS_LABEL[app.status] || app.status));
  node.append(head);

  node.append(el('h3', null, app.name));
  node.append(el('p', null, app.description || ''));

  if (app.tags && app.tags.length) {
    const tags = el('div', 'tags');
    app.tags.forEach((t) => tags.append(el('span', 'tag', t)));
    node.append(tags);
  }

  const note = app.notes || NOTE_BY_STATUS[app.status];
  if (note) node.append(el('div', 'note', note));

  return node;
}

async function load() {
  const grid = document.getElementById('grid');
  try {
    const res = await fetch('/api/_apps');
    const apps = await res.json();
    grid.innerHTML = '';
    if (!apps.length) {
      grid.append(el('div', 'empty', '등록된 앱이 없습니다. apps/ 폴더에 앱을 추가하세요.'));
      return;
    }
    apps.forEach((a) => grid.append(card(a)));
  } catch (e) {
    grid.innerHTML = '';
    grid.append(el('div', 'empty', `앱 목록을 불러오지 못했습니다: ${e}`));
  }
}

load();
