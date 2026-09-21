/* unifi 공용 모션 런타임 — `/ui.js`
 *
 * CSS 로 표현할 수 없는 부분만 담당한다. 의존성 없음, 6KB 미만.
 *  - 스크롤에 맞춰 순서대로 드러나기 (IntersectionObserver)
 *  - 카드 위 빛 따라다니기 (포인터 기기에서만)
 *  - 버튼 물결 + 휴대폰 진동 피드백
 *  - iOS 키보드가 입력칸을 가리는 문제 보정
 *
 * 모션을 꺼 달라고 설정한 사용자에게는 전부 건너뛴다.
 */
(() => {
  "use strict";

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;

  /* ── 스크롤 등장 ──────────────────────────────────────── */
  function observeReveals(root = document) {
    const items = root.querySelectorAll(".reveal:not(.in)");
    if (!items.length) return;

    if (reduced || !("IntersectionObserver" in window)) {
      items.forEach((el) => el.classList.add("in"));
      return;
    }

    const io = new IntersectionObserver(
      (entries, obs) => {
        // 같은 화면에 들어온 것들끼리 순서대로 터뜨려야 자연스럽다
        const shown = entries.filter((e) => e.isIntersecting);
        shown.forEach((entry, i) => {
          entry.target.style.setProperty("--d", `${Math.min(i, 6) * 55}ms`);
          entry.target.classList.add("in");
          obs.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.06 }
    );

    items.forEach((el) => io.observe(el));
  }

  /* ── 카드 위 빛 ───────────────────────────────────────── */
  function trackGlow(e) {
    const card = e.target.closest?.(".card");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${((e.clientX - r.left) / r.width) * 100}%`);
    card.style.setProperty("--my", `${((e.clientY - r.top) / r.height) * 100}%`);
  }

  /* ── 버튼 물결 + 진동 ─────────────────────────────────── */
  function ripple(e) {
    const btn = e.target.closest?.(".btn");
    if (!btn || btn.disabled) return;

    // 아주 짧은 진동은 "눌렸다"는 확신을 준다 (안드로이드에서 동작)
    navigator.vibrate?.(8);
    if (reduced) return;

    const r = btn.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const span = document.createElement("span");
    span.className = "ripple";
    span.style.width = span.style.height = `${size}px`;
    span.style.left = `${e.clientX - r.left}px`;
    span.style.top = `${e.clientY - r.top}px`;
    btn.appendChild(span);
    setTimeout(() => span.remove(), 600);
  }

  /* ── iOS 키보드 보정 ──────────────────────────────────── */
  // 소프트 키보드가 올라오면 포커스된 입력칸이 가려지는 경우가 있다.
  function keepFocusVisible(e) {
    const el = e.target;
    if (!el.matches?.("input, select, textarea")) return;
    setTimeout(() => {
      el.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
    }, 320);
  }

  /* ── 자동완성 목록 (datalist 대체) ─────────────────────
   * 브라우저 기본 <datalist> 는 CSS 로 전혀 꾸밀 수 없어서 사이트 톤과
   * 따로 논다. 같은 동작을 직접 그려서 디자인·터치 크기·키보드 조작을
   * 우리가 통제한다.
   *
   *   const box = unifiUI.combobox(inputEl);
   *   box.setOptions(['오디세이', '어벤져스', …]);
   */
  const MAX_SHOWN = 80;   // 너무 많이 그리면 폰에서 버벅인다

  function combobox(input, opts = {}) {
    if (!input || input._combo) return input?._combo;

    const empty = opts.emptyText || '일치하는 항목이 없습니다';
    let items = [];
    let ready = false;   // 아직 목록을 못 받았으면 "없다" 가 아니라 "불러오는 중"
    let shown = [];
    let active = -1;

    // 입력칸을 감싸서 목록의 기준 위치를 만든다
    const wrap = document.createElement('div');
    wrap.className = 'combo';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const list = document.createElement('ul');
    list.className = 'combo-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    wrap.appendChild(list);

    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-autocomplete', 'list');
    input.autocomplete = 'off';

    const close = () => {
      list.hidden = true;
      wrap.classList.remove('open', 'flip');
      input.setAttribute('aria-expanded', 'false');
      active = -1;
    };

    const choose = (value) => {
      input.value = value;
      close();
      // 기존 코드가 값 변화를 알아챌 수 있게 실제 이벤트를 흘려 준다
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const paint = () => {
      list.textContent = '';
      if (!shown.length) {
        const li = document.createElement('li');
        li.className = 'combo-empty';
        li.textContent = ready ? empty : '목록 불러오는 중…';
        list.appendChild(li);
        return;
      }
      shown.forEach((name, i) => {
        const li = document.createElement('li');
        li.className = 'combo-item' + (i === active ? ' active' : '');
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', String(i === active));
        li.textContent = name;
        // pointerdown 으로 잡아야 입력칸이 포커스를 잃기 전에 선택된다
        li.addEventListener('pointerdown', (e) => { e.preventDefault(); choose(name); });
        list.appendChild(li);
      });
    };

    /* 위/아래 중 넓은 쪽으로 펼치고, 그 공간에 맞춰 높이를 제한한다.
     * 포커스 직후 소프트 키보드 때문에 페이지가 자동으로 스크롤되므로,
     * 한 번만 계산하면 화면 밖으로 삐져나간다. 스크롤될 때마다 다시 잰다. */
    const GAP = 10;
    const reposition = () => {
      if (list.hidden) return;
      const r = input.getBoundingClientRect();
      const below = window.innerHeight - r.bottom - GAP;
      const above = r.top - GAP - 56;              // 상단 바에 가리지 않도록 여유
      const flip = below < 180 && above > below;
      wrap.classList.toggle('flip', flip);
      list.style.maxHeight = `${Math.max(120, Math.floor(flip ? above : below))}px`;
    };

    const open = () => {
      const justOpened = list.hidden;
      const q = input.value.trim().toLowerCase();
      shown = (q ? items.filter((n) => n.toLowerCase().includes(q)) : items).slice(0, MAX_SHOWN);
      active = -1;
      paint();
      list.hidden = false;
      wrap.classList.add('open');
      input.setAttribute('aria-expanded', 'true');
      reposition();
      // 목록 내용이 시간이 지나면 바뀌는 경우(영화 편성 등)를 위해 알려 준다.
      // 앱이 필요하면 새로 받아 setOptions 로 갈아끼운다. 글자를 칠 때마다가
      // 아니라 닫혀 있다 열릴 때만 부른다.
      if (justOpened) {
        try { opts.onOpen?.(); } catch { /* 갱신 실패가 목록을 막으면 안 된다 */ }
      }
    };

    // 스크롤·회전·키보드 등장으로 위치가 바뀌면 따라간다
    window.addEventListener('scroll', reposition, { passive: true, capture: true });
    window.addEventListener('resize', reposition, { passive: true });
    window.visualViewport?.addEventListener('resize', reposition, { passive: true });

    const move = (step) => {
      if (list.hidden) { open(); return; }
      if (!shown.length) return;
      active = (active + step + shown.length) % shown.length;
      paint();
      list.children[active]?.scrollIntoView({ block: 'nearest' });
    };

    input.addEventListener('focus', open);
    input.addEventListener('input', open);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); choose(shown[active]); }
      else if (e.key === 'Escape') close();
      else if (e.key === 'Tab') close();
    });
    document.addEventListener('pointerdown', (e) => {
      if (!wrap.contains(e.target)) close();
    }, { passive: true });

    const api = {
      setOptions(names) {
        items = (names || []).filter(Boolean).map(String);
        ready = true;
        if (!list.hidden) open();   // 열어 둔 채로 목록이 도착하면 바로 채운다
      },
      close,
    };
    input._combo = api;
    return api;
  }

  /* ── 페이지 전환 뒷정리 ───────────────────────────────── */
  // 화면 전환이 도중에 취소되면(빠른 연속 이동 등) 브라우저가 그 약속을
  // 거절하는데, 아무도 받지 않으면 콘솔에 오류로 남는다. 정상 동작이므로
  // 받아서 조용히 넘긴다.
  function quietTransitions() {
    const swallow = (e) => {
      const vt = e.viewTransition;
      if (!vt) return;
      // 거절될 수 있는 약속을 모두 받아 둔다. 하나라도 빠뜨리면 그게 오류로 남는다
      vt.ready?.catch(() => {});
      vt.finished?.catch(() => {});
      vt.updateCallbackDone?.catch(() => {});
    };
    window.addEventListener('pageswap', swallow);
    window.addEventListener('pagereveal', swallow);

    // 위에서 못 잡는 경로(전환이 시작되기도 전에 취소되는 경우)를 위한 마지막 그물.
    // 화면 전환이 건너뛰어졌다는 것뿐이라 동작에는 영향이 없다.
    window.addEventListener('unhandledrejection', (e) => {
      const msg = String(e.reason?.message || e.reason || '');
      if (/transition was skipped|transition was aborted/i.test(msg)) e.preventDefault();
    });
  }

  // pagereveal 은 DOMContentLoaded 보다 먼저 오므로 바로 등록한다
  quietTransitions();

  /* ── 초기화 ───────────────────────────────────────────── */
  function init() {
    observeReveals();

    if (finePointer) {
      document.addEventListener("pointermove", trackGlow, { passive: true });
    }
    document.addEventListener("pointerdown", ripple, { passive: true });

    if (matchMedia("(pointer: coarse)").matches) {
      document.addEventListener("focusin", keepFocusVisible, { passive: true });
    }

    // 동적으로 그려지는 목록(앱 카드, 감시 대상 등)도 자동으로 잡는다
    new MutationObserver(() => observeReveals()).observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  // 앱 스크립트가 직접 부를 수 있게 열어 둔다
  window.unifiUI = { observeReveals, combobox };
})();
