import * as Cesium from 'cesium';

const DATA = './data';

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
      stroke: Cesium.Color.fromCssColorString('#ffd34d'),
      fill: Cesium.Color.TRANSPARENT, strokeWidth: 2, defaultOn: true,
    });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      if (e.polygon) {
        e.polygon.outline = true;
        e.polygon.outlineColor = Cesium.Color.fromCssColorString('#ffd34d');
        e.polygon.material = Cesium.Color.TRANSPARENT;
        e.polygon.arcType = Cesium.ArcType.GEODESIC;
      }
      if (p.LABEL_X !== undefined && p.LABEL_Y !== undefined) {
        e.position = Cesium.Cartesian3.fromDegrees(Number(p.LABEL_X), Number(p.LABEL_Y));
        e.label = new Cesium.LabelGraphics({
          text: pick(p, ctx.lang, ['NAME', 'ADMIN']),
          font: '600 14px "Noto Sans KR", sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          scaleByDistance: nfs(1.5e6, 1.1, 2.0e7, 0.5),
          translucencyByDistance: nfs(2.0e7, 1.0, 4.0e7, 0.0),
          disableDepthTestDistance: 0,
        });
      }
    }
    register({
      id: 'borders', label: '국경 (국가)', color: '#ffd34d', defaultOn: true, hasLabel: true,
      labelFields: ['NAME', 'ADMIN'], ds,
    });
  }

  // 2) 행정경계 (주/도)
  {
    const ds = await loadGeo(viewer, `${DATA}/admin1.geojson`, {
      stroke: Cesium.Color.fromCssColorString('#7fd1ff').withAlpha(0.8),
      fill: Cesium.Color.TRANSPARENT, strokeWidth: 1, defaultOn: false,
    });
    for (const e of ds.entities.values) {
      const p = propsToObj(e);
      e._props = p;
      if (e.polygon) {
        e.polygon.outline = true;
        e.polygon.outlineColor = Cesium.Color.fromCssColorString('#7fd1ff').withAlpha(0.7);
        e.polygon.material = Cesium.Color.TRANSPARENT;
      }
      const lon = Number(p.longitude), lat = Number(p.latitude);
      if (Number.isFinite(lon) && Number.isFinite(lat)) {
        e.position = Cesium.Cartesian3.fromDegrees(lon, lat);
        e.label = new Cesium.LabelGraphics({
          text: pick(p, ctx.lang, ['name', 'NAME']),
          font: '500 12px "Noto Sans KR", sans-serif',
          fillColor: Cesium.Color.fromCssColorString('#cfeaff'),
          outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          distanceDisplayCondition: ddc(7.0e6),
          scaleByDistance: nfs(1.0e6, 1.0, 7.0e6, 0.5),
        });
      }
    }
    register({ id: 'admin1', label: '행정경계 (주/도)', color: '#7fd1ff', defaultOn: false, hasLabel: true, labelFields: ['name', 'NAME'], ds });
  }

  // 3) 분쟁지역
  {
    const ds = await loadGeo(viewer, `${DATA}/disputed.geojson`, {
      stroke: Cesium.Color.fromCssColorString('#ff5d6c'),
      fill: Cesium.Color.fromCssColorString('#ff5d6c').withAlpha(0.28),
      strokeWidth: 2, defaultOn: false,
    });
    register({ id: 'disputed', label: '분쟁지역', color: '#ff5d6c', defaultOn: false, ds });
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
        pixelSize: rank <= 2 ? 7 : rank <= 5 ? 5 : 4,
        color: Cesium.Color.fromCssColorString('#ffb454'),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 1,
        distanceDisplayCondition: ddc(far),
      });
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['NAME']),
        font: '500 13px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(7, 0),
        horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        distanceDisplayCondition: ddc(far),
        scaleByDistance: nfs(far * 0.25, 1.05, far, 0.5),
      });
    }
    register({ id: 'cities', label: '도시 (7천+)', color: '#ffb454', defaultOn: true, hasLabel: true, labelFields: ['NAME'], ds });
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
        color: isCanal ? Cesium.Color.fromCssColorString('#24d3a5') : Cesium.Color.fromCssColorString('#4f8cff'),
        outlineColor: Cesium.Color.WHITE, outlineWidth: 1.5,
      });
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['name']),
        font: '600 13px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString('#cfe4ff'),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -14),
      });
    }
    register({ id: 'straits', label: '해협 · 운하', color: '#4f8cff', defaultOn: false, hasLabel: true, labelFields: ['name'], ds });
  }

  // 6) 강 — 라벨 + 검색
  {
    const ds = await loadGeo(viewer, `${DATA}/rivers.geojson`, {
      stroke: Cesium.Color.fromCssColorString('#5db6ff'), strokeWidth: 2, defaultOn: false,
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
          fillColor: Cesium.Color.fromCssColorString('#8fd0ff'),
          outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          distanceDisplayCondition: ddc(1.2e7),
          scaleByDistance: nfs(1.0e6, 1.05, 1.2e7, 0.5),
        });
      }
    }
    register({ id: 'rivers', label: '주요 강', color: '#5db6ff', defaultOn: false, hasLabel: true, labelFields: ['name'], ds });
  }

  // 7) 호수 — 라벨 + 검색
  {
    const ds = await loadGeo(viewer, `${DATA}/lakes.geojson`, {
      stroke: Cesium.Color.fromCssColorString('#5db6ff'),
      fill: Cesium.Color.fromCssColorString('#2a6fbf').withAlpha(0.55),
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
          fillColor: Cesium.Color.fromCssColorString('#bfe4ff'),
          outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          distanceDisplayCondition: ddc(1.5e7),
          scaleByDistance: nfs(1.0e6, 1.05, 1.5e7, 0.5),
        });
      }
    }
    register({ id: 'lakes', label: '주요 호수', color: '#5db6ff', defaultOn: false, hasLabel: true, labelFields: ['name'], ds });
  }

  // 8) 판의 경계
  {
    const ds = await loadGeo(viewer, `${DATA}/plates.geojson`, {
      stroke: Cesium.Color.fromCssColorString('#ff8c42'), strokeWidth: 3, defaultOn: false,
    });
    register({ id: 'plates', label: '판의 경계', color: '#ff8c42', defaultOn: false, ds });
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
        color: Cesium.Color.fromCssColorString('#e8c07d').withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 1,
        distanceDisplayCondition: ddc(far),
      });
      e.label = new Cesium.LabelGraphics({
        text: pick(p, ctx.lang, ['NAME', 'name']),
        font: 'italic 600 13px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString('#ffe6b0'),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        distanceDisplayCondition: ddc(far),
        scaleByDistance: nfs(far * 0.25, 1.05, far, 0.5),
      });
    }
    register({ id: 'regions', label: '지형·지역 (고원/사막/산맥)', color: '#e8c07d', defaultOn: false, hasLabel: true, labelFields: ['NAME', 'name'], ds });
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
        fillColor: Cesium.Color.fromCssColorString('#9fd0ff'),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        distanceDisplayCondition: ddc(far),
        scaleByDistance: nfs(far * 0.25, 1.1, far, 0.5),
      });
    }
    register({ id: 'marine', label: '바다·해양', color: '#9fd0ff', defaultOn: false, hasLabel: true, labelFields: ['name', 'NAME'], ds });
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
      { lat: 45, latEnd: 48, dir: 'E', color: '#4dd2ff', name: '편서풍(북)' },
      { lat: -45, latEnd: -48, dir: 'E', color: '#4dd2ff', name: '편서풍(남)' },
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
    register({ id: 'winds', label: '편서풍·무역풍', color: '#4dd2ff', defaultOn: false, ds });
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
