const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  orbit:
    '<circle cx="12" cy="12" r="6"/><ellipse cx="12" cy="12" rx="11" ry="3.5" transform="rotate(-36 12 12)"/>',
  pulse: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
  terminal: '<path d="m5 7 5 5-5 5m8 0h6"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"/>',
  folder: '<path d="M3 7V5a1 1 0 0 1 1-1h6l3 3h7a1 1 0 0 1 1 1v11H3z"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8zm-9 10 9 5 9-5m-18 5 9 5 9-5"/>',
  agents:
    '<rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 7V3m-5 9h2m6 0h2m-8 4h6"/>',
  spark:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  brief:
    '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V4h8v3M3 12q9 5 18 0"/>',
  chart: '<path d="M3 3v18h18M6 15l4-5 4 3 6-8"/>',
  flow: '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><path d="M6 9v7q0 2 3 2h6"/>',
  sliders:
    '<path d="M4 6h5m5 0h6M4 12h10m5 0h1M4 18h2m5 0h9"/><circle cx="11.5" cy="6" r="2.5"/><circle cx="16.5" cy="12" r="2.5"/><circle cx="8.5" cy="18" r="2.5"/>',
  mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
  send: '<path d="m3 11 18-8-6 18-4-7zm8 3 10-11"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  wave: '<path d="M3 10v4m4-9v14m5-17v20m5-15v10m4-7v4"/>',
  keyboard:
    '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M5 9h1m3 0h1m3 0h1m3 0h1M5 12h1m3 0h1m3 0h1m3 0h1m-10 3h8"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  play: '<path d="m8 4 12 8-12 8z"/>',
  file: '<path d="M5 2h9l5 5v15H5zM14 2v6h5"/>',
  save: '<path d="M3 3h15l3 3v15H3zM7 3v6h9V3M7 21v-8h10v8"/>',
  expand: '<path d="M3 9V3h6m6 0h6v6m0 6v6h-6m-6 0H3v-6"/>',
  check: '<path d="m4 12 5 5L20 6"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  plus: '<path d="M12 4v16M4 12h16"/>',
  chip: '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M8 2v3m8-3v3M2 8h3m-3 8h3M8 19v3m8-3v3m3-14h3m-3 8h3"/>',
  trash: '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
  link: '<path d="m10 8 3-3a4 4 0 0 1 6 6l-3 3m-2 2-3 3a4 4 0 0 1-6-6l3-3m1 6 6-6"/>',
  volume:
    '<path d="M3 9h4l5-5v16l-5-5H3zm13 0a4 4 0 0 1 0 6m3-9a8 8 0 0 1 0 12"/>',
  mute: '<path d="M3 9h4l5-5v16l-5-5H3zm13 0 5 6m-5 0 5-6"/>',
  chev: '<path d="m9 5 7 7-7 7"/>',
};
export function icon(name, size = 18) {
  return (
    '<svg aria-hidden="true" viewBox="0 0 24 24" width="' +
    size +
    '" height="' +
    size +
    '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    (paths[name] || paths.spark) +
    "</svg>"
  );
}
