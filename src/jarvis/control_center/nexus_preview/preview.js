// Load before the existing V1 consumer starts its event stream. Retain only status fields.
(() => {
  "use strict";
  const host = document.getElementById("nexus-preview-host");
  const toggle = document.getElementById("nexus-toggle");
  const shadow = host.attachShadow({ mode: "open" });
  const query = new URL(document.currentScript.src).search;
  const stateNames = new Map(
    Object.entries({
      ready: "Idle",
      listening: "Listening",
      processing: "Thinking",
      speaking: "Speaking",
      awaiting_confirmation: "Awaiting Approval",
      error: "Error",
      emergency: "Emergency Stop",
    }),
  );
  const templates = new Map(
    Array.from(document.querySelectorAll("template[data-nexus-page]"), (el) => [
      el.dataset.nexusPage,
      el,
    ]),
  );
  for (const sheet of ["styles.css", "polish.css", "surface.css"]) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/nexus/" + sheet + query;
    shadow.append(link);
  }
  const banner = document.createElement("div");
  banner.className = "preview-status";
  banner.setAttribute("role", "status");
  const statusText = document.createElement("span");
  const download = document.createElement("a");
  download.href = "/nexus/standalone.zip" + query;
  download.download = "NEXUS-Ultimate-1.1.0-lokal.zip";
  download.textContent = "Lokalen Workspace herunterladen";
  banner.append(statusText, download);
  const view = document.createElement("div");
  view.id = "app";
  shadow.append(banner, view);
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    "Dreidimensionaler holografischer JARVIS-Kern",
  );
  let core = null,
    renderer = "Initialisierung",
    fps = 0,
    connected = false,
    emergency = null,
    state = null;
  let working = false,
    initialized = false,
    lastSeq = 0,
    name = "core",
    showing = false;
  let sending = false, receipt = "", generation = 0;
  const conversation = document.createElement("ol");
  conversation.className = "live-chat";
  conversation.setAttribute("aria-label", "Gespräch mit JARVIS");
  let voiceActive = null;
  // Project the existing V1 panels, retaining their IDs, listeners and controller state.
  const liveTasks = document.createElement("fieldset");
  liveTasks.slot = "live-tasks";
  liveTasks.className = "nexus-live-tasks";
  const legend = document.createElement("legend");
  legend.textContent = "JARVIS · Aufgaben und Agenten";
  liveTasks.append(legend);
  const panels = ["agent-list", "task-list", "task-detail", "results-list", "history-list"].map(id => {
    const panel = document.getElementById(id).closest(".panel");
    const marker = document.createComment(id);
    panel.before(marker);
    return { panel, marker };
  });
  function restorePanels() {
    for (const { panel, marker } of panels) {
      if (panel.parentNode === liveTasks) marker.after(panel);
    }
    liveTasks.remove();
  }
  function available() {
    return showing && initialized && connected && emergency === false && !host.inert;
  }
  function update() {
    liveTasks.disabled = !available();
    const form = view.querySelector("#command-form");
    if (form) {
      form.querySelector("input").disabled = !available() || sending;
      form.querySelector('[type="submit"]').disabled = !available() || sending;

    }
    const note = view.querySelector(".live-receipt");
    if (note) note.textContent = receipt;
    for (const control of view.querySelectorAll("[data-live-voice]")) {
      control.disabled = !available() || sending || (control.dataset.liveVoice === "start" ? voiceActive === true : voiceActive === false);
    }
    const confirmed = connected && initialized;
    const label = confirmed
      ? emergency === true
        ? "Emergency Stop"
        : !document.getElementById("confirm-dialog").hidden
          ? "Awaiting Approval"
          : working && (state === "ready" || state === "processing")
            ? "Working"
            : stateNames.get(state)
      : null;
    const stop =
      confirmed && typeof emergency === "boolean"
        ? emergency
          ? "aktiv"
          : "inaktiv"
        : "unbekannt";
    const status =
      "JARVIS · " +
      (confirmed
        ? "verbunden"
        : connected
          ? "warte auf Snapshot"
          : "Verbindung unbestätigt") +
      " · Not-Aus " +
      stop +
      " · Projektdaten sind lokale Beispiele.";
    if (statusText.textContent !== status) statusText.textContent = status;
    view.dataset.coreState = label || "unknown";
    const rate = view.querySelector("[data-fps]");
    if (rate) rate.textContent = fps ? fps + " FPS" : "–";
    banner.dataset.alert = String(emergency === true && confirmed);
    for (const el of view.querySelectorAll("[data-current-state]"))
      el.textContent = label || "Unbekannt";
    for (const el of view.querySelectorAll("[data-backend]"))
      el.textContent = renderer;
    const slot = view.querySelector("[data-core-slot]");
    slot?.classList.toggle("is-unknown", !label);
    if (label) core?.setState(label);
    for (const button of view.querySelectorAll("[data-state]"))
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.state === label),
      );
    const summary = view.querySelector(".core-summary");
    if (summary) summary.textContent = label || "Unbekannt";
  }
  function lost() {
    voiceActive = null;
    generation++;
    sending = false;
    receipt = "";
    connected = false;
    initialized = false;
    working = false;
    lastSeq = 0;
    state = null;
    emergency = null;
    update();
  }
  document.addEventListener("nexus:connection", (event) => {
    if (event.detail === true) {
      connected = true;
      update();
    } else lost();
  });
  document.addEventListener("nexus:event", (event) => {
    const record = event.detail;
    if (
      !connected ||
      !record ||
      record.v !== "1.0" ||
      !Number.isSafeInteger(record.seq) ||
      record.seq <= lastSeq ||
      !record.data
    )
      return;
    const d = record.data;
    lastSeq = record.seq;
    if (
      record.type === "hello" &&
      d.contract === "1.0" &&
      typeof d.emergency === "boolean"
    ) {
      initialized = true;
      emergency = null;
      state = null;
    }
    if (!initialized) return;
    if (record.type === "voice_level") { voiceActive = d.active; update(); }
    if (record.type === "chat" || record.type === "error") {
      const item = document.createElement("li");
      item.textContent = record.type === "chat" ? d.sender + ": " + d.text : "Fehler: " + d.message;
      conversation.append(item);
      if (conversation.children.length > 80) conversation.firstChild.remove();
    }
    if (record.type === "emergency" && typeof d.engaged === "boolean")
      emergency = d.engaged;
    if (record.type === "activity") working = d.working === true;
    if (record.type === "state")
      state = stateNames.has(d.state) ? d.state : null;
    if (["hello", "emergency", "state", "activity"].includes(record.type))
      update();
  });
  function render(id, focus) {
    if (!templates.has(id)) id = "core";
    restorePanels();
    name = id;
    view.replaceChildren(templates.get(id).content.cloneNode(true));
    for (const el of view.querySelectorAll("button,input,select,textarea")) {
      if (el.dataset.action === "menu") {
        el.setAttribute("aria-label", "Navigation öffnen");
        el.setAttribute("aria-expanded", "false");
      } else el.disabled = true;
    }
    const form = view.querySelector("#command-form");
    if (form || id === "ai-core") {
      const panel = document.createElement("div");
      panel.className = "live-voice";
      const start = form?.querySelector('[data-action="voice"]') || document.createElement("button");
      start.type = "button";
      start.dataset.liveVoice = "start";
      start.setAttribute("aria-label", "Sprachmodus starten");
      start.title = "Sprachmodus starten";
      if (!form) { start.textContent = "Sprachmodus starten"; panel.append(start); }
      const stop = document.createElement("button");
      stop.type = "button";
      stop.dataset.liveVoice = "stop";
      stop.textContent = "Sprachmodus beenden";
      panel.append(stop);
      const note = document.createElement("p");
      note.className = "live-receipt";
      note.setAttribute("role", "status");
      if (form) form.after(panel, note, conversation);
      else view.querySelector("main").append(panel, note, conversation);
    }
    if (["overview", "agent-center", "live-workspace"].includes(id)) {
      for (const {panel} of panels) liveTasks.append(panel);
      host.append(liveTasks);
      const slot = document.createElement("slot");
      slot.name = liveTasks.slot;
      view.querySelector("main").firstElementChild.after(slot);
    }
    view.querySelector("[data-core-slot]").append(core?.canvas || canvas);
    update();
    if (focus && !host.inert) {
      view.querySelector("main")?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    }
  }
  function surface(open) {
    showing = open;
    host.hidden = !open;
    document.body.classList.toggle("nexus-open", open);
    document.dispatchEvent(new Event("nexus:surface"));
    toggle.textContent = open
      ? "V1-Oberfläche"
      : "NEXUS Ultimate · Leseansicht";
    toggle.setAttribute("aria-expanded", String(open));
    if (open) render(name, true);
    else restorePanels();
  }
  shadow.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.target.id !== "command-form" || sending || !available()) return;
    const field = event.target.querySelector("input");
    const text = field.value.trim();
    if (!text) return;
    const session = generation;
    sending = true;
    receipt = "Warte auf Empfangsbestätigung …";
    update();
    const ack = await send("submit_text", { text });
    if (session !== generation) return;
    sending = false;
    receipt = ack?.ok ? "Auftrag angenommen." : ack ? "Abgelehnt: " + (ack.message || ack.code) : "Empfang unbestätigt.";
    if (ack?.ok) field.value = "";
    update();
  });
  shadow.addEventListener("click", async (event) => {
    const voice = event.target.closest("[data-live-voice]");
    if (voice && available() && !sending) {
      const session = generation;
      sending = true;
      receipt = "Warte auf Sprachdienst …";
      update();
      const ack = await send(voice.dataset.liveVoice === "start" ? "start_voice" : "stop_voice", {});
      if (session === generation) {
        sending = false;
        receipt = ack?.ok ? "Sprachanfrage angenommen." : ack?.message || "Sprachdienst nicht bestätigt.";
        update();
      }
      return;
    }
    const link = event.target.closest("a");
    if (link === download) return;
    if (link) {
      event.preventDefault();
      render(link.getAttribute("href").replace(/^#\//, ""), true);
    }
    if (event.target.closest('[data-action="menu"]')) {
      const open = view.querySelector("#side").classList.toggle("open");
      view
        .querySelector('[data-action="menu"]')
        .setAttribute("aria-expanded", String(open));
    }
  });
  const dialog = document.getElementById("confirm-dialog");
  function syncDialog() {
    host.inert = !dialog.hidden;
    toggle.disabled = !dialog.hidden;
    update();
  }
  new MutationObserver(syncDialog).observe(dialog, {
    attributes: true,
    attributeFilter: ["hidden"],
  });
  syncDialog();
  toggle.addEventListener("click", () => surface(!showing));
  const effects = document.getElementById("effects");
  function setEffects() {
    core?.setMotion(effects.value === "off" ? false : null);
    core?.setQuality(effects.value === "reduced" ? "performance" : "auto");
  }
  effects.addEventListener("change", setEffects);
  import("/nexus/core.js" + query)
    .then(({ createCore }) => {
      surface(true);
      core = createCore(canvas, {
        onMetrics: (m) => {
          renderer = m.backend;
          fps = m.fps;
          update();
        },
      });
      setEffects();
      update();
      toggle.hidden = false;
    })
    .catch(() => {
      surface(false);
      toggle.hidden = true;
    });
  window.addEventListener("pagehide", (event) => {
    if (!event.persisted) core?.dispose();
  });
})();
