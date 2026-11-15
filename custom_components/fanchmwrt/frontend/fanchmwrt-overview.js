/* FanchmWrt v4.2.0 — 深色紧凑总览卡片（零依赖）
 * 参考「飞牛 · 系统总览」的视觉语言：分组 + 网格指标卡片 + 状态徽章。
 * 两种模式：openclash / router。配置由集成部署时写入 Lovelace 面板。
 */

const CSS = `
:host { display: block; }
.fw {
  --bg: #0f1218; --tile: #1a1f2a; --line: #262d3b; --line2: #333d50;
  --text: #e7ebf3; --muted: #8b94a6; --dim: #6f7a8d;
  --ok: #4ade80; --bad: #f87171; --accent: #3b82f6;
  background: var(--bg); color: var(--text); min-height: 100vh;
  box-sizing: border-box; padding: 18px 22px 30px;
  font-family: "Inter", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
}
.head { display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; padding-bottom: 14px; margin-bottom: 18px; border-bottom: 1px solid var(--line); }
.head h1 { margin: 0; font-size: 21px; font-weight: 700; letter-spacing: .4px; }
.sub { color: var(--muted); font-size: 12px; margin-top: 6px; line-height: 1.6; }
.meta { color: var(--dim); font-size: 12px; margin-top: 4px; }
.badge { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap;
  border-radius: 999px; padding: 5px 12px; font-size: 12px; font-weight: 600;
  background: #153a2a; color: var(--ok); border: 1px solid #225c3e; }
.badge.off { background: #3a1a1a; color: var(--bad); border-color: #5a2222; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor;
  box-shadow: 0 0 7px currentColor; }
.group { margin-bottom: 20px; }
.group h2 { margin: 0 0 9px 2px; font-size: 12px; font-weight: 600;
  color: var(--muted); letter-spacing: .6px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); gap: 8px; }
.tile { background: var(--tile); border: 1px solid var(--line); border-radius: 9px;
  padding: 10px 12px; min-height: 64px; box-sizing: border-box; transition: border-color .15s; }
.tile:hover { border-color: var(--line2); }
.label { font-size: 11px; color: var(--muted); margin-bottom: 7px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.value { font-size: 19px; font-weight: 700; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.value.small { font-size: 13px; font-weight: 600; padding-top: 4px; }
.value.ok { color: var(--ok); } .value.bad { color: var(--bad); }
.unit { font-size: 11px; font-weight: 500; color: var(--muted); margin-left: 4px; }
.note { font-size: 11px; color: var(--dim); margin-top: 5px; }
.bar { height: 5px; background: #262d3b; border-radius: 3px; overflow: hidden; margin-top: 9px; }
.bar > i { display: block; height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--accent), #22d3ee); }
.controls { display: flex; gap: 8px; flex-wrap: wrap; }
button.act { background: var(--tile); border: 1px solid var(--line2); color: #dbe3f0;
  border-radius: 8px; padding: 9px 15px; font-size: 12px; cursor: pointer;
  font-family: inherit; transition: all .15s; }
button.act:hover { border-color: var(--accent); color: #fff; }
button.act.danger { border-color: #5a2a2a; color: #fca5a5; }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,.65); z-index: 999;
  display: flex; align-items: center; justify-content: center; padding: 20px; }
.box { background: #1a1f2a; border: 1px solid #313a4c; border-radius: 12px;
  padding: 20px 22px; width: min(360px, 92vw); box-shadow: 0 22px 64px rgba(0,0,0,.55); }
.box h3 { margin: 0 0 10px; font-size: 16px; }
.box p { margin: 0 0 20px; font-size: 13px; color: var(--muted); line-height: 1.7; }
.row { display: flex; justify-content: flex-end; gap: 8px; }
.row button { padding: 8px 16px; border-radius: 8px; font-size: 12px;
  cursor: pointer; font-family: inherit; border: 1px solid var(--line2);
  background: transparent; color: var(--text); }
.row button.go { background: #7f1d1d; border-color: #991b1b; color: #fff; }
.loading { color: var(--muted); font-size: 13px; padding: 30px 0; }
`;

const GROUPS = {
  openclash: [
    { title: "运行状态", items: [
      { k: "version", label: "内核版本", small: true },
      { k: "node", label: "当前节点", small: true },
      { k: "mode", label: "代理模式" },
      { k: "connections", label: "活动连接" },
      { k: "rules", label: "规则数" },
      { k: "dns_health", label: "DNS 解析健康", type: "binary", on: "正常", off: "异常" },
    ] },
    { title: "流量", items: [
      { k: "down_rate", label: "实时下载" },
      { k: "up_rate", label: "实时上传" },
      { k: "proxy_total", label: "代理累计流量" },
      { k: "down_total", label: "累计下载" },
      { k: "up_total", label: "累计上传" },
    ] },
    { title: "订阅套餐", items: [
      { k: "sub_remaining", label: "剩余流量" },
      { k: "sub_total", label: "套餐总流量" },
      { k: "sub_used", label: "已用流量" },
      { k: "sub_percent", label: "使用率", bar: true },
    ] },
    { title: "DNS 与诊断", items: [
      { k: "dns_latency", label: "DNS 解析延迟" },
      { k: "dns_health", label: "解析状态", type: "binary", on: "已连接", off: "异常" },
    ] },
  ],
  router: [
    { title: "资源监控", items: [
      { k: "cpu", label: "CPU 使用率" },
      { k: "memory", label: "内存使用率" },
      { k: "load", label: "负载（1分钟）" },
      { k: "temperature", label: "温度" },
      { k: "clients", label: "在线客户端" },
      { k: "uptime", label: "运行时间", small: true },
    ] },
    { title: "网络流量", items: [
      { k: "down_rate", label: "实时下载" },
      { k: "up_rate", label: "实时上传" },
      { k: "lan_ip", label: "LAN 地址", small: true },
      { k: "gateway", label: "网关延迟" },
      { k: "dns_latency", label: "DNS 解析耗时" },
    ] },
    { title: "存储", items: [
      { k: "storage_usage", label: "存储使用率", bar: true },
      { k: "storage_free", label: "可用存储空间" },
    ] },
    { title: "连网与诊断", items: [
      { k: "internet", label: "外网连通", type: "binary", on: "已连接", off: "断开" },
      { k: "connected", label: "路由器连接", type: "binary", on: "已连接", off: "离线" },
      { k: "eth0", label: "ETH0 状态", type: "binary", on: "已连接", off: "断开" },
      { k: "reboot_required", label: "需要重启", type: "binary", on: "是", off: "否" },
    ] },
  ],
};

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

class FanchmWrtOverviewCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    const style = document.createElement("style");
    style.textContent = CSS;
    this._body = document.createElement("div");
    this.shadowRoot.append(style, this._body);
    this.shadowRoot.addEventListener("click", (event) => this._onClick(event));
  }

  setConfig(config) {
    if (!config || (config.mode !== "openclash" && config.mode !== "router")) {
      throw new Error("FanchmWrt 总览需要 mode: openclash 或 router");
    }
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() { return 20; }

  _state(key) {
    const id = (this._config.entities || {})[key];
    if (!id || !this._hass) return null;
    return this._hass.states[id] || null;
  }

  _value(state) {
    if (!state) return "—";
    const raw = state.state;
    if (raw === undefined || raw === null || ["unknown", "unavailable", "none", ""].includes(raw)) return "—";
    return raw;
  }

  _tile(item, entityId) {
    const state = entityId && this._hass ? this._hass.states[entityId] : this._state(item.k);
    const value = this._value(state);
    const unit = state && state.attributes ? (state.attributes.unit_of_measurement || "") : "";
    let valueClass = "value" + (item.small ? " small" : "");
    let display = esc(value);
    let note = "";

    if (item.type === "binary") {
      const on = state && state.state === "on";
      const off = state && state.state === "off";
      display = esc(on ? item.on : off ? item.off : "—");
      valueClass = "value small " + (on ? "ok" : off ? "bad" : "");
    } else if (!isNaN(Number(value)) && value !== "—" && Number.isInteger(Number(value))) {
      display = esc(Number(value).toLocaleString("zh-CN"));
    }
    if (item.bar && value !== "—") {
      const pct = Math.max(0, Math.min(100, Number(value) || 0));
      note = `<div class="bar"><i style="width:${pct}%"></i></div>`;
    }
    return `<div class="tile"><div class="label">${esc(item.label)}</div>` +
      `<div class="${valueClass}">${display}${unit ? `<span class="unit">${esc(unit)}</span>` : ""}</div>` +
      note + `</div>`;
  }

  _render() {
    if (!this._config) return;
    if (!this._hass) {
      this._body.innerHTML = `<div class="fw"><div class="loading">正在加载 Home Assistant 状态…</div></div>`;
      return;
    }
    const cfg = this._config;
    const groups = GROUPS[cfg.mode] || [];
    const runningId = cfg.running_entity;
    const running = runningId ? this._hass.states[runningId] : null;
    const isOn = running && running.state === "on";
    const badge = `<span class="badge ${isOn ? "" : "off"}"><span class="dot"></span>` +
      esc(isOn ? "运行中" : "未运行") + `</span>`;

    let html = `<div class="fw"><div class="head"><div>` +
      `<h1>${esc(cfg.title || "FanchmWrt 总览")}</h1>` +
      `<div class="sub">${esc(cfg.subtitle || "")}</div>` +
      `<div class="meta">${esc(cfg.meta || "")}</div></div>${badge}</div>`;

    for (const group of groups) {
      html += `<div class="group"><h2>${esc(group.title)}</h2><div class="grid">`;
      for (const item of group.items) html += this._tile(item);
      html += `</div></div>`;
    }

    if (Array.isArray(cfg.group_entities) && cfg.group_entities.length) {
      html += `<div class="group"><h2>分流组当前节点</h2><div class="grid">`;
      for (const item of cfg.group_entities) {
        html += this._tile({ label: item.label, small: true }, item.entity);
      }
      html += `</div></div>`;
    }

    if (Array.isArray(cfg.actions) && cfg.actions.length) {
      html += `<div class="group"><h2>控制（需二次确认）</h2><div class="controls">`;
      for (let i = 0; i < cfg.actions.length; i++) {
        const action = cfg.actions[i];
        html += `<button class="act ${action.danger ? "danger" : ""}" data-action="confirm" data-index="${i}">` +
          esc(action.label) + `</button>`;
      }
      html += `</div></div>`;
    }
    html += `</div>`;

    const modal = this.shadowRoot.querySelector(".modal");
    this._body.innerHTML = html;
    if (modal) this.shadowRoot.append(modal);
  }

  _onClick(event) {
    const target = event.target.closest("button[data-action]");
    if (!target) return;
    const action = target.getAttribute("data-action");
    if (action === "confirm") {
      const item = this._config.actions[Number(target.getAttribute("data-index"))];
      this._confirm(item);
    } else if (action === "cancel") {
      this.shadowRoot.querySelector(".modal")?.remove();
    } else if (action === "go") {
      const entity = target.getAttribute("data-entity");
      this.shadowRoot.querySelector(".modal")?.remove();
      if (entity && this._hass) {
        this._hass.callService("button", "press", { entity_id: entity });
      }
    }
  }

  _confirm(item) {
    const overlay = document.createElement("div");
    overlay.className = "modal";
    overlay.innerHTML = `<div class="box"><h3>确认操作</h3>` +
      `<p>${esc(item.confirm || "确定要执行此操作吗？")}</p>` +
      `<div class="row"><button data-action="cancel">取消</button>` +
      `<button class="go" data-action="go" data-entity="${esc(item.entity)}">确认</button></div></div>`;
    this.shadowRoot.append(overlay);
  }
}

customElements.define("fanchmwrt-overview-card", FanchmWrtOverviewCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "fanchmwrt-overview-card",
  name: "FanchmWrt 总览",
  description: "深色紧凑总览：OpenClash / 路由器",
  preview: true,
});
