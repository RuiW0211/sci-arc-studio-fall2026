// Site sections (Rui, 2026-11-05): a north-up top view and four sections of Parcel Y-1, drawn live from the 2023 LiDAR
// (data/lidar_points.laz, the viewer's file, so the browser reuses it). The cuts, their labels and the top view's
// hillshade come from data/sections.json + data/sections_top.png (site-model/sections/pack_sections.py).
// Orthographic cameras only: a section is seen straight on, the same scale both ways; pan and zoom, no rotation.
import * as THREE from "three";
// colours are used as written (sRGB) by the shaders below, as on the page: no conversion to linear
THREE.ColorManagement.enabled = false;

const $ = (s) => document.querySelector(s);
const FT = 0.3048;
const status = (t) => { const el = $("#status"); el.textContent = t || ""; el.hidden = !t; };
const [S, META] = await Promise.all([fetch("../data/sections.json").then((r) => r.json()),
                                     fetch("../data/lidar_points.json").then((r) => r.json())]);
const R = S.range;
const KEYS = ["top", "A", "B", "C", "D"];

// ---------- renderer, scene ----------
const canvas = $("#c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
renderer.setPixelRatio(devicePixelRatio);
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 2000);
// local (east, north) -> three.js (x east, y up, z -north)
const w3 = (e, n, up = 0) => new THREE.Vector3(e, up, -n);

// ---------- colours from the page (site.css), light or dark ----------
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const col = (v) => new THREE.Color(css(v));
const isDark = () => document.documentElement.dataset.theme === "dark"
  || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
function applyTheme() {
  const bg = col("--bg"), ink = col("--text");
  renderer.setClearColor(bg);
  for (const m of pointMats) { m.uniforms.uInk.value.copy(ink); m.uniforms.uBg.value.copy(bg); }
  topMat.uniforms.uBg.value.copy(bg);
  // the hillshade: light, shadows in the text colour on the page colour; dark, a dim relief on the dark page
  topMat.uniforms.uLo.value.copy(isDark() ? new THREE.Color(0x000000) : ink);
  topMat.uniforms.uHi.value.copy(isDark() ? new THREE.Color(0x6a6a6a) : bg);
  invalidate();
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => requestAnimationFrame(applyTheme));
new MutationObserver(() => requestAnimationFrame(applyTheme)).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

// ---------- the top view: the hillshade as one textured square ----------
const [e0, n0, e1, n1] = S.top.bounds;
const tex = new THREE.TextureLoader().load(`../data/${S.top.image}`, () => invalidate());
tex.colorSpace = THREE.NoColorSpace; tex.anisotropy = 4;
const topMat = new THREE.ShaderMaterial({
  uniforms: { map: { value: tex }, uLo: { value: new THREE.Color() }, uHi: { value: new THREE.Color() }, uBg: { value: new THREE.Color() } },
  vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `uniform sampler2D map; uniform vec3 uLo, uHi, uBg; varying vec2 vUv;
    void main(){ vec4 t = texture2D(map, vUv); vec3 c = mix(uLo, uHi, t.r);
      gl_FragColor = vec4(mix(uBg, c, step(0.5, t.a)), 1.0); }`,
});
const topQuad = new THREE.Mesh(new THREE.PlaneGeometry(e1 - e0, n1 - n0), topMat);
topQuad.rotation.x = -Math.PI / 2;                                   // image top = north (-z)
topQuad.position.copy(w3((e0 + e1) / 2, (n0 + n1) / 2, 0));
scene.add(topQuad);

// ---------- the sections: points within the frame of each cut, drawn by one shader ----------
const NO_CUT = S.noCut;
const pointMats = [], pointSets = {};
const vtx = `attribute float seg;
  uniform vec3 uP0, uW, uR, uInk, uBg; uniform float uSlab, uDepth, uH0, uH1, uZ0, uZ1, uPx;
  varying vec3 vCol;
  void main(){
    vec3 r = position - uP0;
    float d = dot(r, uW), h = dot(r, uR), z = position.y;
    if (d < -uSlab || d > uDepth || h < uH0 || h > uH1 || z < uZ0 || z > uZ1) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); gl_PointSize = 0.0; return; }
    bool noCut = ${NO_CUT.map((s) => `abs(seg - ${s.toFixed(1)}) < 0.5`).join(" || ")};
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    if (abs(d) <= uSlab && !noCut) {
      vCol = uInk; gl_PointSize = clamp(0.25 * uPx, 2.0, 8.0);
      gl_Position.z -= 0.002 * gl_Position.w;                         // the cut over anything at the same pixel
    } else {
      float t = clamp(max(d, 0.0) / uDepth, 0.0, 1.0);
      vCol = mix(uInk, uBg, 0.45 + 0.48 * pow(t, 0.55));              // grey, lighter with distance behind the cut
      gl_PointSize = clamp(0.16 * uPx, 1.0, 6.0);
    }
  }`;
const frg = "varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol, 1.0); }";
function sectionMaterial(sec) {
  const m = new THREE.ShaderMaterial({
    uniforms: {
      uP0: { value: w3(sec.p0[0], sec.p0[1]) }, uW: { value: w3(sec.w[0], sec.w[1]) }, uR: { value: w3(sec.right[0], sec.right[1]) },
      uInk: { value: new THREE.Color() }, uBg: { value: new THREE.Color() }, uSlab: { value: R.slab }, uDepth: { value: R.depth },
      uH0: { value: R.h[0] }, uH1: { value: R.h[1] }, uZ0: { value: R.z[0] }, uZ1: { value: R.z[1] }, uPx: { value: 8 },
    },
    vertexShader: vtx, fragmentShader: frg,
  });
  pointMats.push(m);
  return m;
}
const SECS = Object.fromEntries(["A", "B", "C", "D"].map((k) => [k, { ...S.sections[k], mat: null }]));
for (const k in SECS) SECS[k].mat = sectionMaterial(SECS[k]);

// decode the LAZ in a worker (laz-worker.js, shared with the viewer), then keep only the points each cut can show
function decodeLaz() {
  const abs = new URL(`../data/${META.file}`, location.href).href;   // absolute: the worker resolves against js/
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL("./laz-worker.js", import.meta.url));
    w.onmessage = (e) => {
      if (e.data.progress) { if (view !== "top") status(e.data.progress); return; }
      w.terminate();
      if (e.data.error) reject(new Error(e.data.error)); else resolve(e.data);
    };
    w.postMessage({ url: abs, meta: META });
  });
}
let lidarReady = false;
decodeLaz().then(({ n, pos, seg }) => {
  const keys = Object.keys(SECS), m = keys.length;
  const p = keys.map((k) => SECS[k]);
  const keep = (s, x, y, zN) => {
    const dx = x - s.p0[0], dn = zN - s.p0[1];
    const h = dx * s.right[0] + dn * s.right[1];
    if (h < R.h[0] || h > R.h[1] || y < R.z[0] || y > R.z[1]) return false;
    const d = dx * s.w[0] + dn * s.w[1];
    return d >= -R.slab && d <= R.depth;
  };
  const count = new Array(m).fill(0);
  for (let i = 0; i < n; i++) {
    const x = pos[3 * i], y = pos[3 * i + 1], zN = -pos[3 * i + 2];
    for (let j = 0; j < m; j++) if (keep(p[j], x, y, zN)) count[j]++;
  }
  const P = count.map((c) => new Float32Array(c * 3)), G = count.map((c) => new Uint8Array(c)), at = new Array(m).fill(0);
  for (let i = 0; i < n; i++) {
    const x = pos[3 * i], y = pos[3 * i + 1], zN = -pos[3 * i + 2];
    for (let j = 0; j < m; j++) {
      if (!keep(p[j], x, y, zN)) continue;
      const o = at[j]++;
      P[j][3 * o] = x; P[j][3 * o + 1] = y; P[j][3 * o + 2] = pos[3 * i + 2]; G[j][o] = seg[i];
    }
  }
  keys.forEach((k, j) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(P[j], 3));
    g.setAttribute("seg", new THREE.BufferAttribute(G[j], 1));
    const pts = new THREE.Points(g, SECS[k].mat);
    pts.frustumCulled = false; pts.visible = view === k;
    scene.add(pts); pointSets[k] = pts;
  });
  lidarReady = true; status("");
  invalidate();
}).catch((err) => status(`Could not load the LiDAR: ${err.message}`));

// ---------- views: centre + scale (CSS px per metre); fitted to the window until the reader moves it ----------
let view = KEYS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "top";
const st = {};   // per view: { cx, cy, s, fitted }
const C0 = S.c0;
// the panel sits at the top left: the drawing goes either below it or to its right, whichever leaves it larger
function margins(fw, fh) {
  const ui = $("#ui").getBoundingClientRect();
  const below = { l: 64, r: 52, t: ui.bottom + 16, b: 118 }, beside = { l: ui.right + 64, r: 52, t: 40, b: 118 };
  const sc = (M) => Math.min((innerWidth - M.l - M.r) / fw, (innerHeight - M.t - M.b) / fh);
  return innerWidth > 560 && sc(beside) > sc(below) ? beside : below;
}
function fit(k) {
  // the frame to fit: a section's h x z rectangle; the top view, the section lines with room for their letters
  const fw = k === "top" ? 250 : R.h[1] - R.h[0], fh = k === "top" ? 250 : R.z[1] - R.z[0];
  const M = margins(fw, fh), aw = innerWidth - M.l - M.r, ah = innerHeight - M.t - M.b;
  const s = Math.max(0.5, Math.min(aw / fw, ah / fh));
  const fx = k === "top" ? C0[0] : (R.h[0] + R.h[1]) / 2, fy = k === "top" ? C0[1] : (R.z[0] + R.z[1]) / 2;
  const sx0 = M.l + aw / 2, sy0 = M.t + ah / 2;
  st[k] = { cx: fx - (sx0 - innerWidth / 2) / s, cy: fy + (sy0 - innerHeight / 2) / s, s, fit: s, fitted: true };
}
// world (h, z) or (east, north) -> screen
const SX = (v) => innerWidth / 2 + (v - st[view].cx) * st[view].s;
const SY = (v) => innerHeight / 2 - (v - st[view].cy) * st[view].s;

function placeCamera() {
  const v = st[view], hw = innerWidth / 2 / v.s, hh = innerHeight / 2 / v.s;
  camera.left = -hw; camera.right = hw; camera.top = hh; camera.bottom = -hh;
  if (view === "top") {
    camera.up.set(0, 0, -1);                                         // north up
    camera.position.copy(w3(v.cx, v.cy, 1000)); camera.near = 1; camera.far = 2000;
    camera.lookAt(w3(v.cx, v.cy, 0));
  } else {
    const sec = SECS[view], W = w3(sec.w[0], sec.w[1]), Rr = w3(sec.right[0], sec.right[1]);
    const c = w3(sec.p0[0], sec.p0[1]).addScaledVector(Rr, v.cx).add(new THREE.Vector3(0, v.cy, 0));
    camera.up.set(0, 1, 0);
    camera.position.copy(c).addScaledVector(W, -200); camera.near = 1; camera.far = 200 + R.depth + 50;
    camera.lookAt(c);
    sec.mat.uniforms.uPx.value = v.s * renderer.getPixelRatio();
  }
  camera.updateProjectionMatrix();
}

// ---------- the annotations (SVG over the canvas) ----------
const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
const T = (x, y, t, cls = "", anchor = "middle", extra = "") =>
  `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${anchor}" class="${cls}" ${extra}>${esc(t)}</text>`;
const L = (x1, y1, x2, y2, cls, extra = "") => `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" class="${cls}" ${extra}/>`;
const nice = (target, steps) => steps.reduce((b, s) => (Math.abs(s - target) < Math.abs(b - target) ? s : b), steps[0]);

function scaleBars(o) {
  const s = st[view].s, y = innerHeight - (innerWidth <= 560 ? 80 : 58), x = 16;   // phones: above the two-line source
  const m = nice(130 / s, [1, 2, 5, 10, 20, 30, 50, 100]), f = nice(130 / s / FT, [5, 10, 25, 50, 100, 200, 300]);
  const bar = (x0, len, n, labs) => {
    for (let i = 0; i < n; i++) o.push(`<rect x="${(x0 + (i * len) / n).toFixed(1)}" y="${y}" width="${(len / n).toFixed(1)}" height="5" class="${i % 2 ? "bar-off" : "bar-on"}"/>`);
    labs.forEach((t, i) => o.push(T(x0 + (i * len) / n, y + 17, t, "m")));
  };
  const lm = m * s, lf = f * FT * s;
  bar(x, lm, 2, ["0", `${m / 2}`, `${m} m`]);
  bar(x + lm + 36, lf, 2, ["0", `${f / 2}`, `${f} ft`]);
}

function drawTop(o) {
  const ring = S.parcel.map(([e, n]) => `${SX(e).toFixed(1)},${SY(n).toFixed(1)}`).join(" ");
  o.push(`<polygon points="${ring}" class="ink" stroke-width="2" stroke-dasharray="8 6"/>`);
  for (const [k, [[ax, ay], [bx, by]]] of Object.entries(S.top.lines)) {
    const sec = SECS[k], A = [SX(ax), SY(ay)], B = [SX(bx), SY(by)];
    o.push(L(A[0], A[1], B[0], B[1], "cutline"));
    const lx = sec.w[0], ly = -sec.w[1];                               // the look direction on screen (north up)
    const ux = (B[0] - A[0]) / Math.hypot(B[0] - A[0], B[1] - A[1]), uy = (B[1] - A[1]) / Math.hypot(B[0] - A[0], B[1] - A[1]);
    for (const [P, sgn] of [[A, -1], [B, 1]]) {
      const q = [P[0] + 22 * lx, P[1] + 22 * ly];
      o.push(`<path d="M${P[0].toFixed(1)} ${P[1].toFixed(1)}L${q[0].toFixed(1)} ${q[1].toFixed(1)}M${(q[0] - 9 * lx - 6 * ly).toFixed(1)} ${(q[1] - 9 * ly + 6 * lx).toFixed(1)}L${q[0].toFixed(1)} ${q[1].toFixed(1)}L${(q[0] - 9 * lx + 6 * ly).toFixed(1)} ${(q[1] - 9 * ly - 6 * lx).toFixed(1)}" class="cutline"/>`);
      o.push(T(P[0] + sgn * 18 * ux, P[1] + sgn * 18 * uy + 6, k, "key hit", "middle", `data-k="${k}"`));
    }
  }
  for (const lab of S.top.labels) o.push(T(SX(lab.x), SY(lab.y) + 4, lab.name, "big"));
  // north arrow (north is straight up)
  const nx = innerWidth - 40, ny = innerHeight - 86;
  o.push(`<path d="M${nx} ${ny}V${ny - 36}M${nx - 7} ${ny - 27}L${nx} ${ny - 36}L${nx + 7} ${ny - 27}" class="ink" stroke-width="2"/>`);
  o.push(T(nx, ny - 44, "N", "big"));
}

function drawSection(o) {
  const sec = SECS[view], s = st[view].s;
  const xL = SX(R.h[0]), xR = SX(R.h[1]), yT = SY(R.z[1]), yB = SY(R.z[0]);
  // elevation rulers: feet on the left, metres on the right, kept on screen
  const rl = Math.max(xL, 58), rr = Math.min(xR, innerWidth - 46);
  const fstep = nice(48 / s / FT, [5, 10, 25, 50, 100]), mstep = nice(48 / s, [1, 2, 5, 10, 20]);
  o.push(L(rl, Math.max(yT, 0), rl, Math.min(yB, innerHeight), "tick"), L(rr, Math.max(yT, 0), rr, Math.min(yB, innerHeight), "tick"));
  for (let f = Math.ceil(R.z[0] / FT / fstep) * fstep; f * FT <= R.z[1]; f += fstep) {
    const y = SY(f * FT); if (y < 0 || y > innerHeight) continue;
    o.push(L(rl - 7, y, rl, y, "tick"), T(rl - 10, y + 4, `${f}`, "m", "end"));
  }
  for (let m = Math.ceil(R.z[0] / mstep) * mstep; m <= R.z[1]; m += mstep) {
    const y = SY(m); if (y < 0 || y > innerHeight) continue;
    o.push(L(rr, y, rr + 7, y, "tick"), T(rr + 10, y + 4, `${m}`, "m", "start"));
  }
  o.push(T(rl - 10, Math.max(yT, 14) - 8, "ft", "m", "end"), T(rr + 10, Math.max(yT, 14) - 8, "m", "m", "start"));
  // Olive Street under the deck: dashed, an estimate
  for (const e of sec.estimates) {
    const pts = e.pts.map(([h, z]) => `${SX(h).toFixed(1)},${SY(z).toFixed(1)}`).join(" ");
    o.push(`<polyline points="${pts}" class="ink" stroke-width="2" stroke-dasharray="10 8"/>`);
    const mid = e.pts[Math.floor(e.pts.length / 2)], zft = Math.round(mid[1] / FT);
    const lab = e.pts.length === 2 ? `${e.label.replace(" (estimate)", "")}, ≈${zft} ft (estimate)` : e.label;
    o.push(T(SX(e.pts.length === 2 ? (e.pts[0][0] + e.pts[1][0]) / 2 : mid[0]), SY(mid[1]) + 18, lab));
  }
  // California Plaza levels the cut passes through
  for (const lv of sec.levels) {
    const t = `${lv.label} ≈${Math.round(lv.z / FT)} ft`, half = t.length * 3;
    o.push(T(Math.min(Math.max(SX(lv.h), xL + half + 6), xR - half - 6), SY(lv.z) - 10, t));
  }
  // ground elevations
  let lastX = -1e9;
  for (const g of sec.tags) {
    if (SX(g.h) - lastX < 44) continue;                              // zoomed far out: skip a tag that would overlap
    lastX = SX(g.h);
    o.push(`<circle cx="${SX(g.h).toFixed(1)}" cy="${SY(g.z).toFixed(1)}" r="4" class="tag"/>`, T(SX(g.h), SY(g.z) - 9, `${Math.round(g.z / FT)} ft`));
  }
  // under the frame: Y-1 (solid when cut, dashed when behind the cut) and the streets
  const yb = yB + 24, p = sec.parcel;
  o.push(L(SX(p.h[0]), yb, SX(p.h[1]), yb, "ink", `stroke-width="2"${p.behind ? ' stroke-dasharray="12 8"' : ""}`));
  for (const h of p.h) o.push(L(SX(h), yb - 7, SX(h), yb + 7, "ink", 'stroke-width="2"'));
  o.push(T(SX((p.h[0] + p.h[1]) / 2), yb + 22, p.behind ? "Parcel Y-1 (behind the cut)" : "Parcel Y-1", "big"));
  for (const st_ of sec.streets) o.push(L(SX(st_.h), yb + 32, SX(st_.h), yb + 42, "tick"), T(SX(st_.h), yb + 56, st_.name, "m"));
}

function drawOverlay() {
  const o = [];
  if (view === "top") drawTop(o); else drawSection(o);
  scaleBars(o);
  const ov = $("#ov");
  ov.setAttribute("viewBox", `0 0 ${innerWidth} ${innerHeight}`);
  ov.innerHTML = o.join("");
}
$("#ov").addEventListener("click", (e) => { const k = e.target.dataset?.k; if (k) setView(k); });

// ---------- drawing on demand ----------
let raf = 0;
function invalidate() { if (!raf) raf = requestAnimationFrame(draw); }
function draw() {
  raf = 0;
  placeCamera();
  topQuad.visible = view === "top";
  for (const k in pointSets) pointSets[k].visible = view === k;
  renderer.render(scene, camera);
  drawOverlay();
}
function resize() {
  renderer.setSize(innerWidth, innerHeight);
  for (const k of Object.keys(st)) if (st[k].fitted) fit(k);
  moveThumb(true);
  invalidate();
}
addEventListener("resize", resize);

// ---------- the switch (the viewer's sliding thumb) ----------
function moveThumb(instant) {
  const th = $("#views .thumb"), on = $("#views button.on");
  if (!th || !on) return;
  th.classList.toggle("instant", !!instant);
  th.style.width = `${on.offsetWidth}px`;
  th.style.transform = `translateX(${on.offsetLeft}px)`;
  if (instant) requestAnimationFrame(() => th.classList.remove("instant"));
}
function setView(k, instant = false) {
  view = k;
  for (const b of document.querySelectorAll("#views button")) b.classList.toggle("on", b.dataset.v === k);
  moveThumb(instant);
  if (k === "top") {
    $("#capT").textContent = "Top view, north up";
    $("#capS").textContent = "Parcel Y-1 (dashed) and the four section lines; the arrows show which way each section looks. Click a letter to open that section.";
  } else {
    $("#capT").textContent = SECS[k].title;
    $("#capS").textContent = `Looking ${SECS[k].look}, ${SECS[k].sub}.`;
  }
  $("#legend").hidden = k === "top";
  if (!st[k] || st[k].fitted) fit(k);
  status(k !== "top" && !lidarReady ? "Loading LiDAR…" : "");
  history.replaceState(null, "", `#${k}`);
  invalidate();
}
for (const b of document.querySelectorAll("#views button")) b.addEventListener("click", () => setView(b.dataset.v));
// a link to another view of this page (#A … #D, #top) opens that view
addEventListener("hashchange", () => { const k = location.hash.slice(1); if (KEYS.includes(k) && k !== view) setView(k); });
$("#reset").addEventListener("click", () => { fit(view); invalidate(); });

// ---------- pan and zoom (mouse, trackpad, touch) ----------
const pointers = new Map();
let pinch = null;
canvas.addEventListener("pointerdown", (e) => {
  canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, [e.clientX, e.clientY]); canvas.classList.add("drag");
  if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: st[view].s }; }
});
canvas.addEventListener("pointermove", (e) => {
  if (!pointers.has(e.pointerId)) return;
  const [px, py] = pointers.get(e.pointerId), v = st[view];
  pointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (pointers.size === 1) {
    v.cx -= (e.clientX - px) / v.s; v.cy += (e.clientY - py) / v.s; v.fitted = false;
  } else if (pointers.size === 2 && pinch) {
    const [a, b] = [...pointers.values()];
    zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (pinch.s * Math.hypot(a[0] - b[0], a[1] - b[1])) / pinch.d / v.s);
  }
  invalidate();
});
const up = (e) => { pointers.delete(e.pointerId); if (pointers.size < 2) pinch = null; if (!pointers.size) canvas.classList.remove("drag"); };
canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
function zoomAt(mx, my, k) {
  const v = st[view], s1 = Math.min(Math.max(v.s * k, v.fit * 0.6), v.fit * 16);
  const wx = v.cx + (mx - innerWidth / 2) / v.s, wy = v.cy - (my - innerHeight / 2) / v.s;
  v.s = s1; v.cx = wx - (mx - innerWidth / 2) / s1; v.cy = wy + (my - innerHeight / 2) / s1; v.fitted = false;
}
canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015)); invalidate(); }, { passive: false });
canvas.addEventListener("dblclick", () => { fit(view); invalidate(); });

// ---------- start ----------
renderer.setSize(innerWidth, innerHeight);
applyTheme();
setView(view, true);
