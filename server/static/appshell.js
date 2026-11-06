/* unifi 앱 셸 — `/appshell.js`
 *
 * 사이트를 휴대폰 앱처럼 느끼게 하는 부분만 담당한다. 의존성 없음.
 *  - 화면 전환 방향: 들어갈 때는 오른쪽에서, 뒤로 갈 때는 왼쪽에서 밀려 들어온다
 *  - 미리 불러오기: 누를 만한 화면을 먼저 받아 두고, 누르기 직전에 미리 그려 둔다
 *  - 하단 탭바: 홈과 앱들을 어느 화면에서나 한 번에 오간다 (좁은 화면에서만 보인다)
 *
 * <head> 안에 defer 없이 넣는다. 화면 전환 방향은 새 화면이 처음 그려지기
 * 전(pagereveal)에 정해야 해서, 늦게 실행되면 방향이 안 붙는다.
 *
 *   <script src="/appshell.js"></script>
 */
(() => {
  "use strict";

  /* ── 화면 전환 ────────────────────────────────────────── */
  const depth = (url) => new URL(url).pathname.split("/").filter(Boolean).length;

  // 뒤로가기이거나 더 얕은 화면(앱 → 홈)으로 가면 'back', 아니면 'forward'
  function direction() {
    const act = window.navigation?.activation;
    if (!act?.from || !act.entry) return "forward";
    if (act.navigationType === "traverse") {
      return act.entry.index < act.from.index ? "back" : "forward";
    }
    return depth(act.entry.url) < depth(act.from.url) ? "back" : "forward";
  }

  // 전환이 도중에 취소되면(빠른 연속 이동 등) 브라우저가 그 약속을 거절하는데,
  // 아무도 받지 않으면 콘솔에 오류로 남는다. 정상 동작이므로 받아서 넘긴다.
  function swallow(vt) {
    vt.ready?.catch(() => {});
    vt.finished?.catch(() => {});
    vt.updateCallbackDone?.catch(() => {});
  }

  window.addEventListener("pageswap", (e) => {
    if (e.viewTransition) swallow(e.viewTransition);
  });
  window.addEventListener("pagereveal", (e) => {
    // 새 화면이 처음 그려지기 직전이다. 탭바를 지금 붙여야 전환 중에도 제자리에
    // 있다. DOMContentLoaded 까지 기다리면 첫 화면에 탭바가 없어서 깜빡인다.
    mountCachedDock();
    const vt = e.viewTransition;
    if (!vt) return;
    swallow(vt);
    try { vt.types?.add(direction()); } catch { /* 방향이 없으면 기본 전환 */ }
  });
  // 전환이 시작되기도 전에 취소되는 경우를 위한 마지막 그물. 동작에는 영향이 없다.
  window.addEventListener("unhandledrejection", (e) => {
    const msg = String(e.reason?.message || e.reason || "");
    if (/transition was skipped|transition was aborted/i.test(msg)) e.preventDefault();
  });

  /* ── 미리 불러오기 ────────────────────────────────────── */
  // 사이트 안 링크는 화면 HTML 을 바로 받아 두고(가벼움), 손가락이 닿거나
  // 마우스가 머무는 순간 화면 전체를 뒤에서 미리 그린다. 그래서 떼는 순간
  // 바로 뜬다. API, 다른 사이트로 넘기는 바로가기, 다운로드는 건드리지 않는다.
  function speculate() {
    if (!HTMLScriptElement.supports?.("speculationrules")) return;
    const where = {
      and: [
        { href_matches: "/*" },
        { not: { href_matches: "/api/*" } },
        { not: { href_matches: "/apps/vstock*" } },
        { not: { selector_matches: "[download], [target=_blank], [rel~=nofollow]" } },
      ],
    };
    const s = document.createElement("script");
    s.type = "speculationrules";
    s.textContent = JSON.stringify({
      prefetch: [{ where, eagerness: "eager" }],
      prerender: [{ where, eagerness: "moderate" }],
    });
    document.head.append(s);
  }

  /* ── 하단 탭바 ────────────────────────────────────────── */
  // 앱 목록은 지난번 것을 먼저 써서 탭바가 늦게 튀어나오지 않게 하고,
  // 뒤에서 새로 받아 바뀐 게 있으면 다시 그린다.
  const CACHE_KEY = "unifi.dock.v1";

  function readCache() {
    try { return JSON.parse(localStorage.getItem(CACHE_KEY) || "null"); } catch { return null; }
  }

  function tabsFrom(apps) {
    const tabs = [{ id: "_home", url: "/", icon: "⬢", label: "홈" }];
    for (const a of apps || []) {
      if (a.status !== "ready" || !a.url) continue;
      tabs.push({ id: a.id, url: a.url, icon: a.icon || "🧩", label: a.short_name || a.name });
    }
    return tabs;
  }

  function isActive(tab, path) {
    return tab.url === "/" ? path === "/" || path === "/index.html" : path.startsWith(tab.url);
  }

  function renderDock(tabs) {
    let nav = document.getElementById("unifi-dock");
    const sig = JSON.stringify(tabs);
    if (nav?.dataset.sig === sig) return;

    if (!nav) {
      nav = document.createElement("nav");
      nav.id = "unifi-dock";
      nav.className = "dock";
      nav.setAttribute("aria-label", "앱 이동");
      document.body.append(nav);
      document.documentElement.classList.add("has-dock");
    }
    nav.dataset.sig = sig;
    nav.textContent = "";

    const path = location.pathname;
    for (const t of tabs) {
      const a = document.createElement("a");
      a.className = "dock-tab";
      a.href = t.url;
      const on = isActive(t, path);
      if (on) a.setAttribute("aria-current", "page");
      const icon = document.createElement("span");
      icon.className = "dock-icon";
      icon.textContent = t.icon;
      icon.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.className = "dock-label";
      label.textContent = t.label;
      a.append(icon, label);
      nav.append(a);
    }
    nav.querySelector('[aria-current="page"]')?.scrollIntoView?.({ inline: "nearest", block: "nearest" });
  }

  function onDockTap(e) {
    const a = e.target.closest?.(".dock-tab");
    if (!a) return;
    navigator.vibrate?.(8);
    // 이미 보고 있는 앱의 첫 화면 탭을 다시 누르면 새로 불러오지 않고 맨 위로 올린다
    if (a.getAttribute("aria-current") === "page" && new URL(a.href).pathname === location.pathname) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  // 키보드가 올라오면 탭바가 그 위에 얹혀 입력을 가린다. 입력 중에는 숨긴다.
  function hideDockWhileTyping() {
    const typing = (el) => el?.matches?.("input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]), textarea, select, [contenteditable=true]");
    document.addEventListener("focusin", (e) => {
      if (typing(e.target)) document.documentElement.classList.add("typing");
    });
    document.addEventListener("focusout", () => {
      // 다음 입력칸으로 포커스가 바로 옮겨 가면 숨긴 채로 둔다
      setTimeout(() => {
        if (!typing(document.activeElement)) document.documentElement.classList.remove("typing");
      }, 0);
    });
  }

  function mountCachedDock() {
    if (!document.body || document.getElementById("unifi-dock")) return;
    const cached = readCache();
    if (Array.isArray(cached)) renderDock(cached);
  }

  async function initDock() {
    mountCachedDock();
    try {
      const res = await fetch("/api/_apps", { credentials: "same-origin" });
      if (!res.ok) return;              // 로그인 전 등: 탭바를 띄우지 않는다
      const tabs = tabsFrom(await res.json());
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(tabs)); } catch { /* 저장 불가여도 그린다 */ }
      renderDock(tabs);
    } catch { /* 오프라인이면 지난 목록 그대로 */ }
  }

  function init() {
    speculate();
    document.addEventListener("click", onDockTap);
    hideDockWhileTyping();
    initDock();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
