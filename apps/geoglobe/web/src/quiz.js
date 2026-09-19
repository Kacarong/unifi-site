import * as Cesium from 'cesium';
import { pick } from './layers.js';

const HL = Cesium.Color.fromCssColorString('#ffe14d').withAlpha(0.55);
const TRANSPARENT = Cesium.Color.TRANSPARENT;

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export class Quiz {
  constructor(viewer, bordersLayer, ctx, dom) {
    this.viewer = viewer;
    this.borders = bordersLayer;
    this.ctx = ctx;
    this.dom = dom;
    this.pool = [];
    this.current = null;

    // 이름과 폴리곤이 있는 국가만 후보로
    for (const e of bordersLayer.ds.entities.values) {
      if (!e.polygon || !e.position) continue;
      const p = e._props || {};
      const nameKo = pick(p, 'ko', ['NAME', 'ADMIN']);
      const nameEn = pick(p, 'en', ['NAME', 'ADMIN']);
      if (!nameKo && !nameEn) continue;
      this.pool.push({ entity: e, nameKo, nameEn });
    }

    dom.start.addEventListener('click', () => this.start());
    dom.next.addEventListener('click', () => this.next());
    dom.restart.addEventListener('click', () => this.reset());
  }

  nameOf(item) { return this.ctx.lang === 'ko' ? (item.nameKo || item.nameEn) : (item.nameEn || item.nameKo); }

  start() {
    const count = Math.min(parseInt(this.dom.count.value, 10) || 10, this.pool.length);
    this.questions = shuffle(this.pool).slice(0, count);
    this.index = 0;
    this.score = 0;
    // 퀴즈 중에는 국경 레이어를 강제로 켬
    this.borders.ds.show = true;
    this.dom.setup.classList.add('hidden');
    this.dom.result.classList.add('hidden');
    this.dom.play.classList.remove('hidden');
    this.showQuestion();
  }

  clearHighlight() {
    if (this.current && this.current.entity.polygon) {
      this.current.entity.polygon.material = TRANSPARENT;
    }
  }

  showQuestion() {
    this.clearHighlight();
    const q = this.questions[this.index];
    this.current = q;
    q.entity.polygon.material = HL;

    this.dom.progress.textContent = `문제 ${this.index + 1} / ${this.questions.length}  ·  점수 ${this.score}`;
    this.dom.question.textContent = '지도에서 강조된(노란색) 나라는 어디일까요?';
    this.dom.feedback.textContent = '';
    this.dom.feedback.className = '';
    this.dom.next.classList.add('hidden');

    // 4지선다 보기 구성
    const correct = this.nameOf(q);
    const others = shuffle(this.pool.filter((x) => this.nameOf(x) !== correct)).slice(0, 3).map((x) => this.nameOf(x));
    const choices = shuffle([correct, ...others]);

    this.dom.choices.innerHTML = '';
    for (const name of choices) {
      const btn = document.createElement('button');
      btn.className = 'choice';
      btn.textContent = name;
      btn.addEventListener('click', () => this.answer(name, correct, btn));
      this.dom.choices.appendChild(btn);
    }

    // 해당 국가로 카메라 이동
    this.viewer.flyTo(q.entity, { duration: 1.0 }).catch(() => {});
  }

  answer(name, correct, btn) {
    const buttons = this.dom.choices.querySelectorAll('.choice');
    buttons.forEach((b) => { b.disabled = true; });
    if (name === correct) {
      btn.classList.add('correct');
      this.score++;
      this.dom.feedback.textContent = '정답! 🎉';
      this.dom.feedback.className = 'ok';
    } else {
      btn.classList.add('wrong');
      buttons.forEach((b) => { if (b.textContent === correct) b.classList.add('correct'); });
      this.dom.feedback.textContent = `오답 — 정답은 "${correct}"`;
      this.dom.feedback.className = 'no';
    }
    this.dom.next.classList.remove('hidden');
    this.dom.next.textContent = this.index + 1 >= this.questions.length ? '결과 보기' : '다음';
  }

  next() {
    this.index++;
    if (this.index >= this.questions.length) return this.finish();
    this.showQuestion();
  }

  finish() {
    this.clearHighlight();
    this.dom.play.classList.add('hidden');
    this.dom.result.classList.remove('hidden');
    const total = this.questions.length;
    const pct = Math.round((this.score / total) * 100);
    this.dom.score.textContent = `${total}문제 중 ${this.score}개 정답 (${pct}점)`;
  }

  reset() {
    this.clearHighlight();
    this.dom.result.classList.add('hidden');
    this.dom.play.classList.add('hidden');
    this.dom.setup.classList.remove('hidden');
  }

  stop() {
    this.clearHighlight();
  }
}
