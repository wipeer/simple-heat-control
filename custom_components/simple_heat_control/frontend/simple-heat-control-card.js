// Simple Heat Control card: weekly timeline per room + Vaillant, live reason, presets, schedule and override editor,
// options (live/dry run, time format, language). Plain custom element, no dependencies. Loaded automatically
// by the simple_heat_control integration. Every text comes from the integration's lang/*.json (see _t).

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const VAILLANT_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const WORKDAYS = DAYS.slice(0, 5);
const WEEKEND = DAYS.slice(5);

const toMin = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
const f1 = (v) => (v === null || v === undefined || isNaN(v) ? "–" : Number(v).toFixed(1));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clone = (x) => JSON.parse(JSON.stringify(x));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const bold = (s) => ({ html: `<b>${esc(s)}</b>` });  // a placeholder value shown in bold
const tempColor = (t) => (t < 21 ? "#E6F1FB" : t < 22 ? "#FAECE7" : t < 23 ? "#F5C4B3" : t < 24 ? "#F0997B" : "#D85A30");
const tempText = (t) => (t >= 24 ? "#FAECE7" : t < 21 ? "#0C447C" : "#4A1B0C");

// schedule day [["00:00", 21], ...] -> [{start, end, temp}] in minutes
function dayBlocks(points) {
  const pts = points.map(([t, v]) => [toMin(t), Number(v)]).sort((a, b) => a[0] - b[0]);
  return pts.map(([start, temp], i) => ({ start, end: i + 1 < pts.length ? pts[i + 1][0] : 1440, temp }));
}

function vaillantBlocks(program, day) {
  const list = (program && program[VAILLANT_DAYS[DAYS.indexOf(day)]]) || [];
  return list.map((b) => ({ start: b.start_time, end: b.end_time, temp: Number(b.setpoint) }));
}

function download(name, data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

class SimpleHeatControlCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._cfg = null;       // from simple_heat_control/config, including options and texts
    this._day = null;       // day shown on the timeline
    this._edit = null;      // room editor state, see _startEdit
    this._house = null;     // {mode:"switch", to} or {mode:"manage", ...} while a preset panel is open
    this._opts = null;      // {paste, msg} while the options panel is open
    this._error = "";
    this._loading = false;
    this._loadedAt = 0;
  }

  setConfig(config) { this._config = config || {}; }

  // ---- texts --------------------------------------------------------------------------------------
  _lang() {
    const c = this._cfg;
    if (!c || !c.language) return "en";
    return c.language === "custom" ? (c.custom && c.custom.language) || "en" : c.language;
  }

  _template(key, p) {
    const strings = (this._cfg && this._cfg.strings) || {};
    let v = strings[key];
    if (v === undefined) return key;
    if (typeof v === "object") {
      let form = "other";
      try { form = new Intl.PluralRules(this._lang()).select(Number(p.n) || 0); } catch (e) { /* unknown language */ }
      v = v[form] ?? v.other ?? Object.values(v)[0];
    }
    return String(v);
  }

  // HTML: the text is escaped; placeholder values are escaped unless given as {html}
  _t(key, p = {}) {
    return esc(this._template(key, p)).replace(/\{(\w+)\}/g, (m, k) => {
      if (!(k in p)) return m;
      const v = p[k];
      return v && typeof v === "object" && "html" in v ? v.html : esc(v);
    });
  }

  // plain text, for confirm() and the like
  _tp(key, p = {}) { return this._template(key, p).replace(/\{(\w+)\}/g, (m, k) => (k in p ? String(p[k]) : m)); }

  _d(day) { return this._tp(`day.${day}`); }
  _days(days) { return days.map((d) => this._d(d)).join(", "); }

  // ---- time ---------------------------------------------------------------------------------------
  // Options win; with "auto" the card's `time_format:` and then the HA user profile decide
  _is24() {
    const opt = this._cfg && this._cfg.options && this._cfg.options.time_format;
    if (opt === "24") return true;
    if (opt === "12") return false;
    const own = this._config && this._config.time_format;
    if (own !== undefined) return String(own) !== "12";
    const loc = this._hass && this._hass.locale;
    if (loc && loc.time_format === "12") return false;
    if (loc && loc.time_format === "24") return true;
    try {
      const lang = (loc && loc.time_format === "language" && loc.language) || undefined;
      return !new Intl.DateTimeFormat(lang, { hour: "numeric" }).resolvedOptions().hour12;
    } catch (e) { return true; }
  }

  _fmtMin(min) {
    if (min >= 1440) return this._is24() ? "24:00" : this._tp("time.midnight");
    const h = Math.floor(min / 60) % 24, m = String(min % 60).padStart(2, "0");
    if (this._is24()) return `${String(h).padStart(2, "0")}:${m}`;
    return `${h % 12 === 0 ? 12 : h % 12}:${m} ${h < 12 ? "AM" : "PM"}`;
  }

  _fmtHour(h) { return this._is24() ? String(h).padStart(2, "0") : `${h % 12 === 0 ? 12 : h % 12} ${h < 12 || h === 24 ? "AM" : "PM"}`; }

  // a time from HA; the weekday is added when it isn't today
  _fmtDate(iso) {
    const d = new Date(iso);
    const t = this._fmtMin(d.getHours() * 60 + d.getMinutes());
    return d.toDateString() === new Date().toDateString() ? t : `${this._d(DAYS[(d.getDay() + 6) % 7])} ${t}`;
  }
  getCardSize() { return 6; }
  static getStubConfig() { return {}; }

  set hass(hass) {
    this._hass = hass;
    if (!this._cfg && !this._loading) this._load();
    else this._reloadIfStale();
    this._renderRows();
  }

  async _load() {
    this._loading = true;
    try {
      this._cfg = await this._hass.callWS({ type: "simple_heat_control/config" });
      this._error = "";
    } catch (e) {
      this._error = this._cfg ? this._tp("card.load_error", { error: e.message || e }) : `Couldn't load Simple Heat Control: ${e.message || e}`;
    }
    this._loading = false;
    this._loadedAt = Date.now();
    this._syncEditor();
    this._renderShell();
    this._renderRows();
  }

  // a preset switched elsewhere (an automation, the select entity, another browser) shows up in the
  // rooms' `preset` attribute; reload the schedules then, at most every 10 s
  _reloadIfStale() {
    if (!this._cfg || this._loading || Date.now() - this._loadedAt < 10000) return;
    const stale = this._cfg.rooms.some((r) => {
      const st = this._hass.states[r.climate];
      return st && st.attributes.preset !== undefined && st.attributes.preset !== r.preset;
    });
    if (stale) this._load();
  }

  _today() { return DAYS[(new Date().getDay() + 6) % 7]; }
  _presets() { return (this._cfg && this._cfg.presets) || ["Normal"]; }
  _room(roomId) { return this._cfg.rooms.find((r) => r.room_id === roomId); }
  _week(room, preset) { return (room.schedules && room.schedules[preset]) || room.schedule; }
  _override(room) { const st = this._hass && this._hass.states[room.climate]; return st ? st.attributes.override : null; }
  _dry() {
    const firstRoom = this._cfg.rooms.map((r) => this._hass && this._hass.states[r.climate]).find(Boolean);
    return firstRoom && firstRoom.attributes.dry_run !== undefined ? firstRoom.attributes.dry_run : this._cfg.dry_run;
  }

  _renderShell() {
    const day = this._day || this._today();
    const ready = !!this._cfg;
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .hd { display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
        .title { font-size:16px; font-weight:500; }
        .muted { color: var(--secondary-text-color); font-size:12px; }
        .chips button, .btn { font: inherit; font-size:12px; padding:3px 8px; margin:2px; border-radius:6px; cursor:pointer;
          border:1px solid var(--divider-color); background:transparent; color: var(--primary-text-color); }
        .chips button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
        .chips button.part { border-color: var(--primary-color); }
        .btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
        .btn.danger { background: var(--error-color); color: #fff; border-color: var(--error-color); }
        .btn:disabled { opacity:.45; cursor:default; }
        .ax, .row { display:grid; grid-template-columns: 150px minmax(0,1fr); gap:12px; }
        .ticks { display:flex; justify-content:space-between; font-size:11px; color: var(--secondary-text-color); }
        .row { padding:8px 4px; border-top:1px solid var(--divider-color); cursor:pointer; border-radius:4px; }
        .row:hover, .row.sel { background: var(--secondary-background-color); }
        .name { font-weight:500; font-size:13px; }
        .bar { position:relative; height:24px; border-radius:6px; overflow:hidden; background: var(--secondary-background-color); }
        .bar.sm { height:18px; border-radius:4px; }
        .bar.sm .blk { font-size:10px; }
        .blk { position:absolute; top:0; bottom:0; font-size:11px; display:flex; align-items:center; justify-content:center;
          overflow:hidden; white-space:nowrap; border-right:1px solid var(--card-background-color); }
        .blk.diff { box-shadow: inset 0 0 0 2px var(--primary-text-color); }
        .now { position:absolute; top:0; bottom:0; width:2px; background: var(--primary-text-color); }
        .meta { font-size:12px; color: var(--secondary-text-color); margin-top:3px; display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; }
        .pill { font-size:11px; padding:1px 6px; border-radius:6px; margin-left:4px; white-space:nowrap; }
        .warn { color: var(--error-color); }
        .ok { color: var(--success-color, #2e7d32); font-size:12px; margin-top:4px; }
        .boiler { border-top:1px solid var(--divider-color); padding-top:8px; font-size:13px; }
        .pbar { display:flex; align-items:center; gap:4px; flex-wrap:wrap; margin-bottom:8px; font-size:13px; }
        .ed { border-top:2px solid var(--primary-color); margin-top:8px; padding-top:8px; font-size:13px; }
        .ed table { border-collapse: collapse; margin:6px 0; }
        .ed td { padding:2px 6px 2px 0; }
        input, select, textarea { font: inherit; padding:2px 4px; background: var(--card-background-color); color: var(--primary-text-color);
          border:1px solid var(--divider-color); border-radius:4px; }
        input[type=number] { width:64px; }
        textarea { width:100%; box-sizing:border-box; min-height:70px; font-family: var(--code-font-family, monospace); font-size:12px; }
        .sec { margin:12px 0 4px; font-weight:500; }
        .line { margin:6px 0; display:flex; align-items:center; gap:4px; flex-wrap:wrap; }
        .week { display:grid; grid-template-columns: 52px minmax(0,1fr); gap:3px 8px; align-items:center; margin:6px 0; }
        .week .wl { font-size:12px; cursor:pointer; padding:2px 4px; border-radius:4px; }
        .week .wb { cursor:pointer; border-radius:4px; outline-offset:2px; }
        .week .sel { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .week .wb.sel { background:none; outline:2px solid var(--primary-color); }
        .dot { color: var(--warning-color, #c77700); }
        .pv { border:1px solid var(--warning-color, #c77700); border-radius:8px; padding:8px 10px; margin:8px 0; font-size:13px;
          background: color-mix(in srgb, var(--warning-color, #c77700) 7%, transparent); }
        .op { border:1px solid var(--divider-color); border-radius:8px; padding:8px 10px; margin:8px 0; font-size:13px; }
        .pvt { font-weight:500; margin-bottom:2px; }
        .pvg { display:grid; grid-template-columns: minmax(52px,max-content) minmax(0,1fr) 14px minmax(0,1fr) max-content;
          gap:4px 8px; align-items:center; margin:8px 0; font-size:12px; }
        .pvg .h { color: var(--secondary-text-color); font-size:11px; }
        .pvg .same { opacity:.45; }
        .chg { color: var(--warning-color, #c77700); font-weight:500; }
        .err { color: var(--error-color); font-size:12px; margin-top:4px; }
        .dry { background:#FAEEDA; color:#633806; border-radius:6px; padding:6px 10px; font-size:12px; margin-bottom:8px; }
        .actions { font-size:12px; color: var(--secondary-text-color); font-family: var(--code-font-family, monospace); }
        .mg td { padding:3px 8px 3px 0; }
        @media (max-width: 500px) { .ax, .row { grid-template-columns: 96px minmax(0,1fr); } }
      </style>
      <ha-card>
        <div class="hd">
          <div class="title">${ready ? this._t("card.title") : "Heating"} <span class="muted" id="clock"></span></div>
          <div class="chips" id="days">${DAYS.map((d) => `<button data-day="${d}" class="${d === day ? "on" : ""}">${esc(this._d(d))}</button>`).join("")}
            ${ready ? `<button data-opts="1" class="${this._opts ? "on" : ""}">⚙ ${this._t("opt.button")}</button>` : ""}</div>
        </div>
        <div id="options"></div>
        <div id="dry"></div>
        <div id="presetbar"></div>
        <div id="house"></div>
        <div class="ax"><div></div><div class="ticks">${this._ticks()}</div></div>
        <div id="rows"></div>
        <div class="boiler" id="boiler"></div>
        <div id="editor"></div>
        <div class="err" id="err">${esc(this._error)}</div>
      </ha-card>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("days").addEventListener("click", (e) => {
      if (e.target.closest("button[data-opts]")) {
        this._opts = this._opts ? null : { paste: "", msg: "" };
        this._renderShell(); this._renderRows();
        return;
      }
      const b = e.target.closest("button[data-day]"); if (!b) return;
      this._day = b.dataset.day;
      this.shadowRoot.querySelectorAll("#days button[data-day]").forEach((x) => x.classList.toggle("on", x === b));
      this._renderRows();
      this._renderHouse();
    });
    $("options").addEventListener("click", (e) => this._onOptionsClick(e));
    $("options").addEventListener("change", (e) => this._onOptionsChange(e));
    $("options").addEventListener("input", (e) => {
      if (e.target.id !== "opt-paste" || !this._opts) return;
      this._opts.paste = e.target.value;
      const load = this.shadowRoot.querySelector('#options button[data-o="load"]');
      if (load) load.disabled = !e.target.value.trim();  // no re-render: it would lose the cursor
    });
    $("rows").addEventListener("click", (e) => {
      const r = e.target.closest(".row[data-room]"); if (!r) return;
      this._openEditor(r.dataset.room);
    });
    $("presetbar").addEventListener("click", (e) => this._onPresetBarClick(e));
    $("house").addEventListener("click", (e) => this._onHouseClick(e));
    $("house").addEventListener("change", (e) => this._onHouseChange(e));
    $("house").addEventListener("input", (e) => this._onHouseChange(e));
    this._renderOptions();
    this._renderHouse();
    this._renderEditor();
  }

  _ticks() { return [0, 6, 12, 18, 24].map((h) => `<span>${this._is24() ? h : this._fmtHour(h)}</span>`).join(""); }

  _showError() { const el = this.shadowRoot.getElementById("err"); if (el) el.textContent = this._error; }

  // `other`: blocks to compare with; blocks that aren't in it are outlined (what a copy changes)
  _bars(blocks, { now = false, small = false, other = null } = {}) {
    const minLabel = small ? 180 : 120;
    const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
    const differs = (b) => other && !other.some((o) => o.start === b.start && o.end === b.end && o.temp === b.temp);
    return blocks.map((b) => `<div class="blk${differs(b) ? " diff" : ""}" style="left:${(b.start / 1440) * 100}%;width:${((b.end - b.start) / 1440) * 100}%;background:${tempColor(b.temp)};color:${tempText(b.temp)}" title="${esc(this._fmtMin(b.start))}–${esc(this._fmtMin(b.end))} ${f1(b.temp)}°">${b.end - b.start >= minLabel ? f1(b.temp).replace(".0", "") : ""}</div>`).join("")
      + (now ? `<div class="now" style="left:${(nowMin / 1440) * 100}%"></div>` : "");
  }

  _rowHtml({ id, name, blocks, sub, pill, why, right, clickable, selected }) {
    const showNow = (this._day || this._today()) === this._today();
    return `<div class="row ${selected ? "sel" : ""}" ${clickable ? `data-room="${esc(id)}" title="${this._t("row.edit", { name })}"` : ""}>
      <div><div class="name">${esc(name)}</div><div class="muted">${sub}${pill}</div></div>
      <div><div class="bar">${this._bars(blocks, { now: showNow })}</div>
      <div class="meta"><span>${why}</span><span>${right}</span></div></div></div>`;
  }

  _pill(text, bg, fg) { return `<span class="pill" style="background:${bg};color:${fg}">${esc(text)}</span>`; }

  _renderRows() {
    const rowsEl = this.shadowRoot.getElementById("rows");
    if (!rowsEl || !this._cfg || !this._hass) return;
    const day = this._day || this._today();
    const isToday = day === this._today();
    const now = new Date();
    this.shadowRoot.getElementById("clock").textContent = `${this._d(this._today())} ${this._fmtMin(now.getHours() * 60 + now.getMinutes())}`;

    // live state wins over the value loaded at start (the switch can change it elsewhere)
    this.shadowRoot.getElementById("dry").innerHTML = this._dry()
      ? `<div class="dry"><b>${this._t("dry.title")}</b> · ${this._t("dry.text")}</div>` : "";

    this._renderPresetBar();

    const showPreset = new Set(this._cfg.rooms.map((r) => r.preset)).size > 1;
    const rows = this._cfg.rooms.map((room) => {
      const st = this._hass.states[room.climate];
      const a = st ? st.attributes : {};
      let pill;
      if (!st) pill = this._pill(this._tp("pill.missing"), "var(--error-color)", "#fff");
      else if (st.state === "off") pill = this._pill(this._tp("pill.off"), "var(--secondary-background-color)", "var(--secondary-text-color)");
      else if (a.demand) pill = this._pill(this._tp("pill.heating"), "#FAEEDA", "#633806");
      else pill = this._pill(this._tp("pill.idle"), "var(--secondary-background-color)", "var(--secondary-text-color)");
      if (showPreset) pill += this._pill(room.preset, "transparent", "var(--secondary-text-color)");
      const override = !a.override ? "" : " · " + (a.override.until
        ? this._t("row.override_until", { temp: f1(a.override.temperature), time: this._fmtDate(a.override.until) })
        : this._t("row.override", { temp: f1(a.override.temperature) }));
      const problems = [a.trv_problem, a.last_error].filter(Boolean).map((p) => `<span class="warn">${esc(p)}</span>`).join(" · ");
      const why = isToday ? `${esc(a.reason || "")}${override}${problems ? " · " + problems : ""}` : "";
      const next = a.next_change ? this._t("row.next", { time: this._fmtDate(a.next_change), temp: f1(a.next_target) }) : "";
      const valve = a.valve_position !== null && a.valve_position !== undefined ? this._t("row.valve", { pct: Math.round(a.valve_position) }) : "";
      const trv = a.trv_setpoint !== null && a.trv_setpoint !== undefined ? this._t("row.trv", { temp: f1(a.trv_setpoint) }) : "";
      const right = isToday ? [next, trv, valve].filter(Boolean).join(" · ") : "";
      return this._rowHtml({
        id: room.room_id, name: room.name, blocks: dayBlocks(this._week(room, room.preset)[day]),
        sub: st ? `${f1(st.attributes.current_temperature)}° → ${f1(st.attributes.temperature)}°` : "",
        pill, why, right, clickable: true, selected: this._edit && this._edit.roomId === room.room_id,
      });
    });

    const boiler = this._cfg.boiler;
    const vSt = boiler && this._hass.states[boiler.climate];
    if (vSt && vSt.attributes.time_program_heating) {
      const va = vSt.attributes;
      rows.push(this._rowHtml({
        id: "vaillant", name: "Vaillant", blocks: vaillantBlocks(va.time_program_heating, day),
        sub: `${f1(va.current_temperature)}° → ${f1(va.temperature)}°`,
        pill: this._pill(va.hvac_action || vSt.state, "#E6F1FB", "#0C447C"),
        why: isToday ? this._t("vaillant.why") : "", right: "", clickable: false,
      }));
    }
    rowsEl.innerHTML = rows.join("");

    const actionsEl = this.shadowRoot.querySelector("#editor .actions");
    if (actionsEl && this._edit) {
      const st = this._hass.states[this._room(this._edit.roomId).climate];
      const list = (st && st.attributes.actions) || [];
      actionsEl.innerHTML = list.length ? list.slice().reverse().map((x) => `${esc(x.at)} ${esc(x.text)}`).join("<br>") : this._t("ed.none_yet");
    }

    const bEl = this.shadowRoot.getElementById("boiler");
    const dSt = boiler && this._hass.states[boiler.demand];
    if (!boiler) bEl.innerHTML = `<span class="muted">${this._t("boiler.none")}</span>`;
    else if (!dSt) bEl.innerHTML = `<span class="warn">${this._t("boiler.missing")}</span>`;
    else {
      const b = dSt.attributes;
      const pill = !b.control_enabled ? this._pill(this._tp("pill.control_off"), "var(--error-color)", "#fff")
        : dSt.state === "on" ? this._pill(this._tp("pill.on"), "#FAEEDA", "#633806") : this._pill(this._tp("pill.off"), "var(--secondary-background-color)", "var(--secondary-text-color)");
      const extra = [b.last_call ? this._t("boiler.last", { text: b.last_call }) : "", b.boiler_status ? this._t("boiler.vaillant", { status: b.boiler_status }) : ""].filter(Boolean);
      bEl.innerHTML = `<b>${this._t("boiler.title")}</b>${pill} <span class="muted">${esc(b.reason || "")}${extra.map((x) => " · " + x).join("")}</span>${b.last_error ? ` <span class="warn">${esc(b.last_error)}</span>` : ""}`;
    }
  }

  // ---- options: live/dry run, time format, language, own translation -----------------------------
  _renderOptions() {
    const el = this.shadowRoot.getElementById("options");
    if (!el) return;
    const o = this._opts;
    if (!o || !this._cfg) { el.innerHTML = ""; return; }
    const c = this._cfg, opt = c.options || {};
    const dry = this._dry();
    const timeOpts = [["auto", "opt.time_auto"], ["24", "opt.time_24"], ["12", "opt.time_12"]]
      .map(([v, k]) => `<option value="${v}" ${opt.time_format === v ? "selected" : ""}>${this._t(k)}</option>`).join("");
    const langs = [["auto", this._tp("opt.lang_auto")], ...Object.entries(c.languages || {})];
    if (c.custom) langs.push(["custom", this._tp("opt.lang_custom", { name: c.custom.name })]);
    // temperature sensors HA knows, by name; the chosen one stays listed even if it is gone
    const temps = Object.entries((this._hass && this._hass.states) || {})
      .filter(([id, st]) => id.startsWith("sensor.") && st.attributes && st.attributes.device_class === "temperature")
      .map(([id, st]) => [id, st.attributes.friendly_name || id]);
    if (opt.outdoor_sensor && !temps.some(([id]) => id === opt.outdoor_sensor)) temps.push([opt.outdoor_sensor, opt.outdoor_sensor]);
    temps.sort((a, b) => a[1].localeCompare(b[1]));
    const outdoorOpts = `<option value="">${this._t("opt.room_own")}</option>`
      + temps.map(([id, name]) => `<option value="${esc(id)}" ${opt.outdoor_sensor === id ? "selected" : ""}>${esc(name)}</option>`).join("");
    const langOpts = langs.map(([v, label]) => `<option value="${esc(v)}" ${opt.language === v ? "selected" : ""}>${esc(label)}</option>`).join("");
    el.innerHTML = `<div class="op">
      <div class="hd"><div class="pvt">${this._t("opt.title")}</div><button class="btn" data-o="close">${this._t("card.close")}</button></div>
      <div class="muted">${this._t("opt.shared")}</div>
      <div class="line chips"><span>${this._t("opt.mode")}</span>
        <button data-o="live" class="${dry ? "" : "on"}">${this._t("opt.live")}</button>
        <button data-o="dry" class="${dry ? "on" : ""}">${this._t("opt.dry")}</button></div>
      <div class="muted">${this._t("opt.mode_help")}</div>
      <div class="line"><span>${this._t("opt.time")}</span> <select id="opt-time">${timeOpts}</select></div>
      <div class="line"><span>${this._t("opt.language")}</span> <select id="opt-lang">${langOpts}</select></div>
      <div class="sec">${this._t("opt.heating")}</div>
      <div class="muted">${this._t("opt.heating_help")}</div>
      <div class="line"><span>${this._t("opt.hysteresis")}</span>
        <input type="number" id="opt-hyst" min="0.1" max="2" step="0.1" placeholder="${this._t("opt.room_own")}" value="${opt.hysteresis ?? ""}" style="width:110px"> °C
        ${opt.hysteresis != null ? `<button class="btn" data-o="hyst-clear">${this._t("opt.clear")}</button>` : ""}</div>
      <div class="line"><span>${this._t("opt.outdoor")}</span> <select id="opt-outdoor">${outdoorOpts}</select></div>
      <div class="sec">${this._t("opt.translation")}</div>
      <div class="muted">${this._t("opt.translation_help")}</div>
      <div class="line"><button class="btn" data-o="export-en">${this._t("opt.export_en")}</button>
        <button class="btn" data-o="export-current">${this._t("opt.export_current")}</button>
        <button class="btn" data-o="file">${this._t("opt.load_file")}</button>
        <input type="file" id="opt-file" accept=".json,application/json" hidden>
        ${c.custom ? `<button class="btn" data-o="remove">${this._t("opt.remove")}</button>` : ""}</div>
      <div class="muted">${this._t("opt.paste")}</div>
      <textarea id="opt-paste" spellcheck="false">${esc(o.paste)}</textarea>
      <div class="line"><button class="btn primary" data-o="load" ${o.paste.trim() ? "" : "disabled"}>${this._t("opt.load")}</button></div>
      ${o.msg ? `<div class="ok">${o.msg}</div>` : ""}
    </div>`;
  }

  // new options and texts from the integration: everything is drawn again in the new language
  _applyTexts(res) {
    for (const k of ["options", "language", "strings", "languages", "custom"]) this._cfg[k] = res[k];
    this._renderShell();
    this._renderRows();
  }

  async _setOptions(msg) {
    const res = await this._hass.callWS({ type: "simple_heat_control/options/set", ...msg });
    return res;
  }

  async _loadTranslation(text) {
    let data;
    try { data = JSON.parse(text); } catch (e) {
      this._error = this._tp("opt.bad_json", { error: e.message }); this._showError(); return;
    }
    const res = await this._setOptions({ translation: data, language: "custom" });
    this._opts.paste = "";
    this._applyTexts(res);  // texts are now the new language, so the report is written in it
    const r = res.report || {};
    const lines = [this._t("opt.loaded")];
    if (r.missing && r.missing.length) lines.push(this._t("opt.missing", { n: r.missing.length }));
    if (r.unknown && r.unknown.length) lines.push(this._t("opt.unknown", { keys: r.unknown.join(", ") }));
    this._opts.msg = lines.join(" ");
    this._renderOptions();
  }

  async _onOptionsChange(e) {
    const t = e.target;
    this._error = "";
    try {
      if (t.id === "opt-time") this._applyTexts(await this._setOptions({ time_format: t.value }));
      else if (t.id === "opt-lang") this._applyTexts(await this._setOptions({ language: t.value }));
      else if (t.id === "opt-hyst") this._applyTexts(await this._setOptions({ hysteresis: t.value === "" ? null : Number(t.value) }));
      else if (t.id === "opt-outdoor") this._applyTexts(await this._setOptions({ outdoor_sensor: t.value || null }));
      else if (t.id === "opt-file" && t.files && t.files[0]) await this._loadTranslation(await t.files[0].text());
    } catch (err) { this._error = err.message || String(err); }
    this._showError();
  }

  async _onOptionsClick(e) {
    const b = e.target.closest("button[data-o]"); if (!b) return;
    const act = b.dataset.o;
    this._error = "";
    try {
      if (act === "close") { this._opts = null; this._renderShell(); this._renderRows(); return; }
      if (act === "file") { this.shadowRoot.getElementById("opt-file").click(); return; }
      if (act === "live" || act === "dry") {
        const want = act === "dry";
        if (want === this._dry()) return;
        if (!want && !confirm(this._tp("opt.confirm_live"))) return;
        const res = await this._hass.callWS({ type: "simple_heat_control/dry_run/set", dry_run: want });
        this._cfg.dry_run = res.dry_run;
        this._renderRows();
      } else if (act === "export-en" || act === "export-current") {
        const all = await this._hass.callWS({ type: "simple_heat_control/translations" });
        const code = this._cfg.language;
        if (act === "export-en") download("simple-heat-control-en.json", all.builtin.en);
        else if (code === "custom" && all.custom) download(`simple-heat-control-${all.custom._language || "custom"}.json`, all.custom);
        else download(`simple-heat-control-${code}.json`, all.builtin[code] || all.builtin.en);
        return;
      } else if (act === "load") await this._loadTranslation(this._opts.paste);
      else if (act === "hyst-clear") this._applyTexts(await this._setOptions({ hysteresis: null }));
      else if (act === "remove") { this._applyTexts(await this._setOptions({ translation: null })); this._opts.msg = ""; }
    } catch (err) { this._error = err.message || String(err); }
    this._renderOptions();
    this._showError();
  }

  // ---- before/after preview, used for every copy, discard and preset switch ---------------------
  // p = {title (html), note (html), head: [left, right], rows: [{label, before, after, note}], ok, danger, run}
  _previewHtml(p) {
    const rows = p.rows.map((r) => {
      const unchanged = same(r.before, r.after);
      const before = dayBlocks(r.before), after = dayBlocks(r.after);
      const note = r.note !== undefined ? r.note : unchanged ? `<span class="muted">${this._t("preview.no_change")}</span>` : `<span class="chg">${this._t("preview.replaced")}</span>`;
      return `<div class="${unchanged ? "same" : ""}">${esc(r.label)}</div>
        <div class="bar sm ${unchanged ? "same" : ""}">${this._bars(before, { small: true, other: after })}</div>
        <div class="muted ${unchanged ? "same" : ""}">→</div>
        <div class="bar sm ${unchanged ? "same" : ""}">${this._bars(after, { small: true, other: before })}</div>
        <div>${note}</div>`;
    }).join("");
    const [left, right] = p.head || [this._tp("preview.now"), this._tp("preview.after")];
    return `<div class="pv">
      <div class="pvt">${p.title}</div>${p.note ? `<div class="muted">${p.note}</div>` : ""}
      <div class="muted">${this._t("preview.outlined")}</div>
      <div class="pvg"><div></div><div class="h">${esc(left)}</div><div></div><div class="h">${esc(right)}</div><div></div>${rows}</div>
      <button class="btn ${p.danger ? "danger" : "primary"}" data-pv="ok">${esc(p.ok)}</button>
      <button class="btn" data-pv="cancel">${this._t("card.cancel")}</button></div>`;
  }

  // ---- presets: bar, switch preview, manager ------------------------------------------------------
  _renderPresetBar() {
    const el = this.shadowRoot.getElementById("presetbar");
    if (!el || !this._cfg) return;
    const rooms = this._cfg.rooms;
    const used = (p) => rooms.filter((r) => r.preset === p);
    const chips = this._presets().map((p) => {
      const n = used(p).length;
      const cls = rooms.length && n === rooms.length ? "on" : n ? "part" : "";
      const title = (n ? this._tp("preset.used_by", { rooms: used(p).map((r) => r.name).join(", ") }) : this._tp("preset.unused"))
        + " · " + this._tp("preset.click");
      return `<button class="${cls}" data-hp="${esc(p)}" title="${esc(title)}">${esc(p)}${cls === "part" ? ` <span class="muted">${n}/${rooms.length}</span>` : ""}</button>`;
    }).join("");
    el.innerHTML = `<div class="pbar chips"><span class="muted">${this._t("preset.house")}</span>${chips}
      <button class="btn" data-hp-manage="1">${this._t("preset.manage")}</button></div>`;
  }

  _onPresetBarClick(e) {
    if (e.target.closest("[data-hp-manage]")) {
      this._house = this._house && this._house.mode === "manage" ? null
        : { mode: "manage", rename: null, del: null, name: "", from: `copy:${this._presets()[0]}`, temp: 16 };
    } else {
      const b = e.target.closest("button[data-hp]"); if (!b) return;
      this._house = { mode: "switch", to: b.dataset.hp };
    }
    this._error = ""; this._showError();
    this._renderHouse();
  }

  _renderHouse() {
    const el = this.shadowRoot.getElementById("house");
    if (!el) return;
    const h = this._house;
    if (!h || !this._cfg) { el.innerHTML = ""; return; }
    if (h.mode === "switch") { el.innerHTML = this._switchPreview(h.to); return; }

    const presets = this._presets();
    const users = (p) => this._cfg.rooms.filter((r) => r.preset === p).map((r) => r.name);
    const list = presets.map((p) => {
      const u = users(p);
      if (h.rename === p) {
        return `<tr><td colspan="3"><input id="rnname" value="${esc(h.renameTo ?? p)}" maxlength="30">
          <button class="btn primary" data-mg="rename-ok" data-p="${esc(p)}">${this._t("manage.rename")}</button>
          <button class="btn" data-mg="cancel">${this._t("card.cancel")}</button>
          <div class="muted">${this._t("manage.rename_note", { name: p })}</div></td></tr>`;
      }
      if (h.del === p) {
        return `<tr><td colspan="3">${this._t("manage.delete_q", { name: bold(p) })}
          <button class="btn danger" data-mg="delete-ok" data-p="${esc(p)}">${this._t("manage.delete")}</button>
          <button class="btn" data-mg="cancel">${this._t("card.cancel")}</button></td></tr>`;
      }
      const why = presets.length === 1 ? this._tp("manage.cant_last") : u.length ? this._tp("manage.cant_used") : "";
      return `<tr><td><b>${esc(p)}</b></td><td class="muted">${u.length ? this._t("manage.used_by", { rooms: u.join(", ") }) : this._t("manage.not_used")}</td>
        <td><button class="btn" data-mg="rename" data-p="${esc(p)}">${this._t("manage.rename")}</button>
        <button class="btn" data-mg="delete" data-p="${esc(p)}" ${why ? `disabled title="${esc(why)}"` : ""}>${this._t("manage.delete")}</button></td></tr>`;
    }).join("");
    const fromOpts = presets.map((p) => `<option value="copy:${esc(p)}" ${h.from === `copy:${p}` ? "selected" : ""}>${this._t("manage.from_copy", { name: p })}</option>`).join("")
      + `<option value="flat" ${h.from === "flat" ? "selected" : ""}>${this._t("manage.from_flat")}</option>`;
    el.innerHTML = `<div class="pv">
      <div class="hd"><div class="pvt">${this._t("manage.title")}</div><button class="btn" data-mg="close">${this._t("card.close")}</button></div>
      <div class="muted">${this._t("manage.help")}</div>
      <table class="mg">${list}</table>
      <div class="sec">${this._t("manage.new")}</div>
      <div class="line"><input id="newname" placeholder="${this._t("manage.placeholder")}" maxlength="30" value="${esc(h.name)}">
        ${this._t("manage.starting_as")} <select id="newfrom">${fromOpts}</select>
        ${h.from === "flat" ? `<input type="number" id="newtemp" min="5" max="30" step="0.5" value="${h.temp}"> °C` : ""}
        <button class="btn primary" data-mg="create">${this._t("manage.create")}</button></div>
      <div class="muted">${this._t("manage.automation")}</div>
    </div>`;
  }

  _switchPreview(to) {
    const day = this._day || this._today();
    const rooms = this._cfg.rooms;
    const changing = rooms.filter((r) => r.preset !== to);
    const rows = rooms.map((r) => {
      const ov = r.preset !== to && this._override(r);
      const note = r.preset === to ? `<span class="muted">${this._t("switch.already", { name: to })}</span>`
        : `<span class="chg">${esc(r.preset)} → ${esc(to)}</span>${ov ? ` <span class="warn">${this._t("switch.override_cleared", { temp: f1(ov.temperature) })}</span>` : ""}`;
      return { label: r.name, before: this._week(r, r.preset)[day], after: this._week(r, to)[day], note };
    });
    if (!changing.length) {
      return `<div class="pv"><div class="pvt">${this._t("switch.all_already", { name: to })}</div>
        <button class="btn" data-pv="cancel">${this._t("card.close")}</button></div>`;
    }
    return this._previewHtml({
      title: this._t("switch.title", { name: bold(to) }),
      note: this._t("switch.note", { day: this._d(day) }),
      head: [this._tp("preview.now"), to], rows, ok: this._tp("switch.ok", { n: changing.length }),
    });
  }

  _onHouseChange(e) {
    const h = this._house; if (!h || h.mode !== "manage") return;
    const t = e.target;
    if (t.id === "newname") h.name = t.value;
    else if (t.id === "newtemp") h.temp = Number(t.value);
    else if (t.id === "rnname") h.renameTo = t.value;
    else if (t.id === "newfrom" && e.type === "change") { h.from = t.value; this._renderHouse(); }
  }

  async _onHouseClick(e) {
    const h = this._house; if (!h) return;
    const pv = e.target.closest("button[data-pv]");
    const mg = e.target.closest("button[data-mg]");
    if (!pv && !mg) return;
    this._error = "";
    try {
      if (pv && pv.dataset.pv === "cancel") this._house = null;
      else if (pv) {
        await this._hass.callWS({ type: "simple_heat_control/preset/activate", name: h.to });
        this._house = null;
        await this._load();
      } else {
        const act = mg.dataset.mg, p = mg.dataset.p;
        if (act === "close") this._house = null;
        else if (act === "cancel") { h.rename = null; h.del = null; }
        else if (act === "rename") { h.rename = p; h.renameTo = p; h.del = null; }
        else if (act === "delete") { h.del = p; h.rename = null; }
        else if (act === "rename-ok") {
          const res = await this._hass.callWS({ type: "simple_heat_control/preset/rename", name: p, new_name: h.renameTo || "" });
          if (this._edit && this._edit.preset === p) this._edit.preset = res.name;
          h.rename = null;
          await this._load();
        } else if (act === "delete-ok") {
          await this._hass.callWS({ type: "simple_heat_control/preset/delete", name: p });
          h.del = null;
          await this._load();
        } else if (act === "create") {
          const msg = { type: "simple_heat_control/preset/create", name: h.name };
          if (h.from === "flat") msg.temperature = h.temp; else msg.copy_from = h.from.slice(5);
          await this._hass.callWS(msg);
          h.name = "";
          await this._load();
        }
      }
    } catch (err) { this._error = err.message || String(err); }
    this._showError();
    this._renderHouse();
    this._renderRows();
  }

  // ---- room editor ------------------------------------------------------------------------------
  // _edit = {roomId, preset, day, draft, saved, pending, copyDays, copyRoom, copyPreset, notice}
  // draft is the week being edited for (room, preset); saved is that week as stored
  _startEdit(roomId, preset) {
    const room = this._room(roomId);
    preset = preset || room.preset;
    const saved = clone(this._week(room, preset));
    const prev = this._edit && this._edit.roomId === roomId ? this._edit : null;
    this._edit = {
      roomId, preset, day: (prev && prev.day) || this._day || this._today(), draft: clone(saved), saved,
      pending: null, copyDays: [], notice: "", copyPreset: null,
      copyRoom: (this._cfg.rooms.find((r) => r.room_id !== roomId) || room).room_id,
    };
  }

  _dirtyDays() { const ed = this._edit; return ed ? DAYS.filter((d) => !same(ed.draft[d], ed.saved[d])) : []; }

  // ask before throwing away unsaved changes; `then` runs when there are none or the user agrees
  _guard(then) {
    const dirty = this._dirtyDays();
    if (!dirty.length) { then(); return; }
    const ed = this._edit, room = this._room(ed.roomId);
    ed.pending = {
      title: this._t("discard.title", { room: room.name, preset: ed.preset }),
      head: [this._tp("discard.yours"), this._tp("discard.saved")],
      rows: dirty.map((d) => ({ label: this._d(d), before: ed.draft[d], after: ed.saved[d] })),
      ok: this._tp("discard.ok"), danger: true, run: async () => then(),
    };
  }

  _openEditor(roomId) {
    if (this._edit && this._edit.roomId === roomId) {
      this._guard(() => { this._edit = null; });
    } else if (this._edit) {
      this._guard(() => this._startEdit(roomId));
    } else this._startEdit(roomId);
    this._error = "";
    this._renderEditor();
    this._renderRows();
  }

  // after a reload: follow renames/deletes and pick up a newly saved week if nothing is being edited
  _syncEditor() {
    const ed = this._edit; if (!ed || !this._cfg) return;
    const room = this._room(ed.roomId);
    if (!room || !this._presets().includes(ed.preset)) { this._edit = null; return; }
    const saved = clone(this._week(room, ed.preset));
    if (!this._dirtyDays().length) ed.draft = clone(saved);
    ed.saved = saved;
  }

  _renderEditor() {
    const el = this.shadowRoot.getElementById("editor");
    if (!el) return;
    const ed = this._edit;
    if (!ed) { el.innerHTML = ""; return; }
    const room = this._room(ed.roomId);
    const st = this._hass && this._hass.states[room.climate];
    const a = st ? st.attributes : {};
    const presets = this._presets();
    const day = ed.day;
    const blocks = dayBlocks(ed.draft[day]);
    const dirty = this._dirtyDays();
    const copyPreset = ed.copyPreset || ed.preset;
    const copySelf = ed.copyRoom === ed.roomId && copyPreset === ed.preset;

    const presetChips = presets.map((p) => `<button data-epreset="${esc(p)}" class="${p === ed.preset ? "on" : ""}" title="${this._t(p === room.preset ? "ed.follows_title" : "ed.edit_title")}">${esc(p)}${p === room.preset ? " ✓" : ""}</button>`).join("");
    const presetNote = ed.preset === room.preset
      ? this._t("ed.follows", { room: room.name, preset: bold(ed.preset) })
      : `${this._t("ed.editing_other", { room: room.name, active: bold(room.preset), preset: bold(ed.preset) })}
         <button class="btn" data-act="use">${this._t("ed.use", { preset: ed.preset, room: room.name })}</button>`;

    const week = DAYS.map((d) => `<div class="wl ${d === day ? "sel" : ""}" data-wday="${d}">${esc(this._d(d))}${dirty.includes(d) ? ` <span class="dot" title="${this._t("ed.changed")}">●</span>` : ""}</div>
      <div class="bar sm wb ${d === day ? "sel" : ""}" data-wday="${d}">${this._bars(dayBlocks(ed.draft[d]), { small: true })}</div>`).join("");

    const table = blocks.map((b, i) => `<tr>
        <td>${i === 0 ? `<span class="muted">${esc(this._fmtMin(0))}</span>` : this._timeSelects(i, b.start)}</td>
        <td class="muted">– ${esc(this._fmtMin(b.end))}</td>
        <td><button class="btn" data-act="dec" data-i="${i}" title="−0.5°">−</button><input type="number" data-i="${i}" data-f="v" value="${b.temp}" min="5" max="30" step="0.5"><button class="btn" data-act="inc" data-i="${i}" title="+0.5°">+</button> °C</td>
        <td>${i === 0 ? "" : `<button class="btn" data-act="del" data-i="${i}">${this._t("ed.remove")}</button>`}</td></tr>`).join("");

    const others = DAYS.filter((d) => d !== day);
    const roomOpts = this._cfg.rooms.map((r) => `<option value="${esc(r.room_id)}" ${r.room_id === ed.copyRoom ? "selected" : ""}>${r.room_id === ed.roomId ? this._t("ed.this_room", { name: r.name }) : esc(r.name)}</option>`).join("");
    const presetOpts = presets.map((p) => `<option value="${esc(p)}" ${p === copyPreset ? "selected" : ""}>${esc(p)}</option>`).join("");
    const ovText = !a.override ? this._t("ed.override_none")
      : a.override.until ? this._t("ed.override_until", { temp: f1(a.override.temperature), time: this._fmtDate(a.override.until) })
      : this._t("ed.override_forever", { temp: f1(a.override.temperature) });

    el.innerHTML = `<div class="ed">
      <div class="hd"><div class="title">${esc(room.name)}</div><button class="btn" data-act="close">${this._t("card.close")}</button></div>
      <div class="sec">${this._t("ed.override")}</div>
      <div>${ovText}</div>
      <div class="line"><input type="number" id="ovt" min="5" max="30" step="0.5" value="${a.override ? a.override.temperature : (a.schedule_target ?? 21)}"> °C
        <button class="btn" data-act="ov-next">${this._t("ed.until_next")}</button>
        <button class="btn" data-act="ov-forever">${this._t("ed.until_clear")}</button>
        ${a.override ? `<button class="btn" data-act="ov-clear">${this._t("ed.back")}</button>` : ""}
        <button class="btn" data-act="power">${this._t(st && st.state === "off" ? "ed.turn_on" : "ed.turn_off")}</button></div>
      <div class="sec">${this._t("ed.recent")}</div>
      <div class="actions">${(a.actions || []).length ? a.actions.slice().reverse().map((x) => `${esc(x.at)} ${esc(x.text)}`).join("<br>") : this._t("ed.none_yet")}</div>

      <div class="sec">${this._t("ed.schedule")}</div>
      <div class="chips line"><span class="muted">${this._t("ed.preset")}</span>${presetChips}</div>
      <div class="muted">${presetNote}</div>
      <div class="week"><div></div><div class="ticks">${this._ticks()}</div>${week}</div>
      ${ed.pending ? this._previewHtml(ed.pending) : ""}

      <div class="sec">${esc(this._d(day))} <span class="muted">· ${this._t("ed.day_hint")}</span></div>
      <table>${table}</table>
      <div class="line"><button class="btn" data-act="add">${this._t("ed.add")}</button><span class="muted">${this._t("ed.add_hint")}</span></div>

      <div class="line chips"><span class="muted">${this._t("ed.copy_day", { day: this._d(day) })}</span>
        ${others.map((d) => `<button data-cday="${d}" class="${ed.copyDays.includes(d) ? "on" : ""}">${esc(this._d(d))}</button>`).join("")}
        <span class="muted">·</span>
        <button data-cq="work">${this._t("ed.q_work")}</button><button data-cq="weekend">${this._t("ed.q_weekend")}</button><button data-cq="all">${this._t("ed.q_all")}</button><button data-cq="none">${this._t("ed.q_none")}</button>
        <button class="btn primary" data-act="copyday" ${ed.copyDays.length ? "" : "disabled"}>${this._t("ed.preview")}</button></div>
      <div class="line"><span class="muted">${this._t("ed.copy_week")}</span>
        <select id="cproom">${roomOpts}</select> <span class="muted">${this._t("ed.in_preset")}</span> <select id="cppreset">${presetOpts}</select>
        <button class="btn primary" data-act="copyweek" ${copySelf ? `disabled title="${this._t("ed.copy_self")}"` : ""}>${this._t("ed.preview")}</button></div>

      <div class="line"><button class="btn primary" data-act="save" ${dirty.length ? "" : "disabled"}>${this._t("ed.save", { preset: ed.preset })}</button>
        <button class="btn" data-act="revert" ${dirty.length ? "" : "disabled"}>${this._t("ed.discard")}</button>
        ${dirty.length ? `<span class="muted"><span class="dot">●</span> ${this._t("ed.not_saved", { days: this._days(dirty) })}</span>` : ""}</div>
      ${ed.notice ? `<div class="ok">${esc(ed.notice)}</div>` : ""}
    </div>`;
    el.onclick = (e) => this._onEditorClick(e);
    el.onchange = (e) => this._onEditorChange(e);
    this._showError();
  }

  // hour + minute dropdowns: the browser's time input ignores HA's 12/24 h setting
  _timeSelects(i, min) {
    const h = Math.floor(min / 60), m = min % 60;
    const minutes = [...new Set([...Array(12).keys()].map((x) => x * 5).concat([m]))].sort((a, b) => a - b);
    const hours = [...Array(24).keys()].map((x) => `<option value="${x}" ${x === h ? "selected" : ""}>${this._fmtHour(x)}</option>`).join("");
    const mins = minutes.map((x) => `<option value="${x}" ${x === m ? "selected" : ""}>${String(x).padStart(2, "0")}</option>`).join("");
    return `<select data-i="${i}" data-f="h">${hours}</select> : <select data-i="${i}" data-f="m">${mins}</select>`;
  }

  _onEditorChange(e) {
    const ed = this._edit; const t = e.target;
    if (t.id === "cproom") { ed.copyRoom = t.value; this._renderEditor(); return; }
    if (t.id === "cppreset") { ed.copyPreset = t.value; this._renderEditor(); return; }
    if (t.dataset.i === undefined) return;
    ed.pending = null;  // a preview made before this edit would show the old draft
    const pts = ed.draft[ed.day];
    const i = Number(t.dataset.i);
    this._error = "";
    if (t.dataset.f === "h" || t.dataset.f === "m") {
      const old = toMin(pts[i][0]);
      const next = t.dataset.f === "h" ? Number(t.value) * 60 + (old % 60) : Math.floor(old / 60) * 60 + Number(t.value);
      if (next === 0 || pts.some(([x], j) => j !== i && toMin(x) === next)) {
        this._error = this._tp("err.block_exists", { time: this._fmtMin(next) });
        this._renderEditor();
        return;
      }
      pts[i][0] = hhmm(next);
    } else {
      const v = Number(t.value);
      if (isNaN(v) || v < 5 || v > 30) this._error = this._tp("err.temp_range");
      else pts[i][1] = Math.round(v * 2) / 2;
    }
    pts.sort((x, y) => toMin(x[0]) - toMin(y[0]));
    ed.notice = "";
    this._renderEditor(); this._renderRows();
  }

  _copyDaysPreview() {
    const ed = this._edit, src = ed.day;
    const targets = DAYS.filter((d) => ed.copyDays.includes(d));
    const n = targets.filter((d) => !same(ed.draft[d], ed.draft[src])).length;
    ed.pending = {
      title: this._t("copyday.title", { day: this._d(src), days: this._days(targets) }),
      note: n ? this._t("copyday.note", { n }) : this._t("copyday.same"),
      rows: targets.map((d) => ({ label: this._d(d), before: ed.draft[d], after: ed.draft[src] })),
      ok: n ? this._tp("replace.days", { n }) : this._tp("card.ok"),
      run: async () => {
        targets.forEach((d) => { ed.draft[d] = clone(ed.draft[src]); });
        ed.copyDays = [];
        ed.notice = n ? this._tp("copyday.done", { day: this._d(src), days: this._days(targets) }) : "";
      },
    };
  }

  _copyWeekPreview() {
    const ed = this._edit, room = this._room(ed.roomId);
    const target = this._room(ed.copyRoom), preset = ed.copyPreset || ed.preset;
    const before = this._week(target, preset);
    const n = DAYS.filter((d) => !same(before[d], ed.draft[d])).length;
    const live = target.preset === preset;
    const notes = [this._t("copyweek.note", { target: target.name, preset })];
    if (live) notes.push(this._t("copyweek.note_live", { target: target.name, preset }));
    if (this._dirtyDays().length) notes.push(this._t("copyweek.unsaved", { room: room.name, days: this._days(this._dirtyDays()) }));
    ed.pending = {
      title: this._t("copyweek.title", { room: room.name, preset: ed.preset, target: bold(target.name), target_preset: bold(preset) }),
      note: notes.join(" "),
      head: [this._tp("copyweek.head_now", { target: target.name }), this._tp("preview.after")],
      rows: DAYS.map((d) => ({ label: this._d(d), before: before[d], after: ed.draft[d] })),
      ok: n ? this._tp("replace.days", { n }) : this._tp("copyweek.nothing"),
      run: async () => {
        if (!n) return;
        const res = await this._hass.callWS({ type: "simple_heat_control/schedule/set", room_id: target.room_id, preset, schedule: ed.draft });
        target.schedules = { ...(target.schedules || {}), [preset]: res.schedule };
        if (live) target.schedule = res.schedule;
        if (target.room_id === ed.roomId && preset === ed.preset) ed.saved = clone(res.schedule);
        ed.notice = this._tp("copyweek.done", { target: target.name, preset });
      },
    };
  }

  _usePresetPreview() {
    const ed = this._edit, room = this._room(ed.roomId);
    const ov = this._override(room);
    const notes = [];
    if (ov) notes.push(this._t("use.override", { temp: f1(ov.temperature) }));
    if (this._dirtyDays().length) notes.push(this._t("use.unsaved"));
    ed.pending = {
      title: this._t("use.title", { room: room.name, from: room.preset, to: bold(ed.preset) }),
      note: notes.join(" "),
      head: [room.preset, ed.preset],
      rows: DAYS.map((d) => ({ label: this._d(d), before: this._week(room, room.preset)[d], after: ed.saved[d] })),
      ok: this._tp("use.ok", { preset: ed.preset }),
      run: async () => {
        await this._hass.callWS({ type: "simple_heat_control/preset/activate", name: ed.preset, room_id: room.room_id });
        ed.notice = this._tp("use.done", { room: room.name, preset: ed.preset });
        await this._load();
      },
    };
  }

  async _onEditorClick(e) {
    const ed = this._edit;
    const wday = e.target.closest("[data-wday]");
    if (wday) { ed.day = wday.dataset.wday; ed.copyDays = []; this._renderEditor(); return; }
    const ep = e.target.closest("button[data-epreset]");
    if (ep) {
      const p = ep.dataset.epreset;
      if (p !== ed.preset) this._guard(() => { const keep = ed.day; this._startEdit(ed.roomId, p); this._edit.day = keep; });
      this._renderEditor(); this._renderRows(); return;
    }
    const cd = e.target.closest("button[data-cday]");
    if (cd) {
      const d = cd.dataset.cday;
      ed.copyDays = ed.copyDays.includes(d) ? ed.copyDays.filter((x) => x !== d) : [...ed.copyDays, d];
      this._renderEditor(); return;
    }
    const cq = e.target.closest("button[data-cq]");
    if (cq) {
      const set = { work: WORKDAYS, weekend: WEEKEND, all: DAYS, none: [] }[cq.dataset.cq];
      ed.copyDays = set.filter((d) => d !== ed.day);
      this._renderEditor(); return;
    }
    const pv = e.target.closest("button[data-pv]");
    if (pv) {
      const p = ed.pending;
      ed.pending = null;
      this._error = "";
      if (pv.dataset.pv === "ok" && p) {
        try { await p.run(); } catch (err) { this._error = err.message || String(err); }
      }
      this._renderEditor(); this._renderRows(); return;
    }

    const b = e.target.closest("button[data-act]"); if (!b) return;
    const act = b.dataset.act;
    const room = this._room(ed.roomId);
    const pts = ed.draft[ed.day];
    const ovt = () => Number(this.shadowRoot.getElementById("ovt").value);
    this._error = "";
    ed.pending = null;  // the actions below either change the draft or open a new preview
    if (!["copyday", "copyweek", "use", "revert"].includes(act)) ed.notice = "";
    try {
      if (act === "close") this._guard(() => { this._edit = null; });
      else if (act === "add") {
        const longest = dayBlocks(pts).reduce((x, y) => (y.end - y.start > x.end - x.start ? y : x));
        const mid = longest.start + Math.round((longest.end - longest.start) / 2 / 30) * 30;
        if (longest.end - longest.start < 60 || mid <= longest.start || mid >= longest.end) this._error = this._tp("err.no_split");
        else { pts.push([hhmm(mid), longest.temp]); pts.sort((x, y) => toMin(x[0]) - toMin(y[0])); }
      }
      else if (act === "del") pts.splice(Number(b.dataset.i), 1);
      else if (act === "inc" || act === "dec") {
        const i = Number(b.dataset.i);
        pts[i][1] = Math.min(30, Math.max(5, pts[i][1] + (act === "inc" ? 0.5 : -0.5)));
      }
      else if (act === "copyday") this._copyDaysPreview();
      else if (act === "copyweek") this._copyWeekPreview();
      else if (act === "use") this._usePresetPreview();
      else if (act === "revert") this._guard(() => { ed.draft = clone(ed.saved); });
      else if (act === "save") {
        const res = await this._hass.callWS({ type: "simple_heat_control/schedule/set", room_id: room.room_id, preset: ed.preset, schedule: ed.draft });
        room.schedules = { ...(room.schedules || {}), [ed.preset]: res.schedule };
        if (room.preset === ed.preset) room.schedule = res.schedule;
        ed.saved = clone(res.schedule);
        ed.draft = clone(res.schedule);
        ed.notice = this._tp("ed.saved", { preset: ed.preset });
      }
      else if (act === "ov-next") await this._hass.callWS({ type: "simple_heat_control/override/set", room_id: room.room_id, temperature: ovt() });
      else if (act === "ov-forever") await this._hass.callWS({ type: "simple_heat_control/override/set", room_id: room.room_id, temperature: ovt(), until: null });
      else if (act === "ov-clear") await this._hass.callWS({ type: "simple_heat_control/override/clear", room_id: room.room_id });
      else if (act === "power") {
        const st = this._hass.states[room.climate];
        await this._hass.callService("climate", "set_hvac_mode", { entity_id: room.climate, hvac_mode: st && st.state === "off" ? "heat" : "off" });
      }
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._renderEditor();
    this._renderRows();
  }
}

if (!customElements.get("simple-heat-control-card")) {
  customElements.define("simple-heat-control-card", SimpleHeatControlCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "simple-heat-control-card", name: "Simple Heat Control", description: "Room heating timeline, reasons, presets and schedule editor" });
}
