import * as Cesium from 'cesium';
import './style.css';
import { buildLayers, LAYER_COUNT } from './layers.js';
import { Quiz } from './quiz.js';
import { Search } from './search.js';

const ctx = { lang: 'ko', showLabels: true };

/* 휴대폰은 화면이 촘촘하고(dpr 3) GPU 는 약하다. 데스크톱 기준 화질을 그대로
 * 쓰면 그려야 할 픽셀이 몇 배로 늘어 프레임이 무너진다. 기기를 보고 낮춘다. */
const LOW_POWER =
  matchMedia('(pointer: coarse)').matches ||
  Math.min(screen.width, screen.height) <= 820 ||
  (navigator.hardwareConcurrency || 8) <= 4;

/* 렌더 배율.
 * Cesium 은 기기 픽셀비(폰은 보통 3)에 이 값을 곱해서 그린다.
 * 멈춰 있을 때는 또렷하게(SHARP), 움직이는 동안만 잠깐 낮춘다(MOVING).
 * 움직이는 화면에서는 해상도가 낮아진 게 눈에 띄지 않는다. */
const SHARP_SCALE = LOW_POWER ? 1 : Math.min(window.devicePixelRatio || 1, 2);
const MOVING_SCALE = LOW_POWER ? 0.6 : SHARP_SCALE;

// 선택: Cesium ion 토큰이 있으면 3D 지형 + 위성영상 품질 향상
const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN;
if (ionToken) Cesium.Ion.defaultAccessToken = ionToken;

/* 로딩 화면 — 지금 무엇을 하는 중인지와 얼마나 남았는지를 보여 준다.
 * 화면이 2~3초 비어 있으면 멈춘 것처럼 느껴지기 때문이다. */
const loading = {
  box: () => document.getElementById('loading'),
  say(text, sub = '') {
    const t = document.getElementById('loadText');
    const s = document.getElementById('loadSub');
    if (t) t.textContent = text;
    if (s) s.textContent = sub;
  },
  progress(ratio) {
    const bar = document.getElementById('loadBar');
    if (bar) bar.style.width = `${Math.round(Math.min(1, Math.max(0, ratio)) * 100)}%`;
  },
  done() {
    this.progress(1);
    this.say('준비 완료');
    // 막대가 끝까지 차는 걸 보여 준 뒤 사라진다
    setTimeout(() => this.box()?.classList.add('hidden'), 260);
  },
  fail(msg) {
    this.say('불러오지 못했습니다', msg);
    this.progress(0);
  },
};

async function init() {
  loading.say('지구본 준비 중…', '위성 영상을 불러오고 있어요');
  loading.progress(0.08);

  // 기본 위성영상: Esri World Imagery (토큰 불필요, 무료)
  const viewer = new Cesium.Viewer('cesiumContainer', {
    baseLayer: Cesium.ImageryLayer.fromProviderAsync(
      Cesium.ArcGisMapServerImageryProvider.fromUrl(
        'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'
      )
    ),
    baseLayerPicker: false,
    geocoder: false,
    animation: false,
    timeline: false,
    navigationHelpButton: false,
    homeButton: true,
    sceneModePicker: true,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    useBrowserRecommendedResolution: false,
    // 기본 Cesium 은 가만히 있어도 초당 60번 다시 그린다. 지구본은 움직일
    // 때만 바뀌므로 변화가 있을 때만 그리게 한다. 모바일 발열/배터리와
    // 프레임에 가장 크게 작용하는 설정이다.
    requestRenderMode: true,
    maximumRenderTimeChange: Infinity,
  });

  const scene = viewer.scene;

  /* 화질 — 멈춰 있을 때는 기기 해상도 그대로 또렷하게 그린다.
   *
   * 전에 부드럽게 하려고 해상도를 1.5배로 낮췄더니 글자와 지형이 눈에 띄게
   * 뭉개졌다. 화질을 상시로 깎는 건 대가가 너무 크다. 대신 움직이는 동안에만
   * 잠깐 낮추고(움직이는 화면에서는 안 보인다) 손을 떼면 바로 되돌린다.
   * 아래 easeWhileMoving() 이 그 전환을 맡는다. */
  viewer.resolutionScale = SHARP_SCALE;
  scene.globe.maximumScreenSpaceError = LOW_POWER ? 2.2 : 1.5; // 클수록 타일 적게 = 가볍다
  scene.globe.preloadSiblings = !LOW_POWER;                  // 주변 타일 미리 받기
  if (scene.postProcessStages.fxaa) scene.postProcessStages.fxaa.enabled = !LOW_POWER;

  /* 지구처럼 보이게 하는 것들.
   *
   * 앞서 성능 때문에 대기 표현을 전부 껐더니 위성 사진만 덩그러니 남아
   * 밋밋하고 조잡해 보였다. 지구 가장자리의 푸른 띠(skyAtmosphere)는 화면
   * 테두리만 칠하는 것이라 값이 싸면서 "지구답다"는 인상을 거의 다 만든다.
   * 지면 전체에 얹는 groundAtmosphere 와 원거리 안개는 비싸므로 PC 에서만. */
  scene.skyAtmosphere.show = true;
  scene.globe.showGroundAtmosphere = !LOW_POWER;
  scene.fog.enabled = !LOW_POWER;

  // 타일이 오기 전 흰 바탕이 번쩍이지 않도록 바다색을 깔아 둔다
  scene.globe.baseColor = Cesium.Color.fromCssColorString('#0d2036');
  // 사진 대비를 살짝 올려 위성 영상이 탁해 보이지 않게
  scene.globe.atmosphereBrightnessShift = 0.05;

  // ion 토큰이 있을 때만 3D 지형 사용
  if (ionToken) {
    try { viewer.scene.setTerrain(Cesium.Terrain.fromWorldTerrain()); } catch (e) { /* ignore */ }
  }

  // 초기 시점: 지구 전체
  viewer.camera.flyHome(0);
  loading.progress(0.2);

  // 레이어 구성 — 하나씩 준비될 때마다 진행률을 올린다.
  // 레이어 로딩이 전체 시간의 대부분이라, 0.2~0.95 구간을 여기에 할당한다.
  const layers = await buildLayers(viewer, ctx, (done, label) => {
    loading.say('지도 데이터 불러오는 중…', `${label} (${done}/${LAYER_COUNT})`);
    loading.progress(0.2 + (done / LAYER_COUNT) * 0.75);
  });
  const byId = Object.fromEntries(layers.map((l) => [l.id, l]));

  // 초기 라벨 상태 적용
  for (const L of layers) if (L.applyLabels) L.applyLabels(ctx.showLabels && L.ds.show, ctx.lang);

  buildLayerUI(layers);
  wireControls(layers);
  setupQuiz(viewer, byId.borders);
  setupSearch(viewer, layers, byId);

  window.Cesium = Cesium;
  window.viewer = viewer; // 콘솔에서 카메라 제어/디버깅용
  installRedrawSafetyNet(viewer);
  if (LOW_POWER) easeWhileMoving(viewer, layers);
  viewer.scene.requestRender();
  loading.done();
}

/* 돌리거나 이동할 때 끊기던 것을 없앤다.
 *
 * 손을 대고 있는 동안에만 무게를 덜고, 놓으면 원래 화질로 돌아온다.
 *  - 도시 레이어(엔티티 7천 개 이상)를 잠깐 쉬게 한다. 라벨은 글자를 그리고
 *    겹침까지 매 프레임 따져 가장 비싼데, 움직이는 중엔 어차피 못 읽는다.
 *    라벨을 하나씩 끄면 7천 번을 돌아야 해서 그 자체로 버벅인다. 레이어
 *    표시 플래그 하나만 건드린다.
 *  - 렌더 배율을 잠깐 낮춘다. 움직이는 화면에서는 티가 안 난다.
 *
 * 신호는 카메라 이벤트가 아니라 손가락/마우스 조작에서 받는다. 카메라
 * 이벤트로 하면 해상도를 바꾸는 순간 화면 크기가 변해 카메라가 또 움직인
 * 것으로 잡히고, 되돌리기가 계속 취소돼 저화질에 갇힌다(실제로 그랬다).
 */
const HEAVY_ENTITIES = 2000;
const SETTLE_MS = 420;   // 손을 뗀 뒤 관성이 잦아들 때까지

function easeWhileMoving(viewer, layers) {
  const heavy = layers.filter((L) => (L.ds?.entities?.values?.length || 0) >= HEAVY_ENTITIES);
  const scene = viewer.scene;
  const baseError = scene.globe.maximumScreenSpaceError;
  let hidden = null;
  let settleTimer = 0;

  const lighten = () => {
    clearTimeout(settleTimer);
    if (hidden) return;
    hidden = heavy.filter((L) => L.ds.show);
    hidden.forEach((L) => { L.ds.show = false; });
    scene.globe.maximumScreenSpaceError = baseError * 1.6;  // 타일도 성글게
    viewer.resolutionScale = MOVING_SCALE;
  };

  const restore = () => {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      if (!hidden) return;
      hidden.forEach((L) => { L.ds.show = true; });
      hidden = null;
      scene.globe.maximumScreenSpaceError = baseError;
      viewer.resolutionScale = SHARP_SCALE;
      scene.requestRender();
    }, SETTLE_MS);
  };

  const canvas = scene.canvas;
  canvas.addEventListener('pointerdown', lighten, { passive: true });
  canvas.addEventListener('wheel', () => { lighten(); restore(); }, { passive: true });
  // 손을 뗀 곳이 캔버스 밖일 수도 있으므로 창 전체에서 받는다
  window.addEventListener('pointerup', restore, { passive: true });
  window.addEventListener('pointercancel', restore, { passive: true });
}

/* requestRenderMode 를 켜면 카메라 이동·타일 로딩은 Cesium 이 알아서 다시
 * 그리지만, 코드가 엔티티 색이나 표시 여부를 바꾼 것까지 항상 잡아내지는
 * 않는다. 그 경우 화면이 멈춘 것처럼 보인다. 사용자가 뭔가 조작하면 잠깐
 * 다시 그려 주는 안전망을 둬서, 어느 모듈이 무엇을 바꾸든 화면에 반영되게 한다. */
function installRedrawSafetyNet(viewer) {
  let until = 0;
  const pump = () => {
    viewer.scene.requestRender();
    if (performance.now() < until) requestAnimationFrame(pump);
  };
  const kick = () => {
    const wasIdle = performance.now() >= until;
    until = performance.now() + 450;   // 조작 후 0.45초만 계속 갱신
    if (wasIdle) requestAnimationFrame(pump);
  };
  for (const ev of ['pointerdown', 'pointerup', 'change', 'input', 'keydown']) {
    document.addEventListener(ev, kick, { passive: true });
  }
  window.addEventListener('resize', kick, { passive: true });
}

function buildLayerUI(layers) {
  const list = document.getElementById('layerList');
  for (const L of layers) {
    const row = document.createElement('label');
    row.className = 'row';
    row.innerHTML = `
      <span class="name"><span class="swatch" style="background:${L.color}"></span>${L.label}</span>
    `;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!L.defaultOn;
    cb.addEventListener('change', () => {
      L.setShow(cb.checked);
      if (L.applyLabels) L.applyLabels(ctx.showLabels && cb.checked, ctx.lang);
    });
    row.appendChild(cb);
    list.appendChild(row);
    L._checkbox = cb;
  }
}

function wireControls(layers) {
  const panel = document.getElementById('panel');
  const quizPanel = document.getElementById('quizPanel');
  document.getElementById('menuToggle').addEventListener('click', () => {
    panel.classList.toggle('hidden');
    quizPanel.classList.add('hidden');
  });
  document.getElementById('quizToggle').addEventListener('click', () => {
    quizPanel.classList.toggle('hidden');
    panel.classList.add('hidden');
  });

  document.getElementById('labelToggle').addEventListener('change', (e) => {
    ctx.showLabels = e.target.checked;
    for (const L of layers) if (L.applyLabels) L.applyLabels(ctx.showLabels && L.ds.show, ctx.lang);
  });

}

function setupQuiz(viewer, bordersLayer) {
  const dom = {
    setup: document.getElementById('quizSetup'),
    play: document.getElementById('quizPlay'),
    result: document.getElementById('quizResult'),
    count: document.getElementById('quizCount'),
    start: document.getElementById('quizStart'),
    next: document.getElementById('quizNext'),
    restart: document.getElementById('quizRestart'),
    progress: document.getElementById('quizProgress'),
    question: document.getElementById('quizQuestion'),
    choices: document.getElementById('quizChoices'),
    feedback: document.getElementById('quizFeedback'),
    score: document.getElementById('quizScore'),
  };
  new Quiz(viewer, bordersLayer, ctx, dom);
}

function setupSearch(viewer, layers, byId) {
  const dom = {
    bar: document.getElementById('searchBar'),
    input: document.getElementById('searchInput'),
    clear: document.getElementById('searchClear'),
    results: document.getElementById('searchResults'),
  };
  const showLayer = (id) => {
    const L = byId[id];
    if (!L) return;
    if (L._checkbox) L._checkbox.checked = true;
    L.setShow(true);
    if (L.applyLabels) L.applyLabels(ctx.showLabels, ctx.lang);
  };
  new Search(viewer, layers, ctx, dom, showLayer);
}

init().catch((err) => {
  console.error(err);
  // 실패해도 로딩 화면 구조는 유지해서, 왜 멈췄는지 화면에 남긴다
  loading.fail(err?.message || String(err));
});

// PWA 서비스워커 등록. localhost 개발 중에는 캐시가 예전 JS를 붙잡아
// 디버깅을 방해할 수 있으므로 기존 서비스워커를 해제한다.
const isLocalhost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
if ('serviceWorker' in navigator && isLocalhost) {
  window.addEventListener('load', async () => {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith('geo-globe-')).map((key) => caches.delete(key)));
  });
} else if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  });
}
