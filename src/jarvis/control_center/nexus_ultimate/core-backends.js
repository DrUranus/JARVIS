import { STRIDE } from "./core-geometry.js";
import { glVertex, glFragment, wgsl } from "./core-shaders.js";

export function webGL(canvas, geometry) {
  const gl = canvas.getContext("webgl2", {
    alpha: true,
    antialias: false,
    premultipliedAlpha: true,
    depth: false,
    stencil: false,
    powerPreference: "low-power",
  });
  if (!gl) throw new Error("WebGL 2 unavailable");
  const program = gl.createProgram();
  const shaders = [];
  let buffer;
  const destroy = () => {
    gl.deleteBuffer(buffer ?? null);
    for (const shader of shaders) gl.deleteShader(shader);
    gl.deleteProgram(program);
  };
  try {
    for (const [type, source] of [
      [gl.VERTEX_SHADER, glVertex],
      [gl.FRAGMENT_SHADER, glFragment],
    ]) {
      const shader = gl.createShader(type);
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS))
        throw Error(gl.getShaderInfoLog(shader));
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS))
      throw Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, geometry, gl.STATIC_DRAW);
    for (let i = 0; i < 3; i++) {
      gl.enableVertexAttribArray(i);
      gl.vertexAttribPointer(i, 3, gl.FLOAT, false, STRIDE * 4, i * 12);
    }
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.clearColor(0, 0, 0, 0);
    const maxSprite = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE)[1];
    const spriteUniform = gl.getUniformLocation(program, "sprites");
    let lastSprites;
    const locations = ["scene", "pose", "tint", "detail"].map((key) =>
      gl.getUniformLocation(program, key),
    );
    return {
      name: "WebGL 2",
      draw(params) {
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clear(gl.COLOR_BUFFER_BIT);
        for (let i = 0; i < locations.length; i++)
          gl.uniform4fv(locations[i], params, i * 4, 4);
        // Point sprites shade each particle vertex once. Large halos use quads
        // on drivers whose maximum point size cannot contain the projection.
        const sprites =
          Math.min(canvas.width, canvas.height) * 1.05 <= maxSprite;
        if (sprites !== lastSprites) {
          for (let i = 0; i < 3; i++)
            gl.vertexAttribDivisor(i, sprites ? 0 : 1);
          gl.uniform1i(spriteUniform, sprites ? 1 : 0);
          lastSprites = sprites;
        }
        const count = Math.ceil((geometry.length / STRIDE) * params[15]);
        if (sprites) gl.drawArrays(gl.POINTS, 0, count);
        else gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
      },
      destroy,
    };
  } catch (err) {
    destroy();
    throw err;
  }
}

export async function webGPU(canvas, geometry, onLoss, isCurrent) {
  if (!navigator.gpu) throw Error("WebGPU unavailable");
  // Some platforms expose the API with no usable hardware adapter.
  const adapter = await navigator.gpu.requestAdapter({
    powerPreference: "low-power",
  });
  if (!adapter || !isCurrent()) throw Error("WebGPU adapter unavailable");
  const device = await adapter.requestDevice();
  let context, vertexBuffer, uniformBuffer;
  const destroy = () => {
    context?.unconfigure();
    vertexBuffer?.destroy();
    uniformBuffer?.destroy();
    device.destroy();
  };
  try {
    const format = navigator.gpu.getPreferredCanvasFormat();
    const module = device.createShaderModule({ code: wgsl });
    const blend = { operation: "add", srcFactor: "one", dstFactor: "one" };
    const pipeline = await device.createRenderPipelineAsync({
      layout: "auto",
      vertex: {
        module,
        entryPoint: "vert",
        buffers: [
          {
            arrayStride: STRIDE * 4,
            stepMode: "instance",
            attributes: [0, 1, 2].map((i) => ({
              shaderLocation: i,
              offset: i * 12,
              format: "float32x3",
            })),
          },
        ],
      },
      fragment: {
        module,
        entryPoint: "frag",
        targets: [{ format, blend: { color: blend, alpha: blend } }],
      },
      primitive: { topology: "triangle-strip" },
    });
    if (!isCurrent()) throw Error("WebGPU request superseded");
    vertexBuffer = device.createBuffer({
      size: geometry.byteLength,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(vertexBuffer, 0, geometry);
    uniformBuffer = device.createBuffer({
      size: 64,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });
    const bindings = device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [{ binding: 0, resource: { buffer: uniformBuffer } }],
    });
    context = canvas.getContext("webgpu");
    if (!context) throw Error("WebGPU context unavailable");
    context.configure({ device, format, alphaMode: "premultiplied" });
    device.lost.then((info) => {
      if (info.reason !== "destroyed") onLoss();
    });
    return {
      name: "WebGPU",
      destroy,
      draw(params) {
        device.queue.writeBuffer(uniformBuffer, 0, params);
        const encoder = device.createCommandEncoder();
        const pass = encoder.beginRenderPass({
          colorAttachments: [
            {
              view: context.getCurrentTexture().createView(),
              clearValue: { r: 0, g: 0, b: 0, a: 0 },
              loadOp: "clear",
              storeOp: "store",
            },
          ],
        });
        pass.setPipeline(pipeline);
        pass.setBindGroup(0, bindings);
        pass.setVertexBuffer(0, vertexBuffer);
        pass.draw(4, Math.ceil((geometry.length / STRIDE) * params[15]));
        pass.end();
        device.queue.submit([encoder.finish()]);
      },
    };
  } catch (err) {
    destroy();
    throw err;
  }
}

function rasterize(geometry, width, height, params) {
  // Cache a CPU projection for browsers with all hardware contexts disabled.
  const poster = document.createElement("canvas");
  poster.width = width;
  poster.height = height;
  const ctx = poster.getContext("2d");
  const frame = ctx.createImageData(width, height);
  const pixels = frame.data;
  const unit = Math.min(width, height) * 0.318;
  for (let i = 0; i < geometry.length; i += STRIDE) {
    const z = geometry[i + 2];
    const k = (unit * 4.25) / (4.25 - 0.26 * z);
    const px = width / 2 + geometry[i] * k,
      py = height / 2 - geometry[i + 1] * k;
    const size = Math.max(0.67, geometry[i + 6] * k);
    const type = geometry[i + 7];
    const depth =
      geometry[i + 8] === -1
        ? 1
        : 0.19 + 0.81 * Math.max(0, Math.min(1, (z + 0.68) / 1.52));
    const rgb = [geometry[i + 3], geometry[i + 4], geometry[i + 5]];
    const energy = Math.max(...rgb);
    const [red, green, blue] = rgb.map(
      (n, j) =>
        (n * (1 - params[7]) + params[j + 8] * energy * params[7]) *
        255 *
        depth,
    );
    const x0 = Math.max(0, Math.floor(px - size)),
      x1 = Math.min(width - 1, Math.ceil(px + size));
    const y0 = Math.max(0, Math.floor(py - size)),
      y1 = Math.min(height - 1, Math.ceil(py + size));
    for (let y = y0; y <= y1; y++)
      for (let x = x0; x <= x1; x++) {
        const u = (x + 0.5 - px) / size,
          v = (y + 0.5 - py) / size;
        const d = u * u + v * v;
        if (d > 1) continue;
        const j = 4 * (width * y + x);
        let e;
        if (type === 2) {
          const tz = Math.sqrt(1 - d);
          const light =
            0.1 +
            0.08 * (1 + Math.sin(-v * 7 + u * 5)) +
            0.66 * Math.exp(-tz * 8);
          pixels[j] += red * light * 0.44;
          pixels[j + 1] += green * light * 0.17;
          pixels[j + 2] += blue * light * 0.87;
        } else {
          if (type === 1)
            e =
              Math.exp(-34 * d) +
              0.5 *
                (Math.exp(-36 * Math.abs(u) - 3.8 * Math.abs(v)) +
                  Math.exp(-42 * Math.abs(v) - 3 * Math.abs(u)));
          else
            e =
              Math.exp(-d * (type === 3 ? 5.8 : 2.8)) *
              (1 - Math.max(0, (d - 0.66) / 0.34));
          pixels[j] += red * e;
          pixels[j + 1] += green * e;
          pixels[j + 2] += blue * e;
        }
      }
  }
  for (let i = 0; i < pixels.length; i += 4) {
    const a = Math.max(pixels[i], pixels[i + 1], pixels[i + 2]);
    if (!a) continue;
    pixels[i + 3] = a;
    for (let c = 0; c < 3; c++) pixels[i + c] = (pixels[i + c] * 255) / a;
  }
  ctx.putImageData(frame, 0, 0);
  return poster;
}

export function canvas2D(canvas, geometry) {
  const ctx = canvas.getContext("2d", { alpha: true });
  if (!ctx) throw Error("Canvas unavailable");
  let poster,
    key = "";
  return {
    name: "Canvas 2D",
    draw(params) {
      const stateKey = [
        canvas.width,
        canvas.height,
        params[7],
        params[8],
        params[9],
        params[10],
      ].join("/");
      if (stateKey !== key) {
        const scale = Math.min(1, 650 / Math.min(canvas.width, canvas.height));
        poster = rasterize(
          geometry,
          Math.max(1, Math.round(canvas.width * scale)),
          Math.max(1, Math.round(canvas.height * scale)),
          params,
        );
        key = stateKey;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.save();
      const k = Math.min(canvas.width, canvas.height) * 0.035;
      ctx.translate(
        canvas.width / 2 + params[4] * k,
        canvas.height / 2 + params[5] * k,
      );
      ctx.scale(params[6], params[6]);
      ctx.rotate(Math.sin(params[2] * 0.13) * 0.024 + params[4] * 0.03);
      ctx.drawImage(
        poster,
        -canvas.width / 2,
        -canvas.height / 2,
        canvas.width,
        canvas.height,
      );
      ctx.restore();
    },
    destroy() {
      poster = null;
    },
  };
}
