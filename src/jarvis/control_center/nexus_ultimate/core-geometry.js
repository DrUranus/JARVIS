// Each instance contains a 3D position, luminous RGB, radius, material, and orbital group.
export const STRIDE = 9;
export const PRESETS = [
  {
    name: "Idle",
    speed: 0.12,
    pulse: 0.004,
    frequency: 1,
    mix: 0,
    tint: [0, 0, 0],
  },
  {
    name: "Listening",
    speed: 0.29,
    pulse: 0.012,
    frequency: 1.6,
    mix: 0.6,
    tint: [0.15, 0.95, 1],
  },
  {
    name: "Thinking",
    speed: 0.7,
    pulse: 0.008,
    frequency: 2.3,
    mix: 0.47,
    tint: [0.87, 0.22, 1],
  },
  {
    name: "Speaking",
    speed: 0.34,
    pulse: 0.025,
    frequency: 4.1,
    mix: 0.49,
    tint: [0.34, 0.7, 1],
  },
  {
    name: "Working",
    speed: 0.48,
    pulse: 0.012,
    frequency: 2.9,
    mix: 0.59,
    tint: [0.6, 0.51, 1],
  },
  {
    name: "Awaiting Approval",
    speed: 0.045,
    pulse: 0.006,
    frequency: 0.72,
    mix: 0.78,
    tint: [0.72, 0.59, 1],
  },
  {
    name: "Error",
    speed: 0.16,
    pulse: 0.017,
    frequency: 2.1,
    mix: 0.91,
    tint: [1, 0.15, 0.34],
  },
  {
    name: "Emergency Stop",
    speed: 0,
    pulse: 0,
    frequency: 0,
    mix: 0.96,
    tint: [1, 0.08, 0.12],
  },
];
export const STATES = PRESETS.map((preset) => preset.name);

const TAU = 2 * Math.PI;
function randomGenerator() {
  let seed = 178432;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

// A continuous deformation of the sphere keeps neighbouring filaments bundled.
function streamline(latitude, longitude, shell) {
  const a =
    latitude +
    0.34 *
      Math.sin(longitude * 2 + latitude * 3.6 + shell) *
      Math.cos(latitude) +
    0.08 * Math.sin(5 * longitude - 4 * latitude) * Math.cos(latitude);
  const b =
    longitude +
    0.51 * Math.sin(2.8 * latitude + 1.3 * Math.sin(longitude)) +
    0.3 * Math.sin(latitude * 3 + longitude * 2) +
    shell * 0.5;
  const r =
    0.928 + 0.027 * Math.sin(3 * b - 5 * a) + 0.018 * Math.cos(7 * b + a);
  let x = Math.cos(a) * Math.cos(b) * r;
  const y = Math.sin(a) * r;
  let z = Math.cos(a) * Math.sin(b) * r;
  const twist = 0.85 * Math.sin(y * 2.7 + x * 1.8) + 0.95 * y;
  const cx = x * Math.cos(twist) + z * Math.sin(twist);
  z = z * Math.cos(twist) - x * Math.sin(twist);
  x = cx;
  const bend = 0.42 + 0.55 * Math.sin(z * 3.3 - y);
  return [
    Math.cos(bend) * x - Math.sin(bend) * y,
    Math.sin(bend) * x + Math.cos(bend) * y,
    z,
  ];
}

export function buildGeometry() {
  const data = [];
  const random = randomGenerator();
  const add = (position, color, radius, material = 0, group = 0) =>
    data.push(...position, ...color, radius, material, group);
  // Broad analytic fields give the filament shells a softly scattering interior.
  add([0, 0, 0], [0.25, 0.11, 0.8], 1.47, 3, -1);
  add([0, 0, 0], [1, 1, 1], 1, 2, -1);
  for (let shell = 0; shell < 2; shell++) {
    const lanes = shell === 0 ? 73 : 19;
    for (let i = 0; i < lanes; i++) {
      const latitude = ((i + 0.45) / lanes - 0.5) * Math.PI;
      const count = Math.floor(365 * Math.cos(latitude) + 145);
      const phase = random() * TAU;
      const brightLane = i % 13 === 0 || i % 13 === 1;
      for (let j = 0; j < count; j++) {
        const longitude = (TAU * (j + random() * 0.15)) / count;
        let [x, y, z] = streamline(latitude, longitude, shell);
        const scale = shell ? 0.72 : 1;
        x *= scale;
        y *= scale;
        z *= scale;
        const turbulence =
          0.5 +
          0.5 *
            Math.sin(longitude * 3 + latitude * 7 + Math.sin(longitude * 6));
        const light =
          (brightLane ? 1.5 : 0.78) *
          (0.38 + 0.7 * turbulence) *
          (0.65 + random() * 0.65) *
          (shell ? 0.95 : 0.92);
        const cyan = Math.max(
          0,
          Math.min(
            1,
            (-0.75 * x - y * 0.4 + 0.42 * Math.sin(z * 6 + y * 4)) * 1.1,
          ),
        );
        const pink = Math.max(
          0,
          x * 0.65 + y * 0.38 + 0.2 * Math.sin(z * 4 + x * 7),
        );
        const col = [
          (0.32 + pink * 0.78) * (1 - cyan * 0.79) * light,
          (0.2 + cyan * 0.73 + pink * 0.05) * light,
          (0.93 + 0.06 * Math.cos(phase)) * light,
        ];
        add(
          [x, y, z],
          col,
          (brightLane ? 0.01 : 0.0078) * (0.83 + random() * 0.34),
          0,
          shell ? -2 : 0,
        );
        if (brightLane && j % 4 === 0)
          add(
            [x, y, z],
            col.map((v) => v * 0.07),
            0.034,
            3,
            shell ? -2 : 0,
          );
        if (j % 61 === 0 && random() > 0.48)
          add(
            [x, y, z],
            col.map((v) => v * 1.36),
            0.024 + random() * 0.025,
            1,
            shell ? -2 : 0,
          );
      }
    }
  }

  // Ion streams curl through the volume. Each ribbon is a bundle of neighbouring
  // trajectories with a luminous crest, a soft scattering halo, and tapered ends.
  for (let stream = 0; stream < 3; stream++) {
    for (let lane = -4; lane <= 4; lane++) {
      for (let step = 0; step <= 285; step++) {
        const t = step / 285;
        const envelope = Math.sin(Math.PI * t);
        const x = (t * 2 - 1) * (0.83 - 0.04 * stream);
        const bend = Math.sin(t * TAU * (1.0 + 0.13 * stream) + stream * 1.67);
        const y =
          0.2 * stream -
          0.2 +
          0.4 * x +
          envelope *
            (0.13 * bend +
              0.08 * Math.sin(2 * TAU * t + stream * 1.2) +
              lane * 0.008 * (0.75 + 0.65 * Math.cos(TAU * t + stream)));
        const z =
          0.2 +
          0.4 * Math.sin(Math.PI * t + stream * 1.35) +
          0.14 * Math.sin(t * TAU + stream * 1.8) +
          lane * 0.01;
        const strength =
          0.64 *
          envelope ** 0.8 *
          Math.exp(-Math.abs(lane) * 0.29) *
          (0.65 + 0.35 * Math.sin(t * 11 + stream) ** 2);
        const blue = 0.5 - 0.5 * Math.tanh(4 * (x + 0.25) - 0.25 * stream);
        const color = [
          (0.86 - 0.7 * blue) * strength,
          (0.33 + 0.48 * blue) * strength,
          strength,
        ];
        add([x, y, z], color, lane === 0 ? 0.011 : 0.0075, 0, -4);
        if (lane === 0 && step % 4 === 0)
          add(
            [x, y, z],
            color.map((v) => v * 0.14),
            0.036,
            3,
            -4,
          );
      }
    }
  }

  // Sparse tracer dust occupies the space between the continuous shells.
  for (let i = 0; i < 1250; i++) {
    const a = random() * TAU;
    const h = random() * 2 - 1;
    const r = i < 980 ? 0.97 + random() * 0.045 : 1.07 + random() * 0.32;
    const side = r * Math.sqrt(1 - h * h);
    const l = 0.27 + random() * 0.85;
    add(
      [side * Math.cos(a), r * h, side * Math.sin(a)],
      [l * (0.34 + random() * 0.35), l * (0.37 + random() * 0.36), l],
      i % 46 === 0 ? 0.032 : 0.004 + random() * 0.006,
      i % 46 === 0 ? 1 : 0,
      -3,
    );
  }

  // The orbital planes have their own tilt, phase, and precession rates.
  [
    [1.47, 0.27, -0.26],
    [1.36, 0.3, -0.26],
    [1.29, 0.52, 0.47],
    [1.23, 0.4, -0.84],
  ].forEach(([radius, tilt, angle], index) => {
    const count = 1160;
    const group = index + 1;
    for (let j = 0; j < count; j++) {
      if (index === 1 && j % 24 > 12) continue;
      const theta = (j / count) * TAU;
      const px = Math.cos(theta) * radius;
      const py = Math.sin(theta) * tilt * radius;
      const pz = Math.sin(theta) * Math.sqrt(1 - tilt * tilt) * radius;
      const pos = [
        px * Math.cos(angle) - py * Math.sin(angle),
        px * Math.sin(angle) + py * Math.cos(angle),
        pz,
      ];
      const hot = (Math.sin(theta * 2 - index) + 1) * 0.5;
      const strength = index === 1 ? 0.38 : 0.55;
      const col = [
        (0.31 + hot * 0.4) * strength,
        (0.38 + 0.23 * (1 - hot)) * strength,
        strength,
      ];
      add(pos, col, index === 1 ? 0.0052 : 0.0067, 0, group);
      if ((j + index * 97) % 419 === 61) {
        add(pos, [0.78, 0.77, 1], 0.054, 1, group);
        add(pos, [0.21, 0.17, 0.68], 0.077, 3, group);
      }
    }
  });
  add([0, 0, 0.11], [0.42, 0.31, 1], 0.34, 3, -1);
  add([0, 0, 0.12], [0.68, 0.62, 1], 0.117, 3, -1);
  add([0, 0, 0.13], [0.93, 0.92, 1], 0.085, 1, -1);
  // Order samples in interleaved strata. Any prefix contains all principal
  // light sources plus points from each shell, ribbon and orbital path.
  const packed = new Float32Array(data.length);
  let dest = 0;
  function copy(index) {
    for (let column = 0; column < STRIDE; column++)
      packed[dest++] = data[index + column];
  }
  for (let index = 0; index < data.length; index += STRIDE)
    if (data[index + 8] === -1) copy(index);
  for (const band of [0, 4, 2, 6, 1, 5, 3, 7]) {
    for (let index = band * STRIDE; index < data.length; index += 8 * STRIDE)
      if (data[index + 8] !== -1) copy(index);
  }
  return packed;
}
