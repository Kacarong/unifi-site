import * as Cesium from 'cesium';
import { pick } from './layers.js';

const KIND = {
  borders: '국가', admin1: '행정구역', cities: '도시',
  straits: '해협·운하', regions: '지형', marine: '바다',
  rivers: '강', lakes: '호수',
};
const ALT = { cities: 300000, straits: 700000, regions: 1300000, marine: 4500000, rivers: 900000, lakes: 700000 };
const HL_FILL = Cesium.Color.fromCssColorString('#ffe14d').withAlpha(0.45);

const norm = (s) => (s || '').toString().toLowerCase().replace(/\s+/g, '');

export class Search {
  constructor(viewer, layers, ctx, dom, showLayer) {
    this.viewer = viewer;
    this.ctx = ctx;
    this.dom = dom;
    this.showLayer = showLayer;
    this.prevPoly = null;
    this.hlDs = new Cesium.CustomDataSource('search-hl');
    viewer.dataSources.add(this.hlDs);

    // 국가명 영문→한글 매핑(부제를 한국어로 표시하기 위함)
    this.countryKo = {};
    const bordersL = layers.find((l) => l.id === 'borders');
    if (bordersL) {
      for (const e of bordersL.ds.entities.values) {
        const p = e._props || {};
        const ko = p.NAME_KO;
        if (!ko) continue;
        for (const k of [p.NAME, p.ADMIN, p.NAME_LONG, p.SOVEREIGNT, p.GEOUNIT]) {
          if (k) this.countryKo[norm(k)] = ko;
        }
      }
    }

    this.index = [];
    const seen = new Set();
    for (const L of layers) {
      if (!L.hasLabel || !L.labelFields || !L.ds) continue;
      for (const e of L.ds.entities.values) {
        let pos = e.position && e.position.getValue(Cesium.JulianDate.now());
        if (!pos) continue;
        const p = e._props || {};
        const nameKo = pick(p, 'ko', L.labelFields);
        const nameEn = pick(p, 'en', L.labelFields);
        const name = nameKo;
        if (!name) continue;
        const subRaw = p.ADM0NAME || p.admin || p.ADMIN || '';
        const sub = L.id === 'borders' ? '' : (this.countryKo[norm(subRaw)] || '');
        const dedup = `${L.id}|${name}|${sub}`;
        if (seen.has(dedup)) continue; // 같은 레이어의 동일 이름(예: 다중 폴리곤 국가) 중복 제거
        seen.add(dedup);
        this.index.push({ name, nameKo, nameEn, sub, entity: e, layer: L, pos, key: norm(nameKo) + ' ' + norm(nameEn) });
      }
    }

    dom.input.addEventListener('input', () => this.onInput());
    dom.input.addEventListener('focus', () => { if (dom.input.value.trim()) this.onInput(); });
    dom.clear.addEventListener('click', () => this.reset());
    document.addEventListener('click', (ev) => {
      if (!this.dom.bar.contains(ev.target)) this.hideResults();
    });
  }

  onInput() {
    const q = this.dom.input.value.trim();
    this.dom.bar.classList.toggle('has-text', q.length > 0);
    if (!q) { this.hideResults(); return; }
    const nq = norm(q);
    const scored = [];
    for (const it of this.index) {
      const idx = it.key.indexOf(nq);
      if (idx < 0) continue;
      const starts = norm(it.nameKo).startsWith(nq) || norm(it.nameEn).startsWith(nq);
      scored.push({ it, score: (starts ? 0 : 1) * 1000 + it.name.length });
    }
    scored.sort((a, b) => a.score - b.score);
    this.render(scored.slice(0, 25).map((s) => s.it));
  }

  render(items) {
    const box = this.dom.results;
    box.innerHTML = '';
    if (!items.length) {
      box.innerHTML = '<div class="result"><span class="sub">검색 결과가 없습니다</span></div>';
      box.classList.remove('hidden');
      return;
    }
    for (const it of items) {
      const el = document.createElement('div');
      el.className = 'result';
      const sub = it.sub && it.sub !== it.name ? `<span class="sub">${it.sub}</span>` : '';
      el.innerHTML = `<span class="rname"><span>${it.name}</span>${sub}</span><span class="kind">${KIND[it.layer.id] || ''}</span>`;
      el.addEventListener('click', () => this.select(it));
      box.appendChild(el);
    }
    box.classList.remove('hidden');
  }

  hideResults() { this.dom.results.classList.add('hidden'); }

  clearHighlight() {
    this.hlDs.entities.removeAll();
    if (this.prevPoly && this.prevPoly.polygon) this.prevPoly.polygon.material = Cesium.Color.TRANSPARENT;
    this.prevPoly = null;
  }

  select(it) {
    this.dom.input.value = it.name;
    this.hideResults();
    if (this.showLayer) this.showLayer(it.layer.id);
    this.clearHighlight();

    // 폴리곤(국가/행정구역)은 면 강조
    if (it.entity.polygon) {
      it.entity.polygon.material = HL_FILL;
      this.prevPoly = it.entity;
    }
    // 강조 마커(고리 + 이름) — 항상 보이게
    this.hlDs.entities.add({
      position: it.pos,
      point: {
        pixelSize: 20,
        color: Cesium.Color.TRANSPARENT,
        outlineColor: Cesium.Color.fromCssColorString('#ffe14d'),
        outlineWidth: 3,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: it.name,
        font: '700 16px "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString('#ffe14d'),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 4,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -24),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });

    // 부드럽게 이동
    if (it.entity.polygon) {
      this.viewer.flyTo(it.entity, { duration: 1.8 }).catch(() => {});
    } else {
      const carto = Cesium.Cartographic.fromCartesian(it.pos);
      const alt = ALT[it.layer.id] || 500000;
      this.viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromRadians(carto.longitude, carto.latitude, alt),
        duration: 1.8,
      });
    }
  }

  reset() {
    this.dom.input.value = '';
    this.dom.bar.classList.remove('has-text');
    this.hideResults();
    this.clearHighlight();
  }
}
