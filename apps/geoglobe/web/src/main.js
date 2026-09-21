import * as Cesium from 'cesium';
import './style.css';
import { buildLayers } from './layers.js';
import { Quiz } from './quiz.js';
import { Search } from './search.js';

const ctx = { lang: 'ko', showLabels: true };

/* 휴대폰은 화면이 촘촘하고(dpr 3) GPU 는 약하다. 데스크톱 기준 화질을 그대로
 * 쓰면 그려야 할 픽셀이 몇 배로 늘어 프레임이 무너진다. 기기를 보고 낮춘다. */
const LOW_POWER =
  matchMedia('(pointer: coarse)').matches ||
  Math.min(screen.width, screen.height) <= 820 ||
  (navigator.hardwareConcurrency || 8) <= 4;

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
    // 기본 Cesium 은 가만히 있어도 초당 60번 다시 그린다. 지구본은 움직일
    // 때만 바뀌므로 변화가 있을 때만 그리게 한다. 모바일 발열/배터리와
    // 프레임에 가장 크게 작용하는 설정이다.
    requestRenderMode: true,
    maximumRenderTimeChange: Infinity,
  });

  const scene = viewer.scene;

  // 화질 — 저사양에선 한 단계씩 낮춘다
  viewer.resolutionScale = LOW_POWER ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  scene.globe.maximumScreenSpaceError = LOW_POWER ? 3 : 1.5; // 클수록 타일 적게 = 가볍다
  scene.globe.preloadSiblings = !LOW_POWER;                  // 주변 타일 미리 받기
  if (scene.postProcessStages.fxaa) scene.postProcessStages.fxaa.enabled = !LOW_POWER;

  // 대기 표현은 예쁘지만 매 프레임 추가 셰이딩이 든다
  scene.globe.showGroundAtmosphere = !LOW_POWER;
  scene.skyAtmosphere.show = !LOW_POWER;
  scene.fog.enabled = !LOW_POWER;

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
  installRedrawSafetyNet(viewer);
  document.getElementById('loading').classList.add('hidden');
  viewer.scene.requestRender();
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
