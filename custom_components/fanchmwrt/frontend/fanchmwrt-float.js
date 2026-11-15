/*!
 * FanchmWrt —— 设备页「访问」悬浮窗模块
 *
 * 由 homeassistant.components.frontend.add_extra_js_url 注入 HA 前端（全局生效）。
 * 捕获阶段拦截设备页「访问」链接（/fanchmwrt-openclash、/fanchmwrt-router）的点击：
 * 用 composedPath() 穿透 ha-button 的 Shadow DOM，preventDefault 阻止整页跳转，
 * 改为在当前页面弹出可拖动、可缩放的悬浮窗，窗内直接挂载总览自定义卡片。
 * 两个条目各一个独立窗口，可同时打开；Ctrl/中键点击仍按普通链接处理（dashboard 兜底）。
 */

(() => {
  "use strict";

  const HOST_ID = "fanchmwrt-float-host";
  const CARD_URL = "/local/fanchmwrt-overview.js";
  const PATH_TARGET = {
    "/fanchmwrt-openclash": "openclash",
    "/fanchmwrt-router": "router",
  };
  const CONF = {
    openclash: {
      title: "OpenClash · 总览",
      width: "min(1120px, 94vw)",
      height: "min(820px, 88vh)",
    },
    router: {
      title: "JCG Q30 PRO · 系统总览",
      width: "min(1120px, 94vw)",
      height: "min(820px, 88vh)",
    },
  };

  const CSS = `
    .fw-window {
      position: fixed; z-index: 10; display: none; flex-direction: column;
      min-width: 360px; min-height: 260px;
      background: #0f1218; border: 1px solid #2f3c4e; border-radius: 12px;
      box-shadow: 0 16px 52px rgba(0,0,0,.6); overflow: hidden;
      resize: both; pointer-events: auto; color: #e7ebf3;
    }
    .fw-window.show { display: flex; }
    .fw-window.flash { animation: fw-pop .32s ease; }
    @keyframes fw-pop { 0% { transform: scale(.97); } 60% { transform: scale(1.012); } 100% { transform: scale(1); } }
    .fw-head {
      display: flex; align-items: center; gap: 8px; height: 42px; padding: 0 10px;
      background: #1b222d; border-bottom: 1px solid #2f3c4e; cursor: move;
      touch-action: none; flex: 0 0 auto;
    }
    .fw-grip { color: #6b7787; font-size: 14px; letter-spacing: -2px; }
    .fw-title { font-size: 13.5px; font-weight: 600; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis; }
    .fw-spacer { flex: 1; }
    .fw-btn {
      appearance: none; border: 1px solid #2f3c4e; background: #202a38; color: #e7edf5;
      border-radius: 7px; width: 30px; height: 28px; font-size: 15px; line-height: 1;
      cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
      text-decoration: none; padding: 0;
    }
    .fw-btn:hover { background: #2a3646; border-color: #2f9bff; }
    .fw-x:hover { background: #5a2327; border-color: #f0564a; }
    .fw-body { flex: 1 1 auto; position: relative; overflow: hidden; background: #0f1218; }
  `;

  // composedPath 穿透 ha-button 的 Shadow DOM，拿到真实 <a href>
  function linkFromEvent(event) {
    let path = null;
    try {
      path = typeof event.composedPath === "function" ? event.composedPath() : null;
    } catch (_) { path = null; }
    if (!path || !path.length) {
      path = [];
      let node = event.target;
      while (node) {
        path.push(node);
        const root = node.getRootNode ? node.getRootNode() : null;
        node = node.parentNode || (root && root.host) || null;
      }
    }
    for (const node of path) {
      if (!node || node.nodeType !== 1) continue;
      let href = null;
      if (node.tagName === "A") href = node.href;
      if (!href && typeof node.getAttribute === "function") href = node.getAttribute("href");
      if (!href) continue;
      let url;
      try { url = new URL(href, location.href); } catch (_) { continue; }
      const target = PATH_TARGET[url.pathname];
      if (!target) continue;
      // 主机一律以浏览器当前地址栏为准，避免设备链接里的内网 IP 与当前访问地址不一致
      try {
        url = new URL(url.pathname + url.search, window.location.origin);
      } catch (_) { /* 用原链接兜底 */ }
      return { url, target, node };
    }
    return null;
  }

  function ensureHost() {
    let host = document.getElementById(HOST_ID);
    if (host) return host;
    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "position:fixed;inset:0;z-index:999999;pointer-events:none";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    shadow.appendChild(style);
    document.body.appendChild(host);
    return host;
  }

  function centerWindow(win) {
    const w = win.offsetWidth || Math.min(1120, window.innerWidth * 0.94);
    const h = win.offsetHeight || Math.min(820, window.innerHeight * 0.88);
    win.style.left = Math.max(8, (window.innerWidth - w) / 2) + "px";
    win.style.top = Math.max(8, (window.innerHeight - h) / 2 - 10) + "px";
  }

  function enableDrag(win, head) {
    head.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".fw-btn")) return;
      event.preventDefault();
      const offX = event.clientX - win.offsetLeft;
      const offY = event.clientY - win.offsetTop;
      const move = (ev) => {
        const x = Math.max(-win.offsetWidth + 140,
          Math.min(window.innerWidth - 60, ev.clientX - offX));
        const y = Math.max(0,
          Math.min(window.innerHeight - 40, ev.clientY - offY));
        win.style.left = x + "px";
        win.style.top = y + "px";
      };
      const up = () => {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
      };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  }

  function currentHass() {
    try {
      const root = document.querySelector("home-assistant");
      return root && root.hass ? root.hass : null;
    } catch (_) { return null; }
  }

  async function mountCard(win, kind) {
    try {
      await import(CARD_URL);
    } catch (err) {
      console.error("FanchmWrt: 无法加载总览卡片", err);
    }
    const body = win.querySelector(".fw-body");
    let card = body.querySelector("fanchmwrt-overview-card");
    if (!card) {
      if (!customElements.get("fanchmwrt-overview-card")) return;
      card = document.createElement("fanchmwrt-overview-card");
      card.setAttribute("compact", "");
      card.style.cssText = "display:block;height:100%;";
      body.appendChild(card);
    }
    const cfg = (window.FANCHMWRT_CARD_CONFIG || {})[kind];
    if (cfg && typeof card.setConfig === "function") card.setConfig(cfg);
    const push = () => {
      const hass = currentHass();
      if (hass) card.hass = hass;
    };
    push();
    if (win._fwTimer) clearInterval(win._fwTimer);
    win._fwTimer = setInterval(push, 2000);
  }

  function buildWindow(root, kind) {
    const conf = CONF[kind] || CONF.router;
    const win = document.createElement("div");
    win.className = "fw-window";
    win.dataset.kind = kind;
    win.style.width = conf.width;
    win.style.height = conf.height;
    win.innerHTML = `
      <div class="fw-head">
        <span class="fw-grip">⠿</span>
        <span class="fw-title">${conf.title}</span>
        <span class="fw-spacer"></span>
        <button type="button" class="fw-btn" data-act="reload" title="重新加载">↻</button>
        <a class="fw-btn fw-link" target="_blank" rel="noopener" title="在新标签页打开">↗</a>
        <button type="button" class="fw-btn fw-x" data-act="close" title="关闭">✕</button>
      </div>
      <div class="fw-body"></div>`;
    root.appendChild(win);
    centerWindow(win);
    enableDrag(win, win.querySelector(".fw-head"));

    win.querySelector('[data-act="reload"]').addEventListener("click", () => {
      mountCard(win, kind);
    });
    win.querySelector('[data-act="close"]').addEventListener("click", () => {
      if (win._fwTimer) clearInterval(win._fwTimer);
      win._fwTimer = null;
      win.classList.remove("show");
    });
    return win;
  }

  function openFloat(kind, url) {
    const root = ensureHost().shadowRoot;
    let win = root.querySelector(`.fw-window[data-kind="${kind}"]`);
    if (!win) win = buildWindow(root, kind);
    win.querySelector(".fw-link").href = url.href;
    win.classList.add("show");
    win.classList.remove("flash");
    void win.offsetWidth;
    win.classList.add("flash");
    win.style.zIndex = String(10 + (kind === "openclash" ? 1 : 0));
    mountCard(win, kind);
  }

  function onClick(event) {
    const match = linkFromEvent(event);
    if (!match) return;
    try {
      if (match.node.getAttribute && match.node.getAttribute("href")) {
        match.node.setAttribute("href", match.url.href);
      }
    } catch (_) { /* 只读 DOM 静默 */ }
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    openFloat(match.target, match.url);
  }

  document.addEventListener("click", onClick, true);
  window.__fanchmwrtFloat = "1.0.0";
})();
