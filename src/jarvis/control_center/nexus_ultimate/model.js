export const pages = [
  ["overview", "Overview", "grid"],
  ["ai-core", "AI Core", "orbit"],
  ["live-workspace", "Live Workspace", "folder"],
  ["agent-center", "Agent Center", "agents"],
  ["creative-studio", "Creative Studio", "spark"],
  ["coding-studio", "Coding Studio", "code"],
  ["business-center", "Business Center", "brief"],
  ["trading-center", "Trading Center", "chart"],
  ["automations", "Automations", "flow"],
  ["memory-settings", "Memory & Settings", "sliders"],
];
export { STATES as states } from "./core-geometry.js";
export const qualities = ["auto", "high", "performance"];
export const qualityNames = {
  auto: "Adaptiv",
  high: "Hoch",
  performance: "Performance",
};
export const storageKey = "jarvis-nexus.workspace.v1";
export const initialFiles = {
  "index.html":
    '<main class="signal">\n  <span>NEXUS LAB</span>\n  <div class="halo"></div>\n  <h1>Orbital Signal</h1>\n  <p>Creative workspace · 001</p>\n</main>',
  "theme.css":
    ":root { color-scheme: dark; }\nbody { margin: 0; background: #0a0b17; color: #eeebff; font-family: system-ui, sans-serif; }\n.signal { text-align: center; padding: 36px 16px; }\nspan, p { font: 11px monospace; letter-spacing: 2px; color: #aaa1cf; }\n.halo { width: 66px; height: 66px; border: 1px solid #b08cfe; border-radius: 50%; margin: 24px auto; box-shadow: 0 0 24px #7955cc, inset 0 0 24px #7955cc; }\nh1 { font-size: 30px; margin: 14px 0; }",
  "notes.md":
    "# Orbital Signal\n\nEin lokales Demo-Projekt für den Live Workspace.\n\n- HTML-Struktur anpassen\n- Akzentfarbe in theme.css wählen\n- Vorschau prüfen",
};
export const initialTasks = [
  { id: "t1", title: "Farbpalette abstimmen", phase: "Geplant" },
  { id: "t2", title: "Orbital-Signal gestalten", phase: "In Arbeit" },
  { id: "t3", title: "Projektstruktur anlegen", phase: "Erledigt" },
];
export const phases = ["Geplant", "In Arbeit", "Erledigt"];
export function cleanState(raw = {}) {
  const src = raw && typeof raw === "object" ? raw : {};
  const files = { ...initialFiles };
  for (const key of Object.keys(files))
    if (typeof src.files?.[key] === "string")
      files[key] = src.files[key].slice(0, 120000);
  const tasks = Array.isArray(src.tasks)
    ? src.tasks
        .filter(
          (t) =>
            t &&
            typeof t.title === "string" &&
            typeof t.id === "string" &&
            phases.includes(t.phase),
        )
        .slice(0, 160)
        .map((t) => ({
          id: t.id.slice(0, 80),
          title: t.title.slice(0, 90),
          phase: t.phase,
        }))
    : structuredClone(initialTasks);
  const events = Array.isArray(src.events)
    ? src.events
        .filter(
          (e) => e && typeof e.text === "string" && Number.isFinite(e.time),
        )
        .slice(0, 40)
        .map((e) => ({ text: e.text.slice(0, 160), time: e.time }))
    : [];
  return {
    files,
    tasks,
    events,
    quality: qualities.includes(src.quality) ? src.quality : "auto",
    motion: typeof src.motion === "boolean" ? src.motion : null,
    autoReview: src.autoReview === true,
    autoLog: src.autoLog !== false,
    memory: typeof src.memory === "string" ? src.memory.slice(0, 4000) : "",
    palette: ["Violett", "Cyan", "Magenta"].includes(src.palette)
      ? src.palette
      : "Violett",
    rings: Math.min(20, Math.max(4, Math.round(Number(src.rings) || 12))),
  };
}
export function loadState(storage) {
  try {
    return cleanState(JSON.parse(storage.getItem(storageKey)));
  } catch {
    return cleanState();
  }
}
export function saveState(storage, state) {
  try {
    storage.setItem(storageKey, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}
export function esc(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
export function route(hash) {
  const id = hash.replace(/^#\/?/, "");
  return pages.some((p) => p[0] === id) ? id : "core";
}
export function fileStatus(session, name) {
  if (session.drafts[name] !== undefined) return "Entwurf";
  return session.persistent === false ? "Nur in Sitzung" : "Gespeichert";
}
export function inspectFiles(files) {
  return [
    ["HTML-Hauptbereich", /<main[\s>]/i.test(files["index.html"])],
    ["Stylesheet befüllt", files["theme.css"].trim().length > 0],
    ["Projektnotizen", files["notes.md"].trim().length > 0],
  ];
}
export function previewDocument(files) {
  const css = files["theme.css"].replace(/<\/style/gi, "<\\/style");
  return (
    "<!doctype html><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'\"><style>" +
    css +
    "</style>" +
    files["index.html"]
  );
}
export function commandIntent(text) {
  const q = text.toLowerCase().trim();
  if (/status|diagnos/.test(q)) return "status";
  if (/workspace|projektdatei/.test(q)) return "live-workspace";
  if (/dashboard|overview/.test(q)) return "overview";
  if (/kern|ai core/.test(q)) return "ai-core";
  if (/hilfe|befehl|help/.test(q)) return "help";
  return "unknown";
}
export const palettes = {
  Violett: ["#bd88ff", "#6c65ff"],
  Cyan: ["#72f4fa", "#496eff"],
  Magenta: ["#fd79d7", "#a06bf9"],
};
export function studioArt(name, count) {
  const [a, b] = palettes[name] || palettes.Violett;
  const rings = Array.from(
    { length: count },
    (_, i) =>
      '<ellipse cx="240" cy="150" rx="130" ry="55" transform="rotate(' +
      (180 / count) * i +
      ' 240 150)" stroke="url(#g)" stroke-width="1.3" fill="none"/>',
  ).join("");
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 300"><defs><linearGradient id="g"><stop stop-color="' +
    a +
    '"/><stop offset="1" stop-color="' +
    b +
    '"/></linearGradient></defs><rect width="480" height="300" fill="#090b16"/>' +
    rings +
    "</svg>"
  );
}
