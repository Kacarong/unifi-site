import * as Cesium from 'cesium';
import './style.css';
import { buildLayers } from './layers.js';
import { Quiz } from './quiz.js';
import { Search } from './search.js';

const ctx = { lang: 'ko', showLabels: true };

// 선택: Cesium ion 토큰이 있으면 3D 지형 + 위성영상 품질 향상
const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN;
if (ionToken) Cesium.Ion.defaultAccessToken = ionToken;

async function init() {
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
  });

  // 해상도/선명도 향상
  viewer.resolutionScale = Math.min(window.devicePixelRatio || 1, 2); // 고DPI(레티나/4K)에서 선명하게
  viewer.scene.globe.maximumScreenSpaceError = 1.5; // 위성 타일 상세도 상향(기본 2 → 1.5)
  viewer.scene.globe.preloadSiblings = true;
  if (viewer.scene.postProcessStages.fxaa) viewer.scene.postProcessStages.fxaa.enabled = true;

  viewer.scene.globe.showGroundAtmosphere = true;
  viewer.scene.skyAtmosphere.show = true;

  // ion 토큰이 있을 때만 3D 지형 사용
  if (ionToken) {
    try { viewer.scene.setTerrain(Cesium.Terrain.fromWorldTerrain()); } catch (e) { /* ignore */ }
  }

  // 초기 시점: 지구 전체
  viewer.camera.flyHome(0);

  // 레이어 구성
  const layers = await buildLayers(viewer, ctx);
  const byId = Object.fromEntries(layers.map((l) => [l.id, l]));

  // 초기 라벨 상태 적용
  for (const L of layers) if (L.applyLabels) L.applyLabels(ctx.showLabels && L.ds.show, ctx.lang);

  buildLayerUI(layers);
  wireControls(layers);
  setupQuiz(viewer, byId.borders);
  setupSearch(viewer, layers, byId);

  window.Cesium = Cesium;
  window.viewer = viewer; // 콘솔에서 카메라 제어/디버깅용
  document.getElementById('loading').classList.add('hidden');
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
  const el = document.getElementById('loading');
  el.textContent = '초기화 오류: ' + (err?.message || err);
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
