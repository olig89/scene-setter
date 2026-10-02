// Scene Setter: the sidebar page and the dashboard card, in one file.
// Plain web components: no build step, no dependencies.
//
// The rooms come from one websocket subscription (scene_setter/subscribe), shared by
// every card on the page. Changes go through scene_setter/save, rename, delete and
// (administrators only) save_room. Lights and blinds are read live from Home Assistant.

// Must match manifest.json (a test checks). Compared with the running integration so a
// tab still holding old page code after an update says so.
const PAGE_VERSION = "0.1.2";

const ERRORS = {
  invalid_name: null, // the server's own words are right
  name_taken: null,
  nothing_to_save: null,
  not_editable: null,
  not_in_file: null,
  not_loaded: null,
  unknown_room: "That room no longer exists. Reload the page.",
  unknown_scene: "That scene no longer exists.",
  unauthorized: "Only an administrator can change this.",
  not_set_up: "Scene Setter isn't set up. Add it under Settings → Devices & services.",
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
const sameName = (a, b) => a.trim().replace(/\s+/g, " ").toLowerCase() === b.trim().replace(/\s+/g, " ").toLowerCase();

function loadPref(key, fallback) {
  try {
    const v = localStorage.getItem("scene-setter:" + key);
    return v === null ? fallback : JSON.parse(v);
  } catch (e) {
    return fallback;
  }
}
function savePref(key, value) {
  try {
    localStorage.setItem("scene-setter:" + key, JSON.stringify(value));
  } catch (e) {
    /* private window or storage blocked: the view just won't be remembered */
  }
}

// ---- one subscription for the whole page ------------------------------------------

const feed = {
  data: null,
  error: null,
  listeners: new Set(),
  unsub: null,
  connection: null,
  attach(hass, listener) {
    this.listeners.add(listener);
    if (this.unsub && this.connection === hass.connection) return;
    this.connection = hass.connection;
    this.unsub = hass.connection
      .subscribeMessage(
        (data) => {
          this.data = data;
          this.error = null;
          this.listeners.forEach((l) => l());
        },
        { type: "scene_setter/subscribe" }
      )
      .catch((err) => {
        this.error = err.message || String(err);
        this.unsub = null;
        this.listeners.forEach((l) => l());
      });
  },
  detach(listener) {
    this.listeners.delete(listener);
    if (this.listeners.size || !this.unsub) return;
    this.unsub.then((u) => u && u()).catch(() => {});
    this.unsub = null;
  },
};

// ---- shared by the page and the card ----------------------------------------------

class SceneSetterBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dialog = null; // {kind, room, scene, value, error, busy}
    this._settings = false; // the room's settings are open (page only)
    this._pressed = null; // scene just turned on (for a moment)
    this._shown = "";
    this._onFeed = () => this._render();
    this._onKey = (e) => {
      if (e.key === "Escape" && this._dialog && !this._dialog.busy) this._closeDialog();
    };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      if (this.isConnected) feed.attach(hass, this._onFeed);
      this._render();
      return;
    }
    this._afterHass();
    // Lights change all the time: redraw only when something shown has changed,
    // and never under an open dialog or a control that is being used.
    if (this._dialog || this._busyControl()) return;
    if (this._signature() !== this._shown) this._render();
  }

  _afterHass() {}

  connectedCallback() {
    if (this._hass) feed.attach(this._hass, this._onFeed);
    window.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    feed.detach(this._onFeed);
    window.removeEventListener("keydown", this._onKey);
  }

  get _admin() {
    return !!this._hass?.user?.is_admin;
  }

  _busyControl() {
    const el = this.shadowRoot.activeElement;
    return !!el && (el.tagName === "SELECT" || el.tagName === "INPUT");
  }

  _rooms() {
    return feed.data?.rooms || [];
  }

  _room(areaId) {
    return this._rooms().find((r) => r.area_id === areaId) || null;
  }

  _visibleRooms() {
    return this._rooms();
  }

  // Everything on screen that can change without the server saying so.
  _signature() {
    const parts = [this._pressed || ""];
    for (const room of this._visibleRooms()) {
      for (const e of room.entities) {
        const s = this._hass.states[e.entity_id];
        const a = s?.attributes || {};
        parts.push(
          e.entity_id,
          s?.state,
          a.brightness,
          a.current_position,
          a.current_tilt_position,
          a.color_temp_kelvin,
          String(a.rgb_color),
          a.friendly_name
        );
      }
    }
    return parts.join("|");
  }

  // ---- reading lights and blinds ----

  _shortName(room, name) {
    const prefix = room.name.toLowerCase() + " ";
    const n = String(name);
    return n.toLowerCase().startsWith(prefix) && n.length > prefix.length ? n.slice(prefix.length) : n;
  }

  _saved(room) {
    return room.entities.filter((e) => e.status === "saved");
  }

  // "2 blinds", "1 window", or "3 covers" for a mix (or garage doors and the like).
  _covers(ids) {
    const kinds = new Set(
      ids.map((id) => {
        const c = this._hass.states[id]?.attributes?.device_class;
        if (c === "window") return "window";
        return !c || ["blind", "shade", "curtain", "shutter", "awning"].includes(c) ? "blind" : "cover";
      })
    );
    const word = kinds.size === 1 ? [...kinds][0] : "cover";
    return { word: ids.length === 1 ? word : word + "s", text: plural(ids.length, word) };
  }

  _counts(ids) {
    const lights = ids.filter((id) => id.startsWith("light.")).length;
    const covers = ids.filter((id) => id.startsWith("cover."));
    const bits = [];
    if (lights) bits.push(plural(lights, "light"));
    if (covers.length) bits.push(this._covers(covers).text);
    return bits.join(" and ");
  }

  _contents(room) {
    return this._counts(this._saved(room).map((e) => e.entity_id)) || "nothing to save";
  }

  _chip(room, e) {
    const s = this._hass.states[e.entity_id];
    const name = esc(this._shortName(room, s?.attributes?.friendly_name || e.name));
    let icon;
    let text;
    let cls = "";
    let style = "";
    if (!s || s.state === "unavailable" || s.state === "unknown") {
      icon = e.domain === "light" ? "mdi:lightbulb-off-outline" : "mdi:help-circle-outline";
      text = "Can't be reached";
      cls = "gone";
    } else if (e.domain === "light") {
      const on = s.state === "on";
      icon = on ? "mdi:lightbulb" : "mdi:lightbulb-outline";
      const b = s.attributes.brightness;
      text = on ? (b == null ? "On" : `${Math.max(1, Math.round((b / 255) * 100))}%`) : "Off";
      if (on) {
        cls = "on";
        const rgb = s.attributes.rgb_color;
        if (Array.isArray(rgb)) style = `--chip: rgb(${rgb.map(Number).join(",")})`;
      }
    } else {
      const p = s.attributes.current_position;
      const open = p == null ? s.state === "open" || s.state === "opening" : p > 0;
      const kind = s.attributes.device_class;
      if (kind === "window") icon = open ? "mdi:window-open-variant" : "mdi:window-closed-variant";
      else if (kind === "garage") icon = open ? "mdi:garage-open" : "mdi:garage";
      else icon = open ? "mdi:blinds-open" : "mdi:blinds";
      text = p == null ? (open ? "Open" : "Closed") : p === 0 ? "Closed" : p === 100 ? "Open" : `${Math.round(p)}% open`;
      const tilt = s.attributes.current_tilt_position;
      if (tilt != null) text += `, slats ${Math.round(tilt)}%`;
      if (open) cls = "open";
    }
    return `<button class="chip ${cls}" style="${style}" data-action="more" data-entity="${esc(e.entity_id)}" title="Open ${name}'s controls">
        <ha-icon icon="${icon}"></ha-icon><span class="cname">${name}</span><span class="cstate">${esc(text)}</span>
      </button>`;
  }

  // What a scene sets, in a few words.
  _summary(scene) {
    if (!scene.entities) return "From another app";
    let on = 0;
    let off = 0;
    const positions = [];
    const covers = [];
    for (const [id, e] of Object.entries(scene.entities)) {
      if (id.startsWith("light.")) e.state === "on" ? on++ : off++;
      else if (id.startsWith("cover.")) {
        covers.push(id);
        positions.push(e.current_position ?? (e.state === "closed" ? 0 : 100));
      }
    }
    const bits = [];
    if (on) bits.push(`${plural(on, "light")} on`);
    if (off) bits.push(`${off} off`);
    if (positions.length) {
      const same = positions.every((p) => p === positions[0]);
      const where = (p) => (p === 0 ? "closed" : p === 100 ? "open" : `${Math.round(p)}% open`);
      const named = this._covers(covers);
      bits.push(same ? `${positions.length === 1 ? named.word : named.text} ${where(positions[0])}` : named.text);
    }
    return bits.join(" · ") || "Nothing set";
  }

  // True when the room is as the scene left it (so the list can mark it).
  _matches(scene) {
    if (!scene.entities) return false;
    let compared = 0;
    for (const [id, want] of Object.entries(scene.entities)) {
      const s = this._hass.states[id];
      if (!s || s.state === "unavailable" || s.state === "unknown") continue;
      compared++;
      if (id.startsWith("light.")) {
        if ((s.state === "on") !== (want.state === "on")) return false;
        if (want.state === "on" && want.brightness != null && s.attributes.brightness != null) {
          if (Math.abs(want.brightness - s.attributes.brightness) > 5) return false;
        }
        if (want.state === "on" && want.color_temp_kelvin && s.attributes.color_temp_kelvin) {
          if (Math.abs(want.color_temp_kelvin - s.attributes.color_temp_kelvin) > 100) return false;
        }
      } else if (id.startsWith("cover.")) {
        const p = s.attributes.current_position;
        if (want.current_position != null && p != null) {
          if (Math.abs(want.current_position - p) > 3) return false;
        } else if ((s.state === "closed") !== (want.state === "closed")) return false;
      }
    }
    return compared > 0;
  }

  // ---- a room ----

  _roomHtml(room, { settings = false } = {}) {
    const saved = this._saved(room);
    const editable = room.scenes.filter((s) => s.editable);
    const others = room.scenes.filter((s) => !s.editable);
    const canSave = saved.length > 0;
    return `
      <div class="now">
        <div class="label">Right now</div>
        <div class="chips">${saved.map((e) => this._chip(room, e)).join("") || `<span class="muted">This room has no lights or blinds in Home Assistant yet.</span>`}</div>
      </div>
      <button class="save" data-action="save" data-room="${esc(room.area_id)}" ${canSave ? "" : "disabled"}>
        <ha-icon icon="mdi:content-save-plus"></ha-icon>
        <span><b>Save current scene</b><small>${esc(room.name)}: ${esc(this._contents(room))}, as they are now</small></span>
      </button>
      <div class="label">Saved scenes</div>
      ${
        editable.length
          ? `<div class="scenes">${editable.map((s) => this._sceneRow(room, s)).join("")}</div>`
          : `<div class="empty">None yet. Set the room how you like it, then press <b>Save current scene</b>.</div>`
      }
      ${
        others.length
          ? `<div class="label">From other apps</div>
             <div class="scenes">${others.map((s) => this._sceneRow(room, s)).join("")}</div>
             <div class="hint">These can be turned on here, but only changed in the app that made them.</div>`
          : ""
      }
      ${settings ? this._settingsHtml(room) : ""}`;
  }

  _sceneRow(room, scene) {
    const active = this._matches(scene);
    const pressed = this._pressed === scene.entity_id;
    const id = esc(scene.entity_id);
    const data = `data-room="${esc(room.area_id)}" data-scene="${id}"`;
    return `
      <div class="scene ${active ? "active" : ""} ${pressed ? "pressed" : ""}">
        <button class="scene-main" data-action="activate" ${data} title="Turn on ${esc(scene.name)}">
          <ha-icon icon="${active ? "mdi:check-circle" : "mdi:play-circle-outline"}"></ha-icon>
          <span class="scene-text">
            <span class="sname">${esc(scene.name)}${active ? ` <span class="badge">On now</span>` : ""}</span>
            <span class="ssum">${esc(this._summary(scene))}</span>
            ${this._admin ? `<span class="sid">${id}</span>` : ""}
          </span>
        </button>
        ${
          scene.editable
            ? `<div class="scene-actions">
                <button class="icon" data-action="update" ${data} title="Save the room as it is now over ${esc(scene.name)}"><ha-icon icon="mdi:content-save-outline"></ha-icon><span>Update</span></button>
                <button class="icon" data-action="rename" ${data} title="Rename ${esc(scene.name)}"><ha-icon icon="mdi:pencil-outline"></ha-icon><span>Rename</span></button>
                <button class="icon danger" data-action="delete" ${data} title="Delete ${esc(scene.name)}"><ha-icon icon="mdi:trash-can-outline"></ha-icon><span>Delete</span></button>
              </div>`
            : ""
        }
      </div>`;
  }

  _settingsHtml(room) {
    return "";
  }

  // ---- dialogs ----

  _dialogHtml() {
    const d = this._dialog;
    if (!d) return "";
    const room = this._room(d.room);
    if (!room) return "";
    const scene = d.scene ? room.scenes.find((s) => s.entity_id === d.scene) : null;
    const error = d.error ? `<div class="derror">${esc(d.error)}</div>` : "";
    const busy = d.busy ? "disabled" : "";
    let title;
    let body;
    let ok;
    let okClass = "primary";
    if (d.kind === "save") {
      const existing = room.scenes.filter((s) => s.editable);
      title = "Save current scene";
      ok = "Save";
      body = `
        <p>${esc(room.name)}: ${esc(this._contents(room))}, exactly as they are now.</p>
        <label>Name
          <input type="text" id="name" maxlength="60" autocomplete="off" placeholder="For example: Evening" value="${esc(d.value || "")}">
        </label>
        <div class="replace" id="replace" hidden></div>
        ${
          existing.length
            ? `<div class="over"><span>Or save over:</span>${existing.map((s) => `<button class="pill" data-action="pick-name" data-name="${esc(s.name)}">${esc(s.name)}</button>`).join("")}</div>`
            : ""
        }`;
    } else if (d.kind === "rename") {
      title = `Rename ${scene?.name || "scene"}`;
      ok = "Rename";
      body = `
        <label>New name
          <input type="text" id="name" maxlength="60" autocomplete="off" value="${esc(d.value || "")}">
        </label>
        <p class="muted">Anything that turns this scene on (a wall button, a routine) keeps working.</p>`;
    } else if (d.kind === "update") {
      title = `Update ${scene?.name || "scene"}?`;
      ok = "Update";
      body = `<p>${esc(scene?.name)} will be replaced with ${esc(room.name)}'s ${esc(this._contents(room))} as they are now.</p>`;
    } else {
      title = `Delete ${scene?.name || "scene"}?`;
      ok = "Delete";
      okClass = "danger-fill";
      body = `<p>The scene is removed from Home Assistant. A wall button or routine that turns it on will stop doing anything.</p>`;
    }
    return `
      <div class="scrim" data-action="scrim">
        <div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}">
          <h2>${esc(title)}</h2>
          ${body}
          ${error}
          <div class="dbuttons">
            <button class="btn" data-action="cancel" ${busy}>Cancel</button>
            <button class="btn ${okClass}" id="ok" data-action="confirm" ${busy}>${d.busy ? "Working…" : ok}</button>
          </div>
        </div>
      </div>`;
  }

  _openDialog(kind, roomId, sceneId) {
    const room = this._room(roomId);
    const scene = sceneId ? room?.scenes.find((s) => s.entity_id === sceneId) : null;
    this._dialog = { kind, room: roomId, scene: sceneId || null, value: kind === "rename" ? scene?.name || "" : "", error: null, busy: false };
    this._render();
  }

  _closeDialog() {
    this._dialog = null;
    this._render();
  }

  _afterRender() {
    const d = this._dialog;
    if (!d) return;
    const input = this.shadowRoot.getElementById("name");
    if (input) {
      input.addEventListener("input", () => {
        d.value = input.value;
        this._replaceHint();
      });
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") this._confirm();
      });
      if (!d.busy) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      this._replaceHint();
    } else if (!d.busy) {
      this.shadowRoot.getElementById("ok")?.focus();
    }
  }

  // Saving under a name the room already has replaces that scene: say so first.
  _replaceHint() {
    const d = this._dialog;
    const hint = this.shadowRoot.getElementById("replace");
    const ok = this.shadowRoot.getElementById("ok");
    if (!d || d.kind !== "save" || !hint || !ok) return;
    const room = this._room(d.room);
    const hit = room?.scenes.find((s) => sameName(s.name, d.value || ""));
    hint.hidden = !hit;
    if (hit) {
      hint.textContent = hit.editable
        ? `${hit.name} already exists. Saving replaces it with the room as it is now.`
        : `${hit.name} is a scene from another app. Choose another name.`;
    }
    if (!d.busy) ok.textContent = hit && hit.editable ? "Replace" : "Save";
  }

  async _confirm() {
    const d = this._dialog;
    if (!d || d.busy) return;
    const room = this._room(d.room);
    const scene = d.scene ? room?.scenes.find((s) => s.entity_id === d.scene) : null;
    let msg;
    if (d.kind === "save") msg = { type: "scene_setter/save", area_id: d.room, name: d.value || "" };
    else if (d.kind === "update") msg = { type: "scene_setter/save", area_id: d.room, scene: d.scene };
    else if (d.kind === "rename") msg = { type: "scene_setter/rename", scene: d.scene, name: d.value || "" };
    else msg = { type: "scene_setter/delete", scene: d.scene };
    d.busy = true;
    d.error = null;
    this._render();
    try {
      const result = await this._hass.callWS(msg);
      this._dialog = null;
      this._render();
      this._toast(this._doneText(d.kind, result, scene));
    } catch (err) {
      d.busy = false;
      d.error = this._errorText(err);
      this._render();
    }
  }

  _doneText(kind, result, scene) {
    if (kind === "rename") return `Renamed to ${result.name}.`;
    if (kind === "delete") return `${scene?.name || "Scene"} deleted.`;
    let text = `${result.name} ${result.created ? "saved" : "updated"}: ${this._counts(result.saved)}.`;
    if (result.skipped.length) {
      const names = result.skipped.map((e) => this._hass.states[e]?.attributes?.friendly_name || e);
      text += ` Left out because ${names.length === 1 ? "it" : "they"} can't be reached: ${names.join(", ")}.`;
    }
    return text;
  }

  _errorText(err) {
    const fixed = ERRORS[err?.code];
    return fixed || err?.message || String(err);
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  // ---- actions ----

  _bind() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        if (el.dataset.action === "scrim" && ev.target !== el) return;
        ev.stopPropagation();
        this._act(el.dataset.action, el.dataset, ev);
      });
    });
    this._afterRender();
  }

  async _act(action, data) {
    switch (action) {
      case "save":
        return this._openDialog("save", data.room);
      case "update":
      case "rename":
      case "delete":
        return this._openDialog(action, data.room, data.scene);
      case "cancel":
      case "scrim":
        if (!this._dialog?.busy) this._closeDialog();
        return;
      case "confirm":
        return this._confirm();
      case "pick-name": {
        const input = this.shadowRoot.getElementById("name");
        if (input) {
          input.value = data.name;
          this._dialog.value = data.name;
          this._replaceHint();
          input.focus();
        }
        return;
      }
      case "more":
        this.dispatchEvent(
          new CustomEvent("hass-more-info", { detail: { entityId: data.entity }, bubbles: true, composed: true })
        );
        return;
      case "activate":
        return this._activate(data.room, data.scene);
      case "reload":
        location.reload();
        return;
      default:
        return this._actMore(action, data);
    }
  }

  _actMore() {}

  async _activate(roomId, sceneId) {
    const scene = this._room(roomId)?.scenes.find((s) => s.entity_id === sceneId);
    this._pressed = sceneId;
    this._render();
    setTimeout(() => {
      if (this._pressed === sceneId) {
        this._pressed = null;
        if (!this._dialog) this._render();
      }
    }, 1200);
    try {
      await this._hass.callService("scene", "turn_on", { entity_id: sceneId });
      this._toast(`${scene?.name || "Scene"} turned on.`);
    } catch (err) {
      this._toast(`Couldn't turn on ${scene?.name || "the scene"}: ${err.message || err}`);
    }
  }

  _problems() {
    const d = feed.data;
    if (feed.error) return `<div class="note warn">Couldn't load Scene Setter: ${esc(feed.error)}</div>`;
    if (!d) return `<div class="note">Loading…</div>`;
    if (!d.set_up) return `<div class="note">${esc(ERRORS.not_set_up)}</div>`;
    if (d.version && d.version !== PAGE_VERSION) {
      return `<div class="note warn">Scene Setter was updated to ${esc(d.version)}, but this page is still the old version (${PAGE_VERSION}). <button class="btn small" data-action="reload">Reload the page</button></div>`;
    }
    return "";
  }
}

// ---- the sidebar page --------------------------------------------------------------

class SceneSetterPanel extends SceneSetterBase {
  constructor() {
    super();
    this._areaId = loadPref("room", null);
  }

  set narrow(v) {
    this._narrow = v;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) mb.narrow = v;
  }

  _afterHass() {
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) mb.hass = this._hass;
  }

  _visibleRooms() {
    const room = this._areaId ? this._room(this._areaId) : null;
    return room ? [room] : this._rooms();
  }

  _render() {
    if (!this._hass) return;
    const room = this._areaId ? this._room(this._areaId) : null;
    const problems = this._problems();
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        <div class="title">Scene Setter</div>
      </div>
      <div class="content">
        ${problems}
        ${feed.data?.set_up ? (room ? this._detail(room) : this._overview()) : ""}
      </div>
      ${this._dialogHtml()}`;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) {
      mb.hass = this._hass;
      mb.narrow = this._narrow;
    }
    this._shown = this._signature();
    this._bind();
  }

  _overview() {
    const rooms = this._rooms();
    if (!rooms.length) {
      return `<div class="card">No room has lights or blinds yet. Scene Setter uses Home Assistant's areas: put your lights and blinds in areas under Settings → Areas, and they appear here.</div>`;
    }
    const floors = [];
    for (const room of rooms) {
      const name = room.floor || "";
      let group = floors.find((f) => f.name === name);
      if (!group) floors.push((group = { name, rooms: [] }));
      group.rooms.push(room);
    }
    return `
      <p class="intro">Choose a room, set its lights and blinds how you like them, then save them as a scene.</p>
      ${floors
        .map(
          (f) => `
        ${floors.length > 1 ? `<h2>${esc(f.name || "Other rooms")}</h2>` : ""}
        <div class="grid">${f.rooms.map((r) => this._roomCard(r)).join("")}</div>`
        )
        .join("")}`;
  }

  _roomCard(room) {
    const scenes = room.scenes;
    const lit = this._saved(room).filter((e) => this._hass.states[e.entity_id]?.state === "on").length;
    return `
      <button class="card room" data-action="open" data-room="${esc(room.area_id)}">
        <span class="roomhead">
          <ha-icon icon="${esc(room.icon || "mdi:floor-plan")}"></ha-icon>
          <span class="roomname">${esc(room.name)}</span>
          ${lit ? `<span class="lit" title="${plural(lit, "light")} on"><ha-icon icon="mdi:lightbulb"></ha-icon>${lit}</span>` : ""}
        </span>
        <span class="meta">${esc(this._contents(room))}</span>
        <span class="tags">${
          scenes.length
            ? scenes.map((s) => `<span class="tag ${this._matches(s) ? "active" : ""}">${esc(s.name)}</span>`).join("")
            : `<span class="muted">No scenes yet</span>`
        }</span>
      </button>`;
  }

  _detail(room) {
    return `
      <div class="detailhead">
        <button class="btn small" data-action="back"><ha-icon icon="mdi:arrow-left"></ha-icon> All rooms</button>
      </div>
      <div class="card roomcard">
        <h1>${esc(room.name)}</h1>
        ${this._roomHtml(room, { settings: this._admin })}
      </div>`;
  }

  _settingsHtml(room) {
    const rows = room.entities;
    const others = Object.keys(this._hass.states)
      .filter((id) => (id.startsWith("light.") || id.startsWith("cover.")) && !rows.some((r) => r.entity_id === id))
      .sort((a, b) => this._name(a).localeCompare(this._name(b)));
    const row = (e) => {
      const name = esc(this._hass.states[e.entity_id]?.attributes?.friendly_name || e.name);
      const id = esc(e.entity_id);
      let note = "";
      if (e.status === "group") note = `A group: its ${this._counts(e.members)} ${e.members.length === 1 ? "is" : "are"} saved one by one`;
      else if (e.status === "ignored") note = "Has the scene_setter_ignore label";
      else if (e.via) note = `Part of ${esc(this._name(e.via))}`;
      else if (e.added) note = "Added from elsewhere";
      const ignored = e.status === "ignored";
      return `
        <label class="srow ${e.via ? "indent" : ""}">
          <input type="checkbox" data-toggle="${id}" ${e.status !== "left_out" && !ignored ? "checked" : ""} ${ignored ? "disabled" : ""}>
          <span class="sname2">${name}<small>${id}${note ? " · " + note : ""}</small></span>
          ${e.added ? `<button class="icon danger" data-action="unadd" data-room="${esc(room.area_id)}" data-entity="${id}" title="Remove from this room"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}
        </label>`;
    };
    return `
      <div class="settings">
        <button class="expander" data-action="toggle-settings">
          <ha-icon icon="mdi:chevron-${this._settings ? "down" : "right"}"></ha-icon>
          What this room saves <span class="muted">(administrators only)</span>
        </button>
        ${
          this._settings
            ? `<div class="settings-body" data-room="${esc(room.area_id)}">
                <p class="hint">A scene saves every ticked light and blind. Untick anything this room's scenes should leave alone.</p>
                ${rows.map(row).join("") || `<p class="muted">Nothing in this area yet.</p>`}
                <div class="addrow">
                  <select id="add">
                    <option value="">Add a light or blind from elsewhere…</option>
                    ${others.map((id) => `<option value="${esc(id)}">${esc(this._name(id))} (${esc(id)})</option>`).join("")}
                  </select>
                </div>
              </div>`
            : ""
        }
      </div>`;
  }

  _name(entityId) {
    return this._hass.states[entityId]?.attributes?.friendly_name || entityId;
  }

  _afterRender() {
    super._afterRender();
    const body = this.shadowRoot.querySelector(".settings-body");
    if (!body) return;
    const roomId = body.dataset.room;
    body.querySelectorAll("[data-toggle]").forEach((box) => {
      box.addEventListener("change", () => {
        const room = this._room(roomId);
        const exclude = new Set(room.entities.filter((e) => e.status === "left_out").map((e) => e.entity_id));
        box.checked ? exclude.delete(box.dataset.toggle) : exclude.add(box.dataset.toggle);
        this._saveRoom(room, [...exclude], this._added(room));
      });
    });
    const add = body.querySelector("#add");
    if (add) {
      add.addEventListener("change", () => {
        if (!add.value) return;
        const room = this._room(roomId);
        const value = add.value;
        add.blur();
        this._saveRoom(room, this._excluded(room), [...this._added(room), value]);
      });
    }
  }

  _excluded(room) {
    return room.entities.filter((e) => e.status === "left_out").map((e) => e.entity_id);
  }

  _added(room) {
    return room.entities.filter((e) => e.added).map((e) => e.entity_id);
  }

  async _saveRoom(room, exclude, include) {
    try {
      await this._hass.callWS({ type: "scene_setter/save_room", area_id: room.area_id, exclude, include });
    } catch (err) {
      this._toast(this._errorText(err));
      this._render();
    }
  }

  _actMore(action, data) {
    if (action === "open") {
      this._areaId = data.room;
      this._settings = false;
      savePref("room", this._areaId);
    } else if (action === "back") {
      this._areaId = null;
      savePref("room", null);
    } else if (action === "toggle-settings") {
      this._settings = !this._settings;
    } else if (action === "unadd") {
      const room = this._room(data.room);
      return this._saveRoom(
        room,
        this._excluded(room).filter((e) => e !== data.entity),
        this._added(room).filter((e) => e !== data.entity)
      );
    } else {
      return;
    }
    this._render();
  }
}

// ---- the dashboard card ------------------------------------------------------------

class SceneSetterCard extends SceneSetterBase {
  static getConfigForm() {
    return {
      schema: [
        { name: "area", required: true, selector: { area: {} } },
        { name: "title", selector: { text: {} } },
        { name: "show_now", selector: { boolean: {} } },
      ],
      computeLabel: (field) =>
        ({ area: "Room", title: "Title (the room's name if left empty)", show_now: "Show the lights and blinds as they are now" })[field.name],
    };
  }

  static getStubConfig(hass) {
    return { area: Object.keys(hass?.areas || {})[0] || "", show_now: true };
  }

  setConfig(config) {
    if (!config || !config.area) throw new Error("Choose a room (area) for the Scene Setter card.");
    this._config = { show_now: true, ...config };
    this._render();
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 3 };
  }

  _visibleRooms() {
    const room = this._config ? this._room(this._config.area) : null;
    return room ? [room] : [];
  }

  _render() {
    if (!this._hass || !this._config) return;
    const room = this._room(this._config.area);
    const problems = this._problems();
    const title = this._config.title || room?.name || this._hass.areas?.[this._config.area]?.name || "Scenes";
    let body = "";
    if (!problems || feed.data?.set_up) {
      body = room
        ? this._roomHtml(room)
        : `<div class="empty">This room has no lights or blinds in Home Assistant yet.</div>`;
    }
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card class="${this._config.show_now ? "" : "hide-now"}">
        <div class="cardhead"><ha-icon icon="mdi:palette-swatch-variant"></ha-icon><span>${esc(title)}</span></div>
        <div class="cardbody">${problems}${body}</div>
      </ha-card>
      ${this._dialogHtml()}`;
    this._shown = this._signature();
    this._bind();
  }
}

const STYLES = `
  :host { display:block; color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  :host(scene-setter-panel) { background: var(--primary-background-color); min-height:100vh; }
  button { font:inherit; color:inherit; }
  .toolbar { display:flex; align-items:center; gap:12px; height:56px; padding:0 8px; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); }
  .toolbar .title { font-size:20px; flex:1; }
  .content { padding:16px; max-width:1100px; margin:0 auto; }
  h1 { font-size:24px; font-weight:500; margin:0 0 12px; }
  h2 { font-size:16px; font-weight:500; margin:20px 0 8px; }
  .intro { color: var(--secondary-text-color); margin:0 0 12px; font-size:14px; }
  .card { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); box-shadow: var(--ha-card-box-shadow, none); border:1px solid var(--divider-color); padding:16px; margin-bottom:12px; }
  .roomcard { max-width:720px; }
  .note { border:1px solid var(--primary-color); border-radius:8px; padding:12px; margin-bottom:12px; font-size:14px; }
  .note.warn { border-color: var(--error-color, #db4437); }
  .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap:12px; }
  .grid .card { margin:0; }
  .room { text-align:left; cursor:pointer; display:flex; flex-direction:column; gap:6px; }
  .room:hover, .room:focus-visible { border-color: var(--primary-color); outline:none; }
  .roomhead { display:flex; align-items:center; gap:8px; }
  .roomhead ha-icon { color: var(--secondary-text-color); }
  .roomname { font-size:18px; font-weight:500; flex:1; }
  .lit { display:inline-flex; align-items:center; gap:2px; font-size:13px; color:#f9a825; }
  .lit ha-icon { --mdc-icon-size:16px; color:#fbc02d; }
  .meta { color: var(--secondary-text-color); font-size:13px; }
  .tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:2px; font-size:12px; }
  .tag { border-radius:10px; padding:2px 8px; background: var(--secondary-background-color); }
  .tag.active { background: color-mix(in srgb, var(--success-color, #43a047) 22%, var(--card-background-color)); }
  .muted { color: var(--secondary-text-color); }
  .hint { color: var(--secondary-text-color); font-size:12px; margin:6px 0 0; }
  .detailhead { margin-bottom:12px; }
  .label { font-size:12px; font-weight:500; letter-spacing:.06em; text-transform:uppercase; color: var(--secondary-text-color); margin:16px 0 6px; }
  .now .label { margin-top:0; }
  .hide-now .now { display:none; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--divider-color); background: var(--secondary-background-color); border-radius:16px; padding:4px 10px 4px 6px; font-size:13px; cursor:pointer; }
  .chip:hover, .chip:focus-visible { border-color: var(--primary-color); outline:none; }
  .chip ha-icon { --mdc-icon-size:18px; color: var(--secondary-text-color); }
  .chip.on ha-icon { color: var(--chip, #fbc02d); }
  .chip.open ha-icon { color: var(--primary-color); }
  .chip.gone { opacity:.55; }
  .chip .cstate { color: var(--secondary-text-color); }
  .chip.on .cstate, .chip.open .cstate { color: var(--primary-text-color); font-weight:500; }
  .save { display:flex; align-items:center; justify-content:center; gap:14px; width:100%; min-height:76px; margin-top:16px; padding:12px 20px; border:none; border-radius:14px; cursor:pointer; background: var(--primary-color); color: var(--text-primary-color, #fff); text-align:left; box-shadow:0 2px 6px rgba(0,0,0,.18); transition: transform .08s, box-shadow .08s, filter .12s; }
  .save:hover { filter:brightness(1.08); }
  .save:active { transform:scale(.985); box-shadow:0 1px 2px rgba(0,0,0,.2); }
  .save:focus-visible { outline:3px solid color-mix(in srgb, var(--primary-color) 45%, transparent); outline-offset:2px; }
  .save:disabled { opacity:.45; cursor:default; filter:none; }
  .save ha-icon { --mdc-icon-size:34px; flex:none; }
  .save span { display:flex; flex-direction:column; gap:2px; }
  .save b { font-size:19px; font-weight:500; }
  .save small { font-size:13px; opacity:.9; }
  .scenes { display:flex; flex-direction:column; gap:8px; }
  .scene { display:flex; align-items:stretch; border:1px solid var(--divider-color); border-radius:12px; overflow:hidden; background: var(--card-background-color); }
  .scene.active { border-color: var(--success-color, #43a047); background: color-mix(in srgb, var(--success-color, #43a047) 8%, var(--card-background-color)); }
  .scene.pressed { border-color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 14%, var(--card-background-color)); }
  .scene-main { flex:1; min-width:0; display:flex; align-items:center; gap:12px; padding:10px 12px; background:none; border:none; cursor:pointer; text-align:left; }
  .scene-main:hover, .scene-main:focus-visible { background: color-mix(in srgb, var(--primary-color) 8%, transparent); outline:none; }
  .scene-main > ha-icon { --mdc-icon-size:30px; color: var(--primary-color); flex:none; }
  .scene.active .scene-main > ha-icon { color: var(--success-color, #43a047); }
  .scene-text { display:flex; flex-direction:column; min-width:0; gap:1px; }
  .sname { font-size:16px; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .ssum { font-size:13px; color: var(--secondary-text-color); }
  .sid { font-size:11px; color: var(--secondary-text-color); font-family: var(--code-font-family, monospace); opacity:.8; user-select:all; overflow:hidden; text-overflow:ellipsis; }
  .badge { font-size:11px; font-weight:500; vertical-align:middle; margin-left:6px; padding:1px 7px; border-radius:9px; background: var(--success-color, #43a047); color:#fff; }
  .scene-actions { display:flex; align-items:stretch; border-left:1px solid var(--divider-color); }
  .icon { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; min-width:58px; padding:6px 8px; background:none; border:none; cursor:pointer; font-size:11px; color: var(--secondary-text-color); }
  .icon:hover, .icon:focus-visible { background: var(--secondary-background-color); color: var(--primary-text-color); outline:none; }
  .icon.danger:hover, .icon.danger:focus-visible { color: var(--error-color, #db4437); }
  .icon ha-icon { --mdc-icon-size:20px; }
  .empty { border:1px dashed var(--divider-color); border-radius:12px; padding:14px; font-size:14px; color: var(--secondary-text-color); }
  .btn { font-size:14px; padding:8px 16px; border-radius:8px; border:1px solid var(--primary-color); background:none; color: var(--primary-color); cursor:pointer; display:inline-flex; align-items:center; gap:4px; }
  .btn.small { padding:5px 12px; font-size:13px; }
  .btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger-fill { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color:#fff; }
  .btn:disabled { opacity:.6; cursor:default; }
  .btn ha-icon { --mdc-icon-size:18px; }
  .scrim { position:fixed; inset:0; z-index:10; background: rgba(0,0,0,.5); display:flex; align-items:center; justify-content:center; padding:16px; }
  .dialog { background: var(--card-background-color); color: var(--primary-text-color); border-radius:16px; padding:20px; width:100%; max-width:420px; box-shadow:0 8px 32px rgba(0,0,0,.35); }
  .dialog h2 { font-size:20px; margin:0 0 8px; }
  .dialog p { font-size:14px; margin:0 0 12px; line-height:1.45; }
  .dialog label { display:flex; flex-direction:column; gap:4px; font-size:13px; color: var(--secondary-text-color); margin-bottom:8px; }
  .dialog input[type=text] { font:inherit; font-size:18px; padding:10px 12px; border-radius:8px; border:1px solid var(--divider-color); background: var(--primary-background-color); color: var(--primary-text-color); }
  .dialog input[type=text]:focus { outline:2px solid var(--primary-color); border-color:transparent; }
  .replace { font-size:13px; color: var(--warning-color, #ffa600); margin-bottom:8px; }
  .over { display:flex; flex-wrap:wrap; align-items:center; gap:6px; font-size:13px; color: var(--secondary-text-color); margin-bottom:4px; }
  .pill { font-size:13px; border-radius:14px; padding:4px 10px; border:1px solid var(--divider-color); background: var(--secondary-background-color); cursor:pointer; }
  .pill:hover, .pill:focus-visible { border-color: var(--primary-color); outline:none; }
  .derror { font-size:14px; color: var(--error-color, #db4437); margin:8px 0; }
  .dbuttons { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
  .settings { margin-top:20px; border-top:1px solid var(--divider-color); padding-top:8px; }
  .expander { display:flex; align-items:center; gap:4px; background:none; border:none; cursor:pointer; font-size:14px; padding:6px 0; }
  .srow { display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid var(--divider-color); cursor:pointer; }
  .srow.indent { padding-left:28px; }
  .srow input { width:18px; height:18px; flex:none; }
  .sname2 { flex:1; display:flex; flex-direction:column; font-size:14px; min-width:0; }
  .sname2 small { color: var(--secondary-text-color); font-size:12px; overflow:hidden; text-overflow:ellipsis; }
  .addrow { margin-top:12px; }
  .addrow select { font:inherit; font-size:14px; padding:8px; border-radius:6px; border:1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); max-width:100%; }
  ha-card { overflow:hidden; }
  .cardhead { display:flex; align-items:center; gap:8px; padding:16px 16px 0; font-size:20px; font-weight:500; }
  .cardhead ha-icon { color: var(--secondary-text-color); }
  .cardbody { padding:12px 16px 16px; }
  @media (max-width: 600px) {
    .content { padding:8px; }
    .icon span { display:none; }
    .icon { min-width:44px; }
    .save b { font-size:17px; }
  }
`;

// A tab still open during an update can load the new file next to the old one.
if (!customElements.get("scene-setter-panel")) customElements.define("scene-setter-panel", SceneSetterPanel);
if (!customElements.get("scene-setter-card")) {
  customElements.define("scene-setter-card", SceneSetterCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "scene-setter-card",
    name: "Scene Setter",
    description: "Save a room's lights and blinds as a scene, and turn on, rename or delete saved scenes.",
    preview: false,
  });
}
