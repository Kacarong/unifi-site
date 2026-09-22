/* 화면에 실제로 그려지는 라벨 개수와 "겹치는 쌍" 수를 센다.
 *
 * 라벨 밀도는 스크린샷만으로는 "줄었다"를 검증할 수 없다. 카메라를 고정해
 * 두고 개수와 겹침을 숫자로 뽑아, 라벨 관련 변경 전후를 같은 기준에서
 * 비교한다. 겹침은 canvas measureText 로 글상자 폭을 실제로 재서 판정한다.
 *
 *   npm run build
 *   (cd dist && python3 -m http.server 8791 --bind 127.0.0.1 &)
 *   GEO_PLAYWRIGHT=<playwright/index.mjs 경로> GEO_CHROME=<브라우저 경로> \
 *     node tools/label-audit.mjs http://127.0.0.1:8791/index.html /tmp/audit
 *
 * playwright 는 이 앱의 의존성이 아니다(빌드에는 필요 없다). 설치된 위치를
 * GEO_PLAYWRIGHT 로, 브라우저 실행 파일을 GEO_CHROME 으로 알려 준다.
 */
const { chromium } = await import(process.env.GEO_PLAYWRIGHT || 'playwright');

const url = process.argv[2] || 'http://127.0.0.1:8791/index.html';
const prefix = process.argv[3] || '/tmp/labels';

const browser = await chromium.launch({
  executablePath: process.env.GEO_CHROME || undefined,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
page.on('console', (m) => { if (m.type() === 'error' && !/404/.test(m.text())) console.error('[page]', m.text()); });
await page.goto(url, { waitUntil: 'domcontentloaded' });

await page.waitForFunction(
  () => document.getElementById('loading')?.classList.contains('hidden'),
  null,
  { timeout: 180000 }
);

/* 화면에 남은 라벨을 조사한다.
 * 라벨 글상자는 canvas measureText 로 실제 폭을 재서 겹침을 판정한다. */
const probe = () => page.evaluate(() => {
  const C = window.Cesium, v = window.viewer, scene = v.scene;
  const cam = scene.camera.positionWC;
  const occ = new C.EllipsoidalOccluder(scene.ellipsoid, cam);
  const W = v.canvas.clientWidth, H = v.canvas.clientHeight;
  const m = document.createElement('canvas').getContext('2d');

  const alphaAt = (nfs, d) => {
    if (!nfs) return 1;
    if (d <= nfs.near) return nfs.nearValue;
    if (d >= nfs.far) return nfs.farValue;
    return nfs.nearValue + ((nfs.farValue - nfs.nearValue) * (d - nfs.near)) / (nfs.far - nfs.near);
  };
  const scaleAt = (nfs, d) => (nfs ? alphaAt(nfs, d) : 1);

  const boxes = [];
  const counts = {};
  const scan = (name, coll) => {
    if (!coll) return;
    for (let i = 0; i < coll.length; i++) {
      const l = coll.get(i);
      if (!l.show || l.clusterShow === false) continue;
      const text = (l.text || '').trim();
      if (!text || !l.position) continue;
      if (!occ.isPointVisible(l.position)) continue;           // 지구 뒤편
      const d = C.Cartesian3.distance(cam, l.position);
      const ddc = l.distanceDisplayCondition;
      if (ddc && (d < ddc.near || d > ddc.far)) continue;      // 거리 조건으로 숨김
      if (alphaAt(l.translucencyByDistance, d) < 0.05) continue;
      const sp = C.SceneTransforms.worldToWindowCoordinates(scene, l.position);
      if (!sp || sp.x < 0 || sp.y < 0 || sp.x > W || sp.y > H) continue;

      const font = l.font || '500 12px sans-serif';
      m.font = font;
      const s = scaleAt(l.scaleByDistance, d) * (l.scale ?? 1);
      const px = parseFloat(/(\d+(?:\.\d+)?)px/.exec(font)?.[1] || '12');
      const w = m.measureText(text).width * s;
      const h = px * 1.25 * s;
      const off = l.pixelOffset || { x: 0, y: 0 };
      // horizontalOrigin: LEFT(1) 은 기준점 오른쪽으로, CENTER(0) 은 양쪽으로 뻗는다
      const left = sp.x + off.x - (l.horizontalOrigin === C.HorizontalOrigin.LEFT ? 0 : w / 2);
      const top = sp.y + off.y - h / 2;
      boxes.push({ text, left, top, w, h, layer: name });
      counts[name] = (counts[name] || 0) + 1;
    }
  };

  for (const ds of v.dataSources._dataSources) {
    if (!ds.show) continue;
    const ec = ds.clustering;
    const n = (ds.name || 'ds').replace('.geojson', '');
    scan(n, ec?._labelCollection);
    scan(n + ':cluster', ec?._clusterLabelCollection);
  }

  // 겹치는 쌍 세기 (글상자가 실제로 교차하는 경우만)
  const pairs = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      const ox = Math.min(a.left + a.w, b.left + b.w) - Math.max(a.left, b.left);
      const oy = Math.min(a.top + a.h, b.top + b.h) - Math.max(a.top, b.top);
      if (ox > 1 && oy > 1) pairs.push(`${a.text} × ${b.text}`);
    }
  }

  return {
    total: boxes.length,
    counts,
    overlapPairs: pairs.length,
    overlapExamples: pairs.slice(0, 12),
    cameraHeight: Math.round(scene.camera.positionCartographic.height),
    labels: boxes.map((b) => b.text).sort(),
  };
});

const settle = async () => {
  await page.waitForFunction(() => window.viewer.scene.globe.tilesLoaded, null, { timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(2500);
  await page.evaluate(() => { for (let i = 0; i < 5; i++) window.viewer.scene.render(); });
};

const out = {};

// ① 지구 전체 — 초기 시점과 동일(flyHome(0))
await page.evaluate(() => { window.viewer.camera.flyHome(0); window.viewer.scene.requestRender(); });
await settle();
out.far = await probe();
await page.screenshot({ path: `${prefix}-far.png` });

/* ②~ 라벨이 실제로 붐비는 거리들. pixelRange 는 여기서 효과가 난다.
 * 유럽·미국 동부는 도시 밀도가 가장 높은 곳이라 겹침이 가장 잘 드러난다. */
const VIEWS = {
  europe: [10, 48, 2500000],
  usEast: [-80, 38, 1500000],
  korea: [127.4, 36.8, 900000],
  koreaClose: [127.0, 37.3, 300000],
};
for (const [name, [lon, lat, h]] of Object.entries(VIEWS)) {
  await page.evaluate(([lon, lat, h]) => {
    window.viewer.camera.setView({
      destination: window.Cesium.Cartesian3.fromDegrees(lon, lat, h),
    });
    window.viewer.scene.requestRender();
  }, [lon, lat, h]);
  await settle();
  out[name] = await probe();
  await page.screenshot({ path: `${prefix}-${name}.png` });
}

console.log(JSON.stringify(out, null, 2));
await browser.close();
