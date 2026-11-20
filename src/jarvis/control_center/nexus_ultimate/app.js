import { home, dashboard, settings, paletteLegend } from "./views.js";
import { icon } from "./icons.js";
import { createCore } from "./core.js";
import {
  loadState,
  saveState,
  cleanState,
  route,
  esc,
  commandIntent,
  previewDocument,
  inspectFiles,
  fileStatus,
  studioArt,
  states,
  qualityNames,
} from "./model.js";

const app = document.querySelector("#app"),
  dialog = document.querySelector("#modal");
let storage;
try {
  storage = window.localStorage;
} catch {
  /* Rendering stays available without storage. */
}
let data = loadState(storage);
const session = {
  page: route(location.hash),
  state: "Idle",
  file: "index.html",
  drafts: {},
  review: null,
  symbol: "NXS",
  period: "14T",
};
let metrics = { backend: "Initialisierung", fps: 0 },
  core,
  toastTimer,
  stateTimer;
const $ = (selector) => document.querySelector(selector);
function notify(message) {
  const el = $("#notice");
  el.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.textContent = ""), 3200);
}
function persist(message) {
  const saved = saveState(storage, data);
  session.persistent = saved;
  if (!saved)
    notify(
      "Browserspeicher nicht verfügbar. Änderungen gelten für diese Sitzung.",
    );
  else if (message) notify(message);
  return saved;
}
function log(text) {
  data.events.unshift({ text, time: Date.now() });
  data.events = data.events.slice(0, 40);
}
function telemetry(m) {
  metrics = m;
  $("[data-core-slot]")?.setAttribute(
    "aria-busy",
    String(m.backend === "Initialisierung"),
  );
  document
    .querySelectorAll("[data-backend]")
    .forEach((el) => (el.textContent = m.backend));
  document
    .querySelectorAll("[data-fps]")
    .forEach((el) => (el.textContent = m.fps > 0 ? m.fps + " FPS" : "–"));
}
function render(focusMain = false) {
  const canvas = core?.canvas || document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    "Dreidimensionaler holografischer JARVIS-Kern",
  );
  app.dataset.coreState = session.state;
  app.innerHTML =
    session.page === "core"
      ? home(session.state)
      : dashboard(session.page, data, session);
  $("#main").classList.toggle("enter-view", focusMain || !core);
  document.documentElement.dataset.motion = String(
    data.motion ?? !matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const pref = $('[data-action="preferences"]'),
    menu = $('[data-action="menu"]'),
    expand = $('[data-action="expand-preview"]');
  pref?.setAttribute("aria-label", "Darstellung einstellen");
  menu?.setAttribute("aria-label", "Navigation öffnen");
  menu?.setAttribute("aria-expanded", "false");
  expand?.setAttribute("aria-label", "Vorschau vergrößern");
  $("[data-core-slot]").append(canvas);
  if (!core) {
    core = createCore(canvas, { onMetrics: telemetry });
    core.setState(session.state);
    core.setQuality(data.quality);
    if (data.motion !== null) core.setMotion(data.motion);
  }
  telemetry(metrics);
  if ($("#preview")) $("#preview").srcdoc = previewDocument(data.files);
  if (focusMain) $("#main").focus({ preventScroll: true });
}
function setState(name) {
  clearTimeout(stateTimer);
  session.state = name;
  app.dataset.coreState = name;
  document
    .querySelectorAll("[data-state]")
    .forEach((el) =>
      el.setAttribute("aria-pressed", String(el.dataset.state === name)),
    );
  core.setState(name);
  document
    .querySelectorAll("[data-current-state]")
    .forEach((el) => (el.textContent = name));
}
function showDialog(title, body, wide = false) {
  dialog.classList.toggle("wide-dialog", wide);
  dialog.innerHTML =
    '<div class="dialog-body"><div class="dialog-head"><h2 id="dialog-title">' +
    esc(title) +
    '</h2><button data-action="close" class="icon-btn" aria-label="Schließen">' +
    icon("close") +
    "</button></div>" +
    body +
    "</div>";
  dialog.setAttribute("aria-labelledby", "dialog-title");
  if (!dialog.open) dialog.showModal();
}
function reply(text) {
  const el = $("#reply");
  if (!el) return;
  el.innerHTML =
    '<div role="status"><strong>JARVIS · LOKAL</strong><p>' +
    esc(text) +
    '</p></div><button data-action="dismiss" class="icon-btn" aria-label="Antwort schließen">' +
    icon("close", 16) +
    "</button>";
}
function executeCommand(text) {
  if (!text.trim()) {
    $("#command-field")?.focus();
    return;
  }
  const action = commandIntent(text);
  if (["overview", "ai-core", "live-workspace"].includes(action)) {
    location.hash = "/" + action;
    return;
  }
  if (action === "status") {
    reply(
      "Kernzustand " +
        session.state +
        " · " +
        metrics.backend +
        " · Qualität " +
        qualityNames[data.quality] +
        (metrics.fps ? " · " + metrics.fps + " FPS" : "") +
        ". Projektdateien und Einstellungen liegen lokal im Browser.",
    );
    return;
  }
  reply(
    action === "help"
      ? "Verfügbare Befehle: Systemstatus, Dashboard, Workspace öffnen und Kern steuern."
      : "Für diesen Text ist kein lokaler Befehl hinterlegt. Mit „Hilfe“ siehst du die verfügbaren Befehle.",
  );
}
function review(announce = true) {
  session.review = inspectFiles(data.files);
  const n = session.review.filter(([, pass]) => pass).length;
  log("Workspace Inspector · " + n + " von 3 Kriterien erfüllt");
  if (announce) persist("Projektprüfung abgeschlossen · " + n + "/3");
}
function saveFile() {
  const editor = $("#source-code");
  if (!editor) return;
  data.files[session.file] = editor.value;
  delete session.drafts[session.file];
  if (data.autoLog) log(session.file + " gespeichert");
  if (data.autoReview) review(false);
  persist("Datei lokal gespeichert");
  render();
  $("#source-code")?.focus();
}
function artUpdate() {
  const art = $("#artboard");
  if (art) art.innerHTML = studioArt(data.palette, data.rings);
  if ($("#palette-spec"))
    $("#palette-spec").innerHTML = paletteLegend(data.palette);
  if ($("#ring-value")) $("#ring-value").value = data.rings;
}
const actions = {
  preferences: () => showDialog("Darstellung", settings(data)),
  voice: () =>
    showDialog(
      "Spracheingabe",
      '<p>Die Spracheingabe ist für die spätere JARVIS-Anbindung vorgesehen. In der lokalen Demo kannst du Befehle über die Tastatur eingeben.</p><button class="btn accent" data-action="type">Textbefehl eingeben</button>',
    ),
  type: () => {
    dialog.close();
    $("#command-field")?.focus();
  },
  close: () => dialog.close(),
  dismiss: () => {
    $("#reply").replaceChildren();
    $("#command-field")?.focus();
  },
  status: () => executeCommand("Systemstatus"),
  menu: () => {
    const open = $("#side").classList.toggle("open");
    $('[data-action="menu"]').setAttribute("aria-expanded", String(open));
  },
  "save-file": saveFile,
  "expand-preview": () => {
    showDialog(
      "Orbital Signal · Vorschau",
      '<iframe class="expanded" sandbox="" title="Vergrößerte Projektvorschau"></iframe>',
      true,
    );
    dialog.querySelector("iframe").srcdoc = previewDocument(data.files);
  },
  review: () => {
    review();
    render();
    $('[data-action="review"]')?.focus();
  },
  "save-memory": () => {
    data.memory = $("#memory").value;
    persist("Projektnotiz gespeichert");
  },
  "export-art": () => {
    const url = URL.createObjectURL(
      new Blob([studioArt(data.palette, data.rings)], {
        type: "image/svg+xml",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "nexus-orbital.svg";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify("SVG-Export erstellt");
  },
  reset: () =>
    showDialog(
      "Lokale Demo zurücksetzen?",
      '<p>Gespeicherte Dateien, Entwürfe, Aufgaben, Notizen und Einstellungen werden durch die Ausgangsdaten ersetzt.</p><div class="dialog-actions"><button class="btn" data-action="close">Abbrechen</button><button class="btn accent" data-action="confirm-reset">Zurücksetzen</button></div>',
    ),
  "confirm-reset": () => {
    data = cleanState();
    session.drafts = {};
    session.review = null;
    session.file = "index.html";
    setState("Idle");
    core.setQuality(data.quality);
    core.setMotion(null);
    dialog.close();
    persist("Demo zurückgesetzt");
    render();
  },
};
document.addEventListener("click", (event) => {
  const el = event.target.closest("button");
  if (!el) return;
  if (el.dataset.action) {
    actions[el.dataset.action]?.();
    return;
  }
  if (el.dataset.state && states.includes(el.dataset.state)) {
    setState(el.dataset.state);
  }
  if (el.dataset.file) {
    session.file = el.dataset.file;
    render();
    $("#source-code")?.focus();
  }
  if (el.dataset.period) {
    session.period = el.dataset.period;
    render();
    document.querySelector('[data-period="' + session.period + '"]')?.focus();
  }
});
function updatePosition(event) {
  const editor = event.target;
  if (editor.id !== "source-code") return;
  const lines = editor.value.slice(0, editor.selectionStart).split("\n");
  $("#position").textContent =
    "Z " + lines.length + " · Sp " + (lines.at(-1).length + 1);
}
document.addEventListener("selectionchange", updatePosition, true);
document.addEventListener("keyup", updatePosition);
document.addEventListener("click", updatePosition);
document.addEventListener("input", (event) => {
  const el = event.target;
  if (el.id === "memory")
    $("#memory-count").textContent = el.value.length + " / 4000";
  if (el.id === "source-code") {
    if (el.value === data.files[session.file])
      delete session.drafts[session.file];
    else session.drafts[session.file] = el.value;
    $("#dirty").textContent = fileStatus(session, session.file);
  }
  if (el.id === "rings") {
    data.rings = Number(el.value);
    artUpdate();
  }
});
document.addEventListener("change", (event) => {
  const el = event.target;
  if (el.id === "quality") {
    data.quality = el.value;
    core.setQuality(el.value);
    persist();
  }
  if (el.id === "motion") {
    data.motion = el.checked;
    document.documentElement.dataset.motion = String(el.checked);
    core.setMotion(el.checked);
    persist();
  }
  if (el.id === "autoReview" || el.id === "autoLog") {
    data[el.id] = el.checked;
    persist("Regel aktualisiert");
  }
  if (el.id === "palette") {
    data.palette = el.value;
    artUpdate();
    persist();
  }
  if (el.id === "rings") persist();
  if (el.id === "asset") {
    session.symbol = el.value;
    render();
    $("#asset").focus();
  }
  if (el.dataset.task) {
    const task = data.tasks.find((t) => t.id === el.dataset.task);
    if (task) {
      task.phase = el.value;
      log("Aufgabenstatus · " + task.title + " · " + task.phase);
      persist();
      render();
      document
        .querySelector('[data-task="' + CSS.escape(task.id) + '"]')
        ?.focus();
    }
  }
});
document.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.target.id === "command-form") {
    const el = $("#command-field");
    const value = el.value;
    el.value = "";
    executeCommand(value);
  }
  if (event.target.id === "task-form") {
    const el = event.target.querySelector("input"),
      title = el.value.trim();
    if (!title) return;
    if (data.tasks.length >= 160) {
      notify("Maximal 160 Aufgaben pro Demo.");
      return;
    }
    data.tasks.push({ id: crypto.randomUUID(), title, phase: "Geplant" });
    log("Aufgabe erstellt · " + title);
    persist();
    render();
    $("#task-form input").focus();
  }
});
function routeChange() {
  session.page = route(location.hash);
  if (dialog.open) dialog.close();
  render(true);
  window.scrollTo(0, 0);
  document.title =
    (session.page === "core" ? "JARVIS" : $(".dash-heading h1").textContent) +
    " · Nexus Ultimate";
}
window.addEventListener("hashchange", routeChange);
document.addEventListener("keydown", (event) => {
  if (dialog.open) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (session.page !== "core") {
      location.hash = "/core";
      window.addEventListener(
        "hashchange",
        () => $("#command-field")?.focus(),
        { once: true },
      );
    } else $("#command-field")?.focus();
  }
  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "s" &&
    $("#source-code")
  ) {
    event.preventDefault();
    saveFile();
  }
  if (event.key === "Escape") {
    if ($("#side")?.classList.contains("open")) actions.menu();
    if ($("#reply")?.textContent) actions.dismiss();
  }
});
render();
window.addEventListener("pagehide", (event) => {
  if (!event.persisted) core.dispose();
});
