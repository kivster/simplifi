/* SimpliFi card 0.22.0b1 — backed exclusively by authenticated HA actions. */
const requestId = () => {
  const crypto = globalThis.crypto;
  if (typeof crypto?.randomUUID === "function") return crypto.randomUUID();
  // randomUUID is unavailable on some HA browser origins. getRandomValues
  // still supplies secure random bytes for the same UUID v4 request format.
  if (typeof crypto?.getRandomValues !== "function")
    throw new Error(
      "This browser cannot generate a request ID. Open Home Assistant in a supported browser.",
    );
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4),
    hex.slice(4, 6),
    hex.slice(6, 8),
    hex.slice(8, 10),
    hex.slice(10),
  ]
    .map((part) => part.join(""))
    .join("-");
};
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const icon = (name) => `<ha-icon icon="${escape(name)}"></ha-icon>`;
const words = (value) => String(value ?? "").replaceAll("_", " ");
const choices = (rows, selected) =>
  rows
    .map(
      ([value, label]) =>
        `<option value="${escape(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escape(label)}</option>`,
    )
    .join("");
const statusText = {
  available: "Internet available",
  paused: "Internet paused",
  scheduled_block: "Scheduled restriction",
  network_blocked: "Network restriction",
  partially_blocked: "Some devices restricted",
  allowed: "Temporarily allowed",
  unmanaged: "No devices assigned",
  unknown: "Unable to confirm",
};
const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const styles = `
:host{display:block;overflow-wrap:anywhere;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,inherit)}*{box-sizing:border-box}ha-card{padding:22px;border-radius:var(--ha-card-border-radius,18px);height:100%}h1,h2,h3,p{margin:0}h1{font-size:26px;line-height:1.25;font-weight:650}h2{font-size:20px;font-weight:600}h3{font-size:16px}p{line-height:1.5}.muted,small{color:var(--secondary-text-color)}small{font-size:12px;line-height:1.5}.lead{margin:6px 0 0;color:var(--secondary-text-color);font-size:14px}.row{display:flex;align-items:center;gap:12px}.between{justify-content:space-between}.wrap{flex-wrap:wrap}.grow{flex:1;min-width:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:16px}.people{container-type:inline-size}.card-top{margin-bottom:18px}.avatar{display:grid;place-items:center;background:var(--secondary-background-color);color:var(--primary-color);border-radius:50%;width:46px;height:46px;font-size:20px;font-weight:600;flex-shrink:0}.avatar img{width:46px;height:46px;object-fit:cover;border-radius:50%}.badge{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:8px;font-size:12px;font-weight:500;background:var(--secondary-background-color);color:var(--secondary-text-color)}.blue{color:var(--primary-color);background:color-mix(in srgb,var(--primary-color) 12%,transparent)}.amber{color:var(--warning-color,#bf8700);background:color-mix(in srgb,var(--warning-color,#bf8700) 12%,transparent)}.red{color:var(--error-color);background:color-mix(in srgb,var(--error-color) 10%,transparent)}.status{font-size:17px;font-weight:600;margin-bottom:5px}.dot{width:8px;height:8px;border-radius:50%;background:currentColor;display:inline-block;margin-right:8px}.status.available{color:var(--primary-color)}.status.paused,.status.scheduled_block,.status.network_blocked,.status.partially_blocked{color:var(--error-color)}.status.allowed{color:var(--warning-color,#bf8700)}.description{min-height:42px;margin-bottom:12px;font-size:13px;color:var(--secondary-text-color)}button{font:inherit;cursor:pointer;min-height:44px;border:1px solid var(--divider-color);border-radius:10px;background:var(--card-background-color);color:var(--primary-text-color);padding:9px 14px;display:inline-flex;justify-content:center;align-items:center;gap:7px;font-size:14px;font-weight:500}button:hover{background:var(--secondary-background-color)}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}button.primary:hover{filter:brightness(.93)}button.danger{color:var(--error-color)}button.quiet{border-color:transparent;background:transparent;padding:8px}button:disabled{opacity:.45;cursor:not-allowed}ha-icon{--mdc-icon-size:20px;width:20px;height:20px;flex-shrink:0}.actions{display:flex;gap:8px;margin-bottom:18px}.actions>button{flex:1}.categories{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:3px;border-top:1px solid var(--divider-color);padding-top:14px}.category{min-width:0;border:0;display:flex;flex-direction:column;gap:4px;padding:5px 1px;background:transparent;font-size:10px;min-height:74px;line-height:1.3}.category .category-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:50%;background:var(--secondary-background-color)}.category.dns_blocked .category-icon,.category.restricted .category-icon{color:var(--error-color);background:color-mix(in srgb,var(--error-color) 12%,transparent)}.category.inherited .category-icon,.category.scheduled .category-icon{color:var(--primary-color);background:color-mix(in srgb,var(--primary-color) 10%,transparent)}.category .name{font-size:11px;font-weight:600}.category .state{color:var(--secondary-text-color);font-size:10px}.footer{border-top:1px solid var(--divider-color);margin-top:12px;padding-top:8px;display:flex;align-items:center;justify-content:space-between;gap:8px}.footer small{font-size:12px}.section{margin-top:22px}.section>h2,.section>h3{margin-bottom:12px}.banner{padding:12px 14px;border-radius:10px;background:var(--secondary-background-color);font-size:13px;line-height:1.5;margin-bottom:14px;display:flex;gap:10px;align-items:flex-start}.banner.warning{background:color-mix(in srgb,var(--warning-color,#bf8700) 12%,var(--card-background-color))}.banner.error{background:color-mix(in srgb,var(--error-color) 10%,var(--card-background-color));color:var(--error-color)}.toolbar{margin-bottom:16px}.toolbar>input{flex:1}.empty{text-align:center;padding:35px 16px}.empty ha-icon{width:38px;height:38px;--mdc-icon-size:38px;color:var(--secondary-text-color);margin-bottom:12px}.empty p{margin:8px auto 16px;max-width:380px}.list{display:flex;flex-direction:column;gap:10px}.list-item{padding:14px;border:1px solid var(--divider-color);border-radius:12px;display:flex;align-items:center;gap:12px}.list-item .name{font-weight:600;overflow-wrap:anywhere}.list-item small{display:block}.rule-details{margin:12px 0;font-size:13px;color:var(--secondary-text-color)}.rule-details p+p{margin-top:4px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}.selected{border-color:var(--primary-color);color:var(--primary-color);background:color-mix(in srgb,var(--primary-color) 9%,transparent)}.timeline{display:flex;flex-direction:column;gap:8px}.time-row{position:relative;height:34px;background:var(--secondary-background-color);border-radius:6px;overflow:hidden}.time-bar{position:absolute;top:3px;bottom:3px;border-radius:4px;background:color-mix(in srgb,var(--primary-color) 30%,transparent);min-width:3px}.time-label{position:relative;display:flex;align-items:center;height:100%;padding:0 10px;font-size:12px;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.time-axis{display:flex;justify-content:space-between;font-size:11px;color:var(--secondary-text-color);margin-top:4px}.note{font-size:12px;line-height:1.5;color:var(--secondary-text-color);margin:10px 0}.result{padding:12px 14px;margin-bottom:14px;border-radius:10px;background:var(--secondary-background-color);font-size:13px}.result strong{display:block;margin-bottom:3px}.audit-row{padding:14px 0;border-bottom:1px solid var(--divider-color)}.audit-row:last-child{border-bottom:0}.audit-row .row{align-items:flex-start}.audit-row small{display:block;margin-top:4px}.settings{margin-top:20px;padding-top:18px;border-top:1px solid var(--divider-color)}a{color:var(--primary-color)}dialog{position:fixed;max-width:min(620px,calc(100vw - 28px));width:620px;max-height:calc(100dvh - 40px);margin:auto;border:1px solid var(--divider-color);border-radius:20px;padding:0;background:var(--card-background-color);color:var(--primary-text-color);box-shadow:0 18px 60px #0005;overflow:hidden}dialog::backdrop{background:#0007}.dialog-shell{display:flex;flex-direction:column;max-height:calc(100dvh - 44px)}.dialog-header{padding:18px 22px;border-bottom:1px solid var(--divider-color);display:flex;align-items:center;justify-content:space-between;gap:12px}.dialog-header h2{font-size:20px}.dialog-body{padding:20px 22px;overflow:auto}.dialog-footer{padding:14px 22px;border-top:1px solid var(--divider-color);display:flex;align-items:center;justify-content:flex-end;gap:9px}.dialog-footer .grow{margin-right:auto}.dialog-body .section:first-child{margin-top:0}label.field{display:flex;flex-direction:column;gap:7px;margin:0 0 16px;font-size:13px;font-weight:500}input,select,textarea{font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:11px 12px;min-height:44px;width:100%;font-size:14px}textarea{resize:vertical;min-height:92px}label.check{display:flex;align-items:center;gap:10px;min-height:44px;font-size:14px;font-weight:400}input[type=checkbox]{width:18px;min-height:18px;height:18px;accent-color:var(--primary-color)}fieldset{border:1px solid var(--divider-color);border-radius:12px;margin:0 0 16px;padding:14px;min-width:0}legend{font-size:13px;font-weight:600;padding:0 5px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.form-grid .field{min-width:0}.days{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0 12px}.days label{position:relative;display:grid;place-items:center;min-width:42px;height:42px;border:1px solid var(--divider-color);border-radius:8px;cursor:pointer;font-size:12px}.days label:has(input:checked){background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}.days input{position:absolute;opacity:0;width:100%;height:100%;margin:0;cursor:pointer}.steps{display:flex;gap:8px;margin-bottom:20px;font-size:12px}.steps span{flex:1;padding:8px 4px;border-bottom:2px solid var(--divider-color);color:var(--secondary-text-color)}.steps span.active{border-color:var(--primary-color);color:var(--primary-color);font-weight:600}.catalogue{max-height:220px;overflow:auto;border:1px solid var(--divider-color);border-radius:10px;padding:8px 12px;margin-bottom:12px}.review{background:var(--secondary-background-color);border-radius:12px;padding:16px;margin-bottom:16px}.review p+p{margin-top:10px}.error-text{color:var(--error-color);font-size:13px;margin-bottom:12px}.block{display:block}.spacer{margin-top:14px}@media(max-width:480px){ha-card{padding:16px}.grid{gap:12px}.dialog-header,.dialog-body{padding:16px}.dialog-footer{padding:12px 16px}.list-item{flex-wrap:wrap}.list-item>.grow{min-width:160px}.toolbar{flex-wrap:wrap}.toolbar input{min-width:100%}.category .name{font-size:10px}h1{font-size:24px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}`;

class SimpliFiCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._step = 0;
    this._filter = "all";
    this._networkFilter = "all";
    this._connectionFilter = "all";
    this._presenceFilter = "all";
    this._query = "";
    this._busy = false;
    this._generation = 0;
  }
  setConfig(config) {
    if (!config.entry_id) throw new Error("Select a SimpliFi entry_id");
    this.config = { mode: "family", ...config };
    if (this._hass) this.refresh();
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._started && this.config) {
      this._started = true;
      this.refresh();
      this.startPolling();
    }
  }
  connectedCallback() {
    this.startPolling();
  }
  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
    this._generation++;
  }
  startPolling() {
    if (!this._timer)
      this._timer = setInterval(() => {
        if (this.isConnected && this._hass) this.refresh();
      }, 15000);
  }
  getCardSize() {
    return this.config?.mode === "header" ? 2 : 6;
  }
  getGridOptions() {
    return { columns: "full", rows: "auto" };
  }
  async api(action, data = {}) {
    const result = await this._hass.callWS({
      type: "call_service",
      domain: "simplifi",
      service: action,
      service_data: { entry_id: this.config.entry_id, ...data },
      return_response: true,
    });
    return result.response;
  }
  async refresh() {
    if (!this._hass || !this.config) return;
    if (this._refreshTask) return this._refreshTask;
    const generation = this._generation;
    this._refreshTask = (async () => {
      try {
        const data = await this.api(this.config.mode === "access" ? "access_status" : "dashboard_data");
        if (generation !== this._generation) return;
        this.data = data;
        if (this._modal?.kind === "updates" && data.updates && JSON.stringify(data.updates) !== JSON.stringify(this._updates)) this.drawUpdates(data.updates);
        this._error = null;
        this.render();
      } catch (error) {
        if (generation !== this._generation) return;
        this._error = error.message || String(error);
        this.render();
      }
    })();
    try {
      await this._refreshTask;
    } finally {
      this._refreshTask = null;
    }
  }
  get clockChangeDay() {
    const span = Date.parse(this.data.day_end) - Date.parse(this.data.day_start);
    return Number.isFinite(span) && span !== 86400000;
  }
  timelineTime(value) {
    return this.time(value, false, this.clockChangeDay);
  }
  timelineMiddle() {
    return this.time(new Date((Date.parse(this.data.day_start) + Date.parse(this.data.day_end)) / 2).toISOString());
  }
  timelineEnd(value) {
    return Date.parse(value) === Date.parse(this.data.day_end)
      ? "24:00"
      : this.timelineTime(value);
  }
  time(value, withDay = false, withZone = false) {
    if (!value) return "Until resumed";
    return new Intl.DateTimeFormat(this._hass?.locale?.language || "en-GB", {
      timeZone: this.data?.timezone || "Europe/London",
      hour: "2-digit",
      minute: "2-digit",
      ...(withDay ? { day: "numeric", month: "short" } : {}),
      ...(withZone ? { timeZoneName: "shortOffset" } : {}),
    }).format(new Date(value));
  }
  button(label, action, id = "", extra = "", kind = "") {
    const collection = ["group-edit", "detail", "assign-group", "quick", "control", "coexistence"].includes(action)
      ? this.data?.groups
      : ["rule-edit", "rule-options", "rule-toggle"].includes(action)
        ? this.data?.rules
        : action === "device" ? this.data?.devices : null;
    const name = ["dns", "probe-results", "probe-edit"].includes(action)
      ? this.data?.probes?.[id]?.name : collection?.find(item => item.id === id)?.name;
    if (name && !extra.includes("aria-label="))
      extra += ` aria-label="${escape(label + " · " + name)}"`;
    return `<button type="button" class="${kind}" data-action="${action}" data-id="${escape(id)}" ${extra} ${this._busy ? "disabled" : ""}>${escape(label)}</button>`;
  }
  focusButton(root, key) {
    if (!key?.action) return null;
    return [...root.querySelectorAll("button")].find(button =>
      !button.disabled && Object.keys(key).length === Object.keys(button.dataset).length &&
      Object.keys(key).every(name => button.dataset[name] === key[name]),
    );
  }
  restoreDialogFocus() {
    const content = this.shadowRoot.querySelector("#content");
    // Polling can replace the invoker while its dialog remains open.
    const previous = this._focusBefore;
    const target = previous?.isConnected && content.contains(previous) && !previous.disabled
      ? previous : this.focusButton(content, this._focusKeyBefore);
    (target || content).focus({ preventScroll: true });
    this._focusBefore = this._focusKeyBefore = null;
  }
  groupName(id) {
    return this.data.groups.find((g) => g.id === id)?.name || "Unassigned";
  }
  get disabled() {
    return this._busy || !!this._error || !this.data?.fresh;
  }
  disabledAttr() {
    return this.disabled ? "disabled" : "";
  }
  resultHTML() {
    if (!this._lastChange) return "";
    const change =
      this.data?.changes.find((c) => c.id === this._lastChange.id) ||
      this._lastChange;
    const labels = {
      pending: "Saved · waiting for gateway",
      applied: this.data?.simulation
        ? "Applied in simulator"
        : "Configuration applied",
      partial: "Partly applied · review Activity",
      failed: "Attempt failed · see sync results",
      saved_management_disabled: "Saved · gateway management is disabled",
    };
    return `<div class="result" role="status"><strong>${escape(labels[change.outcome] || words(change.outcome))}</strong>${escape(this._lastLabel || "Change saved")}${change.outcome === "applied" && !this.data?.simulation ? '<small class="block">Gateway readback confirmed; device traffic is a separate check.</small>' : ""}${change.outcome === "failed" ? this.historyChangeButton(change) : ""}</div>`;
  }
  warnings() {
    let html = "";
    if (this._error)
      html += `<div class="banner error" role="alert">${icon("mdi:alert-circle-outline")}<span>Unable to refresh. ${escape(this._error)} Last observations may be stale.</span></div>`;
    else if (this.data && !this.data.fresh) {
      const reason = typeof this.data.issue === "string" ? this.data.issue.trim() : "";
      html += `<div class="banner warning" role="status"><span><strong>Controls unavailable.</strong> ${reason ? escape(reason) : "Gateway confirmation is unavailable or stale. Refresh the observations before making changes."}</span></div>`;
    }
    return html;
  }
  render() {
    if (!this.shadowRoot.querySelector("#content")) {
      this.shadowRoot.innerHTML = `<style>${styles}.health-table{width:100%;border-collapse:collapse;font-size:13px}.health-table th,.health-table td{text-align:left;padding:8px;border-bottom:1px solid var(--divider-color);overflow-wrap:anywhere}.health-table caption{text-align:left;margin:12px 0;font-weight:600}.continuous-rule{flex-wrap:wrap;align-items:flex-start}.continuous-rule .grow{flex-basis:160px}.rule-controls{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-left:auto}</style><div id="content" tabindex="-1" role="region" aria-label="SimpliFi controls"></div><dialog aria-labelledby="dialog-title"><div class="dialog-shell"></div></dialog>`;
      this.shadowRoot.addEventListener("click", (e) => this.click(e));
      this.shadowRoot.addEventListener("input", (e) => this.input(e));
      this.shadowRoot.addEventListener("change", (e) => this.change(e));
      this.shadowRoot.querySelector("dialog").addEventListener("close", () => {
        if (this.shadowRoot.querySelector("dialog").open) return;
        this._modal = null;
        this.restoreDialogFocus();
      });
    }
    const content = this.shadowRoot.querySelector("#content");
    if (!this.data) {
      content.innerHTML = `<ha-card><p role="status">${escape(this._error || "Loading family controls…")}</p>${this._error ? this.button("Retry", "refresh") : ""}</ha-card>`;
      return;
    }
    // Polling must not replace an input being edited or steal keyboard focus.
    if (
      content.contains(this.shadowRoot.activeElement) &&
      ["INPUT", "SELECT", "TEXTAREA"].includes(
        this.shadowRoot.activeElement?.tagName,
      )
    )
      return;
    const focused = this.shadowRoot.activeElement;
    const focusKey =
      content.contains(focused) && focused?.tagName === "BUTTON"
        ? { ...focused.dataset }
        : null;
    const mode = this.config.mode;
    const openDetails = new Set(
      [...content.querySelectorAll("details[data-readback-key][open]")].map(
        (details) => details.dataset.readbackKey,
      ),
    );
    const focusedDetail = focused?.tagName === "SUMMARY"
      ? focused.parentElement?.dataset.readbackKey : null;
    content.innerHTML =
      this.warnings() +
      this.resultHTML() +
      (mode === "access" ? this.scopedAccess() : mode === "header"
        ? this.header()
        : mode === "family"
          ? this.family()
          : mode === "devices"
            ? this.devices()
            : mode === "rules"
              ? this.rules()
              : mode === "filtering"
                ? this.filtering()
                : this.activity());
    for (const details of content.querySelectorAll("details[data-readback-key]")) {
      details.open = openDetails.has(details.dataset.readbackKey);
      if (focusedDetail === details.dataset.readbackKey)
        details.querySelector("summary")?.focus({ preventScroll: true });
    }
    if (focusKey)
      this.focusButton(content, focusKey)?.focus({ preventScroll: true });
  }
  header() {
    const d = this.data;
    const unassigned = d.devices.filter((x) => !x.group).length;
    return `<ha-card><div class="row between wrap"><div><h1>SimpliFi</h1><p class="lead">Family internet controls for UniFi, made effortless via Home Assistant.</p></div><div class="row wrap"><span class="badge ${d.fresh ? "blue" : "amber"}">${icon(d.fresh ? "mdi:check-network-outline" : "mdi:lan-disconnect")}${d.simulation ? "Simulator" : d.fresh ? "Connected" : "Last known"}</span>${d.updates?.check?.available === true ? this.button("Update available", "updates", "", "", "primary") : ""}${unassigned ? `<span class="badge amber">${unassigned} unassigned</span>` : ""}</div></div>${d.simulation ? '<p class="note spacer">Preview household · fictional devices and policies. Real UniFi controls are not connected.</p>' : !d.management ? '<p class="note spacer">Observation mode · changes are saved but gateway management is disabled.</p>' : ""}</ha-card>`;
  }
  family() {
    const groups = this.data.groups.filter((g) => !g.archived);
    return `<div class="row between card-top"><div><h2>Your family</h2><p class="lead">A clear view of who can get online</p></div><div class="row wrap">${this.button("Guided setup", "setup")}${this.button("Add person", "group-new")}</div></div>${
      groups.some((g) => g.kind === "family")
        ? `<div class="grid people">${groups
            .filter((g) => g.kind === "family")
            .map((g) => this.person(g))
            .join("")}</div>`
        : `<ha-card class="empty">${icon("mdi:account-group-outline")}<h3>Add your household</h3><p>Create a person, then assign their devices to keep their controls together.</p>${this.button("Add person", "group-new", "", "", "primary")}</ha-card>`
    }<div class="section"><div class="row between card-top"><h2>Shared devices</h2>${this.button("Add shared group", "thing-new")}</div>${
      groups.some((g) => g.kind === "thing")
        ? `<div class="grid">${groups
            .filter((g) => g.kind === "thing")
            .map((g) => this.person(g))
            .join("")}</div>`
        : '<p class="muted">Group the TV, games console or other shared devices here.</p>'
    }</div>${
      this.data.groups.some((g) => g.archived)
        ? `<div class="section"><h3>Archived</h3>${this.data.groups
            .filter((g) => g.archived)
            .map((g) => this.button(g.name, "group-edit", g.id))
            .join(" ")}</div>`
        : ""
    }`;
  }
  person(g) {
    const picture =
      g.person && this._hass.states[g.person]?.attributes?.entity_picture;
    const photo =
      picture?.startsWith("/") && !picture.startsWith("//")
        ? `<img src="${escape(picture)}" alt="">`
        : escape(g.name.slice(0, 1).toUpperCase());
    let explanation = g.expires_at
      ? `Until ${this.time(g.expires_at)}`
      : g.state === "paused"
        ? "Until resumed"
        : g.next_change
          ? `${g.next_state === "scheduled_block" ? "Next restriction" : "Next change"} at ${this.time(g.next_change)}`
          : "No upcoming internet restriction";
    if (g.actor) explanation += ` · ${g.actor}`;
    const other = (g.other_policies?.length || 0) + (g.possible_other_policies?.length || 0);
    const accessLabel = this.accessLabel(g);
    return `<ha-card><div class="row card-top"><div class="avatar">${g.kind === "thing" ? icon("mdi:devices") : photo}</div><div class="grow"><h2>${escape(g.name)}</h2><small>${g.kind === "thing" ? "Shared devices" : escape(g.age ? words(g.age) : "Family member")}</small></div>${this.button("Edit", "group-edit", g.id, 'aria-label="Edit ' + escape(g.name) + '"', "quiet")}</div><div class="status ${escape(g.state)}"><span class="dot"></span>${escape(accessLabel)}</div><div class="description">${escape(explanation)}${g.reason && g.reason !== "Content restrictions may still apply" ? `<br>${escape(g.reason)}` : ""}</div>${other ? `<p class="note spacer">Other UniFi restrictions may also apply. ${this.button("Review other rules", "coexistence", g.id, "", "quiet")}</p>` : ""}<div class="actions">${this.personActions(g)}</div>${this.continuousRules(g)}${this.personRestrictionActions(g)}<div class="categories">${g.categories.map((c) => `<button type="button" class="category ${c.state}" data-action="category" data-id="${escape(g.id)}" data-category="${escape(c.slug || String(c.id))}" aria-label="${escape(g.name + " — " + c.name + ": " + this.categoryControlLabel(c))}"><span class="category-icon">${icon(c.icon)}</span><span class="name">${escape(c.name)}</span><span class="state">${escape(this.categoryControlLabel(c))}</span></button>`).join("")}</div><div class="footer"><small>${g.devices} assigned · ${this.data.fresh ? g.connected + " connected" : "last known"}</small>${this.button("Details", "detail", g.id, "", "quiet")}</div></ha-card>`;
  }
  categoryControlLabel(c) {
    if ((c.label || "").startsWith("DNS") || ["Needs checking", "Not checked"].includes(c.label))
      return c.supported ? "No app-category rule" : "No profile confirmed";
    return c.label || words(c.state);
  }
  personRestrictionActions(g) {
    return `<section class="section"><h3>Restrictions</h3><div class="row wrap spacer">${[["application","Block apps"],["domain","Block websites"],["category","Block categories"],["internet","Schedules"]].map(([kind,label]) => this.button(label,"person-rule",g.id,`data-kind="${kind}"`)).join("")}${this.button("Content filtering & SafeSearch","person-protection",g.id)}</div><p class="note">Choose what to restrict on this person’s assigned devices.</p></section>`;
  }
  personProtection(id) {
    const g = this.data.groups.find(g => g.id === id);
    const ids = new Set((g.protection?.profiles || []).map(p => p.id));
    const profiles = (this.data.protection?.profiles || []).filter(p => ids.has(p.id));
    this.open("Content filtering · " + g.name, `<p>These UniFi profiles apply to this person’s devices. Editing a shared profile affects its other networks and devices too.</p>${profiles.map(p => `<div class="audit-row"><h3>${escape(p.name)}</h3><p>${p.categories.length} blocked categories · SafeSearch: ${escape(p.safe_search.join(", ") || "Off")}</p>${this.profileEditButton(p)}</div>`).join("") || '<p>No enabled matching profile was confirmed. Open Filtering to review all UniFi profiles and their scope.</p>'}`,this.button("Close","close"));
  }
  profileEditButton(p) {
    return this.data.protection?.editing_available ? this.button("Edit content filter","profile-edit",p.id) : '<p class="note">Editing requires a fresh UniFi connection.</p>';
  }
  profileForm(id) {
    const p = this.data.protection.profiles.find(p => p.id === id);
    if (!p || !this.data.protection.editing_available) throw new Error("Refresh UniFi profiles before editing.");
    const categories = [...new Set([...(this.data.protection.category_choices || []), ...p.categories])].sort();
    this.open("Edit UniFi profile · " + p.name, `<p><strong>Applies to:</strong> ${escape(p.networks.map(n=>n.name).join(", ") || "No networks")} · ${p.client_macs.length} individually assigned devices.</p><p class="note">This edits the shared UniFi profile. Its device/network assignments and schedule are preserved.</p><form>${this.check("Enable this profile","enabled",p.enabled)}<h3>SafeSearch</h3>${[...new Set(["GOOGLE","BING","YOUTUBE",...p.safe_search])].map(v=>`<label class="check"><input type="checkbox" name="safe_search" value="${escape(v)}" ${p.safe_search.includes(v)?"checked":""}>${escape(words(v))}</label>`).join("")}<details class="section"><summary>Blocked content categories (${p.categories.length} selected)</summary><p class="note">Choices observed on this controller. Application categories are managed separately using Block categories.</p>${categories.map(v=>`<label class="check"><input type="checkbox" name="categories" value="${escape(v)}" ${p.categories.includes(v)?"checked":""}>${escape(words(v))}</label>`).join("")}</details>${[["allow_list","Allowed domains"],["block_list","Blocked domains"]].map(([k,label])=>`<label class="field">${label}<textarea name="${k}" rows="5">${escape(p[k].join("\n"))}</textarea></label>`).join("")}<p class="note">One domain per line. Allowed domains are exceptions to this profile’s filtering.</p></form>`,this.button("Cancel","close")+this.button("Review changes","submit","","","primary"),{kind:"profile-edit",id});
  }
  accessLabel(g) {
    if (g.state === "scheduled_block" && g.always_on_internet) return "Internet rule active";
    if (g.state === "scheduled_block" && g.all_day_internet) return "All-day restriction";
    const other = (g.other_policies?.length || 0) + (g.possible_other_policies?.length || 0);
    return other && ["available", "allowed"].includes(g.state) ? "Managed access allowed" : statusText[g.state] || words(g.state);
  }
  continuousRules(g, ruleIds) {
    const rows = (g.rule_rows || []).filter(r => !ruleIds || ruleIds.includes(r.rule_id));
    if (!rows.length) return "";
    const scoped = this.config?.mode === "access", controls = !scoped || this.data.scope !== "read_only";
    const icons = {internet:"mdi:web-off",category:"mdi:filter-outline",application:"mdi:apps",domain:"mdi:web"};
    return `<section class="section" aria-label="Always-on and all-day rules for ${escape(g.name)}"><h3>Always-on and all-day rules</h3><div class="list">${rows.map(r => {
      const rule = this.data.rules.find(rule => rule.id === r.rule_id);
      const canControl = controls && (r.person_control || !scoped || rule?.whole_rule_control);
      return `<div class="list-item continuous-rule">${icon(icons[r.kind] || "mdi:filter-outline")}<div class="grow"><strong>${escape(r.name)}</strong><p class="note">${r.targets.map(t => escape(t.name)).join(" · ")}</p><small>${r.mode === "always_on" ? "Always on" : "All day today"} · ${r.network_scope ? "Whole-network rule" : "Person rule"}<br>${r.covered_devices} of ${r.devices} managed devices${r.coverage_fresh ? "" : " · last-known coverage"}</small></div><div class="rule-controls"><span class="badge ${r.state === "restricted" ? "red" : ["unknown","partial"].includes(r.state) ? "amber" : ""}">${escape(r.label)}</span>${canControl ? this.button(r.network_scope ? "Network options" : "Options", "rule-options", r.rule_id, `${!r.enabled ? "disabled" : this.disabledAttr()}${r.person_control ? ` data-group="${escape(g.id)}"` : ""} aria-label="${escape((r.network_scope ? "Network options" : "Options") + " · " + r.name + " · " + g.name)}"`, "quiet") : ""}</div></div>`;
    }).join("")}</div><p class="note">Gateway configuration evidence; confirm filtering on the device.</p></section>`;
  }
  personActions(g) {
    return this.internetActions(g) + this.unblockButton(g);
  }
  unblockButton(g) {
    return g.devices && g.unblock && (g.unblock.eligible_rules || g.unblock.can_unblock || g.unblock.allowances)
      ? this.button(g.unblock.allowances ? "Manage rule allowances" : "Unblock rules…", "group-unblock", g.id, this.disabledAttr()) : "";
  }
  internetActions(g) {
    g = { ...g, state: g.control_state || g.state };
    const disabled = this.disabledAttr();
    if (!g.devices) return this.button("Assign devices", "assign-group", g.id);
    if (g.state === "paused")
      return (
        this.button(
          "Resume",
          "quick",
          g.id,
          `${disabled} data-service="resume_internet"`,
          "primary",
        ) +
        this.button(
          "Extend 30 min",
          "quick",
          g.id,
          `${disabled} data-service="extend_pause" data-duration="30"`,
        )
      );
    if (g.state === "allowed")
      return (
        this.button(
          "Return to schedule",
          "quick",
          g.id,
          `${disabled} data-service="end_allowance"`,
          "primary",
        ) + (this.allowanceButtons(this.data.exceptions.filter(e => e.group === g.id && !e.rule)) || this.button("Options", "control", g.id, disabled))
      );
    if (g.state === "scheduled_block")
      return (
        this.button(
          "Allow 30 min",
          "quick",
          g.id,
          `${disabled} data-service="allow_internet" data-duration="30"`,
          "primary",
        ) + this.button("Allow until…", "control", g.id, disabled)
      );
    return (
      this.button(
        "Pause 30 min",
        "quick",
        g.id,
        `${disabled} data-service="pause_internet" data-duration="30"`,
        "primary",
      ) + this.button("More", "control", g.id, disabled)
    );
  }
  devicePresence(d) {
    if (!d.last_seen) return "Not observed yet";
    const label = d.connected ? "Connected" : "Offline";
    return this.data.fresh ? label : "Last known · " + label.toLowerCase();
  }
  deviceRows() {
    const query = (this._query || "").trim().toLowerCase();
    return this.data.devices.filter(d =>
      (!this._filter || this._filter === "all" || (this._filter === "unassigned" && !d.group) || (this._filter === "assigned" && d.group) || d.group === this._filter) &&
      (!this._networkFilter || this._networkFilter === "all" || d.network === this._networkFilter) &&
      (!this._connectionFilter || this._connectionFilter === "all" || d.kind === this._connectionFilter) &&
      (!this._presenceFilter || this._presenceFilter === "all" || (this._presenceFilter === "online" ? d.connected : !d.connected)) &&
      [d.name, d.mac, d.ip, d.registrant, d.uplink_name, this.data.networks[d.network]?.name].filter(Boolean).join(" ").toLowerCase().includes(query)
    ).sort((a, b) => a.name.localeCompare(b.name));
  }
  deviceRow(d) {
    const outside = this.data.managed_networks && !this.data.managed_networks.includes(d.network);
    return `<div class="list-item">${icon(d.kind === "wired" ? "mdi:ethernet" : "mdi:wifi")}<div class="grow"><div class="name">${escape(d.name)}</div><small>${escape(this.groupName(d.group))} · ${escape(this.data.networks[d.network]?.name || "Unknown network")}${outside ? " · outside managed scope" : ""}</small><small>${escape(this.devicePresence(d))}${d.last_seen ? " · last seen " + this.time(d.last_seen, true) : ""}</small><small>${escape([d.kind === "unknown" ? "" : words(d.kind), d.ip, d.uplink_name].filter(Boolean).join(" · "))}</small></div>${this.button("Details & assign", "device", d.id)}</div>`;
  }
  devices() {
    const rows = this.deviceRows();
    const filter = (label, key, options, selected) => `<select aria-label="${label}" data-filter="${key}">${choices(options, selected || "all")}</select>`;
    return `<ha-card><div class="row between card-top"><div><h2>Devices</h2><p class="lead">Keep each device with the right person</p></div>${this.button("Refresh", "sync")}</div><div class="row wrap toolbar"><input type="search" aria-label="Search devices" data-search="devices" placeholder="Name, IP, MAC, registrant or access point" value="${escape(this._query || "")}">
      ${filter("Filter devices by owner", "owner", [["all", "All owners"], ["assigned", "Assigned"], ["unassigned", "Unassigned"], ...this.data.groups.filter(g => !g.archived).map(g => [g.id, g.name])], this._filter)}
      ${filter("Filter devices by network", "network", [["all", "All networks"], ...Object.entries(this.data.networks).map(([id, n]) => [id, n.name])], this._networkFilter)}
      ${filter("Filter devices by connection", "connection", [["all", "Wired & wireless"], ["wired", "Wired"], ["wireless", "Wireless"], ["unknown", "Unknown connection"]], this._connectionFilter)}
      ${filter("Filter devices by presence", "presence", [["all", "Any presence"], ["online", this.data.fresh ? "Connected" : "Last known connected"], ["offline", this.data.fresh ? "Offline" : "Last known offline"]], this._presenceFilter)}</div>
      <p class="note" id="device-count">${rows.length} of ${this.data.devices.length} devices${this.data.fresh ? "" : " · observations are not current"}</p><div id="device-list" class="list">${rows.length ? rows.map(d => this.deviceRow(d)).join("") : '<div class="empty"><h3>No matching devices</h3><p>Try another filter. Present devices reappear after successful discovery.</p></div>'}</div><div class="settings row between wrap"><div><h3>Unknown-device quarantine</h3><p class="note">${this.data.quarantine ? "Enabled" : "Disabled"}${this.data.quarantine_paused ? (this.data.quarantine_until ? " · suspended until " + this.time(this.data.quarantine_until) : " · paused until resumed") : ""}. Blocks unassigned devices after discovery within the managed network.</p></div>${this.button("Manage quarantine", "quarantine")}</div></ha-card>`;
  }
  quarantineCard() {
    const q = this.data.quarantine_rule;
    if (!q) return "";
    const tag = this.config?.mode === "access" ? "div" : "ha-card";
    const state = !q.enabled ? "Disabled" : q.paused ? "Paused" : "Enabled";
    const control = (label, id) => this.button(label, "quarantine-control", id, this.disabledAttr());
    return `<${tag} class="${tag === "div" ? "settings" : ""}"><div class="row between wrap"><div><h3>Unknown-device quarantine</h3><small>Built-in rule · all managed networks</small></div><span class="badge ${q.paused ? "amber" : q.enabled ? "blue" : ""}">${state}</span></div><p class="rule-details">Blocks internet for unassigned devices after discovery. Assigned devices and exclusions keep their own rules.${q.paused ? " Pause ends " + (q.expires_at ? this.time(q.expires_at, true) : "when resumed manually") + "." : ""}</p><div class="row wrap">${q.can_control && q.enabled ? (q.paused ? control("Resume quarantine", "resume") + (q.expires_at ? control("Extend 30 min", "extend") : "") : control("Pause 30 min", "pause") + control("Pause until resumed", "indefinite")) : ""}${q.can_toggle ? this.button("Manage quarantine", "quarantine") : ""}</div></${tag}>`;
  }
  ruleCard(r) {
    const exceptions = this.data.exceptions.filter((e) => e.rule === r.id || e.kind === "internet_allow" && e.captured?.includes(r.id));
    return `<ha-card><div class="row between"><div class="grow"><h3>${escape(r.name)}</h3><small>${escape(words(r.kind))}</small></div><span class="badge ${r.enabled ? (r.active ? "red" : "blue") : ""}">${!r.enabled ? "Disabled" : exceptions.length ? "Exception active" : r.active ? "Active now" : "Scheduled"}</span></div><div class="rule-details"><p>${escape(this.ruleScope(r))}</p><p>${escape((r.target_names || r.targets).join(", ") || "All internet")}</p><p>${escape(this.scheduleLabel(r))}</p>${exceptions.map((e) => `<p>${escape(words(e.kind))} · ${e.group ? escape(this.groupName(e.group)) : "Everyone on this rule"} · ${e.expires_at ? "until " + this.time(e.expires_at) : "until resumed"}</p>`).join("")}</div><div class="row wrap">${this.button("Edit", "rule-edit", r.id)}${this.button("Options", "rule-options", r.id, !r.enabled ? "disabled" : this.disabledAttr())}${this.button(r.enabled ? "Disable" : "Enable", "rule-toggle", r.id, this.disabledAttr(), "quiet")}</div></ha-card>`;
  }
  scheduleLabel(r) {
    return r.windows.length
      ? r.windows
          .map(
            (w) =>
              `${w.name || "Window"} · ${w.days.map((d) => dayNames[d]).join(", ")} · ${w.all_day ? "all day" : w.start + "–" + w.end + (w.overnight ? " next day" : "")}`,
          )
          .join("; ")
      : "Always";
  }
  rules() {
    let rows = this.data.rules;
    if (this._ruleGroup)
      rows = rows.filter((r) => (r.groups.includes(this._ruleGroup) || r.affected_groups?.includes(this._ruleGroup)));
    return `<div class="row between card-top"><div><h2>Rules & schedules</h2><p class="lead">Set boundaries for people or whole networks</p></div>${this.button("Add rule", "rule-new", "", "", "primary")}</div><div class="filters">${this.button("Everyone", "rules-filter", "", "", !this._ruleGroup ? "selected" : "")}${this.data.groups
      .filter((g) => !g.archived)
      .map((g) =>
        this.button(
          g.name,
          "rules-filter",
          g.id,
          "",
          this._ruleGroup === g.id ? "selected" : "",
        ),
      )
      .join(
        "",
      )}</div><div class="grid">${this.quarantineCard()}${rows.length ? `${rows.map((r) => this.ruleCard(r)).join("")}` : `<ha-card class="empty">${icon("mdi:calendar-clock-outline")}<h3>No rules yet</h3><p>Create a bedtime, homework or content rule. Choose people or networks, days and times.</p>${this.button("Create a rule", "rule-new", "", "", "primary")}</ha-card>`}</div><p class="note">Schedules use ${escape(this.data.timezone)}. Temporary exceptions keep unrelated content restrictions in place.</p>`;
  }
  protectionHTML() {
    const protection = this.data.protection;
    const fresh = protection?.fresh === true;
    const profiles = protection?.profiles || [];
    const status = fresh ? "Controller configuration read" : profiles.length ? "Last-known configuration" : "Filtering readback unavailable";
    const list = (values) => values.length ? values.map((value) => `<li>${escape(value)}</li>`).join("") : "<li>None configured</li>";
    return `<ha-card><div class="row between wrap"><div><h2>Content filtering & SafeSearch</h2><p class="lead">UniFi profiles shared by networks and devices</p></div>${this.button("Refresh", "refresh")}</div>
      <div class="banner ${fresh ? "" : "warning"} spacer" role="status">${icon("mdi:shield-search")}<div><strong>${escape(status)}</strong><p>${escape(protection?.issue || (fresh ? `${profiles.length} profiles · checked ${this.time(protection.observed_at, true)}` : "Waiting for the matching Home Assistant UniFi connection."))}</p></div></div>
      <p class="note">A disabled profile does not disable other profiles. Expand a profile to review or edit its filtering.</p>${protection?.last_edit ? `<details class="section" data-readback-key="profile-edit-history"><summary>Last profile save · ${escape(protection.last_edit.status)}</summary><p class="note">${this.time(protection.last_edit.at,true)} · ${escape(profiles.find(p=>p.id===protection.last_edit.profile_id)?.name || "UniFi profile")}</p>${protection.last_edit.status === "uncertain" ? '<p>Save could not be confirmed. Inspect the profile in UniFi, then reopen its editor. Further saves are blocked until readback resolves the outcome.</p>' : ""}${["before","after"].map(k=>`<h3>${k === "before" ? "Previous settings" : "Requested settings"}</h3><ul>${Object.entries(protection.last_edit[k]).map(([field,value])=>`<li>${escape(words(field))}: ${escape(Array.isArray(value) ? value.join(", ") || "None" : value ? "Enabled" : "Disabled")}</li>`).join("")}</ul>`).join("")}</details>` : ""}${profiles.map((profile) => `<details class="audit-row" data-readback-key="${escape(profile.id)}:profile"><summary><strong>${escape(profile.name)}</strong> <span class="badge ${!fresh ? "amber" : ""}">${!fresh ? "Last known · " : ""}${profile.enabled ? "Enabled" : "Disabled"}</span></summary>
        <p class="note">Networks: ${escape(profile.networks.map((n) => n.name).join(", ") || "None")} · ${profile.client_macs.length} individual devices</p>
        ${this.profileEditButton(profile)}${!profile.enabled ? '<p class="note">This profile is switched off in UniFi. Other enabled profiles can still apply.</p>' : ""}<p class="note">Schedule: ${escape(words(profile.schedule.mode))}${profile.schedule.days?.length ? " · " + escape(profile.schedule.days.join(", ")) : ""}${profile.schedule.time_start ? " · " + escape(profile.schedule.time_start) + "–" + escape(profile.schedule.time_end) : ""}${profile.schedule.date_start ? " · " + escape(profile.schedule.date_start) + "–" + escape(profile.schedule.date_end) : ""}</p>
        <p><strong>SafeSearch:</strong> ${escape(profile.safe_search.join(", ") || "None configured")}</p>
        <details class="section" data-readback-key="${escape(profile.id)}:categories"><summary>Blocked categories (${profile.categories.length})</summary><ul>${list(profile.categories.map(words))}</ul></details>
        <details class="section" data-readback-key="${escape(profile.id)}:allowed"><summary>Allowed domains (${profile.allow_list.length})</summary><ul>${list(profile.allow_list)}</ul></details>
        <details class="section" data-readback-key="${escape(profile.id)}:blocked"><summary>Blocked domains (${profile.block_list.length})</summary><ul>${list(profile.block_list)}</ul></details>
        ${profile.client_macs.length ? `<details class="section" data-readback-key="${escape(profile.id)}:clients"><summary>Individual devices (${profile.client_macs.length})</summary><ul>${list(profile.client_macs.map((mac) => this.data.devices.find((device) => device.mac.toLowerCase() === mac.toLowerCase())?.name || mac))}</ul></details>` : ""}
      </details>`).join("")}
      ${fresh && !profiles.length ? '<p class="note">No content-filtering profiles returned for this site.</p>' : ""}
      ${protection?.observed_at ? `<p class="note">Last successful read: ${this.time(protection.observed_at, true)}</p>` : ""}
      <p class="note">${escape(protection?.source || "Home Assistant UniFi Network integration")} · all profiles on this site. Configuration readback; client traffic has not been tested. Editing requires review. An internet allowance does not bypass these filters.</p>
    </ha-card>`;
  }
  policyRows(snapshot = this.data.coexistence, group = this._policyGroup || "", mode = this._policyMode || "restrictions") {
    const query = (this._policyQuery || "").trim().toLocaleLowerCase();
    return (snapshot?.policies || []).filter(p =>
      (!group || p.matched_groups.includes(group) || p.possible_groups.includes(group)) &&
      (mode === "all" || (mode === "managed" ? p.ownership !== "external" : ["external", "drift"].includes(p.ownership) && p.enabled && ["BLOCK", "REJECT"].includes(p.action))) &&
      (!query || [p.name, p.source, p.destination, p.source_zone, p.destination_zone].join(" ").toLocaleLowerCase().includes(query)),
    );
  }
  policyListHTML(snapshot = this.data.coexistence, group = this._policyGroup || "", mode = this._policyMode || "restrictions") {
    const rows = this.policyRows(snapshot, group, mode), limit = this._policyLimit || 50;
    const owner = {managed:"SimpliFi · recorded ownership", drift:"Recorded policy changed since verification", external:"Other UniFi policy", pending:"Recorded policy · awaiting a newer observation"};
    return `<p class="note">Showing ${Math.min(rows.length, limit)} of ${rows.length} matching rules · ${snapshot?.policy_count || 0} read from the site</p>${rows.slice(0,limit).map(p => `<details class="audit-row" data-readback-key="${escape(p.id)}:policy"><summary><strong>${escape(p.name)}</strong> <span class="badge ${p.ownership === "drift" ? "red" : !snapshot.fresh ? "amber" : ""}">${!snapshot.fresh ? "Last known · " : ""}${p.enabled ? escape(p.action) : "Disabled"}</span></summary>
      <p class="note">${escape(owner[p.ownership] || "Ownership unknown")} · ${escape(words(p.origin))}</p>
      <p><strong>From:</strong> ${escape(p.source_zone)} · ${escape(p.source)}</p><p><strong>To:</strong> ${escape(p.destination_zone)}${p.internet_destination ? " (internet zone)" : ""} · ${escape(p.destination)}</p>
      <p class="note">${escape(p.conditions.join(" · "))}</p><p class="note">Schedule: ${escape(p.schedule)}</p>
      <p class="note">Order: ${p.order ? `${p.order.position} ${p.order.section === "beforeSystemDefined" ? "before" : "after"} system rules in this zone pair` : "Not confirmed in user-defined ordering"}${p.index !== null ? " · controller index " + escape(p.index) : ""}</p>
      <p class="note">Source address matches: ${escape(p.matched_groups.map(id => this.groupName(id)).join(", ") || "No confirmed person match")}${p.possible_groups.length ? ". Source may match: " + escape(p.possible_groups.map(id => this.groupName(id)).join(", ")) : ""}. Other conditions and rule precedence still apply.</p>
    </details>`).join("")}${!rows.length ? `<p class="note">${snapshot?.fresh ? "No rules match these filters." : "No current matching rules confirmed."}</p>` : ""}${rows.length > limit ? this.button("Show 50 more", "policy-more") : ""}`;
  }
  policyReadbackNote(snapshot) {
    if (!snapshot) return "Policy readback is not available yet.";
    return `${snapshot.fresh ? "Configuration read" : snapshot.observed_at ? "Last-known configuration" : "Policy readback unavailable"}${snapshot.observed_at ? " · " + this.time(snapshot.observed_at, true) : ""}${snapshot.issue ? ". " + snapshot.issue : ""}`;
  }
  coexistenceHTML() {
    const s = this.data.coexistence, controls = s?.controls;
    const options = [["restrictions","Other enabled restrictions"],["managed","Recorded SimpliFi policies"],["all","All site policies"]];
    return `<ha-card><h2>Other UniFi rules</h2><p class="lead">Configuration that can affect access alongside SimpliFi</p><p class="note spacer">${escape(this.policyReadbackNote(s))}</p>
      <p class="note">Source matches identify people whose known device addresses fit a rule. Schedules, ports, protocol, rule order and existing connections determine whether traffic is affected. An allowance here does not override these rules.</p>
      <div class="row wrap toolbar spacer"><input type="search" data-search="policies" aria-label="Search UniFi rules" placeholder="Rule, network or destination" value="${escape(this._policyQuery || "")}"><select data-policy-filter="mode" aria-label="Filter UniFi rules">${choices(options,this._policyMode || "restrictions")}</select><select data-policy-filter="group" aria-label="Filter UniFi rules by person">${choices([["","All site scopes"],...this.data.groups.map(g=>[g.id,g.name])],this._policyGroup || "")}</select></div>
      <div id="policy-list" tabindex="-1" aria-label="UniFi rules">${this.policyListHTML()}</div><p class="note">${escape(s?.source || "UniFi read-only API")}. Ordering: ${escape(words(s?.ordering?.status || "unavailable"))} · ${s?.ordering?.read || 0} of ${s?.ordering?.pairs || 0} zone pairs${s?.ordering?.failed ? " · " + s.ordering.failed + " failed" : ""}. Read-only; no policy or ordering changes.</p>
      <details class="section" data-readback-key="alternate-controls"><summary>Independent Home Assistant UniFi controls (${controls?.status === "available" ? (controls.items.filter(c=>c.registry_enabled).length + " enabled in HA") : "readback " + (controls?.status || "unavailable")})</summary><p class="note">${escape(controls?.status || "unavailable")}${controls?.observed_at ? " · snapshot " + this.time(controls.observed_at,true) : ""}${controls?.issue ? ". " + escape(controls.issue) : ""}. These switches use Home Assistant's own permissions. SimpliFi grants do not restrict them; hidden controls can still be callable.</p>${(controls?.items || []).map(c=>`<div class="audit-row"><strong>${escape(c.name)}</strong><p class="note">${escape(c.kind)} · ${c.registry_enabled ? "Enabled in HA" : "Disabled in HA"} · reported state ${escape(words(c.state))}${c.hidden ? " · hidden" : ""}</p></div>`).join("")}</details>
    </ha-card>`;
  }
  otherPolicies(id, reset = true) {
    if (reset) { this._policyLimit = 50; this._policyQuery = ""; this._policySnapshot = structuredClone(this.data.coexistence); }
    const snapshot = this._policySnapshot;
    this.open("UniFi rules · " + this.groupName(id), `<p class="note">Snapshot: ${escape(this.policyReadbackNote(snapshot))}. Includes confirmed and possible source matches. This view does not test device traffic or change rules.</p><div id="policy-list" tabindex="-1" aria-label="UniFi rules">${this.policyListHTML(snapshot, id, "all")}</div>`, this.button("Refresh snapshot", "policy-refresh", id) + this.button("Close", "close"), {kind:"coexistence", id});
  }
  updatePolicyList() {
    const list = this.shadowRoot.querySelector("#policy-list");
    if (!list) return;
    const focused = this.shadowRoot.activeElement, key = list.contains(focused) && focused?.dataset?.action ? {...focused.dataset} : null;
    list.innerHTML = this._modal?.kind === "coexistence" ? this.policyListHTML(this._policySnapshot, this._modal.id, "all") : this.policyListHTML();
    if (key) (this.focusButton(list, key) || list).focus({preventScroll:true});
  }
  filtering() {
    const probes = Object.entries(this.data.probes);
    return `${this._profileResult ? `<div class="banner" role="status">${escape(this._profileResult)}</div>` : ""}<div class="grid">${this.protectionHTML()}<ha-card><h2>Managed restrictions</h2><p class="lead">Rules created by SimpliFi</p><div class="list spacer">${
      this.data.rules
        .filter((r) => r.kind !== "internet")
        .map(
          (r) =>
            `<div class="list-item"><div class="grow"><strong>${escape(r.name)}</strong><small>${escape((r.target_names || r.targets).join(", "))} · ${escape(this.ruleScope(r))}</small></div>${this.button("Edit", "rule-edit", r.id)}</div>`,
        )
        .join("") ||
      '<p class="muted">No category, application or website rules yet.</p>'
    }</div><div class="spacer">${this.button("Add restriction", "rule-new")}</div></ha-card></div><details class="section" data-readback-key="advanced-diagnostics"><summary>Advanced diagnostics · DNS samples and other UniFi rules</summary><p class="note">These tools diagnose Home Assistant’s network view. They do not test a child’s device or apply restrictions.</p><div class="section">${this.coexistenceHTML()}</div><div class="section"><div class="row between card-top wrap"><div><h2>DNS checks</h2><p class="lead">Sample responses from Home Assistant</p></div><div class="row wrap">${this.button("Resolver settings", "dns-settings")}${this.button("Check all", "dns-all", "", this.data.dns_progress?.running || !this.data.dns_settings?.enabled ? "disabled" : "")}${this.button("Add check", "probe-new")}</div></div>
    <p class="note">Runs from Home Assistant, even when querying another network’s DNS server. A person context selects a resolver; it does not use that person’s device or network identity. DNS resolution cannot confirm application blocking or access from that device.</p>
    ${this.data.dns_progress?.running ? `<div class="banner" role="status">Checking ${this.data.dns_progress.completed} of ${this.data.dns_progress.total} resolver/list combinations…</div>` : ""}
    ${this.data.dns_progress?.issue ? `<div class="banner warning">${escape(this.data.dns_progress.issue)}</div>` : ""}
    ${!this.data.dns_settings?.enabled ? '<div class="banner warning">DNS observations are disabled. Enable them in Resolver settings.</div>' : ""}
    <div class="grid">${probes.map(([id, p]) => {
      const view = this.data.dns_views?.[id]?.[p.group_id || "household"];
      const label = !p.enabled ? "Disabled" : this.dnsLabel(view?.verdict);
      return `<ha-card><div class="row between"><h3>${escape(p.name)}</h3><span class="badge">${escape(label)}</span></div><p class="note">${p.domains.length} samples${p.seed ? " · Built-in list" : ""}${p.group_id ? " · " + escape(this.groupName(p.group_id)) : ""}</p><p class="note">${escape(view?.contexts?.map(c => c.source + ": " + c.resolver).join(" · ") || "No resolver discovered")}</p>${view?.issues?.length ? `<p class="note">${escape(view.issues.join(" · "))}</p>` : ""}<div class="row wrap">${this.button("Check now", "dns", id, !p.enabled || !this.data.dns_settings?.enabled || this.data.dns_progress?.running ? "disabled" : "")}${this.button("Results", "probe-results", id)}${this.button("Edit", "probe-edit", id)}</div></ha-card>`;
    }).join("")}</div><div class="spacer">${this.button("Check schedule", "probe-schedule")}</div></div></details>`;
  }
  dnsLabel(value) {
    return {open: "DNS resolves", blocked: "DNS blocked", partial: "DNS mixed", unknown: "Needs checking"}[value] || "Not checked";
  }
  categoryDetail(id, slug) {
    const g = this.data.groups.find(g => g.id === id);
    const c = g.categories.find(c => (c.slug || String(c.id)) === slug);
    this.open(`${g.name} · ${c.name}`,
      `<div class="row wrap"><span class="badge">${escape(this.categoryControlLabel(c))}</span></div><ul>${(c.reasons || []).filter(r => !/DNS|sample|comparison/i.test(r)).map(r => `<li>${escape(r)}</li>`).join("")}</ul><p class="note">${escape(c.scope || "Device traffic has not been tested")}. A DNS answer can coexist with an application-blocking rule.</p>
      <h3>Inherited protection</h3>${g.protection?.profiles?.length ? g.protection.profiles.map(p => `<p class="note">${escape(p.name)} · ${p.device_count} device(s) · SafeSearch: ${escape(p.safe_search.join(", ") || "None configured")} · ${p.exceptions} allowed domain(s)${g.protection.fresh ? "" : " · Last known"}</p>`).join("") : '<p class="note">No matching profile was confirmed.</p>'}
      <details class="section"><summary>Advanced DNS diagnostics from Home Assistant</summary><p class="note">These lookups do not test this person’s device or change filtering.</p><p>${escape(c.dns?.label || "Not checked")}</p><div class="row wrap spacer">${(c.dns?.lists || []).map(key => this.button(this.data.probes[key].name + " results", "probe-results", key, `data-group="${escape(id)}"`)).join("")}${this.button("Run HA DNS samples", "dns-group", id, this.data.dns_progress?.running ? "disabled" : "")}</div></details>
      <div class="row wrap spacer">${c.rules.map(r => this.button(this.data.rules.find(rule => rule.id === r)?.name || "Edit rule", "rule-edit", r)).join("")}${c.supported ? this.button("Add category rule", "category-rule", id, `data-category="${escape(c.slug)}"`) : ""}</div>`,
      this.button("Close", "close"), {kind: "category-detail"});
  }
  activity() {
    return `<ha-card><div class="row between card-top"><div><h2>Activity</h2><p class="lead">Changes and their individual results</p></div>${this.button("Browse history", "history")}${this.button("Sync now", "sync")}</div>${
      this.data.changes
        .slice(0, 40)
        .map(
          (c) =>
            `<div class="audit-row"><div class="row between"><div class="grow"><strong>${escape(words(c.action))}</strong><small>${escape(c.target_names.join(", "))}</small></div><span class="badge ${["failed", "partial"].includes(c.outcome) ? "red" : c.outcome === "pending" ? "amber" : ""}">${escape(this.changeOutcomeLabel(c))}</span></div><small>${escape(c.actor || "Administrator")} · ${this.time(c.requested_at, true)}${c.reason ? " · " + escape(c.reason) : ""}</small>${this.syncEvidenceHTML(c)}${this.timingHistoryHTML(c)}${this.historyChangeButton(c)}</div>`,
        )
        .join("") || '<div class="empty"><h3>No changes recorded</h3></div>'
    }<div class="settings"><h3>Administration</h3><p class="note">Integration ${escape(this.data.version)} · ${escape(this.data.sync)} · revision ${this.data.revision}. ${this.data.management ? "Gateway management enabled." : "Gateway management disabled."}</p>${this.data.issue ? `<div class="banner error">${escape(this.data.issue)}</div>` : ""}<div class="row wrap">${this.button("Updates", "updates")}${this.button("Gateway load", "gateway-health")}${this.button("Management", "management")}${this.button("Inspect recovery", "recovery")}${this.button("Manage access", "access")}${this.button("Export configuration", "export")}${this.button("Restore configuration", "import")}<a href="/config/integrations/integration/simplifi">Connection settings</a></div><p class="note">Timed exception expiry needs Home Assistant. Gateway schedules continue during an HA outage, but a temporary pause or allowance may last beyond its deadline.</p></div></ha-card>`;
  }
  setupForm() {
    this._setupDraft = {name:"", kind:"family", age:"", person:"", devices:[], schedules:[]};
    this._setupStep = 0;
    this.drawSetup();
  }
  drawSetup() {
    const d = this._setupDraft, step = this._setupStep;
    let body = `<div class="steps">${["Person", "Devices", "Schedules", "Review"].map((name,i) => `<span class="${step === i ? "active" : ""}">${i+1}. ${name}</span>`).join("")}</div><form>`;
    if (step === 0) body += `${this.select("Person or shared group", "group_id", [["", "Create a new person or group"], ...this.data.groups.filter(g => !g.archived).map(g => [g.id,g.name])], d.group_id || "")}${this.field("Name (new person/group only)", "name", d.name, "text", 'maxlength="100"')}${this.select("Kind (new only)", "kind", [["family", "Person"], ["thing", "Shared devices"]], d.kind)}${this.select("Age label (new only)", "age", [["", "No label"], ["child", "Child"], ["teen", "Teen"], ["adult", "Adult"]], d.age)}<p class="note">Existing people keep their settings, assignments, rules and allowances. Age is a label; it does not choose restrictions.</p>`;
    if (step === 1) {
      const devices = this.data.devices.filter(x => (!x.group || x.group === d.group_id) && this.data.managed_networks.includes(x.network));
      body += `<p>Select devices to assign. Devices owned by someone else must be reassigned from Devices first.</p><div class="list">${devices.map(x => `<label class="check"><input type="checkbox" name="devices" value="${escape(x.id)}" ${d.devices.includes(x.id) ? "checked" : ""}><span>${escape(x.name)}<small class="block">${escape(x.ip || x.mac)} · ${escape(this.data.networks[x.network]?.name || x.network)} · ${x.connected ? "Connected" : "Last known / offline"}</small></span></label>`).join("") || '<p class="note">No unassigned devices in managed networks. You can add devices later.</p>'}</div><p class="note">Unselected devices keep their current assignment. Assigning a device can release its unknown-device quarantine.</p>`;
    }
    if (step === 2) {
      const suggestions = [{name:"School nights", days:[0,1,2,3,6], start:"21:00", end:"07:00", overnight:true}, {name:"Weekend nights", days:[4,5], start:"22:00", end:"08:00", overnight:true}];
      body += `<p>Optional internet schedules. Nothing is selected automatically. Adjust times and start weekdays before reviewing.</p><p class="note">Times use ${escape(this.data.timezone)}. These rules block all internet for the group during each window; existing content rules still apply.</p>`;
      body += suggestions.map((suggestion,i) => {const chosen=d.schedules.find(r => r.name===suggestion.name), r=chosen || suggestion;return `<div class="settings">${this.check("Add " + r.name, "schedule_"+i, !!chosen)}<div class="row wrap">${dayNames.map((day,n) => `<label class="check"><input type="checkbox" name="days_${i}" value="${n}" ${r.days.includes(n) ? "checked" : ""}>${day}</label>`).join("")}</div><div class="form-grid">${this.field("Start", "start_"+i, r.start, "time")}${this.field("End", "end_"+i, r.end, "time")}</div>${this.check("Ends the next day", "overnight_"+i, r.overnight)}</div>`;}).join("");
    }
    if (step === 2 && !this.data.gateway_timezone_confirmed) body += this.check("I verified the UniFi timezone and recurring schedule behavior match " + this.data.timezone, "gateway_timezone_confirmed", !!d.gateway_timezone_confirmed);
    body += '</form>';
    this.open("Guided household setup", body, (step ? this.button("Back", "setup-back") : this.button("Cancel", "close")) + this.button(step===2 ? "Review setup" : "Next", "setup-next", "", "", "primary"), {kind:"setup-draft"});
  }
  captureSetup() {
    const f=this.form(); if (!f.reportValidity()) return false;
    const fd=new FormData(f), d=this._setupDraft;
    if (this._setupStep===0) {
      const group=fd.get("group_id") || undefined;
      if (group!==d.group_id) d.devices=[];
      Object.assign(d,{group_id:group,name:fd.get("name").trim(),kind:fd.get("kind"),age:fd.get("age")});
      if (!group && !d.name) {this.showError("Enter a name or select an existing person.");return false;}
    }
    if (this._setupStep===1) d.devices=fd.getAll("devices");
    if (this._setupStep===2) {
      d.schedules=[]; d.gateway_timezone_confirmed=fd.has("gateway_timezone_confirmed");
      for (const [i,name] of ["School nights","Weekend nights"].entries()) if (fd.has("schedule_"+i)) d.schedules.push({name,days:fd.getAll("days_"+i).map(Number),start:fd.get("start_"+i),end:fd.get("end_"+i),overnight:fd.has("overnight_"+i)});
    }
    return true;
  }
  async setupReview() {
    const configuration=JSON.parse(JSON.stringify(this._setupDraft));
    const result=await this.api("preview_setup", {configuration});
    this._setupStep=3;
    const schedules=result.rules.map(r => r.windows.map(w => `<li><strong>${escape(r.name)}</strong>: ${w.days.map(i => dayNames[i]).join(", ")} · ${escape(w.start)}–${escape(w.end)}${w.overnight ? " next day" : ""}</li>`).join("")).join("");
    this.open("Review household setup", `<h3>${result.existing_group ? "Update" : "Create"} ${escape(result.group.name)}</h3><p class="spacer">Assign ${result.devices.length} selected device${result.devices.length===1 ? "" : "s"}:</p><ul>${result.devices.map(d => `<li>${escape(d.name)}</li>`).join("") || '<li>No new assignments</li>'}</ul><h3>Internet schedules · ${escape(result.timezone)}</h3>${schedules ? `<ul>${schedules}</ul>` : '<p class="note">No new internet schedules.</p>'}<p class="note">${escape(result.note)}</p>${result.confirms_gateway_timezone ? '<p class="note">Save the gateway timezone/schedule verification you confirmed in the previous step.</p>' : ""}${result.assignment_releases_quarantine ? '<div class="banner warning">Assigning selected devices releases their unknown-device quarantine. The group’s existing restrictions and these schedules will apply.</div>' : ''}<p class="note">${result.management ? "Management is enabled. Saving applies these controls through the next gateway sync." : "Management is disabled. Saving stores intent; enable management separately when ready."}</p><form>${this.check("Confirm this person, device assignments and schedules", "confirm", false)}</form>`,this.button("Back", "setup-back") + this.button("Save setup", "submit", "", "", "primary"), {kind:"setup-review", revision:result.revision, configuration, preview_hash:result.preview_hash});
  }
  scopedAccess() {
    const d = this.data, controls = d.scope !== "read_only";
    return `<ha-card><div class="row between wrap card-top"><div><h2>Family controls</h2><p class="lead">${escape(words(d.scope))}${d.expires_at ? " · expires " + this.time(d.expires_at, true) : ""}</p></div>${this.button("Refresh", "refresh")}</div>${!d.management ? '<p class="note">Gateway management is disabled. Controls save intent only.</p>' : ''}<div class="grid">${d.groups.map(g => `<div class="settings"><h3>${escape(g.name)}</h3><p>${escape(this.accessLabel(g))}</p><small>${g.devices} assigned · ${g.connected} connected${g.expires_at ? " · until " + this.time(g.expires_at) : ""}</small>${this.continuousRules(g)}${controls ? `<div class="row spacer">${this.button("Internet controls", "control", g.id, this.disabledAttr())}${this.unblockButton(g)}</div>` : ""}</div>`).join("")}</div><h3 class="spacer">Rules</h3>${this.quarantineCard()}${d.rules.map(r => `<div class="audit-row"><div class="row between wrap"><div><strong>${escape(r.name)}</strong><p class="note">${escape(words(r.kind))} · ${r.enabled ? "Enabled" : "Disabled"}</p></div><div class="row wrap">${controls && (r.whole_rule_control || r.groups.length) ? this.button("Options", "rule-options", r.id, !r.enabled ? "disabled" : this.disabledAttr()) : ""}${controls && r.whole_rule_control ? this.button(r.enabled ? "Disable" : "Enable", "rule-toggle", r.id, this.disabledAttr()) : ""}</div></div></div>`).join("") || '<p class="note">No rules in your scope.</p>'}<p class="note">These states describe SimpliFi controls; other UniFi restrictions may also apply. Gateway confirmation is separate from testing traffic on a device. Account permissions are checked again for every action.</p></ha-card>`;
  }
  async accessView() {
    const result = await this.api("list_access_grants"), users = await this.api("access_users");
    this._access = {...result, users:users.users};
    const name = id => users.users.find(u => u.id === id)?.name || "Unavailable account";
    this.open("SimpliFi access", `<p>Grant an existing Home Assistant account access to selected people and networks.</p><p class="note">These grants apply only to SimpliFi actions and scoped status. They do not restrict the account elsewhere in Home Assistant, including ordinary entity visibility. Administrators already have full access.</p>${Object.entries(result.grants).map(([id,g]) => `<div class="audit-row"><div class="row between wrap"><div><strong>${escape(name(id))}</strong><p class="note">${escape(words(g.scope))} · ${g.all_groups ? "All current and future groups" : g.groups.map(x => escape(this.groupName(x))).join(", ") || "No group controls"}${g.networks.length ? " · Networks: " + g.networks.map(n => escape(this.data.networks?.[n]?.name || n)).join(", ") : ""}${g.expires_at ? " · expires " + this.time(g.expires_at, true) : " · no expiry"}</p></div><div class="row">${this.button("Edit", "access-edit", id)}${this.button("Revoke", "access-revoke", id, "", "danger")}</div></div></div>`).join("") || '<p class="spacer">No access grants.</p>'}<details class="spacer"><summary>Companion, Watch and scoped dashboard</summary><p class="note">Use this account's authenticated HA actions for Companion or Watch. Actions without a user context are rejected. For a limited native dashboard, add this manual card:</p><pre>type: custom:simplifi-card
entry_id: ${escape(this.config.entry_id)}
mode: access</pre><p class="note">Use an existing non-administrator account. A new grant does not create an account or issue a token.</p></details>`, this.button("Grant access", "access-new") + this.button("Close", "close"), {kind:"access", accessRevision:result.access_revision});
  }
  accessForm(id) {
    const g = this._access.grants[id] || {scope:"watch_rules", groups:[], networks:[], all_groups:false};
    this.open(id ? "Edit access grant" : "Grant SimpliFi access", `<form>${this.select("Home Assistant account", "user_id", [["", "Select an existing account"], ...this._access.users.map(u => [u.id, u.name])], id || "")}${this.select("Role", "scope", [["read_only", "Read-only status"], ["watch_rules", "Watch · existing rule and internet controls"], ["agent_controls", "Agent · controls plus household editing"]], g.scope)}<p class="note">Watch can pause, resume and extend internet restrictions, allow temporarily, and control existing rules. Agent can also edit people, assignments and rules within the selected scope. Connection, DNS, recovery and access administration stay administrator-only.</p><h3>People and shared groups</h3>${this.data.groups.map(x => `<label class="check"><input type="checkbox" name="groups" value="${escape(x.id)}" ${g.groups.includes(x.id) ? "checked" : ""}>${escape(x.name)}</label>`).join("")}${this.check("Include every current and future group", "all_groups", g.all_groups)}<h3>Whole-network scope</h3><p class="note">Network access allows network-wide rules, including devices outside the selected groups. Select only networks this account should control.</p>${this.data.managed_networks.map(n => `<label class="check"><input type="checkbox" name="networks" value="${escape(n)}" ${g.networks.includes(n) ? "checked" : ""}>${escape(this.data.networks?.[n]?.name || n)}</label>`).join("")}${this.field("Expires at (optional, this device's local time)", "expires_at", this.localDateValue(g.expires_at), "datetime-local")}${this.check("Confirm this account, role and target scope", "confirm", false)}</form>`, this.button("Cancel", "close") + this.button("Save grant", "submit", "", "", "primary"), {kind:"access-grant", accessRevision:this._access.access_revision});
  }
  localDateValue(value) {
    if (!value) return "";
    const date = new Date(value);
    return new Date(date.getTime() - date.getTimezoneOffset()*60000).toISOString().slice(0,16);
  }
  importForm() {
    this.open("Restore household configuration", `<p>A portable restore replaces people, groups, rules, assignments, DNS lists and settings. Gateway credentials stay on this Home Assistant.</p><p class="note">Disable management and clean up owned policies before saving a restore. Access grants are revoked and temporary exceptions are cleared. A local recovery snapshot is saved.</p><form><label class="field">Configuration export (.json, at most 2 MB)<input name="configuration_file" type="file" accept=".json,application/json" required></label></form>`, this.button("Cancel", "close") + this.button("Read file", "import-file", "", "", "primary"), {kind:"import-file"});
  }
  async importFile() {
    const file = this.form().querySelector('[name="configuration_file"]').files[0];
    if (!file || file.size > 2000000) throw new Error("Choose a JSON export no larger than 2 MB.");
    const configuration = JSON.parse(await file.text());
    const source = configuration.format === "simplifi" ? configuration.configuration : configuration;
    if (!source || !Array.isArray(source.networks) || !source.networks.length || source.networks.length > 200) throw new Error("This file does not contain a supported household configuration.");
    this._importDraft = {configuration, source};
    this.open("Map restored networks", `<p>Source: ${escape(source.controller)} · ${escape(source.site)}</p><p class="note">Choose where each old network's rules should apply. Device ownership is matched by MAC address, never by an old controller's device ID. Devices not seen yet wait for discovery.</p><form>${source.networks.map((n,i) => this.select("Old network: " + n, "network_" + i, [["", "Choose a managed network"], ...this.data.managed_networks.map(id => [id, this.data.networks[id]?.name || id])], "")).join("")}</form>`, this.button("Cancel", "close") + this.button("Preview restore", "import-preview", "", "", "primary"), {kind:"import-mapping"});
  }
  async importPreview() {
    const fd = new FormData(this.form()), mapping = {};
    this._importDraft.source.networks.forEach((n,i) => {const target=fd.get("network_"+i);if (!target) throw new Error("Map every source network before continuing.");mapping[n]=target;});
    const configuration = this._importDraft.configuration;
    const result = await this.api("preview_import", {configuration, network_mapping:mapping});
    const devices = (items, empty) => items.map(d => `<li>${escape(d.name)} · ${escape(d.mac)} → ${escape(configuration.configuration?.groups?.[d.group]?.name || configuration.groups?.[d.group]?.name || "Unassigned")}</li>`).join("") || `<li>${empty}</li>`;
    this.open("Review household restore", `<div class="review"><p><strong>${result.groups} groups · ${result.rules} rules</strong></p><p>Timezone: ${escape(result.timezone)} · Quarantine: ${result.quarantine ? "enabled when management resumes" : "off"}</p><p>${Object.entries(result.mapping).map(([old,id]) => escape(old) + " → " + escape(this.data.networks[id]?.name || id)).join("<br>")}</p></div><h3>Matched devices</h3><ul>${devices(result.matched, "None")}</ul><h3>Waiting for discovery</h3><ul>${devices(result.pending, "None")}</ul>${result.dns_resolvers_reset ? '<div class="banner warning">The source connection differs. Explicit DNS resolvers will be reset; review them on this network after restoring.</div>' : ""}<p class="note">${escape(result.note)}</p><form>${this.check("Replace this household with the reviewed configuration", "confirm", false)}</form>`, this.button("Cancel", "close") + this.button("Restore household", "submit", "", "", "primary"), {kind:"import-review", configuration, network_mapping:mapping, preview_hash:result.preview_hash, revision:result.revision});
  }
  timingHistoryHTML(change) {
    const timing = change.details?.timing;
    if (!timing) {
      if (change.details && "expires_at" in change.details) {
        return `<p class="note">Recorded end time changed from ${this.time(change.details.previous_deadline, true, true)} to ${this.time(change.details.expires_at, true, true)}. Requested timing mode was not recorded.</p>`;
      }
      const timed = /^(pause_internet|allow_internet|suspend_rule|allow_rule|suspend_quarantine|extend_pause|extend_rule_suspension|extend_quarantine_suspension|resume_internet|end_allowance|resume_rule|end_rule_allowance|resume_quarantine|edit_allowance|set_access_grant|revoke_access_grant|unblock_group|end_group_unblock|extend_group_unblock)$/;
      return timed.test(change.action) ? '<p class="note">Deadline details were not recorded for this older change.</p>' : "";
    }
    if (timing.version !== 1) return '<p class="note">Deadline details require a newer dashboard.</p>';
    const time = value => {
      if (!value) return "No deadline · until ended";
      try {
        return escape(new Intl.DateTimeFormat(this._hass?.locale?.language || "en-GB", {
          timeZone: timing.timezone, year:"numeric", month:"short", day:"numeric",
          hour:"2-digit", minute:"2-digit", second:"2-digit", timeZoneName:"shortOffset",
        }).format(new Date(value)));
      } catch { return "Deadline unavailable"; }
    };
    const request = timing.request;
    const labels = {
      duration_minutes: `${escape(request.value)} minutes from request`,
      extend_minutes: `Extend by ${escape(request.value)} minutes from previous deadline`,
      extend_group_minutes: `Extend every timed group allowance by ${escape(request.value)} minutes from the latest deadline`,
      expires_at: `End at ${time(request.value)}`,
      next_window_end: "Until applicable schedule windows end",
      indefinite: "No deadline · until ended",
      default: "Default timing for this control",
      remove: "End the selected temporary control",
      implicit: "Temporary controls updated by this change",
    };
    const kinds = {pause:"Internet pause", internet_allow:"Internet allowance", suspension:"Rule suspension", rule_allow:"Rule allowance", quarantine_suspension:"Quarantine suspension", access_grant:"Access grant"};
    const record = value => value === null ? "No saved temporary control" : `${time(value.expires_at)}${value.captured_rules?.length ? "<br>Captured restrictions: " + value.captured_rules.map(r=>escape(r.name)).join(", ") : ""}`;
    return `<details class="spacer" data-readback-key="timing:${escape(change.id)}"><summary>Saved timing details</summary><p class="note">Requested: ${labels[request.mode] || "Timing mode unavailable"}<br>Saved timezone: ${escape(timing.timezone)}</p>${timing.changes.map(row=>{
      const r = row.after || row.before;
      const names = [r.group_name, r.rule_name, r.user_id].filter(Boolean);
      return `<div class="audit-row"><strong>${escape(kinds[r.kind] || words(r.kind))}${names.length ? " · " + escape(names.join(" · ")) : ""}</strong><p class="note">Before: ${record(row.before)}<br>After: ${record(row.after)}</p></div>`;
    }).join("") || '<p class="note">No saved deadlines or temporary controls changed.</p>'}<p class="note">These are saved settings. Gateway sync results and device tests are separate evidence.</p></details>`;
  }
  historyChangeButton(change) {
    if ("dns_revision" in change || "access_revision" in change ||
        !["pending", "applying", "applied", "failed", "partial", "superseded", "saved_management_disabled"].includes(change.outcome)) return "";
    const label = "View sync results · " + words(change.action) + " · " + this.time(change.requested_at, true);
    return `<div class="spacer">${this.button("View sync results", "history-change", change.id, `aria-label="${escape(label)}"`)}</div>`;
  }
  syncEvidenceHTML(change) {
    const e = change.sync_evidence;
    if (!e) return "";
    if (!e.latest) return '<p class="note">No retained sync result for this revision.</p>';
    const when = e.latest.finished_at || e.latest.started_at;
    const label = e.latest_confirmed
      ? (["failed", "partial"].includes(change.outcome) ? "Later settings readback confirmed" : "Settings readback confirmed")
      : e.latest.outcome === "applied" ? "Readback confirmation incomplete"
      : e.latest.outcome === "running" ? "Latest sync in progress"
      : "Latest sync: " + words(e.latest.outcome);
    return `<p class="note">${escape(label)} · ${this.time(when, true, true)} · revision ${escape(e.revision)}</p>${!e.latest_confirmed && e.last_confirmed_at ? `<p class="note">Last confirmed readback: ${this.time(e.last_confirmed_at, true, true)}</p>` : ""}${e.latest_confirmed && ["failed", "partial"].includes(change.outcome) ? '<p class="note">The original attempt result is retained. Later readback does not prove an expired temporary control ran.</p>' : ""}`;
  }
  changeOutcomeLabel(change) {
    return change.outcome === "failed"
      ? change.sync_evidence?.latest_confirmed ? "Original attempt failed" : "Attempt failed"
      : words(change.outcome);
  }
  async historyView(kind = "changes", before, outcome = "", changeId) {
    const result = await this.api("activity_history", {kind, limit:30,
      ...(before ? {before_id:before} : {}), ...(outcome ? {outcome} : {}),
      ...(changeId ? {change_id:changeId} : {})});
    this._historyKind = kind; this._historyNext = result.next_cursor;
    this._historyOutcome = outcome; this._historyChangeId = changeId;
    const options = kind === "sync"
      ? [["applied", "Applied"], ["management_disabled", "Management disabled"], ["failed", "Failed"], ["interrupted", "Interrupted"]]
      : [["applied", "Applied"], ["failed", "Failed attempt"], ["pending", "Pending"], ["recovery_recorded", "Recovery recorded"]];
    let evidence = "";
    if (result.change) {
      const c = result.change, latest = result.latest;
      evidence = `<section class="review"><h3>${escape(words(c.action))}</h3><p>${escape(c.actor || "Administrator")} · ${this.time(c.requested_at, true)}</p>
        <p>Original result: <strong>${escape(c.outcome === "failed" ? "Attempt failed" : words(c.outcome))}</strong></p>
        ${this.timingHistoryHTML(c)}
        ${latest ? `<p>Latest sync for these settings: <strong>${escape(words(latest.outcome))}</strong> · ${this.time(latest.finished_at || latest.started_at, true)}</p>` : '<p>No sync results are retained for this change. This does not confirm success.</p>'}
        <p class="note">Only syncs for this saved change are shown. Earlier failed attempts stay in the record. A later successful sync confirms the settings in effect then; it does not prove an expired temporary action took effect or that device traffic was tested.</p></section>`;
    }
    const rows = result.items.map(r => `<div class="audit-row"><div class="row between"><strong>${escape(kind === "sync" ? "Sync · revision " + r.revision : words(r.action))}</strong><span class="badge">${escape(kind === "changes" ? this.changeOutcomeLabel(r) : words(r.outcome))}</span></div><small>${this.time(r.started_at || r.requested_at, true)}${r.actor ? " · " + escape(r.actor) : ""}</small>
      ${kind === "sync" ? `<p class="note">${r.duration_ms ?? "?"} ms · ${r.owned_policies ?? "?"} owned policies · Write attempts: ${r.writes?.create || 0} creates, ${r.writes?.update || 0} updates, ${r.writes?.delete || 0} deletes</p>` : r.reason ? `<p class="note">${escape(r.reason)}</p>` : ""}
      ${r.issue ? `<p class="note">${escape(r.issue)}</p>` : ""}${kind === "changes" ? this.syncEvidenceHTML(r) + this.timingHistoryHTML(r) + this.historyChangeButton(r) : ""}</div>`).join("");
    this.open(changeId ? "Sync results" : "Activity history", `${evidence}<form><div class="form-grid">${changeId ? "" : this.select("History", "history_kind", [["changes", "Household changes"], ["sync", "Sync runs"]], kind)}${this.select("Outcome", "history_outcome", [["", "All outcomes"], ...options], outcome)}</div></form>
      <div class="list">${rows || '<p>No matching records.</p>'}</div><p class="note">${kind === "sync" ? "Every retained run, including failures and interrupted restarts. At most 10,000 runs within the configured audit retention; older runs expire." : "Protected household change history within audit retention, at most 1,000 records."} Gateway confirmation is separate from testing traffic on a device.</p>`,
      (changeId ? this.button("All history", "history") : "") + this.button("Newest", "history-newest", "", "", "grow") + (result.next_cursor ? this.button("Older", "history-older") : "") + this.button("Close", "close"), {kind:"history"});
  }
  async recoveryView() {
    const result = await this.api("preview_recovery");
    this._recovery = result;
    this.open("Gateway recovery", `<p class="note">A complete controller read was obtained at ${this.time(result.observed_at, true)}. Reviewing this evidence does not write a gateway policy.</p>${result.drift.map(r => `<div class="banner warning">${escape(r.message)} Policy ${escape(r.policy_id)}</div>`).join("")}${result.operations.map(r => `<div class="audit-row"><strong>${escape(words(r.action))} · revision ${r.revision}</strong><small>${this.time(r.created_at, true)} · ${escape(r.operation_id)}</small><p class="note">${escape(r.message)}</p>${r.candidate_id || r.can_close_absent || r.can_close_not_applied ? this.button("Review resolution", "recover-operation", r.operation_id) : ""}<details><summary>Recorded request</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${escape(JSON.stringify(r.requested_policy || r.previous_policy, null, 2))}</pre></details></div>`).join("") || (result.drift.length ? "" : '<p>No unresolved operations or ownership drift were found.</p>')}<p class="note">Names alone never establish ownership. Changed or duplicate policies stay frozen. Recheck after a delayed response; never close an absent or unchanged request while UniFi may still be processing it.</p>`, this.button("Recheck", "recovery") + this.button("Close", "close"), {kind:"recovery", revision:result.revision});
  }
  recoveryForm(id) {
    const row = this._recovery.operations.find(r => r.operation_id === id);
    const attach = Boolean(row.candidate_id), unchanged = Boolean(row.can_close_not_applied);
    const decision = attach ? "attach" : unchanged ? "confirm_not_applied" : "confirm_absent";
    const finished = unchanged ? "I independently confirmed the original update or delete finished without changing this policy" : "I independently confirmed the original UniFi request has finished without creating a policy";
    this.open(attach ? "Attach confirmed policy" : unchanged ? "Confirm request ended without a change" : "Confirm request finished without a policy", `<p>${escape(row.message)}</p>${attach ? `<p class="note">Policy ID: ${escape(row.candidate_id)}</p>` : `<div class="banner warning">This controller read cannot prove a timed-out request has finished. Check the original request in UniFi independently before continuing. ${unchanged ? "An incorrect confirmation can let a delayed request override your newer settings." : "An incorrect confirmation can create a duplicate policy."}</div>`}${unchanged ? `<p class="note">Policy ID: ${escape(row.policy_id)}</p>` : ""}<form>${!attach ? this.check(finished, "request_finished", false) : ""}${this.field("How was this checked?", "reason", "", "text", 'required maxlength="300"')}${this.check("Confirm this resolution and replan current saved intent", "confirm", false)}</form>`, this.button("Cancel", "close") + this.button("Record resolution", "submit", "", "", "primary"), {kind:"resolve-operation", row, decision, revision:this._recovery.revision});
  }

  async updatesView() {
    this.drawUpdates(await this.api("update_status"));
  }
  async gatewayHealthView() {
    const request = this._healthRequest = (this._healthRequest || 0) + 1;
    this.open("Gateway load", '<p role="status">Reading the latest device samples…</p>', this.button("Close", "close"), {kind:"gateway-health"});
    try {
      const view = await this.api("gateway_health", {refresh:true});
      if (request === this._healthRequest && this._modal?.kind === "gateway-health") this.drawGatewayHealth(view);
    } catch (error) {
      if (request === this._healthRequest && this._modal?.kind === "gateway-health") this.open("Gateway load", `<div class="banner error" role="alert">${escape(error.message || String(error))}</div>`, this.button("Retry", "gateway-health") + this.button("Close", "close"), {kind:"gateway-health"});
    }
  }
  drawGatewayHealth(h) {
    const value = (v, suffix = "") => v == null ? "Unknown" : escape(String(v)) + suffix;
    const uptime = v => v == null ? "Unknown" : `${Math.floor(v / 86400)}d ${Math.floor(v % 86400 / 3600)}h ${Math.floor(v % 3600 / 60)}m`;
    const r = h.requests;
    this.open("Gateway load", `${h.simulation ? '<div class="banner warning">Offline simulator · fictional device samples. No controller requests are sent.</div>' : ""}<p class="note">${escape(h.scope)}</p>${h.issue ? `<div class="banner warning">${escape(h.issue)}</div>` : ""}<p class="note spacer">Snapshot read: ${h.read_at ? escape(this.time(h.read_at, true, true)) : "Not read"}. ${h.refresh_after_seconds ? `Device reads are cached for another ${escape(h.refresh_after_seconds)} seconds.` : "Refresh to read again."} Status and sample ages are as of this snapshot.</p>${h.capped ? `<div class="banner warning">Showing ${h.returned_devices} of ${h.total_devices} devices; the ${h.device_limit}-device safety limit was reached.</div>` : ""}<div class="section"><h3>Device samples</h3>${h.devices.map(d => `<div class="section"><div class="row between wrap"><strong>${escape(d.name)}</strong><span class="badge ${d.fresh ? "blue" : "amber"}">${d.fresh ? (d.status === "partial" ? "Partial sample" : "Sample available") : escape(words(d.status))}</span></div><p class="note">${escape(d.model)} · ${escape(words(d.state.toLowerCase()))}${d.gateway ? " · Gateway" + (d.gateway_source === "ha_unifi_inventory" ? " (HA UniFi inventory)" : "") : d.controller ? " · Controller" : ""}</p><p>CPU ${value(d.cpu_pct, "%")} · Memory ${value(d.memory_pct, "%")}</p><p class="note">Load (1 / 5 / 15 min): ${value(d.load_1)} / ${value(d.load_5)} / ${value(d.load_15)}<br>Uptime: ${uptime(d.uptime_seconds)}<br>Sample: ${d.sampled_at ? escape(this.time(d.sampled_at, true, true)) + ` · ${value(d.sample_age_seconds, "s")} old` : "Timestamp unknown"}</p>${d.issue ? `<p class="note">${escape(d.issue)}</p>` : ""}</div>`).join("") || '<p class="note">No device samples available.</p>'}</div><div class="section"><h3>SimpliFi controller traffic · last 5 minutes</h3>${r ? `<p>${r.requests} requests · ${r.failures} failures · ${r.retries} retries · ${r.rate_limited} rate limited</p><p class="note">${r.in_flight} in flight · peak ${r.peak_in_flight} · mean ${value(r.mean_ms, " ms")} · max ${value(r.max_ms, " ms")}<br>Window coverage: ${r.observed_seconds}s of ${r.window_seconds}s. Counts reset on reload.</p><p class="note">${escape(r.scope)}</p><div style="overflow-x:auto"><table class="health-table"><caption>Requests by endpoint</caption><thead><tr><th scope="col">Endpoint</th><th scope="col">Requests</th><th scope="col">Failures</th><th scope="col">Retries</th></tr></thead><tbody>${r.endpoints.map(e => `<tr><th scope="row">${escape(e.method)} ${escape(e.endpoint)}</th><td>${e.requests}</td><td>${e.failures}</td><td>${e.retries}</td></tr>`).join("")}</tbody></table></div>` : '<p class="note">Request accounting unavailable.</p>'}</div>`, this.button("Refresh snapshot", "gateway-health") + this.button("Close", "close"), {kind:"gateway-health"});
  }
  drawUpdates(u) {
    this._updates = u;
    this.open("SimpliFi updates", `<p><strong>Installed ${escape(u.installed)}</strong></p><p>Manage releases in HACS. The integration and its dashboard card are updated together; restart Home Assistant when prompted.</p>${u.hacs_loaded ? '<p><a href="/hacs">Open HACS</a></p>' : '<p class="note">HACS is not loaded. For a manual installation, replace the integration folder with a reviewed release and restart Home Assistant.</p>'}<p class="note">Release availability is shown in HACS. SimpliFi does not need a GitHub token.</p>${u.legacy_attention ? `<div class="banner warning">${escape(u.legacy_attention)}</div>` : ""}`, this.button("Close", "close"), {kind:"updates"});
  }

  async click(event) {
    const target = event.composedPath().find((n) => n?.dataset?.action);
    if (!target || target.disabled) return;
    // Retain the actual invoker even when pointer activation does not focus it.
    if (target.tagName === "BUTTON") target.focus?.({ preventScroll: true });
    const action = target.dataset.action,
      id = target.dataset.id;
    try {
      if (action === "coexistence") { this.otherPolicies(id); return; }
      if (action === "policy-refresh") { await this.refresh(); this.otherPolicies(id); return; }
      if (action === "policy-more") { this._policyLimit = (this._policyLimit || 50) + 50; this.updatePolicyList(); return; }
      if (action === "updates") { await this.updatesView(); return; }
      if (action === "gateway-health") { await this.gatewayHealthView(); return; }
      if (action === "refresh") {
        await this.refresh();
        return;
      }
      if (action === "close") {
        this.close();
        return;
      }
      if (
        action === "group-new" ||
        action === "thing-new" ||
        action === "group-edit"
      ) {
        this.groupForm(
          action === "group-edit"
            ? this.data.groups.find((g) => g.id === id)
            : { kind: action === "thing-new" ? "thing" : "family", name: "" },
        );
        return;
      }
      if (action === "detail") {
        this.detail(id);
        return;
      }
      if (action === "control") {
        this.control(id);
        return;
      }
      if (action === "quick") {
        const data = { group_id: id };
        if (target.dataset.duration)
          data.duration_minutes = Number(target.dataset.duration);
        this.confirm(
          target.textContent.trim(),
          target.dataset.service,
          data,
          `${this.groupName(id)} · ${target.textContent.trim()}. Existing content restrictions still apply.`,
        );
        return;
      }
      if (action === "assign-group") {
        this.assignGroup(id);
        return;
      }
      if (action === "allowance-edit") {
        this.allowanceForm(id);
        return;
      }
      if (action === "device-forget") {
        const d = this.data.devices.find(d => d.id === id), revision = this._modal?.revision ?? this.data.revision;
        this.confirm("Forget " + d.name, "forget_device", {device_id:id, confirm:true}, `Remove this device's assignment and quarantine exclusion from SimpliFi. If it is still present on a managed network, discovery will add it again as unassigned${this.data.quarantine ? " and quarantine it" : ""}. Its person's restrictions will no longer apply. This does not delete the client from UniFi.`);
        this._modal.revision = revision;
        return;
      }
      if (action === "device") {
        this.deviceForm(id);
        return;
      }
      if (action === "person-rule") {
        const kind = target.dataset.kind;
        this.ruleForm({name: kind === "internet" ? "Internet schedule" : "", kind, groups:[id], targets:[], target_names:[], windows:kind === "internet" ? [{name:"Bedtime",days:[0,1,2,3,4],start:"21:00",end:"07:00",overnight:true,all_day:false}] : [], enabled:true});
        return;
      }
      if (action === "person-protection") { this.personProtection(id); return; }
      if (action === "profile-edit") { this.profileForm(id); return; }
      if (action === "rule-new" || action === "rule-edit") {
        this.ruleForm(
          action === "rule-edit"
            ? this.data.rules.find((r) => r.id === id)
            : null,
        );
        return;
      }
      if (action === "category") {
        this.categoryDetail(id, target.dataset.category);
        return;
      }
      if (action === "category-rule") {
        const c = this.data.groups.find((g) => g.id === id).categories.find((c) => c.slug === target.dataset.category);
        this.ruleForm({name: c.name, kind: "category", groups: [id], targets: [c.id], target_names: [c.name], windows: [], enabled: true});
        return;
      }
      if (action === "rules-filter") {
        this._ruleGroup = id;
        target.blur();
        this.render();
        return;
      }
      if (action === "rule-toggle") {
        const r = this.data.rules.find((r) => r.id === id);
        this.confirm(
          `${r.enabled ? "Disable" : "Enable"} ${r.name}`,
          "set_rule_enabled",
          { rule_id: id, enabled: !r.enabled },
          `${this.ruleScope(r)} · ${(r.target_names || r.targets).join(", ") || "All internet"}`,
        );
        return;
      }
      if (action === "rule-options") {
        this.ruleOptions(id, target.dataset.group);
        return;
      }
      if (action === "group-unblock") {
        this.unblockForm(id);
        return;
      }
      if (action === "rule-delete") {
        const r = this.data.rules.find((r) => r.id === id);
        this.confirm(
          "Delete rule",
          "delete_rule",
          { rule_id: id },
          `Remove “${r.name}” and its managed restrictions from ${this.ruleScope(r)}.`,
        );
        return;
      }
      if (action === "group-delete") {
        this.confirm(
          "Delete group",
          "delete_group",
          { group_id: id, confirm: true },
          `Remove ${this.groupName(id)} and unassign its devices. Unassigned devices may be quarantined.`,
        );
        return;
      }
      if (action === "quarantine-control") {
        const actions = {
          pause: ["suspend_quarantine", {duration_minutes:30}],
          indefinite: ["suspend_quarantine", {indefinite:true}],
          resume: ["resume_quarantine", {}],
          extend: ["extend_quarantine_suspension", {duration_minutes:30}],
        };
        if (!actions[id]) throw new Error("Unknown quarantine action");
        const [service, payload] = actions[id];
        this.confirm(target.textContent.trim(), service, payload,
          "This affects unassigned devices on all managed networks. Timed pauses need Home Assistant running to end them.");
        return;
      }
      if (action === "quarantine") {
        this.quarantine();
        return;
      }
      if (action === "management") {
        this.management();
        return;
      }
      if (action === "sync") {
        await this.perform(
          "sync_now",
          {},
          "Refresh gateway observations",
          this.data.revision,
        );
        return;
      }
      if (action === "dns" || action === "dns-all" || action === "dns-group") {
        await this.perform(
          "check_dns",
          action === "dns" ? { probe_id: id } : action === "dns-group" ? { group_id: id } : {},
          "DNS check",
          this.data.revision,
        );
        return;
      }
      if (action === "dns-settings") {
        this.dnsSettings();
        return;
      }
      if (action === "probe-restore") {
        await this.perform("restore_probe", {probe_id: id}, "Restore default samples", this.data.revision);
        return;
      }
      if (action === "probe-new" || action === "probe-edit") {
        this.probeForm(
          id && this.data.probes[id] ? { ...this.data.probes[id], id } : {},
        );
        return;
      }
      if (action === "probe-results") {
        this.probeResults(id, target.dataset.group || "household");
        return;
      }
      if (action === "probe-schedule") {
        this.probeSchedule();
        return;
      }
      if (action === "probe-delete") {
        this.confirm(
          this.data.probes[id].seed ? "Disable sample list" : "Delete DNS check",
          "delete_probe",
          { probe_id: id },
          `${this.data.probes[id].seed ? "Disable" : "Remove"} ${this.data.probes[id].name} and its observations. Gateway policies are unaffected.`,
        );
        return;
      }
      if (action === "setup") { this.setupForm(); return; }
      if (action === "setup-back") { if (this._setupStep<3) this.captureSetup(); this._setupStep=Math.max(0,this._setupStep-1);this.drawSetup();return; }
      if (action === "setup-next") {
        if (!this.captureSetup()) return;
        if (this._setupStep===2) await this.setupReview(); else {this._setupStep++;this.drawSetup();}
        return;
      }
      if (action === "access") { await this.accessView(); return; }
      if (action === "access-new" || action === "access-edit") { this.accessForm(id); return; }
      if (action === "access-revoke") {
        this.confirm("Revoke SimpliFi access", "revoke_access_grant", {user_id:id, confirm:true, expected_access_revision:this._access.access_revision}, "This account will immediately lose its SimpliFi grant. Its existing Home Assistant account remains active."); return;
      }
      if (action === "history") {
        await this.historyView(); return;
      }
      if (action === "history-change") {
        await this.historyView("sync", undefined, "", id); return;
      }
      if (action === "history-newest") {
        await this.historyView(this._historyKind, undefined, this._historyOutcome, this._historyChangeId); return;
      }
      if (action === "history-older") {
        await this.historyView(this._historyKind, this._historyNext, this._historyOutcome, this._historyChangeId); return;
      }
      if (action === "recovery") {
        await this.recoveryView(); return;
      }
      if (action === "recover-operation") {
        this.recoveryForm(id); return;
      }
      if (action === "import") { this.importForm(); return; }
      if (action === "import-file") { await this.importFile(); return; }
      if (action === "import-preview") { await this.importPreview(); return; }
      if (action === "export") {
        const result = await this.api("export_configuration");
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(result.configuration, null, 2)], {
            type: "application/json",
          }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = "simplifi-configuration.json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return;
      }
      if (action === "rule-next" || action === "rule-back") {
        if (action === "rule-next" && !this.captureRule()) return;
        this._step += action === "rule-next" ? 1 : -1;
        this.drawRule();
        return;
      }
      if (action === "window-add") {
        this.captureRule(false);
        this._draft.windows.push({
          name: "",
          days: [0, 1, 2, 3, 4],
          start: "21:00",
          end: "07:00",
          overnight: true,
          all_day: false,
        });
        this.drawRule();
        return;
      }
      if (action === "window-remove") {
        this.captureRule(false);
        this._draft.windows.splice(Number(id), 1);
        this.drawRule();
        return;
      }
      if (action === "catalogue-search") {
        await this.catalogue();
        return;
      }
      if (action === "submit") {
        await this.submit();
        return;
      }
    } catch (error) {
      this.showError(error.message || String(error));
    }
  }
  input(event) {
    const el = event.target;
    if (el.dataset.search === "policies") { this._policyQuery = el.value; this._policyLimit = 50; this.updatePolicyList(); return; }
    if (el.dataset.search === "devices") {
      this._query = el.value;
      const list = this.shadowRoot.querySelector("#device-list");
      const rows = this.deviceRows();
      this.shadowRoot.querySelector("#device-count").textContent = `${rows.length} of ${this.data.devices.length} devices${this.data.fresh ? "" : " · observations are not current"}`;
      list.innerHTML =
        rows.map((d) => this.deviceRow(d)).join("") ||
        '<p class="muted">No matching devices.</p>';
    }
  }
  change(event) {
    const el = event.target;
    if (el.dataset.policyFilter) { this[el.dataset.policyFilter === "group" ? "_policyGroup" : "_policyMode"] = el.value; this._policyLimit = 50; this.updatePolicyList(); return; }
    if (["owner", "network", "connection", "presence"].includes(el.dataset.filter)) {
      this[({owner:"_filter", network:"_networkFilter", connection:"_connectionFilter", presence:"_presenceFilter"})[el.dataset.filter]] = el.value;
      el.blur();
      this.render();
    }
    if (["history_kind", "history_outcome"].includes(el.name)) {
      const form = this.form();
      this.historyView(form.elements.history_kind?.value || this._historyKind, undefined, el.name === "history_kind" ? "" : form.elements.history_outcome.value, el.name === "history_kind" ? undefined : this._historyChangeId).catch(e => this.showError(e.message));
      return;
    }
    if (el.name === "dns_context") {
      this.probeResults(this._modal.id, el.value);
      return;
    }
    if (el.name === "rule_kind" && !this._draft.id) {
      this._draft.kind = el.value;
      this._draft.targets = [];
      this._draft.target_names = [];
      this._draft.name = this.form().elements.name.value;
      this.drawRule();
    }
    if (el.name === "rule_scope" && !this._draft.id) {
      this._draftScope = el.value;
      this._draft.groups = [];
      this._draft.networks = [];
      this.drawRule();
    }
    if (el.name === "schedule_mode") {
      this.captureRule(false);
      this.drawRule();
    }
  }
  open(title, body, footer = "", modal = {}) {
    this._modal = modal;
    this._modal.revision ??= this.data.revision;
    this._modal.dnsRevision ??= this.data.dns_revision;
    const dialog = this.shadowRoot.querySelector("dialog");
    if (!dialog.open) {
      this._focusBefore = this.shadowRoot.activeElement;
      this._focusKeyBefore = this._focusBefore?.tagName === "BUTTON"
        ? { ...this._focusBefore.dataset } : null;
    }
    dialog.querySelector(".dialog-shell").innerHTML =
      `<div class="dialog-header"><h2 id="dialog-title">${escape(title)}</h2><button type="button" class="quiet" data-action="close" aria-label="Close dialog">${icon("mdi:close")}</button></div><div class="dialog-body"><div id="form-error" role="alert"></div>${body}</div>${footer ? `<div class="dialog-footer">${footer}</div>` : ""}`;
    if (!dialog.open) dialog.showModal();
    else dialog.querySelector(".dialog-body").scrollTop = 0;
    queueMicrotask(() =>
      dialog
        .querySelector(
          'input,select,textarea,button[data-action="submit"],button[data-action="close"]',
        )
        ?.focus(),
    );
  }
  close() {
    this.shadowRoot.querySelector("dialog").close();
    this._modal = null;
    this.render();
  }
  form() {
    return this.shadowRoot.querySelector("dialog form");
  }
  field(label, name, value = "", type = "text", extra = "") {
    return `<label class="field">${escape(label)}<input name="${name}" type="${type}" value="${escape(value)}" ${extra}></label>`;
  }
  select(label, name, rows, value, disabled = false) {
    return `<label class="field">${escape(label)}<select name="${name}" ${disabled ? "disabled" : ""}>${choices(rows, value)}</select></label>`;
  }
  check(label, name, checked = false) {
    return `<label class="check"><input name="${name}" type="checkbox" ${checked ? "checked" : ""}>${escape(label)}</label>`;
  }
  showError(message) {
    const el = this.shadowRoot.querySelector("#form-error");
    if (this._modal && el) {
      el.className = "error-text";
      el.textContent = message;
      el.scrollIntoView({ block: "nearest" });
    } else {
      this._error = message;
      this.render();
    }
  }
  confirm(title, service, data, message) {
    this.open(
      title,
      `<p>${escape(message)}</p><p class="note">${["set_access_grant", "revoke_access_grant"].includes(service) ? "This changes SimpliFi permissions only; it does not write gateway policies." : ["delete_probe", "restore_probe"].includes(service) ? "This changes DNS observations only." : this.data.simulation ? "This affects the simulator only." : !this.data.management ? "Gateway management is disabled. This will save intent only." : "The gateway will apply the change after it is saved."}</p>`,
      this.button("Cancel", "close") +
        this.button("Confirm", "submit", "", "", "primary"),
      { kind: "confirm", service, payload: data, title },
    );
  }
  detail(id, category) {
    const g = this.data.groups.find((g) => g.id === id);
    const rules = this.data.rules.filter(
      (r) =>
        (r.groups.includes(id) || r.affected_groups?.includes(id)) &&
        (category === undefined ||
          (r.kind === "category" && r.targets.includes(category))),
    );
    const start = Date.parse(this.data.day_start),
      duration = Date.parse(this.data.day_end) - start;
    const timeline = g.timeline.filter(
      (t) => category === undefined || rules.some((r) => r.id === t.rule_id),
    );
    const body = `<div class="status ${g.state}">${escape(this.accessLabel(g))}</div><p class="note">${escape(g.reason)}${g.expires_at ? " · until " + this.time(g.expires_at) : ""}</p><div class="actions">${this.personActions(g)}</div>${this.continuousRules(g, rules.map(r => r.id))}<div class="section"><h3>Timed windows today · ${escape(this.data.timezone)}</h3><div class="timeline">${timeline.map((t) => `<button class="time-row" data-action="rule-edit" data-id="${escape(t.rule_id)}" aria-label="${escape(t.name + " " + this.timelineTime(t.start) + " to " + this.timelineEnd(t.end))}"><span class="time-bar" style="left:${Math.max(0, ((Date.parse(t.start) - start) / duration) * 100)}%;width:${Math.min(100, ((Date.parse(t.end) - Date.parse(t.start)) / duration) * 100)}%"></span><span class="time-label">${escape(t.name)} · ${this.timelineTime(t.start)}–${this.timelineEnd(t.end)}${t.lifted_now ? " · exception now" : ""}</span></button>`).join("") || '<p class="muted">No timed restrictions today.</p>'}</div><div class="time-axis"><span>00:00</span><span>${this.timelineMiddle()}</span><span>24:00</span></div><p class="note">${this.clockChangeDay ? "Clock change today: UTC offsets distinguish repeated times. " : ""}Projected windows; temporary exceptions and confirmed gateway state are shown separately.</p></div><div class="section"><h3>Rules</h3><div class="list">${rules.map((r) => `<div class="list-item"><div class="grow"><strong>${escape(r.name)}</strong><small>${escape(this.scheduleLabel(r))}</small></div>${this.button("Edit", "rule-edit", r.id)}${this.button(r.networks?.length ? "Network options" : "Options for " + g.name, "rule-options", r.id, (!r.enabled ? "disabled" : this.disabledAttr()) + (r.groups.includes(id) ? ` data-group="${escape(id)}"` : ""))}</div>`).join("") || '<p class="muted">No matching rules.</p>'}</div></div><div class="section"><h3>Devices</h3><div class="list">${
      this.data.devices
        .filter((d) => d.group === id)
        .map((d) => this.deviceRow(d))
        .join("") ||
      '<p class="muted">Assign a device to start using these controls.</p>'
    }</div></div>`;
    this.open(g.name, body, this.button("Close", "close"), {
      kind: "detail",
      id,
    });
  }
  groupForm(g) {
    const persons = Object.values(this._hass.states)
      .filter((s) => s.entity_id.startsWith("person."))
      .map((s) => [s.entity_id, s.attributes.friendly_name || s.entity_id]);
    this.open(
      g.id
        ? "Edit " + g.name
        : "Add " + (g.kind === "thing" ? "shared group" : "person"),
      `<form>${this.field("Name", "name", g.name, "text", 'required maxlength="100"')}${this.select(
        "Type",
        "kind",
        [
          ["family", "Family member"],
          ["thing", "Shared devices"],
        ],
        g.kind,
      )}${this.select(
        "Age label (optional)",
        "age",
        [
          ["", "No label"],
          ["child", "Child"],
          ["teen", "Teen"],
          ["adult", "Adult"],
        ],
        g.age || "",
      )}${this.select("Home Assistant person (optional)", "person", [["", "None"], ...persons], g.person || "")}${g.id ? this.check("Archived — retain configuration but exclude from controls", "archived", g.archived) : ""}</form><p class="note">Age labels do not grant Home Assistant access. Device ownership is assigned separately.</p>`,
      (g.id
        ? this.button("Delete", "group-delete", g.id, "", "danger grow")
        : "") +
        this.button("Cancel", "close") +
        this.button("Save", "submit", "", "", "primary"),
      { kind: "group", id: g.id },
    );
  }
  assignGroup(id) {
    this.open(
      "Assign devices to " + this.groupName(id),
      `<div class="list">${this.data.devices.map((d) => this.deviceRow(d)).join("")}</div><p class="note">Choose a device, then select ${escape(this.groupName(id))} as its owner.</p>`,
      this.button("Close", "close"),
      { kind: "assign-group" },
    );
  }
  deviceForm(id) {
    const d = this.data.devices.find(d => d.id === id);
    const registrant = d.registrant_status === "private" ? "Private/local MAC address" : d.registrant_status === "ambiguous" ? "Multiple IEEE registrants; identity unknown" : d.registrant_status === "unlisted" ? "Not listed in the bundled IEEE registry" : d.registrant ? d.registrant + (d.registrant_status === "unavailable" ? " · last known" : "") : "Unavailable";
    const source = {current_network_id:"UniFi current connection network", current_network_id_reference_differs:"UniFi current connection; saved reference differs", subnet_and_current_network_id:"Current connection network and IP subnet agree", subnet_and_current_network_id_reference_differs:"Current connection and IP subnet agree; saved reference differs", subnet_and_reference:"Current IP subnet and UniFi reference agree", subnet_observation:"Current IP subnet observation", subnet_observation_reference_differs:"Current IP subnet; saved UniFi reference differs"}[d.network_source] || "Last-known subnet observation";
    this.open(d.name,
      `<p class="note">${escape(this.devicePresence(d))} · ${escape(words(d.kind))}<br>${escape(d.ip || "No IP observation")} · ${escape(d.mac)}</p><div class="review"><p><strong>Network:</strong> ${escape(this.data.networks[d.network]?.name || "Unknown")} · ${escape(source)}${this.data.managed_networks && !this.data.managed_networks.includes(d.network) ? " · outside managed scope" : ""}</p><p><strong>${d.kind === "wireless" ? "Access point" : "Uplink"}:</strong> ${escape(d.uplink_name || "Name unavailable")}${d.uplink ? " · " + escape(d.uplink) : ""}</p><p><strong>${d.connected ? "Connection started" : "Last connection started"}:</strong> ${d.connected_at ? this.time(d.connected_at, true) : "Not supplied by UniFi"}</p><p><strong>Last seen:</strong> ${d.last_seen ? this.time(d.last_seen, true) : "Not observed yet"}</p><p><strong>MAC registrant:</strong> ${escape(registrant)}</p><p class="note">IEEE registration identifies an address allocation, not the device model or its owner. Connection details are ${this.data.fresh && d.connected ? "current observations" : "last known observations"}.</p></div><form>${this.select("Assigned to", "group_id", [["", "Unassigned"], ...this.data.groups.filter(g => !g.archived).map(g => [g.id, g.name])], d.group || "")}</form><p class="note">Reassignment applies the new owner's restrictions. Unassigned devices may be quarantined. Existing network filters remain.</p>`,
      this.button("Forget device…", "device-forget", id, "", "danger grow") + this.button("Cancel", "close") + this.button("Review assignment", "submit", "", "", "primary"), {kind:"device", id});
  }
  allowanceButtons(exceptions) {
    return exceptions.filter(e => ["internet_allow", "rule_allow"].includes(e.kind)).map(e => this.button(e.rule ? "Change " + (e.group ? this.groupName(e.group) : "everyone’s") + " allowance end time" : "Change allowance end time", "allowance-edit", e.id)).join("");
  }
  allowanceForm(id) {
    const e = this.data.exceptions.find(e => e.id === id);
    if (!e) throw new Error("This allowance has ended. Refresh the household.");
    const local = this.localDateValue(e.expires_at);
    const captured = e.captured.map(id => this.data.rules.find(r => r.id === id)?.name || "Removed rule").join(", ");
    this.open("Change allowance end time",
      `<p class="note">${escape(e.group ? this.groupName(e.group) : "Everyone on this rule")} · ${e.expires_at ? "currently until " + this.time(e.expires_at, true) : "until ended"}</p><div class="review"><strong>Restrictions originally lifted</strong><p>${escape(captured || "None remaining")}</p></div><form>${this.field("New end time", "expires_at", local, "datetime-local", "required")}${this.field("Reason (optional)", "reason", "", "text", 'maxlength="300"')}</form><p class="note">Only the deadline changes. New or unrelated restrictions still apply. Choose a time within the next seven days, using this device's local timezone. Home Assistant must be running to end the allowance.</p>`,
      this.button("Cancel", "close") + this.button("Review end time", "submit", "", "", "primary"), {kind:"allowance", id});
  }
  control(id) {
    const group = this.data.groups.find((g) => g.id === id);
    const g = { ...group, state: group.control_state || group.state };
    const options =
      g.state === "allowed"
        ? [
            ["pause_internet", "Pause internet"],
            ["end_allowance", "Return to schedule"],
          ]
        : g.state === "paused"
          ? [
              ["resume_internet", "Resume manual pause"],
              ["extend_pause", "Extend pause"],
            ]
          : g.state === "scheduled_block"
            ? [
                ["allow_internet", "Allow internet temporarily"],
                ["pause_internet", "Pause internet"],
              ]
            : [["pause_internet", "Pause internet"]];
    this.open(
      g.name + " · internet",
      `${g.network_rules?.length ? `<p class="note">${escape(g.reason)} Manage these restrictions from the rule's Options.</p>` : ""}${this.allowanceButtons(this.data.exceptions.filter(e => e.group === id && !e.rule))}<form>${this.select("Action", "service", options, options[0][0])}${this.select(
        "Duration",
        "deadline",
        [
          ["30", "30 minutes"],
          ["60", "1 hour"],
          ["120", "2 hours"],
          ["custom", "Until a chosen time"],
          ["window", "Until current restriction ends"],
          ["indefinite", "Until ended manually"],
          ["default", "Automatic · pause until resumed / allow until window end"],
        ],
        "30",
      )}${this.field("Chosen end time (only for a chosen time)", "expires_at", "", "datetime-local")}<p class="note">Chosen times use this device's local timezone. Household schedules use ${escape(this.data.timezone)}.</p>${this.field("Reason (optional)", "reason", "", "text", 'maxlength="300"')}</form><p class="note">Allowing internet lifts current managed internet rules. It does not end a manual pause; other content restrictions remain. Exception expiry requires Home Assistant.</p>`,
      this.button("Cancel", "close") +
        this.button("Review", "submit", "", "", "primary"),
      { kind: "control", id },
    );
  }
  unblockForm(id) {
    const g = this.data.groups.find(g=>g.id===id), s = g.unblock;
    const options = [["unblock_group", "Unblock this person's rules"]];
    if (s.allowances) options.push(["end_group_unblock", "End this person's rule allowances"]);
    if (s.timed_allowances) options.push(["extend_group_unblock", "Extend all timed allowances together"]);
    this.open(g.name + " · rule allowances", `<p>Temporarily lift internet, category, application and website rules that explicitly name ${escape(g.name)}. This also ends their manual internet pause.</p><p class="note">Other people, whole-network rules, inherited UniFi filters and existing rule suspensions keep their settings.</p>${s.allowances ? `<p>${s.allowances} active rule allowances${s.latest_deadline ? " · latest timed end " + this.time(s.latest_deadline, true, true) : ""}${s.indefinite_allowances ? " · " + s.indefinite_allowances + " without a deadline" : ""}.</p>` : ""}<form>${this.select("Action", "service", options, "unblock_group")}${this.select("Duration", "deadline", [["default", "Current restrictions · each until its window ends"],["30", "30 minutes"],["60", "1 hour"],["120", "2 hours"],["custom", "Until a chosen time"],["indefinite", "Until ended manually"]], "default")}${this.field("Chosen end time", "expires_at", "", "datetime-local")}${this.field("Reason (optional)", "reason", "", "text", 'maxlength="300"')}</form><p class="note">Default timing lifts only rules active now; an always-on rule stays lifted until ended. A chosen duration/time or no deadline also covers currently assigned enabled rules whose windows start later. Rules added afterwards still apply. Extension sets every timed allowance to the latest end plus the selected minutes; indefinite allowances stay indefinite. Choose a minute duration to extend. Chosen times use this device's timezone. Home Assistant must run to end timed allowances.</p>`, this.button("Cancel", "close") + this.button("Review", "submit", "", "", "primary"), {kind:"group-unblock", id});
  }
  ruleOptions(id, group) {
    const r = this.data.rules.find((r) => r.id === id);
    if (group && (!r.groups.includes(group) || r.networks?.length)) throw new Error("This rule has no allowance for that person.");
    this.open(
      r.name + (group ? " · " + this.groupName(group) : " · options"),
      `${this.allowanceButtons(this.data.exceptions.filter(e => e.rule === id && (!group || e.group === group)))}<form>${this.select(
        "Action",
        "service",
        [
          ["suspend_rule", "Suspend restriction"],
          ["resume_rule", "End suspension"],
          ["extend_rule_suspension", "Extend suspension"],
          ["allow_rule", "Allow temporarily"],
          ["end_rule_allowance", "End allowance"],
        ],
        "suspend_rule",
      )}${this.select("Applies to", "group_id", group ? [[group, this.groupName(group)]] : [...(this.config?.mode !== "access" || r.whole_rule_control ? [["", r.networks?.length ? "Every device on the selected networks" : "Everyone on this rule"]] : []), ...r.groups.map((g) => [g, this.groupName(g)])], group || "")}${this.select(
        "Duration",
        "deadline",
        [
          ["30", "30 minutes"],
          ["60", "1 hour"],
          ["120", "2 hours"],
          ["custom", "Until a chosen time"],
          ["window", "Until current window ends"],
          ["indefinite", "Until ended manually"],
          ["default", "Automatic · pause until resumed / allow until window end"],
        ],
        "30",
      )}${this.field("Chosen end time", "expires_at", "", "datetime-local")}${this.field("Reason (optional)", "reason", "", "text", 'maxlength="300"')}</form><p class="note">Suspending this rule removes this restriction only. Other rules still apply. Timed exceptions require Home Assistant to end them.</p>`,
      (group || this.config?.mode === "access" ? this.button("Cancel", "close") : this.button("Delete rule", "rule-delete", id, "", "danger grow")) +
        this.button("Review", "submit", "", "", "primary"),
      { kind: "rule-control", id, group },
    );
  }
  ruleScope(rule) {
    return rule.networks?.length
      ? "Whole networks: " + rule.networks.map(n => this.data.networks?.[n]?.name || n).join(", ")
      : rule.groups.map(g => this.groupName(g)).join(", ");
  }
  ruleForm(rule) {
    this._draft = structuredClone(
      rule || {
        name: "",
        kind: "internet",
        groups: this._ruleGroup ? [this._ruleGroup] : [],
        targets: [],
        target_names: [],
        windows: [],
        enabled: true,
      },
    );
    this._draft.networks ||= [];
    this._draftScope = this._draft.networks.length ? "networks" : "groups";
    this._draftRevision = this.data.revision;
    this._step = 0;
    this._catalogue = [];
    this.drawRule();
  }
  drawRule() {
    const d = this._draft;
    let body = `<div class="steps">${["What", "Who", "When", "Review"].map((s, i) => `<span class="${i === this._step ? "active" : ""}">${i + 1}. ${s}</span>`).join("")}</div><form>`;
    if (this._step === 0) {
      body +=
        this.field(
          "Rule name",
          "name",
          d.name,
          "text",
          'required maxlength="100"',
        ) +
        this.select(
          "Restrict",
          "rule_kind",
          [
            ["internet", "All internet"],
            ["category", "An application category"],
            ["application", "Specific applications"],
            ["domain", "Websites"],
          ],
          d.kind,
          Boolean(d.id),
        );
      if (d.id) body += '<p class="note">Create a new rule to change its restriction kind or scope type.</p>';
      if (d.kind === "domain")
        body += `<label class="field">Domains (one per line)<textarea name="domains" placeholder="example.com">${escape(d.targets.join("\n"))}</textarea></label><p class="note">Enter domains, without URLs or paths. Encrypted DNS may bypass domain matching.</p>`;
      if (["category", "application"].includes(d.kind)) {
        body += `<p class="note" id="selected-targets">Selected: ${escape(d.target_names.join(", ") || "None")}</p><div class="row toolbar"><input name="catalogue_query" aria-label="Search catalogue" placeholder="Search ${d.kind === "category" ? "categories" : "applications"}">${this.button("Search", "catalogue-search")}</div><div class="catalogue" id="catalogue">${this.catalogueHTML(d.kind === "category" ? this.data.categories : this._catalogue)}</div><p class="note" id="catalogue-note">Choose one or more entries from the gateway catalogue.</p>`;
      }
    }
    if (this._step === 1) {
      body += this.select("Rule scope", "rule_scope", [["groups", "People and shared groups"], ["networks", "Whole managed networks"]], this._draftScope, Boolean(d.id));
      if (this._draftScope === "networks") {
        body += '<p class="note">Every device on a selected network is affected, including unassigned devices and devices that connect later. A person’s temporary allowance cannot override this rule.</p>';
        body += this.data.managed_networks.map(n => `<label class="check"><input type="checkbox" name="networks" value="${escape(n)}" ${d.networks.includes(n) ? "checked" : ""}>${escape(this.data.networks?.[n]?.name || n)}</label>`).join("");
      } else {
        body += '<p class="note">All assigned devices in each selected group will follow this rule.</p>';
        body += this.data.groups.filter(g => !g.archived).map(g => `<label class="check"><input type="checkbox" name="groups" value="${escape(g.id)}" ${d.groups.includes(g.id) ? "checked" : ""}>${escape(g.name)} · ${g.devices} devices</label>`).join("") || "<p>Add a person or shared group first.</p>";
      }
    }
    if (this._step === 2) {
      body += this.select(
        "When",
        "schedule_mode",
        [
          ["always", "Always"],
          ["windows", "Scheduled windows"],
        ],
        d.windows.length ? "windows" : "always",
      );
      body += d.windows
        .map(
          (w, i) =>
            `<fieldset data-window="${i}"><legend>Window ${i + 1}</legend>${this.field("Name", "window_name_" + i, w.name, "text", 'required maxlength="100"')}<div class="days">${dayNames.map((day, j) => `<label>${day}<input type="checkbox" name="window_days_${i}" value="${j}" aria-label="${day}" ${w.days.includes(j) ? "checked" : ""}></label>`).join("")}</div>${this.check("All day", "window_all_" + i, w.all_day)}<div class="form-grid">${this.field("Start", "window_start_" + i, w.start, "time", "required")}${this.field("End", "window_end_" + i, w.end, "time", "required")}</div>${this.button("Remove window", "window-remove", String(i), "", "quiet danger")}</fieldset>`,
        )
        .join("");
      if (d.windows.length) body += this.button("Add window", "window-add");
      body += `<p class="note">${escape(this.data.timezone)}. An end earlier than the start continues into the next day. Recurrence is enforced by UniFi after gateway setup is verified.</p>`;
    }
    if (this._step === 3) {
      body += `<div class="review"><h3>${escape(d.name)}</h3><p><strong>What:</strong> ${escape(d.kind === "internet" ? "All internet" : d.target_names.join(", ") || d.targets.join(", "))}</p><p><strong>Who:</strong> ${escape(this.ruleScope(d))}</p>${d.networks.length ? "<p>Includes all current, future and unassigned devices on these networks. Exceptions affect the whole rule, not one person.</p>" : ""}<p><strong>When:</strong> ${escape(this.scheduleLabel(d))}</p></div>${this.check("Enabled", "enabled", d.enabled)}<p class="note">${d.id ? "Editing keeps current exceptions for retained targets. Disabling the rule ends its exceptions. " : ""}${this.data.simulation ? "This is a simulator change." : this.data.management ? "The gateway will reconcile these restrictions after saving." : "Management is disabled; this saves intent only."} Existing network filters remain in place.</p>`;
    }
    body += "</form>";
    this.open(
      d.id ? "Edit rule" : "Create rule",
      body,
      (d.id && this._step === 0 ? this.button("Delete rule", "rule-delete", d.id, "", "danger") : "") +
      (this._step
        ? this.button("Back", "rule-back", "", "", "grow")
        : this.button("Cancel", "close", "", "", "grow")) +
        (this._step < 3
          ? this.button("Continue", "rule-next", "", "", "primary")
          : this.button("Save rule", "submit", "", "", "primary")),
      { kind: "rule", revision: this._draftRevision },
    );
  }
  catalogueHTML(rows) {
    return (
      rows
        .map(
          (r) =>
            `<label class="check"><input type="checkbox" name="targets" value="${r.id}" data-name="${escape(r.name)}" ${this._draft.targets.includes(r.id) ? "checked" : ""}>${escape(r.name)}</label>`,
        )
        .join("") || '<p class="note">Search for an application.</p>'
    );
  }
  async catalogue() {
    this.captureRule(false);
    const q = this.form().elements.catalogue_query.value;
    const result = await this.api("dashboard_catalogue", {
      kind: this._draft.kind,
      query: q,
    });
    this._catalogue = result.items;
    this.shadowRoot.querySelector("#catalogue").innerHTML = this.catalogueHTML(
      result.items,
    );
    this.shadowRoot.querySelector("#catalogue-note").textContent = result.capped
      ? `Showing 100 of ${result.total}; refine the search.`
      : `${result.total} matches`;
  }
  captureRule(validate = true) {
    const form = this.form();
    if (validate && !form.reportValidity()) return false;
    const fd = new FormData(form),
      d = this._draft;
    if (this._step === 0) {
      d.name = String(fd.get("name") || "").trim();
      if (!d.id) d.kind = fd.get("rule_kind");
      if (d.kind === "internet") {
        d.targets = [];
        d.target_names = [];
      }
      if (d.kind === "domain") {
        d.targets = String(fd.get("domains") || "")
          .split(/[\n,]+/)
          .map((x) => x.trim())
          .filter(Boolean);
        d.target_names = [...d.targets];
      }
      if (["category", "application"].includes(d.kind)) {
        const map = new Map(
          d.targets.map((id, i) => [id, d.target_names[i] || String(id)]),
        );
        form.querySelectorAll("input[name=targets]").forEach((el) => {
          if (el.checked) map.set(Number(el.value), el.dataset.name);
          else map.delete(Number(el.value));
        });
        d.targets = [...map.keys()];
        d.target_names = [...map.values()];
      }
      if (validate && d.kind !== "internet" && !d.targets.length) {
        this.showError("Select at least one restriction target.");
        return false;
      }
    }
    if (this._step === 1) {
      d.groups = this._draftScope === "groups" ? fd.getAll("groups") : [];
      d.networks = this._draftScope === "networks" ? fd.getAll("networks") : [];
      if (validate && !d.groups.length && !d.networks.length) {
        this.showError("Select at least one group or managed network.");
        return false;
      }
    }
    if (this._step === 2) {
      if (fd.get("schedule_mode") === "always") d.windows = [];
      else if (!d.windows.length)
        d.windows = [
          {
            name: "Bedtime",
            days: [0, 1, 2, 3, 4],
            start: "21:00",
            end: "07:00",
            all_day: false,
            overnight: true,
          },
        ];
      else
        d.windows = d.windows.map((w, i) => ({
          ...w,
          name: fd.get("window_name_" + i),
          days: fd.getAll("window_days_" + i).map(Number),
          start: fd.get("window_start_" + i),
          end: fd.get("window_end_" + i),
          all_day: fd.has("window_all_" + i),
          overnight:
            !fd.has("window_all_" + i) &&
            fd.get("window_end_" + i) < fd.get("window_start_" + i),
        }));
      if (
        validate &&
        d.windows.some(
          (w) => !w.days.length || (!w.all_day && w.start === w.end),
        )
      ) {
        this.showError(
          "Each window needs a weekday and distinct start/end times, or All day.",
        );
        return false;
      }
    }
    return true;
  }
  quarantine() {
    this.open(
      "Unknown-device quarantine",
      `<form>${this.check("Block unassigned devices after discovery", "enabled", this.data.quarantine)}<p class="note">Only devices in the configured network scope are eligible. Assign devices to people before enabling this.</p>${this.select(
        "Temporary suspension",
        "pause",
        [
          ["unchanged", "Keep current suspension"],
          ["30", "Suspend for 30 minutes"],
          ["60", "Suspend for 1 hour"],
          ["indefinite", "Pause until resumed"],
          ...(this.data.quarantine_paused && this.data.quarantine_until ? [["extend", "Extend pause by 30 minutes"]] : []),
          ["resume", "Resume quarantine now"],
        ],
        "unchanged",
      )}</form>`,
      this.button("Cancel", "close") +
        this.button("Review", "submit", "", "", "primary"),
      { kind: "quarantine" },
    );
  }
  management() {
    this.open(
      "Gateway management",
      `<form>${this.check("Enable gateway policy management", "enabled", this.data.management)}${this.check("I understand timed exceptions may overrun while HA is offline", "expiry_acknowledged", this.data.expiry_acknowledged)}${this.check("Gateway timezone and recurring schedules have been verified", "gateway_timezone_confirmed", this.data.gateway_timezone_confirmed)}</form><p class="note">${this.data.simulation ? "This entry controls only fictional devices." : "Enabling management applies saved restrictions to the configured networks. Disabling management keeps existing gateway policies in place."}</p>`,
      this.button("Cancel", "close") +
        this.button("Review", "submit", "", "", "primary"),
      { kind: "management" },
    );
  }
  dnsSettings() {
    const cfg = this.data.dns_settings;
    this.open("DNS resolver settings",
      `<form>${this.check("Enable DNS observations", "enabled", cfg.enabled)}${this.field("Household resolver (blank = device network DHCP DNS)", "household_resolver", cfg.household_resolver)}${this.field("Reference resolver IP or HTTPS DoH URL", "baseline_resolver", cfg.baseline_resolver, "text", "required")}${this.field("Results remain current for (hours)", "freshness_hours", cfg.freshness_hours, "number", 'min="1" max="168" required')}<h3>Person and shared-group overrides</h3><p class="note">Leave blank to inherit the household resolver or device network DNS. A list-specific resolver takes priority.</p>${this.data.groups.map((g, i) => this.field(g.name, "resolver_" + i, cfg.group_resolvers[g.id] || "")).join("")}</form><p class="note">Enter an IP address or HTTPS DNS endpoint, such as https://dns.example/dns-query. Checks originate on Home Assistant’s network and cannot reproduce client-specific policies. Saving settings invalidates previous observations.</p>`,
      this.button("Cancel", "close") + this.button("Save settings", "submit", "", "", "primary"),
      {kind: "dns-settings", groups: this.data.groups.map(g => g.id)});
  }
  probeForm(p) {
    const categories = [["custom", "Custom"], ["video", "Video"], ["social", "Social"], ["gaming", "Gaming"], ["vpn", "VPN"], ["messaging", "Messaging"], ["adult", "Adult content"], ["gambling", "Gambling"], ["advertising", "Advertising"]];
    this.open(
      p.id ? "Edit DNS check" : "Add DNS check",
      `<form>${this.field("Name", "name", p.name || "", "text", p.seed ? "readonly" : "required")}${this.check("Enable this sample list", "enabled", p.enabled !== false)}${this.select("Category", "category", p.seed ? categories.filter(c => c[0] === p.category) : categories, p.category || "custom")}<label class="field">Sample domains (one per line; up to 1,000)<textarea name="domains">${escape((p.domains || []).join("\n"))}</textarea></label>${this.field("List resolver IP or DoH URL (blank = inherit)", "resolver", p.resolver || "")}${this.field("Reference resolver (blank = household reference)", "baseline_resolver", p.baseline_resolver || "")}${this.select("Person context (optional)", "group_id", [["", "Household and all people"], ...this.data.groups.map(g => [g.id, g.name])], p.group_id || "")}</form><p class="note">These checks run from Home Assistant. Empty lists remain inconclusive. Removing built-in samples is remembered across upgrades.${p.seed ? ` ${p.removed_seed_domains?.length || 0} default samples removed.` : ""}</p>${p.seed ? this.button("Restore default samples", "probe-restore", p.id) : ""}`,
      (p.id ? this.button(p.seed ? "Disable list" : "Delete", "probe-delete", p.id, "", "danger grow") : "") + this.button("Cancel", "close") + this.button("Save check", "submit", "", "", "primary"),
      { kind: "probe", id: p.id },
    );
  }
  probeResults(id, selected = "household") {
    const p = this.data.probes[id], views = this.data.dns_views?.[id] || {};
    if (!views[selected]) selected = Object.keys(views)[0];
    const view = views[selected];
    const stored = Object.values(this.data.probe_results[id]?.contexts || {});
    this.open(p.name + " · results",
      `${this.select("Device context", "dns_context", Object.keys(views).map(key => [key, key === "household" ? "Household device networks" : this.groupName(key)]), selected)}<span class="badge">${escape(this.dnsLabel(view?.verdict))}</span><p class="note">${escape(view?.issues?.join(" · ") || "DNS observations from Home Assistant; device traffic has not been tested.")}</p>${(view?.contexts || []).map(context => {
        const r = stored.find(r => r.resolver === context.resolver);
        return `<section class="section"><h3>${escape(context.source)}</h3><p class="note">${escape(context.resolver)}${context.networks.length ? " · " + escape(context.networks.join(", ")) : ""}</p>${context.issue ? `<div class="banner warning">${escape(context.issue)}</div>` : ""}${r ? `<p class="note">${escape(r.vantage)} · ${this.time(r.timestamp, true)} · expires ${this.time(r.expires_at, true)}</p>${!context.fresh ? '<div class="banner warning">Last-known results below are not current. Run a new check.</div>' : ""}<div class="list">${r.domains.map(row => `<details class="audit-row"><summary>${escape(row.domain)} · ${context.fresh ? escape(this.dnsLabel(row.verdict)) : "Last known · " + escape(this.dnsLabel(row.verdict))}</summary><p class="note">${escape(row.reason)}</p>${["observed", "reference"].map(side => `<p class="note"><strong>${side === "observed" ? "Observed resolver" : "Reference resolver"}</strong><br>${["A", "AAAA"].map(kind => { const a = row[side][kind]; return escape(kind + ": " + (a.addresses.join(", ") || words(a.status)) + (a.ede?.length ? " · EDE " + a.ede.join(", ") : "") + (a.issue ? " · " + a.issue : "")); }).join("<br>")}</p>`).join("")}</details>`).join("")}</div>` : '<p class="note">No observations yet.</p>'}</section>`;
      }).join("")}`,
      this.button("Close", "close"), {kind: "probe-results", id});
  }
  probeSchedule() {
    const p = this.data.probe_schedule;
    this.open(
      "DNS check schedule",
      `<form>${this.check("Run checks automatically", "enabled", p.enabled)}<div class="days">${dayNames.map((name, i) => `<label>${name}<input type="checkbox" name="days" value="${i}" aria-label="${name}" ${p.days.includes(i) ? "checked" : ""}></label>`).join("")}</div>${this.field("Time · " + this.data.timezone, "time", p.time, "time", "required")}</form>`,
      this.button("Cancel", "close") +
        this.button("Save schedule", "submit", "", "", "primary"),
      { kind: "probe-schedule" },
    );
  }
  deadline(fd, service) {
    if (
      [
        "resume_internet",
        "end_allowance",
        "resume_rule",
        "end_rule_allowance",
        "end_group_unblock",
      ].includes(service)
    )
      return {};
    const value = fd.get("deadline");
    if (["extend_pause", "extend_rule_suspension", "extend_group_unblock"].includes(service)) {
      if (!/^\d+$/.test(value))
        throw new Error("Choose a minute duration when extending a pause.");
      return { duration_minutes: Number(value) };
    }
    if (value === "default") return {};
    if (value === "window") return { next_window_end: true };
    if (value === "indefinite") return { indefinite: true };
    if (value === "custom") {
      const date = new Date(fd.get("expires_at"));
      if (!fd.get("expires_at") || !Number.isFinite(date.getTime()))
        throw new Error("Choose a valid end time.");
      return { expires_at: date.toISOString() };
    }
    return { duration_minutes: Number(value) };
  }
  async submit() {
    const modal = this._modal,
      form = this.form();
    if (form && !form.reportValidity()) return;
    const fd = form ? new FormData(form) : null;
    let service, payload, title;
    if (modal.kind === "profile-edit") {
      const changes = {enabled:fd.has("enabled"),categories:fd.getAll("categories"),safe_search:fd.getAll("safe_search")};
      for (const key of ["allow_list","block_list"]) changes[key] = String(fd.get(key)).split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
      const preview = await this.api("preview_content_filter",{profile_id:modal.id,changes});
      this.open("Review shared UniFi profile · " + preview.profile.name, `<p>${escape(preview.note)}</p><p><strong>Networks:</strong> ${escape(preview.profile.networks.map(n=>n.name).join(", ") || "None")}</p><p><strong>Individual devices:</strong> ${escape(preview.profile.client_macs.map(mac=>this.data.devices.find(d=>d.mac.toLowerCase()===mac.toLowerCase())?.name || mac).join(", ") || "None")}</p><p><strong>Schedule:</strong> ${escape(words(preview.profile.schedule.mode))}${preview.profile.schedule.time_start ? " · " + escape(preview.profile.schedule.time_start) + "–" + escape(preview.profile.schedule.time_end) : ""}${preview.profile.schedule.days?.length ? " · " + escape(preview.profile.schedule.days.join(", ")) : ""}</p>${preview.changed_fields.map(k=>`<div class="audit-row"><h3>${escape(words(k))}</h3><p>Before: ${escape(Array.isArray(preview.before[k]) ? preview.before[k].join(", ") || "None" : String(preview.before[k]))}</p><p>After: ${escape(Array.isArray(preview.after[k]) ? preview.after[k].join(", ") || "None" : String(preview.after[k]))}</p></div>`).join("") || '<p>No changes.</p>'}`,this.button("Cancel","close")+this.button("Save to UniFi","submit","","","primary"),{kind:"profile-review",token:preview.preview_token});
      return;
    }
    if (modal.kind === "profile-review") {
      if (this._busy) return;
      this._busy = true;
      try {
        const result = await this.api("apply_content_filter",{preview_token:modal.token,confirm:true,request_expires_at:this.requestExpiry()});
        this._profileResult = result.message;
        this.close(); await this.refresh();
      } finally { this._busy = false; }
      return;
    }
    if (modal.kind === "confirm") {
      await this.perform(
        modal.service,
        modal.payload,
        modal.title,
        modal.revision,
      );
      return;
    }
    if (modal.kind === "import-review") {
      if (!fd.has("confirm")) { this.showError("Confirm the reviewed household restore."); return; }
      service="apply_import";payload={configuration:modal.configuration,network_mapping:modal.network_mapping,preview_hash:modal.preview_hash};title="Restore household";
    }
    if (modal.kind === "setup-review") {
      if (!fd.has("confirm")) { this.showError("Confirm the reviewed household setup.");return; }
      service="apply_setup";payload={configuration:modal.configuration,preview_hash:modal.preview_hash,confirm:true};title="Save household setup";
    }
    if (modal.kind === "access-grant") {
      if (!fd.get("user_id") || !fd.has("confirm")) { this.showError("Select an account and confirm its access scope."); return; }
      const groups = fd.getAll("groups"), networks = fd.getAll("networks"), all_groups = fd.has("all_groups");
      if (!all_groups && !groups.length && !networks.length) { this.showError("Select at least one group or network."); return; }
      const expires = fd.get("expires_at");
      service = "set_access_grant";
      payload = {user_id:fd.get("user_id"), scope:fd.get("scope"), groups, networks, all_groups, confirm:true, expected_access_revision:modal.accessRevision, ...(expires ? {expires_at:new Date(expires).toISOString()} : {})};
      title = "Save access grant";
    }
    if (modal.kind === "group") {
      service = "upsert_group";
      payload = {
        ...(modal.id ? { group_id: modal.id } : {}),
        name: fd.get("name").trim(),
        kind: fd.get("kind"),
        age: fd.get("age"),
        person: fd.get("person"),
        archived: fd.has("archived"),
      };
      title = "Save " + payload.name;
    }
    if (modal.kind === "device") {
      service = "assign_device";
      payload = { device_id: modal.id, group_id: fd.get("group_id") };
      this.confirm(
        "Assign device",
        service,
        payload,
        `Assign ${this.data.devices.find((d) => d.id === modal.id).name} to ${this.groupName(payload.group_id)}. Their restrictions will apply; unassigned devices may be quarantined.`,
      );
      this._modal.revision = modal.revision;
      return;
    }
    if (modal.kind === "allowance") {
      const date = new Date(fd.get("expires_at"));
      if (!Number.isFinite(date.getTime())) throw new Error("Choose a valid end time.");
      payload = {exception_id: modal.id, expires_at: date.toISOString(), reason: fd.get("reason")};
      this.confirm("Change allowance end time", "edit_allowance", payload, `The same captured restrictions remain lifted until ${this.time(payload.expires_at, true)}. Other restrictions still apply.`);
      this._modal.revision = modal.revision;
      return;
    }
    if (modal.kind === "control" || modal.kind === "rule-control" || modal.kind === "group-unblock") {
      service = fd.get("service");
      payload = {
        ...(modal.kind !== "rule-control"
          ? { group_id: modal.id }
          : {
              rule_id: modal.id,
              ...(modal.group || fd.get("group_id") ? { group_id: modal.group || fd.get("group_id") } : {}),
            }),
        ...this.deadline(fd, service),
        reason: fd.get("reason"),
      };
      this.confirm(
        words(service),
        service,
        payload,
        `${modal.kind !== "rule-control" ? this.groupName(modal.id) : this.data.rules.find((r) => r.id === modal.id).name + (payload.group_id ? " · " + this.groupName(payload.group_id) : " · everyone on this rule")} · ${words(service)}${payload.duration_minutes ? " · " + payload.duration_minutes + " minutes" : payload.expires_at ? " until " + this.time(payload.expires_at) : payload.next_window_end ? " until the relevant window ends" : payload.indefinite ? " until resumed" : ""}. ${modal.kind === "group-unblock" ? (service === "extend_group_unblock" ? "All timed group allowances will share the latest deadline plus this duration. " : service === "end_group_unblock" ? "All of this person's rule allowances end; suspensions remain. " : "Only rules naming this person are lifted. Existing rule suspensions remain; whole-network and inherited restrictions still apply. ") : service === "allow_internet" ? "A manual pause remains in place until resumed or its own deadline. Other restrictions remain." : "Other restrictions remain."}`,
      );
      this._modal.revision = modal.revision;
      return;
    }
    if (modal.kind === "resolve-operation") {
      if (!fd.has("confirm") || (!modal.row.candidate_id && !fd.has("request_finished"))) {
        this.showError("Confirm the evidence and selected recovery decision."); return;
      }
      service = "resolve_operation";
      payload = {operation_id:modal.row.operation_id, preview_hash:modal.row.preview_hash,
        decision:modal.decision, confirm:true,
        request_finished:fd.has("request_finished"), reason:String(fd.get("reason") || "").trim()};
      title = "Record gateway recovery";
    }
    if (modal.kind === "rule") {
      const d = this._draft;
      service = "upsert_rule";
      payload = {
        ...(d.id ? { rule_id: d.id } : {}),
        name: d.name,
        kind: d.kind,
        groups: d.groups,
        networks: d.networks,
        targets: d.targets,
        windows: d.windows,
        enabled: fd.has("enabled"),
      };
      title = "Save " + d.name;
    }
    if (modal.kind === "management") {
      service = "set_management";
      payload = {
        enabled: fd.has("enabled"),
        expiry_acknowledged: fd.has("expiry_acknowledged"),
        gateway_timezone_confirmed: fd.has("gateway_timezone_confirmed"),
      };
      this.confirm(
        payload.enabled ? "Enable management" : "Disable management",
        service,
        payload,
        payload.enabled
          ? "Apply saved restrictions to the configured network scope."
          : "Stop reconciliation writes. Existing gateway policies remain in place.",
      );
      this._modal.revision = modal.revision;
      return;
    }
    if (modal.kind === "quarantine") {
      const pause = fd.get("pause");
      if (fd.has("enabled") !== this.data.quarantine && pause !== "unchanged")
        throw new Error(
          "Save the quarantine switch first, then change its suspension.",
        );
      service =
        pause === "unchanged"
          ? "set_quarantine"
          : pause === "resume"
            ? "resume_quarantine"
            : pause === "extend" ? "extend_quarantine_suspension" : "suspend_quarantine";
      payload =
        pause === "unchanged"
          ? {
              enabled: fd.has("enabled"),
              excluded_devices: this.data.quarantine_excluded,
              confirm: true,
            }
          : pause === "resume"
            ? {}
            : pause === "indefinite" ? {indefinite:true} : { duration_minutes: pause === "extend" ? 30 : Number(pause) };
      this.confirm(
        "Change quarantine",
        service,
        payload,
        `${words(service)}. This affects unknown devices after discovery within the configured network scope.`,
      );
      this._modal.revision = modal.revision;
      return;
    }
    if (modal.kind === "probe") {
      service = "upsert_probe";
      payload = {
        ...(modal.id ? { probe_id: modal.id } : {}),
        name: fd.get("name"),
        domains: fd
          .get("domains")
          .split(/[\n,]+/)
          .map((x) => x.trim())
          .filter(Boolean),
        resolver: fd.get("resolver"),
        baseline_resolver: fd.get("baseline_resolver"),
        category: fd.get("category"),
        enabled: fd.has("enabled"),
        ...(fd.get("group_id") ? { group_id: fd.get("group_id") } : {}),
      };
      title = "Save DNS check";
    }
    if (modal.kind === "dns-settings") {
      service = "set_dns_settings";
      payload = {enabled: fd.has("enabled"), household_resolver: fd.get("household_resolver").trim(), baseline_resolver: fd.get("baseline_resolver").trim(), freshness_hours: Number(fd.get("freshness_hours")), group_resolvers: Object.fromEntries(modal.groups.map((id, i) => [id, fd.get("resolver_" + i).trim()]).filter(([, value]) => value))};
      title = "Save resolver settings";
    }
    if (modal.kind === "probe-schedule") {
      service = "set_probe_schedule";
      payload = {
        enabled: fd.has("enabled"),
        days: fd.getAll("days").map(Number),
        time: fd.get("time"),
      };
      title = "Save DNS schedule";
    }
    if (service) await this.perform(service, payload, title, modal.revision);
  }
  async perform(service, payload, label, revision) {
    if (this._busy) return;
    this._busy = true;
    this.shadowRoot
      .querySelectorAll('button[data-action="submit"]')
      .forEach((b) => (b.disabled = true));
    try {
      const result = await this.api(service, {
        ...payload,
        expected_revision: revision,
        expected_dns_revision: this._modal?.dnsRevision ?? this.data?.dns_revision,
        request_id: requestId(),
        request_expires_at: this.requestExpiry(),
      });
      this._lastChange = result.change || result;
      this._lastLabel = label;
      if (this._modal) this.close();
      await this._refreshTask;
      await this.refresh();
    } catch (error) {
      this.showError(error.message || String(error));
    } finally {
      this._busy = false;
      this.shadowRoot
        .querySelectorAll('button[data-action="submit"]')
        .forEach((b) => (b.disabled = false));
      this.render();
    }
  }
  requestExpiry() {
    // Bound delayed delivery from the latest server observation. Device clock
    // skew cannot extend validity; an old cached screen needs a fresh read.
    const observed = Date.parse(this.data?.now);
    if (!Number.isFinite(observed)) throw new Error("Refresh SimpliFi before sending a command.");
    return new Date(observed + 60000).toISOString();
  }
}
if (!customElements.get("simplifi-card"))
  customElements.define("simplifi-card", SimpliFiCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "simplifi-card",
  name: "SimpliFi",
  description: "People, devices and rules for the SimpliFi integration.",
});
