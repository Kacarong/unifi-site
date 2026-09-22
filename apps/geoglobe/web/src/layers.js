import * as Cesium from 'cesium';

const DATA = './data';

/* 색·굵기를 한곳에 모은다.
 *
 * 처음엔 형광에 가까운 노랑·주황에 라벨마다 3px 검은 테두리를 둘렀더니,
 * 위성 사진 위에서 선과 글자가 먼저 튀어 지도가 조잡해 보였다. 구글 어스처럼
 * 사진이 주인공이 되도록 선은 가늘고 반투명하게, 글자 테두리는 그림자
 * 정도로만 남긴다. 레이어를 구분하는 색 성격은 유지하되 채도만 낮춘다.
 */
export const PALETTE = {
  border: '#d8c995',      // 국경 — 위성 사진을 덮지 않는 낮은 채도의 모래빛
  admin: '#a9c6dd',       // 행정경계
  city: '#fff3dc',        // 도시 점 — 거의 흰색
  water: '#8fbce0',       // 강·호수·해협
  disputed: '#e08a92',
  plate: '#d99a6c',
  region: '#dcc9a3',
  marine: '#a8c6e4',
  wind: '#8fd3e8',
};

// 라벨은 검은 테두리를 얇게 깔아 사진 위에서 읽히게만 한다(그림자 역할)
const LABEL_HALO = Cesium.Color.BLACK.withAlpha(0.62);
const LABEL_HALO_W = 1.6;

// 언어별 이름 선택 헬퍼
export function pick(props, lang, fields) {
  for (const base of fields) {
    const keys = lang === 'ko'
      ? [base + '_KO', base.toLowerCase() + '_ko', base + '_ko', base, base + '_EN', base.toLowerCase()]
      : [base + '_EN', base.toLowerCase() + '_en', base, base.toLowerCase()];
    for (const k of keys) {
      const v = props[k];
      if (v !== undefined && v !== null && String(v).trim() !== '') return String(v);
    }
  }
  return '';
}

function propsToObj(entity) {
  const p = {};
  const ep = entity.properties;
  if (!ep) return p;
  for (const key of ep.propertyNames) p[key] = ep[key] ? ep[key].getValue() : undefined;
  return p;
}

// GeoJSON 데이터소스 로더
async function loadGeo(viewer, url, opts = {}) {
  const ds = await Cesium.GeoJsonDataSource.load(url, {
    stroke: opts.stroke ?? Cesium.Color.WHITE,
    fill: opts.fill ?? Cesium.Color.TRANSPARENT,
    strokeWidth: opts.strokeWidth ?? 2,
    clampToGround: false,
  });
  ds.show = !!opts.defaultOn;
  await viewer.dataSources.add(ds);
  return ds;
}

// 거리 표시 조건(가까울 때만 보이게 → 라벨 밀집 방지). far는 항상 near(0)보다 크게 보정.
function ddc(far) {
  const f = Number.isFinite(far) && far > 1 ? far : 1.0e7;
  return new Cesium.DistanceDisplayCondition(0.0, f);
}
// NearFarScalar 안전 생성기: Cesium은 far > near 를 강제하므로 항상 보정한다.
function nfs(near, nearValue, far, farValue) {
  let n = Number.isFinite(near) && near >= 0 ? near : 0;
  let f = Number.isFinite(far) ? far : n + 1;
  if (f <= n) f = n + 1;
  return new Cesium.NearFarScalar(n, nearValue, f, farValue);
}
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// 폴리곤/폴리라인 엔티티의 대표 좌표(라벨·검색 위치용)
function entityCenter(e) {
  const t = Cesium.JulianDate.now();
  if (e.polygon && e.polygon.hierarchy) {
    const h = e.polygon.hierarchy.getValue(t);
    const pts = h && h.positions ? h.positions : h;
    if (pts && pts.length) return Cesium.BoundingSphere.fromPoints(pts).center;
  }
  if (e.polyline && e.polyline.positions) {
    const pts = e.polyline.positions.getValue(t);
    if (pts && pts.length) return pts[Math.floor(pts.length / 2)];
  }
  return undefined;
}

// 도시 중요도(SCALERANK 0~10)별 표시 거리(m)
const CITY_FAR = [4.2e7, 3.0e7, 2.0e7, 1.2e7, 7.0e6, 4.5e6, 2.8e6, 1.7e6, 1.0e6, 6.5e5, 4.0e5];
// 도시 이름은 점이 보이는 거리의 이만큼 안쪽으로 들어와야 나타난다
const CITY_LABEL_RATIO = 0.18;
function cityFar(scalerank) {
  const r = Number.isFinite(scalerank) ? Math.round(scalerank) : 8;
  return CITY_FAR[clamp(r, 0, 10)];
}
// 지형/지역 min_label(0~9)별 표시 거리
function regionFar(minLabel) {
  const m = Number.isFinite(minLabel) ? minLabel : 6;
  return clamp(4.0e5 * Math.pow(2, 8 - m), 4.0e5, 4.0e7);
}

// ── 개별 레이어 정의 ─────────────────────────────────────────────
// 아래에서 register() 로 등록하는 레이어 개수. 로딩 진행률에 쓴다.
// 레이어를 늘리거나 줄이면 이 값도 맞춰야 한다(안 맞으면 콘솔에 경고가 뜬다).
export const LAYER_COUNT = 12;

/** @param onStep 레이어 하나가 준비될 때마다 (지금까지 개수, 이름) 으로 불린다 */
export async function buildLayers(viewer, ctx, onStep) {
  const layers = [];
  const register = (obj) => {
    layers.push(obj);
    // 모든 레이어가 이 한 곳을 지나가므로 진행 보고도 여기에만 둔다
    try { onStep?.(layers.length, obj.label); } catch { /* 보고 실패가 로딩을 막으면 안 된다 */ }
    return obj;
  };

  // 1) 국경 (국가 경계) — 라벨 지원
  {
    const ds = await loadGeo(viewer, `${DATA}/countries.geojson`, {
      stroke: Cesium.Color.fromCssColorString(PALETTE.border).withAlpha(0.72),
      fill: Cesium.Color.TRANSPARENT, strokeWidth: 0.8, defaultOn: true,
    });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      if (e.polygon) {
        e.polygon.outline = true;
        e.polygon.outlineColor = Cesium.Color.fromCssColorString(PALETTE.border).withAlpha(0.72);
        e.polygon.material = Cesium.Color.TRANSPARENT;
        e.polygon.arcType = Cesium.ArcType.GEODESIC;
      }
      if (p.LABEL_X !== undefined && p.LABEL_Y !== undefined) {
        e.position = Cesium.Cartesian3.fromDegrees(Number(p.LABEL_X), Number(p.LABEL_Y));
        e.label = new Cesium.LabelGraphics({
          text: pick(p, ctx.lang, ['NAME', 'ADMIN']),
          font: '600 13px "Noto Sans KR", sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          /* 지구 전체 뷰에서 읽히는 유일한 이름이다.
           *
           * 전에는 멀어질수록 0.42배까지 줄이고 투명도도 같이 빼서, 초기
           * 시점(약 2.1e7 m)에서 13px 글자가 5.5px·투명도 0.6 으로 찍혔다.
           * 그때는 클러스터 대표 라벨이 이 설정을 못 받아 원래 크기로 떠서
           * 문제가 드러나지 않았을 뿐이다. 도시 이름이 이 거리에서 모두
           * 빠지는 지금은 국가 이름마저 안 보이면 이름 없는 지구가 된다.
           * 멀리서도 읽을 수 있는 크기를 유지하고, 그보다 더 뒤로 빼야
           * 사라지게 한다. */
          scaleByDistance: nfs(1.5e6, 1.0, 2.6e7, 0.8),
          translucencyByDistance: nfs(2.8e7, 0.95, 4.2e7, 0.0),
          disableDepthTestDistance: 0,
        });
      }
    }
    register({
      id: 'borders', label: '국경 (국가)', color: PALETTE.border, defaultOn: true, hasLabel: true,
      labelFields: ['NAME', 'ADMIN'], ds,
    });
  }

  // 2) 행정경계 (주/도)
  {
    const ds = await loadGeo(viewer, `${DATA}/admin1.geojson`, {
      stroke: Cesium.Color.fromCssColorString(PALETTE.admin).withAlpha(0.8),
      fill: Cesium.Color.TRANSPARENT, strokeWidth: 1, defaultOn: false,
    });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      if (e.polygon) {
        e.polygon.outline = true;
        e.polygon.outlineColor = Cesium.Color.fromCssColorString(PALETTE.admin).withAlpha(0.7);
        e.polygon.material = Cesium.Color.TRANSPARENT;
      }
      const lon = Number(p.longitude), lat = Number(p.latitude);
      if (Number.isFinite(lon) && Number.isFinite(lat)) {
        e.position = Cesium.Cartesian3.fromDegrees(lon, lat);
        e.label = new Cesium.LabelGraphics({
          text: pick(p, ctx.lang, ['name', 'NAME']),
          font: '500 12px "Noto Sans KR", sans-serif',
          fillColor: Cesium.Color.fromCssColorString(PALETTE.admin),
          outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          distanceDisplayCondition: ddc(7.0e6),
          scaleByDistance: nfs(1.0e6, 1.0, 7.0e6, 0.5),
        });
      }
    }
    register({ id: 'admin1', label: '행정경계 (주/도)', color: PALETTE.admin, defaultOn: false, hasLabel: true, labelFields: ['name', 'NAME'], ds });
  }

  // 3) 분쟁지역
  {
    const ds = await loadGeo(viewer, `${DATA}/disputed.geojson`, {
      stroke: Cesium.Color.fromCssColorString(PALETTE.disputed),
      fill: Cesium.Color.fromCssColorString(PALETTE.disputed).withAlpha(0.28),
      strokeWidth: 2, defaultOn: false,
    });
    register({ id: 'disputed', label: '분쟁지역', color: PALETTE.disputed, defaultOn: false, ds });
  }

  // 4) 도시 — 7천여 개(중요도별 거리 표시로 밀집 방지)
  {
    const ds = await loadGeo(viewer, `${DATA}/cities.geojson`, { defaultOn: true });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      const far = cityFar(p.SCALERANK);
      const rank = Number.isFinite(p.SCALERANK) ? p.SCALERANK : 8;
      e.billboard = undefined;
      e.point = new Cesium.PointGraphics({
        pixelSize: rank <= 2 ? 4 : rank <= 5 ? 3.5 : 2.5,
        color: Cesium.Color.fromCssColorString(PALETTE.city).withAlpha(rank <= 5 ? 0.92 : 0.72),
        outlineColor: Cesium.Color.BLACK.withAlpha(0.45), outlineWidth: 0.8,
        distanceDisplayCondition: ddc(far),
      });
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['NAME']),
        font: '500 12px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.WHITE, outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(7, 0),
        horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        // 이름은 점보다 늦게 나타난다. 점과 같은 거리에서 함께 띄우면
        // 지구 전체를 볼 때 글자끼리 겹쳐 지도를 덮어 버린다.
        // 멀리서는 위치(점)만, 가까이 가야 이름까지 보인다.
        distanceDisplayCondition: ddc(far * CITY_LABEL_RATIO),
        scaleByDistance: nfs(far * 0.12, 1.0, far * CITY_LABEL_RATIO, 0.45),
      });
    }
    register({ id: 'cities', label: '도시 (7천+)', color: PALETTE.city, defaultOn: true, hasLabel: true, labelFields: ['NAME'], ds });
  }

  // 5) 해협 · 운하 (커스텀)
  {
    const ds = await loadGeo(viewer, `${DATA}/straits.geojson`, { defaultOn: false });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      const isCanal = p.kind === 'canal';
      e.billboard = undefined;
      e.point = new Cesium.PointGraphics({
        pixelSize: 8,
        color: isCanal ? Cesium.Color.fromCssColorString(PALETTE.water) : Cesium.Color.fromCssColorString(PALETTE.water),
        outlineColor: Cesium.Color.WHITE, outlineWidth: 1.5,
      });
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['name']),
        font: '600 13px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString(PALETTE.water),
        outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -14),
      });
    }
    register({ id: 'straits', label: '해협 · 운하', color: PALETTE.water, defaultOn: false, hasLabel: true, labelFields: ['name'], ds });
  }

  // 6) 강 — 라벨 + 검색
  {
    const ds = await loadGeo(viewer, `${DATA}/rivers.geojson`, {
      stroke: Cesium.Color.fromCssColorString(PALETTE.water), strokeWidth: 2, defaultOn: false,
    });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      const pos = entityCenter(e);
      if (pos) {
        e.position = pos;
        e.label = new Cesium.LabelGraphics({
          text: pick(p, ctx.lang, ['name']),
          font: 'italic 500 13px "Noto Sans KR", sans-serif',
          fillColor: Cesium.Color.fromCssColorString(PALETTE.water),
          outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          distanceDisplayCondition: ddc(1.2e7),
          scaleByDistance: nfs(1.0e6, 1.05, 1.2e7, 0.5),
        });
      }
    }
    register({ id: 'rivers', label: '주요 강', color: PALETTE.water, defaultOn: false, hasLabel: true, labelFields: ['name'], ds });
  }

  // 7) 호수 — 라벨 + 검색
  {
    const ds = await loadGeo(viewer, `${DATA}/lakes.geojson`, {
      stroke: Cesium.Color.fromCssColorString(PALETTE.water),
      fill: Cesium.Color.fromCssColorString(PALETTE.water).withAlpha(0.35),
      strokeWidth: 1, defaultOn: false,
    });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      const pos = entityCenter(e);
      if (pos) {
        e.position = pos;
        e.label = new Cesium.LabelGraphics({
          text: pick(p, ctx.lang, ['name']),
          font: '500 13px "Noto Sans KR", sans-serif',
          fillColor: Cesium.Color.fromCssColorString(PALETTE.marine),
          outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          distanceDisplayCondition: ddc(1.5e7),
          scaleByDistance: nfs(1.0e6, 1.05, 1.5e7, 0.5),
        });
      }
    }
    register({ id: 'lakes', label: '주요 호수', color: PALETTE.water, defaultOn: false, hasLabel: true, labelFields: ['name'], ds });
  }

  // 8) 판의 경계
  {
    const ds = await loadGeo(viewer, `${DATA}/plates.geojson`, {
      stroke: Cesium.Color.fromCssColorString(PALETTE.plate), strokeWidth: 3, defaultOn: false,
    });
    register({ id: 'plates', label: '판의 경계', color: PALETTE.plate, defaultOn: false, ds });
  }

  // 8b) 지형·지역 (고원/사막/산맥/반도/평원 등) — 라벨
  {
    const ds = await loadGeo(viewer, `${DATA}/regions.geojson`, { defaultOn: false });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      const far = regionFar(p.min_label);
      e.billboard = undefined;
      e.point = new Cesium.PointGraphics({
        pixelSize: 4,
        color: Cesium.Color.fromCssColorString(PALETTE.region).withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK.withAlpha(0.55), outlineWidth: 1,
        distanceDisplayCondition: ddc(far),
      });
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['NAME', 'name']),
        font: 'italic 600 13px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString(PALETTE.region),
        outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        distanceDisplayCondition: ddc(far),
        scaleByDistance: nfs(far * 0.25, 1.05, far, 0.5),
      });
    }
    register({ id: 'regions', label: '지형·지역 (고원/사막/산맥)', color: PALETTE.region, defaultOn: false, hasLabel: true, labelFields: ['NAME', 'name'], ds });
  }

  // 8c) 바다·해양 (대양/바다/만/해협) — 라벨
  {
    const ds = await loadGeo(viewer, `${DATA}/marine.geojson`, { defaultOn: false });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      const fc = (p.featurecla || '').toLowerCase();
      const far = fc.includes('ocean') ? 4.0e7 : fc.includes('sea') ? 2.2e7 : 7.0e6;
      e.billboard = undefined;
      e.point = undefined;
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['name', 'NAME']),
        font: 'italic 500 13px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString(PALETTE.marine),
        outlineColor: LABEL_HALO, outlineWidth: LABEL_HALO_W,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        distanceDisplayCondition: ddc(far),
        scaleByDistance: nfs(far * 0.25, 1.1, far, 0.5),
      });
    }
    register({ id: 'marine', label: '바다·해양', color: PALETTE.marine, defaultOn: false, hasLabel: true, labelFields: ['name', 'NAME'], ds });
  }

  // 9) 위도·경도 격자 (그래티큘) — 이미지 레이어
  {
    const grid = new Cesium.GridImageryProvider({
      cells: 8, color: Cesium.Color.WHITE.withAlpha(0.35),
      glowColor: Cesium.Color.WHITE.withAlpha(0.05), glowWidth: 0,
      backgroundColor: Cesium.Color.TRANSPARENT,
    });
    const imgLayer = viewer.imageryLayers.addImageryProvider(grid);
    imgLayer.show = false;
    register({
      id: 'graticule', label: '위도·경도 격자', color: '#ffffff', defaultOn: false,
      _imagery: imgLayer,
      setShow(v) { imgLayer.show = v; },
    });
  }

  // 10) 편서풍·무역풍 (기후 개략)
  {
    const ds = new Cesium.CustomDataSource('winds');
    const bands = [
      { lat: 15, latEnd: 8, dir: 'W', color: '#ffa94d', name: '북동 무역풍' },
      { lat: -15, latEnd: -8, dir: 'W', color: '#ffa94d', name: '남동 무역풍' },
      { lat: 45, latEnd: 48, dir: 'E', color: PALETTE.wind, name: '편서풍(북)' },
      { lat: -45, latEnd: -48, dir: 'E', color: PALETTE.wind, name: '편서풍(남)' },
      { lat: 72, latEnd: 68, dir: 'W', color: '#c792ff', name: '극동풍(북)' },
      { lat: -72, latEnd: -68, dir: 'W', color: '#c792ff', name: '극동풍(남)' },
    ];
    for (const b of bands) {
      for (let lon = -170; lon <= 170; lon += 40) {
        const dLon = b.dir === 'E' ? 22 : -22;
        const start = [lon, b.lat];
        const end = [lon + dLon, b.latEnd];
        ds.entities.add({
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray([start[0], start[1], end[0], end[1]]),
            width: 6,
            material: new Cesium.PolylineArrowMaterialProperty(Cesium.Color.fromCssColorString(b.color).withAlpha(0.9)),
            arcType: Cesium.ArcType.GEODESIC,
            clampToGround: false,
          },
        });
      }
    }
    ds.show = false;
    await viewer.dataSources.add(ds);
    register({ id: 'winds', label: '편서풍·무역풍', color: PALETTE.wind, defaultOn: false, ds });
  }

  // 공통 show/label 컨트롤 부여
  for (const L of layers) {
    if (!L.setShow) {
      L.setShow = (v) => { if (L.ds) L.ds.show = v; };
    }
    if (L.hasLabel && !L.applyLabels) {
      L.applyLabels = (show, lang) => {
        for (const e of L.ds.entities.values) {
          if (!e.label) continue;
          e.label.show = show;
          if (e._props || e.properties) {
            const p = e._props || propsToObj(e);
            e.label.text = pick(p, lang, L.labelFields);
          }
        }
      };
    }
  }

  if (layers.length !== LAYER_COUNT) {
    console.warn(`LAYER_COUNT(${LAYER_COUNT}) 와 실제 레이어 수(${layers.length}) 가 다릅니다. 진행률 표시가 어긋납니다.`);
  }
  return layers;
}
