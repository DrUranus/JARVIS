import { buildGeometry, STATES, PRESETS, STRIDE } from "./core-geometry.js";
import { webGPU, webGL, canvas2D } from "./core-backends.js";

let sharedGeometry;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const modes = new Set(["auto", "performance", "high"]);

/** A self-contained renderer. Call dispose() before discarding the owning view. */
export function createCore(input, { onMetrics = () => {} } = {}) {
  const geometry = (sharedGeometry ??= buildGeometry());
  const params = new Float32Array(16);
  const lastTint = new Float32Array(4);
  let transitionStart = null;
  let canvas = input,
    renderer,
    disposed = false,
    generation = 0,
    handle = 0;
  let state = 0,
    quality = "auto",
    automaticScale = 1,
    detailFraction = 1,
    intersecting = true;
  let motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  let targetX = 0,
    targetY = 0,
    yaw = 0,
    pitch = 0,
    velocityX = 0,
    velocityY = 0,
    hover = 0,
    hoverTarget = 0,
    clock = 0,
    phase = 0;
  let previous = 0,
    sampleStart = 0,
    frames = 0,
    fps = 0,
    dirty = true;
  let cssWidth = 0,
    cssHeight = 0;
  const reducedMotionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  const metrics = () =>
    onMetrics({
      backend: renderer?.name ?? "Initialisierung",
      fps,
      quality,
      particles: geometry.length / STRIDE,
      width: canvas.width,
      height: canvas.height,
      scale: params[3] || 1,
      bufferBytes: geometry.byteLength,
      drawnParticles:
        renderer?.name === "Canvas 2D"
          ? 0
          : Math.ceil((geometry.length / STRIDE) * params[15]),
    });
  const resize = new ResizeObserver((entries) => {
    const box = entries[entries.length - 1].contentRect;
    cssWidth = box.width;
    cssHeight = box.height;
    dirty = true;
    requestFrame();
  });
  const intersection = new IntersectionObserver((entries) => {
    intersecting = entries[entries.length - 1].isIntersecting;
    resetTiming();
    dirty = true;
    requestFrame();
  });
  function resetTiming() {
    previous = 0;
    sampleStart = 0;
    frames = 0;
    if (handle) cancelAnimationFrame(handle);
    handle = 0;
  }
  function requestFrame() {
    if (!handle && !disposed && renderer && !document.hidden && intersecting)
      handle = requestAnimationFrame(frame);
  }
  function visibility() {
    resetTiming();
    dirty = true;
    requestFrame();
  }
  function pointer(event) {
    if (!motion) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    hoverTarget = 1;
    targetX =
      clamp(((event.clientX - rect.left) / rect.width) * 2 - 1, -1, 1) * 0.34;
    targetY =
      clamp(((event.clientY - rect.top) / rect.height) * 2 - 1, -1, 1) * 0.22;
    requestFrame();
  }
  function leave() {
    hoverTarget = 0;
    targetX = 0;
    targetY = 0;
    requestFrame();
  }
  function lost(event) {
    event.preventDefault();
    if (!disposed) fallback("canvas");
  }
  function watch(node, enable) {
    const method = enable ? "addEventListener" : "removeEventListener";
    node[method]("pointermove", pointer);
    node[method]("pointerleave", leave);
    node[method]("webglcontextlost", lost);
    if (enable) {
      resize.observe(node);
      intersection.observe(node);
    } else {
      resize.unobserve(node);
      intersection.unobserve(node);
    }
  }
  function freshCanvas(next = canvas.cloneNode(false)) {
    // A canvas with a lost/committed context cannot acquire a different context type.
    watch(canvas, false);
    canvas.replaceWith(next);
    canvas = next;
    watch(canvas, true);
  }
  function attach(result) {
    renderer = result;
    resetTiming();
    fps = 0;
    dirty = true;
    metrics();
    requestFrame();
  }
  function fallback(initial = "gl", keepPendingGPU = false) {
    if (disposed) return;
    if (!keepPendingGPU) generation++;
    const hadContext = Boolean(renderer);
    renderer?.destroy();
    renderer = null;
    if (hadContext) freshCanvas();
    for (const build of initial === "canvas" ? [canvas2D] : [webGL, canvas2D]) {
      try {
        attach(build(canvas, geometry));
        return;
      } catch {
        // A rejected WebGL request leaves the original canvas available for 2D.
        // Retry on a fresh canvas only when a partially initialized context owns it.
        if (build === canvas2D && !disposed) {
          freshCanvas();
          try {
            attach(canvas2D(canvas, geometry));
            return;
          } catch {
            /* graphics disabled */
          }
        }
      }
    }
    onMetrics({ backend: "Nicht verfügbar", fps: 0, quality, particles: 0 });
  }
  function frame(now) {
    handle = 0;
    if (disposed || !renderer || document.hidden || !intersecting) return;
    const preset = PRESETS[state];
    const animate = motion && preset.speed > 0;
    const limit =
      cssWidth < 180
        ? 24
        : quality === "performance" || renderer.name === "Canvas 2D"
          ? 30
          : 60;
    if (!dirty && previous && now - previous < 1000 / limit - 1.0) {
      requestFrame();
      return;
    }
    const dt = previous ? clamp((now - previous) / 1000, 0, 0.16) : 0;
    previous = now;
    if (!cssWidth || !cssHeight) {
      const rect = canvas.getBoundingClientRect();
      cssWidth = rect.width;
      cssHeight = rect.height;
      if (!cssWidth || !cssHeight) return;
    }
    const base =
      quality === "performance"
        ? 0.76
        : quality === "auto"
          ? automaticScale
          : 1;
    const ratio =
      Math.min(devicePixelRatio || 1, quality === "performance" ? 1 : 1.7) *
      base;
    const bounded = Math.min(
      ratio,
      Math.sqrt(1300000 / (cssWidth * cssHeight)),
    );
    const w = Math.max(1, Math.round(cssWidth * bounded)),
      h = Math.max(1, Math.round(cssHeight * bounded));
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    if (animate) {
      clock += dt * preset.speed;
      phase += dt;
    }
    // Closed-form critical damping stays stable across long frames.
    if (animate) {
      const k = 10,
        decay = Math.exp(-k * dt);
      const dx = yaw - targetX,
        dy = pitch - targetY;
      const ax = velocityX + k * dx,
        ay = velocityY + k * dy;
      yaw = targetX + (dx + ax * dt) * decay;
      pitch = targetY + (dy + ay * dt) * decay;
      velocityX = (velocityX - k * ax * dt) * decay;
      velocityY = (velocityY - k * ay * dt) * decay;
      hover += (hoverTarget - hover) * (1 - Math.exp(-dt * 6));
    }
    const fraction = !animate
      ? 1
      : quality === "performance"
        ? 0.25
        : quality === "auto"
          ? detailFraction
          : 1;
    params.set([
      w,
      h,
      clock,
      bounded,
      yaw,
      pitch,
      animate ? 1 + preset.pulse * Math.sin(phase * preset.frequency) : 1,
      preset.mix,
      ...preset.tint,
      hover,
      Math.min(2.6, 1 / Math.sqrt(fraction)),
      state,
      animate ? phase : 0,
      fraction,
    ]);
    if (transitionStart !== null && animate && renderer.name !== "Canvas 2D") {
      const t = Math.min(1, (now - transitionStart) / 280);
      const eased = t * t * (3 - 2 * t);
      for (let i = 0; i < 4; i++)
        params[7 + i] = lastTint[i] + (params[7 + i] - lastTint[i]) * eased;
      if (t === 1) transitionStart = null;
    }
    renderer.draw(params);
    dirty = false;
    if (!sampleStart) {
      sampleStart = now;
      frames = 0;
    } else frames++;
    if (now - sampleStart >= 1350) {
      fps = Math.round((frames * 1000) / (now - sampleStart));
      if (quality === "auto" && animate) {
        if (fps < 20) detailFraction = Math.max(0.125, detailFraction * 0.5);
        else if (fps > 50) detailFraction = Math.min(1, detailFraction * 2);
        if (fps < Math.min(27, limit - 5))
          automaticScale = Math.max(0.62, automaticScale - 0.09);
        if (fps > 52) automaticScale = Math.min(1, automaticScale + 0.035);
      }
      metrics();
      sampleStart = now;
      frames = 0;
    }
    if (animate) requestFrame();
  }
  function motionChange(event) {
    if (motionOverride === null) applyMotion(!event.matches);
  }
  let motionOverride = null;
  function applyMotion(value) {
    motion = Boolean(value);
    if (!motion) {
      yaw = 0;
      pitch = 0;
      velocityX = velocityY = hover = hoverTarget = 0;
      targetX = 0;
      targetY = 0;
      fps = 0;
    }
    resetTiming();
    dirty = true;
    metrics();
    requestFrame();
  }
  const api = {
    setState(value) {
      const normalized = String(value)
        .replace(/[-_\s]/g, "")
        .toLowerCase();
      const index = STATES.findIndex(
        (n) => n.replace(/\s/g, "").toLowerCase() === normalized,
      );
      if (index < 0 || index === state) return;
      lastTint.set(params.subarray(7, 11));
      transitionStart =
        motion && renderer && STATES[index] !== "Emergency Stop"
          ? performance.now()
          : null;
      state = index;
      fps = 0;
      resetTiming();
      dirty = true;
      metrics();
      requestFrame();
    },
    setQuality(value) {
      if (!modes.has(value) || quality === value) return;
      quality = value;
      automaticScale = 1;
      detailFraction = 1;
      dirty = true;
      metrics();
      requestFrame();
    },
    setMotion(value) {
      motionOverride = value == null ? null : Boolean(value);
      applyMotion(motionOverride ?? !reducedMotionQuery.matches);
    },
    get canvas() {
      return canvas;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      generation++;
      clearTimeout(timeout);
      resetTiming();
      document.removeEventListener("visibilitychange", visibility);
      reducedMotionQuery.removeEventListener("change", motionChange);
      watch(canvas, false);
      resize.disconnect();
      intersection.disconnect();
      renderer?.destroy();
      renderer = null;
      if (canvas !== input && canvas.isConnected) canvas.replaceWith(input);
    },
  };
  watch(canvas, true);
  document.addEventListener("visibilitychange", visibility);
  reducedMotionQuery.addEventListener("change", motionChange);
  // Compile on a separate canvas so a slow adapter never blocks the first image.
  const candidate = canvas.cloneNode(false);
  const attempt = ++generation;
  const valid = () => !disposed && generation === attempt;
  const timeout = setTimeout(() => {
    if (valid() && !renderer) fallback("gl", true);
  }, 450);
  webGPU(
    candidate,
    geometry,
    () => {
      if (!disposed && canvas === candidate) fallback();
    },
    valid,
  )
    .then((result) => {
      clearTimeout(timeout);
      if (!valid()) {
        result.destroy();
        return;
      }
      renderer?.destroy();
      freshCanvas(candidate);
      attach(result);
    })
    .catch(() => {
      clearTimeout(timeout);
      if (valid() && !renderer) fallback();
    });
  return api;
}
