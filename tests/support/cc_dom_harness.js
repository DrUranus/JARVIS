"use strict";
// Minimaler DOM-Ersatz fuer tests/test_control_center_dashboard.py: laedt web/app.js unveraendert, erzeugt Elemente nur fuer die ids aus index.html
// (so scheitert der Test, wenn app.js eine id braucht, die es nicht gibt) und gibt den gerenderten Text als JSON aus. Kein Netzwerk.
const fs = require("fs");
const vm = require("vm");
const [webDir, scenarioFile] = process.argv.slice(2);
const html = fs.readFileSync(webDir + "/index.html", "utf8");
const scenario = JSON.parse(fs.readFileSync(scenarioFile, "utf8"));

class El {
  constructor(tag) { this.tag = tag; this.children = []; this._text = ""; this.dataset = {}; this.hidden = false; this.className = ""; this.listeners = {};
    this.disabled = false; this.calls = []; this.min = 0; this.max = 1; this.attrs = {}; this.scrollTop = 0; this.scrollHeight = 0; this.parent = null; this.value = ""; this.type = ""; this.title = ""; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join("\n"); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  replaceChildren(...cs) { this.children = []; this._text = ""; for (const c of cs) this.appendChild(c); }
  all(tag, out) { for (const c of this.children) { if (c.tag === tag) out.push(c); c.all(tag, out); } return out; }
  querySelectorAll(sel) { return this.all(sel, []); }
  querySelector(sel) { return this.all(sel, [])[0] || null; }
  addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  focus() {}
  click() { if (this.disabled) return; for (const f of this.listeners.click || []) f({ preventDefault() {} }); }
  getContext() { const self = this; return new Proxy({}, { get: (_t, name) => (...a) => { self.calls.push([String(name), a]); return ({ addColorStop(_o, c) { drawn.push(String(c)); } }); }, set: (_t, k, v) => { if (k === "fillStyle" || k === "strokeStyle") drawn.push(String(v)); return true; } }); }
}
const drawn = [];  // alle beim Zeichnen benutzten Farben (Pruefung der Kern-Darstellung)
const byId = new Map();
for (const m of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g)) byId.set(m[2], new El(m[1]));
const body = new El("body");
body.dataset.mode = "orb";
const docListeners = {};
const document = {
  getElementById: (id) => byId.get(id) || null,
  createElement: (t) => new El(t),
  addEventListener: (n, f) => { (docListeners[n] = docListeners[n] || []).push(f); },
  get body() { return body; },
};
const sources = [];
class EventSource { constructor(u) { this.url = u; sources.push(this); } close() {} }
EventSource.CLOSED = 2;
const sent = [];
const fetched = [];
const fetchedUrls = [];
let viewsData = {};
let rafCb = null;
const reduced = process.env.JARVIS_HARNESS_REDUCED !== "0";
let ackReply = null;
const ctx = {
  document, EventSource, console, setTimeout: () => 0, setInterval: () => 0, clearInterval() {}, requestAnimationFrame(cb) { rafCb = cb; return 1; }, Date, Math, JSON,
  URLSearchParams, Promise, Map, Set, Number, String, Array, Object,
  location: { search: "?t=TESTTOKEN" },
  window: { matchMedia: () => ({ matches: reduced }) },
  fetch: async (u, opts) => {
    if (String(u).startsWith("view/")) { const which = String(u).slice(5).split("?")[0]; fetched.push(which); fetchedUrls.push(String(u));
      if (!opts || opts.method !== "GET" || (opts && opts.body !== undefined)) throw new Error("views must be GET without body");
      return { ok: true, status: 200, json: async () => viewsData[which] }; }
    if (String(u).startsWith("core_states.json")) { if (process.env.JARVIS_HARNESS_NO_TABLE) throw new Error("offline"); return { ok: true, json: async () => JSON.parse(fs.readFileSync(webDir + "/core_states.json", "utf8")) }; }
     const cmd = JSON.parse(opts.body); sent.push(cmd); const d = ackReply ? ackReply(cmd) : { id: cmd.id, ok: true, code: "ok", message: "" };
    return { json: async () => ({ v: "1.0", seq: 1, ts: "2026-11-02T10:00:00Z", type: "ack", data: d }) }; },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(webDir + "/app.js", "utf8"), ctx);

(async () => {
  const snapshots = {};
  for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r));  // Zustandstabelle laden lassen
  for (const [i, step] of scenario.entries()) {
    if (step.views) viewsData = step.views;
    if (step.set) byId.get(step.set.id).value = step.set.value;
    if (step.ev) sources[0].onmessage({ data: JSON.stringify(step.ev) });
    if (step.ack) { const a = step.ack; ackReply = (cmd) => ({ id: cmd.id, ok: a.ok, code: a.code, message: a.message }); }
    if (step.click) { const e = byId.get(step.click.id); const btns = e.querySelectorAll("button"); btns.find((b) => b.textContent.trim() === step.click.text).click(); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); }
    if (step.clickId) { byId.get(step.clickId).click(); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); }
    if (step.wait) for (let k = 0; k < 4; k++) await new Promise((r) => setImmediate(r));
    if (step.key) { for (const f of docListeners.keydown || []) f({ key: step.key, preventDefault() {} }); await new Promise((r) => setImmediate(r)); }
    if (step.frames) for (const t of step.frames) { if (rafCb) { const cb = rafCb; rafCb = null; cb(t); } }
    if (step.effects) { const sel = byId.get("effects"); sel.value = step.effects; for (const f of sel.listeners.change || []) f({}); }
    if (step.disconnect) sources[0].onerror({});
    if (step.toggle) byId.get("mode-toggle").click();
    if (step.snap) snapshots[step.snap] = { mode: body.dataset.mode, state: body.dataset.state, effects: body.dataset.effects, drawn: drawn.splice(0), readyState: sources[0].readyState, sent: sent.slice(), fetched: fetched.slice(), fetchedUrls: fetchedUrls.slice(), text: Object.fromEntries([...byId].map(([k, v]) => [k, v.textContent])),
      props: Object.fromEntries([...byId].map(([k, v]) => [k, { value: v.value, disabled: v.disabled, hidden: v.hidden, dataset: { ...v.dataset }, calls: v.calls.map((c) => c[0]) }])),
      items: Object.fromEntries([...byId].map(([k, v]) => [k, v.children.map((c) => ({ text: c.textContent, className: c.className, dataset: { ...c.dataset } }))])),
      buttons: Object.fromEntries([...byId].map(([k, v]) => [k, v.querySelectorAll("button").map((b) => b.textContent.trim())])) };
  }
  process.stdout.write(JSON.stringify(snapshots));
})();
