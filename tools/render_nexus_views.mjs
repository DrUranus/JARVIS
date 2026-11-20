// Render pinned Premium views as inert templates using only local build-time data.
import { writeFile } from "node:fs/promises";
import {
  home,
  dashboard,
} from "../src/jarvis/control_center/nexus_ultimate/views.js";
import {
  cleanState,
  pages,
} from "../src/jarvis/control_center/nexus_ultimate/model.js";
globalThis.matchMedia = () => ({ matches: false });
const demo = cleanState();
const session = {
  state: "Unbekannt",
  file: "index.html",
  drafts: {},
  review: null,
  symbol: "NXS",
  period: "14T",
};
const templates = [
  ["core", home(session.state)],
  ...pages.map(([id]) => [id, dashboard(id, demo, session)]),
];
let output = "";
for (const [id, html] of templates) {
  const safe = html
    .replaceAll(
      /<iframe\b[^>]*><\/iframe>/g,
      '<p class="preview-offline">Die Dateivorschau ist in dieser Leseansicht deaktiviert.</p>',
    )
    .replaceAll(/ style="[^"]*"/g, "")
    .replaceAll('src="./nexus.svg"', 'src="/nexus/nexus.svg?t=__TOKEN__"');
  output += `<template data-nexus-page="${id}">${safe}</template>\n`;
}
await writeFile(
  new URL(
    "../src/jarvis/control_center/nexus_preview/pages.html",
    import.meta.url,
  ),
  output,
);
