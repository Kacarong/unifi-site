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
  window.unifiUI = { observeReveals };
})();
