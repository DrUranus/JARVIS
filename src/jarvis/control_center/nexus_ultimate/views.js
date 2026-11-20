import { icon } from "./icons.js";
import {
  pages,
  states,
  qualityNames,
  qualities,
  esc,
  phases,
  studioArt,
  inspectFiles,
  fileStatus,
  palettes,
} from "./model.js";
const i = icon;
const link = (id, label, ico) =>
  `<a class="btn" href="#/${id}">${i(ico)}${label}</a>`;
const button = (action, label, ico, cls = "btn") =>
  `<button class="${cls}" data-action="${action}">${ico ? i(ico) : ""}${label}</button>`;
const brand = `<a class="brand" href="#/core" aria-label="Nexus Ultimate, Core-Modus"><img src="./nexus.svg" alt=""><span>NEXUS<small>ULTIMATE</small></span></a>`;
const tag = '<span class="demo"><b></b>Lokale Demo</span>';
const bars =
  '<span class="meter" aria-hidden="true">' +
  Array.from({ length: 15 }, (_, n) => '<i style="--n:' + n + '"></i>').join(
    "",
  ) +
  "</span>";
const frame =
  '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';
export function home(state) {
  return `<div class="shell home"><header class="top">${brand}<span class="header-rule"></span><span class="header-kind">Core Interface</span><div class="tools">${button("preferences", i("sliders", 19), "", "icon-btn prefs")}<a class="dash-btn" href="#/overview">${i("grid", 15)}Dashboard</a></div></header>
<main id="main" class="core-main" tabindex="-1"><div class="cosmos"></div><div class="floor"></div>
<div class="stage"><div class="readout left-read"><span class="micro"><b></b>CORE STATUS</span><span class="read-value"><span class="live-dot"></span><span data-current-state>${esc(state)}</span></span><span class="read-line"></span></div>
<div class="holo"><div class="target-frame" aria-hidden="true">${frame}</div><div class="orb-mount" data-core-slot></div><div class="projector" aria-hidden="true"><i></i><i></i><i></i><b></b></div></div>
<div class="readout right-read"><span class="micro"><b></b>RENDER ENGINE</span><span class="read-value" data-backend>Initialisierung</span>${bars}</div></div>
<div class="hero-name"><h1>JARVIS</h1><div class="edition"><span></span>NEXUS ULTIMATE<span></span></div></div>
<section class="command-area" aria-label="Lokale Befehlseingabe"><div id="reply"></div>
<form class="command" id="command-form"><span class="wave-icon">${i("wave", 23)}</span><input id="command-field" aria-label="Befehl an JARVIS" placeholder="Befehl an JARVIS eingeben …" autocomplete="off" maxlength="500"><button type="button" class="mic icon-btn" aria-label="Informationen zur Spracheingabe" data-action="voice">${i("mic", 18)}</button><button class="send" type="submit" aria-label="Befehl senden">${i("send", 18)}</button></form>
<div class="quick">${button("status", "Systemstatus", "pulse", "quick-btn")}<a class="quick-btn" href="#/live-workspace">${i("folder", 15)}Workspace öffnen</a><a class="quick-btn" href="#/ai-core">${i("sliders", 15)}Kern steuern</a></div></section></main>
<footer class="footer"><div>${tag}<span class="footer-rule"></span><span>Core-Modus</span></div><div class="foot-right">${i("keyboard", 15)}<kbd>Ctrl</kbd><kbd>K</kbd><span>Eingabe fokussieren</span></div></footer></div>`;
}
const subtitles = {
  overview: "Dein lokaler Arbeitsbereich auf einen Blick.",
  "ai-core": "Visualisierung und Verhalten des holografischen Kerns.",
  "live-workspace":
    "Dateien bearbeiten, Vorschau prüfen und Arbeitsschritte verfolgen.",
  "agent-center": "Lokale Prüfprofile für dein Workspace-Projekt.",
  "creative-studio": "Gestalte eine orbitale Vektorgrafik für dein Projekt.",
  "coding-studio": "Quelltext und Struktur deines lokalen Projekts.",
  "business-center": "Aufgaben für Orbital Signal planen und organisieren.",
  "trading-center": "Historische Muster anhand fiktiver Kursdaten erkunden.",
  automations: "Lokale Abläufe für den Workspace konfigurieren.",
  "memory-settings": "Lokalen Speicher und Darstellung verwalten.",
};
function panel(title, body, extra = "") {
  return `<section class="panel ${extra}"><h2>${title}</h2>${body}</section>`;
}
function emptyState(symbol, text) {
  return `<div class="empty-state">${i(symbol, 18)}<span>${text}</span></div>`;
}
// Project artwork samples a family of phase-shifted signal traces.
function signalField() {
  const paths = Array.from({ length: 38 }, (_, row) => {
    const points = Array.from({ length: 74 }, (_, col) => {
      const x = col * 7,
        t = col / 73,
        z = row / 37;
      const envelope = Math.sin(Math.PI * t);
      const y =
        110 +
        (z - 0.5) * 105 +
        envelope *
          (47 * Math.sin(t * 7.6 + z * 3.9) +
            32 * Math.sin(t * 11.2 - z * 3.2));
      return `${x},${y.toFixed(2)}`;
    });
    return `<polyline points="${points.join(" ")}"/>`;
  });
  return `<svg class="signal-field" aria-hidden="true" viewBox="0 0 512 220"><defs><linearGradient id="signal"><stop stop-color="#9562ff" stop-opacity=".12"/><stop offset=".35" stop-color="#ad7eff"/><stop offset=".68" stop-color="#9cacff"/><stop offset="1" stop-color="#57c8e8" stop-opacity=".4"/></linearGradient></defs><g fill="none" stroke="url(#signal)" stroke-width="1.05">${paths.join("")}</g></svg>`;
}
const signalIllustration = signalField();
function eventList(data) {
  return data.events.length
    ? `<ul class="activity">${data.events
        .slice(0, 5)
        .map(
          (e) =>
            `<li>${i("pulse", 15)}<span>${esc(e.text)}</span><time>${new Date(e.time).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}</time></li>`,
        )
        .join("")}</ul>`
    : emptyState("pulse", "Bisher keine lokalen Aktivitäten.");
}
function checkResults(session, files) {
  return session.review
    ? `<ul class="checks">${session.review.map(([name, pass]) => `<li>${i(pass ? "check" : "close", 16)}${name}<span>${pass ? "Erfüllt" : "Offen"}</span></li>`).join("")}</ul>`
    : `<ul class="checks pending">${inspectFiles(files)
        .map(
          ([name]) =>
            `<li>${i("layers", 15)}${name}<span>Ausstehend</span></li>`,
        )
        .join("")}</ul>`;
}
function projectProgress(data) {
  const n = data.tasks.filter((t) => t.phase === "Erledigt").length;
  return `<div class="pair"><strong class="progress-figure">${Math.round((100 * n) / Math.max(1, data.tasks.length))}<small> %</small></strong><span>${n} / ${data.tasks.length} Aufgaben</span></div><progress aria-label="Erledigte Projektaufgaben" value="${n}" max="${Math.max(1, data.tasks.length)}"></progress><small>Erledigte Aufgaben · Orbital Signal</small>`;
}
function workspace(data, s, coding) {
  const file = s.file,
    files = Object.keys(data.files);
  return `<div class="workbar"><span>${i("folder", 17)} Orbital Signal</span><span class="muted">${files.length} Projektdateien</span></div><div class="workgrid ${coding ? "coding" : ""}">
 <div class="file-tree"><h2>Projektdateien</h2>${files.map((name) => `<button class="file ${file === name ? "active" : ""}" data-file="${name}">${i(name.endsWith("html") ? "code" : name.endsWith("css") ? "layers" : "file", 15)}${name}</button>`).join("")}</div>
 <section class="editor"><div class="editor-head"><strong>${i("code", 15)}${file}</strong><span id="dirty">${fileStatus(s, file)}</span></div><textarea wrap="off" aria-label="Quelltext von ${file}" id="source-code" spellcheck="false" maxlength="120000">${esc(s.drafts[file] ?? data.files[file])}</textarea><div class="editor-tools">${button("save-file", "Speichern", "save", "btn accent")}<kbd>Ctrl S</kbd><output class="position" id="position" aria-live="off">Z 1 · Sp 1</output></div></section>
 <section class="preview"><div class="editor-head"><strong>${i("expand", 15)}Vorschau</strong>${button("expand-preview", i("expand", 16), "", "icon-btn")}</div><iframe title="Sandbox-Vorschau von Orbital Signal" sandbox="" id="preview"></iframe></section></div>
 <div class="two-cols">${panel(coding ? "Strukturprüfung" : "Agentenaktivität", (coding ? checkResults(s, data.files) : eventList(data)) + button("review", "Lokal prüfen", "play"))}${panel("Projektstatus", projectProgress(data))}</div>`;
}
export function paletteLegend(name) {
  return palettes[name]
    .map(
      (hex) =>
        `<span><i style="--swatch:${hex}"></i>${hex.toUpperCase()}</span>`,
    )
    .join("");
}
export const markets = {
  NXS: [40, 44, 42, 52, 46, 58, 53, 60, 57, 66, 61, 70, 68, 77],
  ORB: [57, 54, 51, 57, 55, 59, 50, 53, 48, 55, 52, 58, 57, 62],
  VEC: [75, 73, 80, 68, 71, 66, 69, 61, 65, 63, 70, 67, 66, 69],
};
function marketView(s) {
  const values = markets[s.symbol].slice(s.period === "7T" ? -7 : 0),
    last = values.at(-1),
    delta = last - values[0];
  const points = values
    .map(
      (v, n) =>
        `${12 + (n * 576) / (values.length - 1)},${190 - (v - 35) * 3.5}`,
    )
    .join(" ");
  return panel(
    'Marktverlauf <span class="badge">Fiktive Kurse</span>',
    `<div class="chart-top"><div><label for="asset">Demo-Asset</label><select id="asset">${Object.keys(
      markets,
    )
      .map((n) => `<option ${s.symbol === n ? "selected" : ""}>${n}</option>`)
      .join(
        "",
      )}</select></div><div class="seg">${["7T", "14T"].map((t) => `<button data-period="${t}" aria-pressed="${s.period === t}">${t}</button>`).join("")}</div></div><div class="quote">${last.toFixed(2).replace(".", ",")} <small>Credits</small><span class="${delta < 0 ? "down" : "up"}">${delta >= 0 ? "+" : ""}${delta} im Zeitraum</span></div><svg class="price-chart" viewBox="-2 0 630 208" role="img" aria-label="Fiktiver Kursverlauf ${s.symbol}, von ${values[0]} bis ${last} Credits"><defs><linearGradient id="area" x2="0" y2="1"><stop stop-color="#8e74ff" stop-opacity=".4"/><stop offset="1" stop-color="#8e74ff" stop-opacity="0"/></linearGradient></defs>${[
      40, 50, 60, 70, 80,
    ]
      .map((value) => {
        const y = 190 - (value - 35) * 3.5;
        return `<path d="M12 ${y}H588" stroke="#363347" stroke-dasharray="2 5"/><text x="598" y="${y + 3}" fill="#a9a3bf" font-size="9" font-family="monospace">${value}</text>`;
      })
      .join(
        "",
      )}<polygon points="12,205 ${points} 588,205" fill="url(#area)"/><polyline points="${points}" fill="none" stroke="#a997ff" stroke-linejoin="round" stroke-width="2.2"/><circle cx="588" cy="${190 - (last - 35) * 3.5}" r="5.6" fill="#9d91ef" opacity=".22"/><circle cx="588" cy="${190 - (last - 35) * 3.5}" r="2.2" fill="#e0daff"/></svg><div class="pair muted"><span>Tag 1</span><span>Tag ${values.length}</span></div>`,
  );
}
function settings(data) {
  return `<label for="quality">Renderqualität</label><select id="quality">${qualities.map((q) => `<option value="${q}" ${q === data.quality ? "selected" : ""}>${qualityNames[q]}</option>`).join("")}</select><div class="setting"><div><strong>Animation</strong><small>Rotation und Lichtströme</small></div><input type="checkbox" role="switch" id="motion" aria-label="Animation aktivieren" ${(data.motion ?? !matchMedia("(prefers-reduced-motion: reduce)").matches) ? "checked" : ""}></div>`;
}
export { settings };
function content(id, d, s) {
  switch (id) {
    case "overview":
      return `<div class="overview-lead">${signalIllustration}<div class="micro">AKTUELLES PROJEKT</div><h2>Orbital Signal</h2><p>Holografisches Interface · Lokales Demo-Projekt</p>${link("live-workspace", "Workspace öffnen", "folder")}</div><div class="two-cols">${panel("Projektfortschritt", projectProgress(d))}${panel("JARVIS-Kern", '<div class="core-summary"><span class="live-dot"></span>' + esc(s.state) + "</div>" + link("ai-core", "Kern steuern", "sliders"))}</div>${panel("Letzte Aktivitäten", eventList(d))}`;
    case "ai-core":
      return `<div class="two-cols">${panel("Kernzustand", '<div class="state-grid">' + states.map((t) => `<button data-state="${t}" aria-pressed="${s.state === t}">${i(t === "Emergency Stop" ? "stop" : { Listening: "mic", Speaking: "wave", Thinking: "layers", Working: "flow", Error: "pulse", "Awaiting Approval": "check" }[t] || "orbit", 16)}${t}</button>`).join("") + '</div><p class="muted">Die Auswahl steuert die lokale Visualisierung.</p>')}${panel("Rendering", settings(d) + '<div class="setting"><strong>Renderer</strong><span data-backend></span></div><div class="setting"><strong>Bildrate</strong><span data-fps>–</span></div>')}</div>`;
    case "live-workspace":
      return workspace(d, s, false);
    case "coding-studio":
      return workspace(d, s, true);
    case "agent-center":
      return (
        panel(
          'Workspace Inspector <span class="badge">Lokales Prüfprofil</span>',
          `<div class="agent-head"><div class="big-icon">${i("agents", 30)}</div><div><h3>Projektprüfung</h3><p>Prüft HTML-Hauptbereich, Stylesheet und Projektnotizen der gespeicherten Dateien.</p></div></div>${checkResults(s, d.files)}${button("review", "Prüfung starten", "play", "btn accent")}`,
        ) + panel("Aktivität", eventList(d))
      );
    case "creative-studio":
      return `<div class="creative-layout"><div class="artboard" id="artboard">${studioArt(d.palette, d.rings)}</div>${panel("Orbital-Generator", `<label for="palette">Farbpalette</label><select id="palette">${["Violett", "Cyan", "Magenta"].map((v) => `<option ${v === d.palette ? "selected" : ""}>${v}</option>`).join("")}</select><div class="palette-spec" id="palette-spec">${paletteLegend(d.palette)}</div><label for="rings">Energieringe <output id="ring-value">${d.rings}</output></label><input type="range" id="rings" min="4" max="20" value="${d.rings}">${button("export-art", "SVG exportieren", "save", "btn accent")}`)}</div>`;
    case "business-center":
      return `<form class="inline-form" id="task-form"><input required maxlength="90" aria-label="Neue Projektaufgabe" placeholder="Neue Projektaufgabe …"><button class="btn accent">${i("plus", 16)}Hinzufügen</button></form><div class="kanban">${phases
        .map((p) =>
          panel(
            p +
              ' <span class="count">' +
              d.tasks.filter((t) => t.phase === p).length +
              "</span>",
            d.tasks
              .filter((t) => t.phase === p)
              .map(
                (t) =>
                  `<article class="task"><strong>${esc(t.title)}</strong><select data-task="${esc(t.id)}" aria-label="Status von ${esc(t.title)}">${phases.map((v) => `<option ${p === v ? "selected" : ""}>${v}</option>`).join("")}</select></article>`,
              )
              .join("") || emptyState("brief", "Keine Aufgaben"),
          ),
        )
        .join("")}</div>`;
    case "trading-center":
      return marketView(s);
    case "automations":
      return (
        panel(
          "Workspace-Regeln",
          `<div class="setting rule"><span class="rule-icon">${i("agents", 20)}</span><div><strong>Prüfung nach dem Speichern</strong><small>Führt das lokale Prüfprofil nach jeder Dateispeicherung aus.</small></div><input type="checkbox" role="switch" aria-label="Automatische Prüfung" id="autoReview" ${d.autoReview ? "checked" : ""}></div><div class="setting rule"><span class="rule-icon">${i("file", 20)}</span><div><strong>Speicheraktivitäten protokollieren</strong><small>Hält Dateispeicherungen im lokalen Aktivitätsverlauf fest.</small></div><input type="checkbox" role="switch" aria-label="Speicherprotokoll" id="autoLog" ${d.autoLog ? "checked" : ""}></div>`,
        ) + panel("Aktivitätsverlauf", eventList(d))
      );
    case "memory-settings":
      return `<div class="two-cols">${panel("Darstellung", settings(d))}${panel("Projektnotiz", `<label for="memory">Lokaler Kontext</label><textarea id="memory" maxlength="4000" placeholder="Projektnotizen festhalten …">${esc(d.memory)}</textarea><div class="memory-tools">${button("save-memory", "Notiz speichern", "save")}<output id="memory-count">${d.memory.length} / 4000</output></div>`)}</div>${panel("Lokaler Speicher", "<p>Projektdateien, Aufgaben und Einstellungen werden in diesem Browser gespeichert.</p>" + button("reset", "Demo zurücksetzen", "trash"))}`;
  }
}
export function dashboard(id, d, s) {
  const page = pages.find((p) => p[0] === id);
  return `<div class="dash-shell"><header class="top">${brand}<span class="header-rule"></span><span class="header-kind">Dashboard</span><span class="mobile-demo">Lokale Demo</span><div class="tools">${button("menu", i("menu"), "", "icon-btn nav-toggle")}<a class="dash-btn" href="#/core">${i("orbit", 16)}Core-Modus</a></div></header><div class="dash-layout"><nav id="side" aria-label="Dashboard-Bereiche">${pages.map(([key, name, ico]) => `<a href="#/${key}" ${key === id ? 'aria-current="page"' : ""}>${i(ico)}${name}</a>`).join("")}<div class="side-demo">${tag}</div></nav><main id="main" class="dash-main ${id}" tabindex="-1"><div class="dash-heading"><div><div class="micro">NEXUS WORKSPACE</div><h1>${page[1]}</h1><p>${subtitles[id]}</p></div>${id === "ai-core" ? "" : '<div class="mini-core" data-core-slot></div>'}</div>${id === "ai-core" ? '<div class="core-inspect"><div data-core-slot></div><span class="core-caption"><span class="live-dot"></span><span data-current-state>' + esc(s.state) + "</span></span></div>" : ""}${content(id, d, s)}</main></div></div>`;
}
