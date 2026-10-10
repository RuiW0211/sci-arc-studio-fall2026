// Y-1 site viewer: the 2023 USGS LiDAR point cloud, every point labelled by Houdini with its object and layer, plus the
// design files (design_<name>.glb) on top. Layers are read from the point cloud meta and the design GLBs (extras.layer);
// config.json only adds labels, order and colours.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";

const $ = (s) => document.querySelector(s);
const status = (t) => { $("#status").textContent = t || ""; };
const cfg = await (await fetch("config.json")).json();
// ---------- display units: every length goes through len() (user, 2026-10-08: m / ft switch in the panel; ft is the
// default, config.json "units" can change it; the data and all files stay in metres) ----------
const FT = 0.3048;
let units = (() => { try { return localStorage.getItem("y1-viewer-units") || cfg.units || "ft"; } catch { return cfg.units || "ft"; } })();
const toUnit = (m) => (units === "ft" ? m / FT : m);
const len = (m, digits = 1) => `${toUnit(m).toFixed(digits)} ${units}`;
// building / landmark entities (which LiDAR objects make up one real building, and what it is): optional
const ENTITIES = cfg.entities ? await fetch(cfg.entities).then((r) => (r.ok ? r.json() : null)).catch(() => null) : null;
const entityOfName = new Map();
for (const e of ENTITIES?.entities ?? []) for (const p of e.parts) entityOfName.set(p, e);
// Display settings (panel section): ?px= ?keep= ?cap= ?size= override config.json "lidar" for this page only (lodPixels,
// lodKeepDensity, pointCap, size), so settings can be tried before they go into config.json
const urlq = new URLSearchParams(location.search);
const CFG_LIDAR = { ...cfg.lidar };   // config.json as delivered: the Display settings "Reset"
for (const [k, key] of [["px", "lodPixels"], ["keep", "lodKeepDensity"], ["cap", "pointCap"], ["size", "size"]])
  if (urlq.has(k)) cfg.lidar[key] = +urlq.get(k);

// ---------- renderer / scene / camera ----------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
document.body.prepend(renderer.domElement);
const scene = new THREE.Scene();
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
scene.background = new THREE.Color(css("--bg3d"));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { scene.background.set(css("--bg3d")); invalidate(); });
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.5, 6000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxDistance = 2500;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(300, 500, 200);
scene.add(sun);
const v0 = cfg.views[0];
camera.position.fromArray(v0.position);
controls.target.fromArray(v0.target);

// ---------- overlays: the design files ----------
const draco = new DRACOLoader().setDecoderPath("https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/");
const model = new THREE.Group();   // everything drawn as geometry over the point cloud
scene.add(model);

// ---------- "white point cloud" (user, 2026-10-09): an option of the population layer; the point cloud fades to white,
// a little transparent, so the people stand out. One shared uniform, eased over 0.5 s.
const FOCUS = { value: 0 };
const FOCUS_GREY = { value: cfg.population?.whiteCloud?.white ?? 0.8 }, FOCUS_ALPHA = { value: cfg.population?.whiteCloud?.opacity ?? 0.5 };
const focusMats = [];
function withFocus(shader) {
  shader.uniforms.uFocus = FOCUS; shader.uniforms.uFocusGrey = FOCUS_GREY; shader.uniforms.uFocusAlpha = FOCUS_ALPHA;
  shader.fragmentShader = "uniform float uFocus, uFocusGrey, uFocusAlpha;\n" + shader.fragmentShader.replace("#include <color_fragment>",
    `#include <color_fragment>
  diffuseColor.rgb = mix(diffuseColor.rgb, vec3(uFocusGrey), uFocus);
  diffuseColor.a *= mix(1.0, uFocusAlpha, uFocus);`);
}
let focusAnim = 0;
function setWhiteCloud(on) {
  const from = FOCUS.value, to = on ? 1 : 0, t0 = performance.now();
  $("#colorSec").classList.toggle("overridden", on);
  if (on) for (const m of focusMats) if (!m.userData.alwaysTransparent && !m.transparent) { m.transparent = true; m.needsUpdate = true; }
  cancelAnimationFrame(focusAnim);
  const step = (now) => {
    const k = Math.min((now - t0) / 500, 1), e = k * k * (3 - 2 * k);
    FOCUS.value = from + (to - from) * e;
    pop?.highlight(FOCUS.value);   // people grow with it
    invalidate();
    if (k < 1) focusAnim = requestAnimationFrame(step);
    else if (!on) for (const m of focusMats) if (!m.userData.alwaysTransparent) { m.transparent = false; m.needsUpdate = true; }
  };
  focusAnim = requestAnimationFrame(step);
}

// estimated facade points (site-model/houdini/tools/synth_facades.py): walls the airborne LiDAR barely saw, filled
// only where no return is near. NOT measured: their own layer and colour, drawn over the cloud, never picked.
// (user, 2026-10-10) they are merged into the building points when the LiDAR loads (loadLidar): same layer, colour,
// opacity, picking and highlight; each point carries the object of the nearest measured return and its height above
// the ground. Here only the file is read.
let facadeData = null;
try {
  const fm = await (await fetch(cfg.facades.meta)).json();
  const buf = await (await fetch(cfg.facades.meta.replace(/[^/]*$/, "") + fm.file)).arrayBuffer();
  const m = fm.count;
  facadeData = { n: m, names: fm.objects || [], pos: new Float32Array(buf, 0, 3 * m),
                 obj: fm.objects ? new Uint16Array(buf, 12 * m, m) : null, hag: fm.objects ? new Int16Array(buf, 14 * m, m) : null };
} catch (e) { /* no estimated facades */ }

// design files: every site-model/exports/design_<name>.glb (listed in assets/models.json by the Pages workflow and by
// web/serve.py), one per person, so nobody overwrites anyone else's file. Nodes without extras.layer go into the
// layer "Design_<name>". Design layers also show over the point cloud.
const designLayers = new Set();
try {
  const list = await (await fetch(cfg.designs)).json();
  for (const file of list.filter((f) => /^design_.+\.glb$/i.test(f))) {
    const who = file.replace(/^design_|\.glb$/gi, "");
    status(`Loading ${file}…`);
    const d = (await new GLTFLoader().setDRACOLoader(draco).loadAsync(cfg.designs.replace(/[^/]*$/, "") + file)).scene;
    for (const o of d.children) if (!o.userData.layer) o.userData.layer = `Design_${who}`;
    d.traverse((o) => o.userData.layer && designLayers.add(o.userData.layer));
    // exported without materials (the Houdini starter scene): the Design colour, both faces
    const mat = new THREE.MeshStandardMaterial({ color: cfg.layers.Design?.color || "#DDE5B6", roughness: 0.8, side: THREE.DoubleSide });
    d.traverse((o) => {
      if (!o.isMesh) return;
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();   // no normals: three.js would draw it black
      if (!o.material.name || o.material.name === "default") o.material = mat;
    });
    d.updateMatrixWorld(true);
    model.add(d);
  }
} catch (e) { /* no list (or no designs yet) */ }

const layers = new Map(); // name -> { cfg, objects, meshes, visible, points }
model.traverse((o) => {
  const name = o.userData.layer;
  if (!name || layers.get(name)?.objects.includes(o)) return;
  if (!layers.has(name)) {
    const c = cfg.layers[name] || (designLayers.has(name)
      ? { ...cfg.layers.Design, label: name.replace(/_/g, " "), visible: true } : {});
    if (designLayers.has(name)) c.overlay = true;
    layers.set(name, { name, cfg: c, objects: [], meshes: [], visible: c.visible ?? true });
  }
  const L = layers.get(name);
  L.objects.push(o);
  o.traverse((m) => m.isMesh && L.meshes.push(m));
});
// the point cloud's layers (from its meta, which is tiny) get their toggles
const lidarMeta = await (await fetch(cfg.lidar.meta)).json();
// a cloud thinned with distance (Houdini wide site) says so in the Point cloud button's tooltip
const CLOUD_TIP = $('[data-mode="cloud"]').title;
function cloudTip() {
  $('[data-mode="cloud"]').title = CLOUD_TIP + (!lidarMeta.thinning ? "" : ". Every return as captured within "
    + `${len(lidarMeta.thinning.full_density_radius_m, 0)} of Y-1; farther out each object (building, tree, car …) keeps a `
    + "share of its points, fewer with distance.");
}
cloudTip();
for (const raw of new Set(lidarMeta.attributes?.object?.layers ?? [])) {
  const name = cfg.mergeLayers?.[raw] ?? raw;   // merged layers (config.json mergeLayers) get no row of their own
  if (!layers.has(name)) {
    const c = cfg.layers[name] || {};
    layers.set(name, { name, cfg: c, objects: [], meshes: [], visible: c.visible ?? true });
  }
}
const ordered = [...layers.values()].sort((a, b) => (a.cfg.order ?? 99) - (b.cfg.order ?? 99) || a.name.localeCompare(b.name));

let mode = null;
let glassAt = -1e9;   // last adaptive-glass check (see adaptGlass); declared early: setMode resets it
const lidarGroup = new THREE.Group();
scene.add(lidarGroup);
let lidar = null;

function applyVisibility() {
  for (const L of ordered) {
    // strict booleans: three.js only skips objects whose visible === false (undefined still renders)
    // the Y-1 outline overlay stays on in the raw LiDAR, where there are no toggles
    const showMesh = Boolean(L.visible && L.cfg.overlay);   // overlays (the designs) are drawn over the cloud
    for (const o of L.objects) o.visible = showMesh;
    for (const p of L.lidarParts || []) p.visible = Boolean(L.visible && mode === "cloud");
  }
  invalidate();
}

// ---------- render on demand: only when something changed (camera, colours, visibility, size) ----------
let dirty = true, lastMove = -1e9;
function invalidate() { dirty = true; }
controls.addEventListener("change", () => { dirty = true; lastMove = performance.now(); });

$("#layers").innerHTML = "";
for (const L of ordered) {
  const row = document.createElement("label");
  row.className = "layer";
  const n = "";   // filled by layerCounts(): objects in the point cloud
  // the dot is the toggle: filled = shown, ring = hidden (the checkbox stays for keyboard / screen readers, visually hidden);
  // it shows the layer colour when the point cloud is coloured by layer, a neutral dot otherwise
  const sw = `<i class="sw" style="--c:${L.cfg.color || "var(--muted)"}"></i>`;
  row.innerHTML = `<input type="checkbox" ${L.visible ? "checked" : ""}>${sw}<span class="nm">${L.cfg.label || L.name}</span><span class="n">${n}</span>`;
  L.countEl = row.querySelector(".n");
  row.querySelector("input").onchange = (e) => { L.visible = e.target.checked; applyVisibility(); };
  $("#layers").append(row);
}

// ---------- point material: size in metres (perspective), never smaller than 1 px ----------
function pointMaterial(sizeMetres) {
  const mat = new THREE.PointsMaterial({ size: sizeMetres, vertexColors: true, sizeAttenuation: true });
  focusMats.push(mat);
  mat.onBeforeCompile = (shader) => {
    withFocus(shader);
    shader.vertexShader = shader.vertexShader.replace(
      "#include <fog_vertex>", "gl_PointSize = max(gl_PointSize, 1.0);\n#include <fog_vertex>");
    // round points instead of squares
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <clipping_planes_fragment>",
      "if (length(gl_PointCoord - vec2(0.5)) > 0.5) discard;\n#include <clipping_planes_fragment>");
  };
  return mat;
}

// ---------- LiDAR (2023 USGS), loaded on first use ----------
// One LAZ file (LAS point format 0 + extra bytes object / segment / hag, written by site-model/houdini/tools/pack_wide.py),
// decoded in a worker with laz-perf.
// Points are split per layer (from the "object" attribute) so layer toggles apply to the LiDAR too, and each layer is cut into
// square chunks of one size (LOD_CELL m, everywhere: chunks of two sizes thin differently and leave a visible seam where
// they meet) whose points are shuffled: drawing the first k points of a chunk is then an even thinning (see updateLod).
const LOD_CELL = cfg.lidar.lodCell ?? 120;
const lodCell = () => LOD_CELL;
function decodeLaz(url, meta) {
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL("./laz-worker.js", import.meta.url));
    w.onmessage = (e) => {
      if (e.data.progress) return status(e.data.progress);
      w.terminate();
      if (e.data.error) reject(new Error(e.data.error)); else resolve(e.data);
    };
    w.postMessage({ url: new URL(url, location.href).href, meta });   // absolute: a worker resolves relative URLs against js/
  });
}
async function loadLidar() {
  status("Loading LiDAR…");
  const meta = lidarMeta;
  const base = cfg.lidar.meta.replace(/[^/]*$/, "");
  const objAttr = meta.attributes?.object;
  let { n, pos: P, cls: C, inten: I, obj, hag: HG } = await decodeLaz(base + meta.file, meta);
  status("Preparing LiDAR…");
  // config.json mergeLayers folds LiDAR layers into others in the viewer (user, 2026-10-10: street furniture and the
  // unassigned points draw as Terrain); the objects keep their own names
  const MERGE = cfg.mergeLayers || {};
  const objNames = objAttr?.names ?? ["_other"], objLayers = (objAttr?.layers ?? ["_other"]).map((l) => MERGE[l] ?? l);
  // estimated facade points join the measured ones as ordinary building points: the object of their nearest return,
  // that object's mean intensity, class "building"; after this nothing tells them apart
  if (facadeData?.obj) {
    const nameIdx = new Map(objNames.map((nm, k) => [nm, k]));
    const map = facadeData.names.map((nm) => nameIdx.get(nm) ?? -1);
    const sum = new Float64Array(objNames.length), cnt = new Uint32Array(objNames.length);
    for (let i = 0; i < n; i++) { sum[obj[i]] += I[i]; cnt[obj[i]]++; }
    const keep = [];
    for (let j = 0; j < facadeData.n; j++) if (map[facadeData.obj[j]] >= 0) keep.push(j);
    const m = keep.length, N2 = n + m;
    const P2 = new P.constructor(3 * N2), C2 = new C.constructor(N2), I2 = new I.constructor(N2), O2 = new obj.constructor(N2);
    const H2 = HG ? new HG.constructor(N2) : null;
    P2.set(P); C2.set(C); I2.set(I); O2.set(obj); if (H2) H2.set(HG);
    keep.forEach((j, k) => {
      const i = n + k, o = map[facadeData.obj[j]];
      P2[3 * i] = facadeData.pos[3 * j]; P2[3 * i + 1] = facadeData.pos[3 * j + 1]; P2[3 * i + 2] = facadeData.pos[3 * j + 2];
      C2[i] = 6; O2[i] = o; I2[i] = cnt[o] ? Math.round(sum[o] / cnt[o]) : 128;
      if (H2) H2[i] = facadeData.hag[j];
    });
    P = P2; C = C2; I = I2; obj = O2; HG = H2; n = N2;
    facadeData = null;   // memory
  }
  const material = pointMaterial(cfg.lidar.size ?? 0.3);
  // local density of each point's layer (returns per m2 of plan, from a 10 m grid, bilinear so it varies smoothly) and a
  // draw priority q = random * density^(1 - LOD_KEEP): the LOD draws the points with q below a target, so dense ground is
  // thinned more than sparse ground, point by point (no steps at chunk borders). On screen the density then goes as
  // (density / LOD_RHO0)^LOD_KEEP: 0 would flatten everything to one screen density and hide the fade from Y-1 outwards,
  // 1 would keep the data's density as it is; 0.8 keeps most of the fade (16x denser data shows ~9x denser).
  const layerIdx = new Map(), objL = new Uint8Array(objLayers.length);
  objLayers.forEach((l, k) => { if (!layerIdx.has(l)) layerIdx.set(l, layerIdx.size); objL[k] = layerIdx.get(l); });
  let gx0 = Infinity, gz0 = Infinity, gx1 = -Infinity, gz1 = -Infinity;
  for (let i = 0; i < n; i++) { const x = P[3 * i], z = P[3 * i + 2]; if (x < gx0) gx0 = x; if (x > gx1) gx1 = x; if (z < gz0) gz0 = z; if (z > gz1) gz1 = z; }
  const GW = 10, gnx = Math.ceil((gx1 - gx0) / GW) + 2, gnz = Math.ceil((gz1 - gz0) / GW) + 2, gsz = gnx * gnz;
  const grid = new Float32Array(layerIdx.size * gsz);
  for (let i = 0; i < n; i++) grid[objL[obj[i]] * gsz + Math.floor((P[3 * i] - gx0) / GW) * gnz + Math.floor((P[3 * i + 2] - gz0) / GW)] += 1 / (GW * GW);
  const q = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const fx = Math.max((P[3 * i] - gx0) / GW - 0.5, 0), fz = Math.max((P[3 * i + 2] - gz0) / GW - 0.5, 0);
    const ix = Math.min(Math.floor(fx), gnx - 2), iz = Math.min(Math.floor(fz), gnz - 2), tx = fx - ix, tz = fz - iz, o = objL[obj[i]] * gsz;
    const rho = (grid[o + ix * gnz + iz] * (1 - tx) + grid[o + (ix + 1) * gnz + iz] * tx) * (1 - tz)
              + (grid[o + ix * gnz + iz + 1] * (1 - tx) + grid[o + (ix + 1) * gnz + iz + 1] * tx) * tz;
    q[i] = Math.random() * Math.max(rho, 1e-4) ** (1 - LOD_KEEP) * LOD_RHO0 ** LOD_KEEP;
  }
  // bucket point indices by layer and LOD chunk
  const buckets = new Map();
  for (let i = 0; i < n; i++) {
    const c = lodCell(P[3 * i], P[3 * i + 2]);
    const key = `${objLayers[obj[i]]}|${c}|${Math.floor(P[3 * i] / c)}|${Math.floor(P[3 * i + 2] / c)}`;
    let b = buckets.get(key); if (!b) buckets.set(key, (b = []));
    b.push(i);
  }
  const parts = [];
  for (const [key, idx] of buckets) {
    const [name, cell] = key.split("|"), m = idx.length;
    idx.sort((a, b) => q[a] - q[b]);   // by draw priority: the first k points are the ones to keep when thinning
    const pos = new Float32Array(m * 3), zs = new Float32Array(m), cls = new Uint8Array(m), inten = new Uint8Array(m), ob = new Uint16Array(m);
    const qs = new Float32Array(m), hag = HG ? new Int16Array(m) : null;   // height above ground, 0.1 m (Houdini LAZ)
    for (let j = 0; j < m; j++) {
      const i = idx[j];
      pos[3 * j] = P[3 * i]; pos[3 * j + 1] = P[3 * i + 1]; pos[3 * j + 2] = P[3 * i + 2];
      zs[j] = P[3 * i + 1]; cls[j] = C[i]; inten[j] = I[i]; ob[j] = obj[i]; qs[j] = q[i];
      if (hag) hag[j] = HG[i];
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const col = new Float32Array(m * 3);
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.computeBoundingSphere();
    const pts = new THREE.Points(g, material);
    pts.frustumCulled = true;
    pts.userData.part = { name, pos, hag, zs, cls, inten, ob, col, n: m, cell: +cell, q: qs };
    lidarGroup.add(pts);
    parts.push(pts.userData.part);
    const L = layers.get(name);
    if (L) (L.lidarParts ||= []).push(pts);
  }
  const objCount = new Uint32Array(objNames.length);
  for (let i = 0; i < n; i++) objCount[obj[i]]++;
  // per object: its entity (index into ENTITIES.entities, -1 = none); per entity: its objects
  const objEntity = new Int32Array(objNames.length).fill(-1), entityObjs = new Map();
  const entIndex = new Map((ENTITIES?.entities ?? []).map((e, i) => [e, i]));
  objNames.forEach((nm, k) => {
    const e = entityOfName.get(nm);
    if (e) { const i = entIndex.get(e); objEntity[k] = i; (entityObjs.get(i) ?? entityObjs.set(i, []).get(i)).push(k); }
  });
  lidar = { parts, material, objNames, objLayers, objCount, objEntity, entityObjs, count: n,
            how: urlq.get("color") ?? cfg.cloudColor ?? "layer", selected: -1, selMask: new Uint8Array(objNames.length) };
  status("");
}

// ---------- level of detail for the LiDAR (screen-space, continuous) ----------
// Each point is drawn when its priority q (random x the local density of its layer, set in loadLidar) is below the density the
// screen can show at the chunk's distance, (focal / d)^2 / LOD_PX^2 returns per m2: a point in dense ground is kept with a
// lower probability than one in sparse ground, so neighbouring points end up at most ~LOD_PX pixels apart everywhere and the
// thinning has no steps at chunk borders. Chunks hold their points sorted by q, so this is a draw range. The count depends
// only on where the camera is, never on whether it is moving, so nothing pops when a drag or zoom stops; counts also ease
// towards their target over a few frames. A total cap protects slow machines.
let LOD_PX = cfg.lidar.lodPixels ?? 1.2, LOD_CAP = cfg.lidar.pointCap ?? 6e6;   // let: Display settings change them live
const LOD_EASE = 0.25;
const LOD_KEEP = cfg.lidar.lodKeepDensity ?? 0.8, LOD_RHO0 = cfg.lidar.lodRefDensity ?? 1.0;   // see loadLidar
const _c = new THREE.Vector3();
const below = (q, t) => { let lo = 0, hi = q.length; while (lo < hi) { const m = (lo + hi) >> 1; if (q[m] < t) lo = m + 1; else hi = m; } return lo; };
function updateLod() {
  if (!lidar) return false;
  const focal = renderer.domElement.height / 2 / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const chunks = [];
  for (const p of lidarGroup.children) {
    if (!p.visible) continue;
    const bs = p.geometry.boundingSphere;
    _c.copy(bs.center);
    const d = Math.max(camera.position.distanceTo(_c) - bs.radius, 1);
    chunks.push([p, p.userData.part.q, (focal / d) ** 2]);                 // returns per m2 the screen shows at a 1 px gap
  }
  const count = (px) => { let s = 0; for (const [, q, a] of chunks) s += below(q, a / (px * px)); return s; };
  // over the cap: widen the allowed on-screen gap (binary search) instead of thinning everything, so near chunks stay complete
  let px = LOD_PX;
  if (count(px) > LOD_CAP) { let lo = LOD_PX, hi = 64; for (let it = 0; it < 20; it++) { const mid = (lo + hi) / 2; if (count(mid) > LOD_CAP) lo = mid; else hi = mid; } px = hi; }
  let moving = false;
  for (const [p, q, a] of chunks) {
    const n = q.length, target = Math.max(1, below(q, a / (px * px)));
    const cur = Math.min(p.geometry.drawRange.count, n);
    if (cur === target) continue;
    const step = (target - cur) * LOD_EASE;
    const next = Math.abs(target - cur) < 64 ? target : Math.round(cur + step);
    p.geometry.setDrawRange(0, next);
    moving = true;
  }
  return moving;   // true while some chunk is still easing: keep rendering
}
const RAMP = [[0.18, 0.2, 0.45], [0.13, 0.55, 0.6], [0.55, 0.78, 0.35], [0.98, 0.85, 0.3], [0.85, 0.35, 0.2]];
function ramp(t) {
  t = Math.min(Math.max(t, 0), 1) * (RAMP.length - 1);
  const k = Math.min(Math.floor(t), RAMP.length - 2), f = t - k, a = RAMP[k], b = RAMP[k + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
// Point cloud colours: by layer (config.json colours, with a legend), or by height / ground-other / intensity. The clicked
// object is highlighted in every colouring.
const HILITE = new THREE.Color(cfg.linked?.highlight ?? "#22d3ee");
const layerColor = (name) => new THREE.Color(cfg.layers[name]?.color ?? "#888888");
// "object" (?color=object, for checking the grouping): one random colour per object, the non-objects dim grey
const NOT_OBJECTS = new Set(["Terrain", "_other", "Street_furniture"]);
const objCols = [];
function objColor(k) {
  if (objCols[k]) return objCols[k];
  if (NOT_OBJECTS.has(lidar.objNames[k])) return (objCols[k] = [0.22, 0.22, 0.22]);
  // the parts of one entity (building) share a colour
  const ent = lidar.objEntity[k], key = ent >= 0 ? 1e6 + ent : k;
  let h = (key * 2654435761) >>> 0; h ^= h >>> 15;
  const c = new THREE.Color().setHSL((h % 360) / 360, 0.75, 0.45 + ((h >>> 9) % 20) / 100);
  return (objCols[k] = [c.r, c.g, c.b]);
}
function paintCloud(how = lidar.how) {
  lidar.how = how;
  const hi = [HILITE.r, HILITE.g, HILITE.b], mask = lidar.selMask;
  // the selection lights the clicked object, or all objects of its entity (a whole building)
  mask.fill(0);
  for (const s of selection) for (const k of s.objs) mask[k] = 1;   // all selected objects (shift + click adds)
  for (const part of lidar.parts) {
    const { zs, cls, inten, ob, col, n } = part, b = layerColor(part.name), base = [b.r, b.g, b.b];
    for (let i = 0; i < n; i++) {
      let c;
      if (mask[ob[i]]) c = hi;
      else if (how === "layer") c = base;
      else if (how === "height") c = ramp((zs[i] - 78) / 60);
      else if (how === "object") c = objColor(ob[i]);
      else if (how === "class") c = cls[i] === 2 ? [0.72, 0.6, 0.42] : zs[i] > 140 ? [0.55, 0.58, 0.62] : [0.3, 0.52, 0.36];
      else { const v = 0.15 + (inten[i] / 255) * 0.85; c = [v, v, v]; }
      col.set(c, 3 * i);
    }
  }
  for (const p of lidarGroup.children) p.geometry.attributes.color.needsUpdate = true;
  const first = !$("#lidarOpts button.on");
  document.querySelectorAll("#lidarOpts button").forEach((b) => b.classList.toggle("on", b.dataset.c === how));
  moveThumb(first, "#lidarOpts");
  document.body.classList.toggle("linked", mode === "cloud" && how === "layer");   // layer legend swatches
  invalidate();
}
document.querySelectorAll("#lidarOpts button").forEach((b) => (b.onclick = () => paintCloud(b.dataset.c)));

// ---------- modes ----------
let busy = false;
// a segmented control's thumb slides under its selected button (no animation for the first placement);
// used by Mode (#modes) and Color (#lidarOpts)
function moveThumb(instant, sel = "#modes") {
  const th = $(`${sel} .thumb`), on = $(`${sel} button.on`);
  if (th && on && !on.offsetWidth) return;   // section hidden or folded: placed when shown
  if (!th || !on) return;
  th.classList.toggle("instant", !!instant);
  th.style.width = `${on.offsetWidth}px`;
  th.style.transform = `translateX(${on.offsetLeft}px)`;
  if (instant) requestAnimationFrame(() => th.classList.remove("instant"));
}
addEventListener("resize", () => { moveThumb(true); moveThumb(true, "#lidarOpts"); });
$("#modes").closest("details")?.addEventListener("toggle", () => moveThumb(true));   // re-measure after unfolding
$("#colorSec").addEventListener("toggle", () => moveThumb(true, "#lidarOpts"));
// one mode, "cloud" (the LiDAR points, coloured by layer / height / class / intensity); the mode machinery stays for
// later modes (e.g. a potential field). The Mode section is hidden while there is only one.
// The old names still work (config.json defaultMode, links): "linked" = cloud by layer, "lidar" = cloud by height.
const OLD_MODES = { linked: "layer", lidar: "height" };
async function setMode(m) {
  let how = null;
  if (m in OLD_MODES) { how = OLD_MODES[m]; m = "cloud"; }
  if (busy || (m === mode && !how)) return;
  busy = true;
  // the thumb slides at once, even while the point cloud is still loading
  document.querySelectorAll("#modes button").forEach((b) => { b.disabled = true; b.classList.toggle("on", b.dataset.mode === m); });
  moveThumb(mode === null);
  if (m === "cloud" && !lidar) await loadLidar();
  const prev = mode;
  mode = m;
  if (prev !== m) hideInfo();  // also clears any highlight
  if (m === "cloud") paintCloud(how || lidar.how);
  else document.body.classList.remove("linked");
  applyVisibility();
  document.querySelectorAll("#modes button").forEach((b) => { b.disabled = false; b.classList.toggle("on", b.dataset.mode === m); });
  layerCounts();
  glassAt = -1e9;   // the picture behind the panels changes completely: pick light / dark glass again right away
  $("#colorSec").hidden = m !== "cloud";
  moveThumb(true, "#lidarOpts");   // measured now that the section shows
  $("#disp").hidden = m !== "cloud";           // the point settings are for the cloud; Units stay in both modes
  syncDisplay();
  busy = false;
}
document.querySelectorAll("#modes button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

// ---------- views ----------
// A view change orbits around the target instead of sliding the camera along a straight line: distance (log scale),
// tilt and heading ease separately, heading the short way round. A straight slide passes almost exactly above the target
// on the way to a top view, where the heading is undefined and the picture twists in the last frames. Damping is off
// during the move, so leftover drag momentum cannot add a jolt.
let tween = null;
const _off = new THREE.Vector3(), _sph = new THREE.Spherical();
const sphOf = (pos, tgt) => { _sph.setFromVector3(_off.subVectors(pos, tgt)); return { r: _sph.radius, phi: Math.max(_sph.phi, 0.001), th: _sph.theta }; };
function goTo(v) {
  const q1 = new THREE.Vector3().fromArray(v.target), a = sphOf(camera.position, controls.target);
  const b = sphOf(new THREE.Vector3().fromArray(v.position), q1);
  let dth = b.th - a.th; dth = Math.atan2(Math.sin(dth), Math.cos(dth));   // short way round
  tween = { t0: performance.now(), dur: 1100, q0: controls.target.clone(), q1, a, b: { ...b, th: a.th + dth } };
  controls.enableDamping = false;
}
function stepTween(now) {
  const t = Math.min((now - tween.t0) / tween.dur, 1), e = t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;   // ease in-out
  const { a, b } = tween;
  controls.target.lerpVectors(tween.q0, tween.q1, e);
  _sph.set(Math.exp(Math.log(a.r) + (Math.log(b.r) - Math.log(a.r)) * e), a.phi + (b.phi - a.phi) * e, a.th + (b.th - a.th) * e);
  camera.position.copy(controls.target).add(_off.setFromSpherical(_sph));
  camera.lookAt(controls.target);
  if (t === 1) { tween = null; controls.enableDamping = true; }
}
// ---------- Google Earth camera <-> this view (for checking the grouping side by side; user, 2026-10-08) ----------
// A Google Earth web URL holds its camera as @lat,lon,<alt>a,<range>d,<fov>y,<heading>h,<tilt>t: the point looked at
// (WGS84, metres above sea level ~ NAVD88), the distance to it, the horizontal field of view, the heading (from true
// north) and the tilt (0 = straight down). ?earth=<that URL> opens the same view here; y1cam.earthUrl() gives the
// Earth URL of the current view. The site frame is UTM 11N from (E 384580, N 3768520), so headings are turned by the
// meridian convergence.
const UTM0 = [384580, 3768520];
function utm11(lat, lon) {      // WGS84 -> UTM zone 11N (Krueger series, mm level), plus the convergence (rad)
  const a = 6378137, f = 1 / 298.257223563, k0 = 0.9996, n = f / (2 - f), A = a / (1 + n) * (1 + n * n / 4 + n ** 4 / 64);
  const al = [n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16, 13 * n * n / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240];
  const phi = lat * Math.PI / 180, dl = (lon + 117) * Math.PI / 180, e2 = 2 * Math.sqrt(n) / (1 + n);
  const t = Math.sinh(Math.atanh(Math.sin(phi)) - e2 * Math.atanh(e2 * Math.sin(phi)));
  const xi = Math.atan2(t, Math.cos(dl)), eta = Math.atanh(Math.sin(dl) / Math.sqrt(1 + t * t));
  let E = eta, N = xi;
  for (let j = 1; j <= 3; j++) { E += al[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta); N += al[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta); }
  return { E: 500000 + k0 * A * E, N: k0 * A * N, gamma: Math.atan(Math.tan(dl) * Math.sin(phi)) };
}
function fromUtm11(E, N) {      // inverse by two Newton steps on utm11 (enough for a camera)
  let lat = 34.05, lon = -118.25;
  for (let k = 0; k < 4; k++) {
    const u = utm11(lat, lon), d = 1e-5, ux = utm11(lat, lon + d), uy = utm11(lat + d, lon);
    const j11 = (ux.E - u.E) / d, j12 = (uy.E - u.E) / d, j21 = (ux.N - u.N) / d, j22 = (uy.N - u.N) / d, det = j11 * j22 - j12 * j21;
    const dE = E - u.E, dN = N - u.N;
    lon += (j22 * dE - j12 * dN) / det; lat += (-j21 * dE + j11 * dN) / det;
  }
  return [lat, lon];
}
function setEarthView(url) {
  const m = /@(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)a,([\d.]+)d,([\d.]+)y,(-?[\d.]+)h,([\d.]+)t/.exec(url);
  if (!m) return false;
  const [lat, lon, alt, d, fov, hd, tl] = m.slice(1).map(Number);
  const u = utm11(lat, lon), h = hd * Math.PI / 180 - u.gamma, t = Math.max(tl, 0.05) * Math.PI / 180;
  const tx = u.E - UTM0[0], tz = -(u.N - UTM0[1]);
  controls.target.set(tx, alt, tz);
  camera.position.set(tx - d * Math.sin(t) * Math.sin(h), alt + d * Math.cos(t), tz + d * Math.sin(t) * Math.cos(h));
  camera.fov = 2 * Math.atan(Math.tan(fov * Math.PI / 360) / camera.aspect) * 180 / Math.PI;   // Earth's fov is horizontal
  camera.updateProjectionMatrix(); controls.update(); invalidate();
  return true;
}
function earthUrl() {
  const q = controls.target, off = camera.position.clone().sub(q), d = off.length();
  const [lat, lon] = fromUtm11(q.x + UTM0[0], -q.z + UTM0[1]), g = utm11(lat, lon).gamma;
  const t = Math.acos(off.y / d), h = Math.atan2(-off.x, off.z) + g;
  return `https://earth.google.com/web/@${lat.toFixed(6)},${lon.toFixed(6)},${q.y.toFixed(1)}a,${d.toFixed(1)}d,${(2 * Math.atan(Math.tan(camera.fov * Math.PI / 360) * camera.aspect) * 180 / Math.PI).toFixed(0)}y,`
    + `${((h * 180 / Math.PI + 360) % 360).toFixed(2)}h,${(t * 180 / Math.PI).toFixed(2)}t,0r`;
}
window.y1cam = { setEarthView, earthUrl, current: () => ({ position: camera.position.toArray(), target: controls.target.toArray(), fov: camera.fov }) };
// views from config.json, plus views saved in this browser (with a "−" to delete them)
const SAVED_KEY = "y1-viewer-views";
const loadSaved = () => { try { return JSON.parse(localStorage.getItem(SAVED_KEY)) || []; } catch { return []; } };
const storeSaved = (list) => { try { localStorage.setItem(SAVED_KEY, JSON.stringify(list)); } catch { /* private mode: lives until reload */ } };
let savedViews = loadSaved();
function renderViews() {
  $("#views").innerHTML = "";
  const add = (v, saved, k) => {
    const b = document.createElement("button");
    b.className = saved ? "view saved" : "view";
    b.textContent = v.name;
    b.onclick = () => goTo(v);
    if (saved) {
      const x = document.createElement("span");
      x.className = "del"; x.textContent = "−"; x.title = `Delete the view “${v.name}”`;
      x.onclick = (e) => { e.stopPropagation(); savedViews.splice(k, 1); storeSaved(savedViews); renderViews(); };
      b.append(x);
    }
    $("#views").append(b);
  };
  cfg.views.forEach((v) => add(v, false));
  savedViews.forEach((v, k) => add(v, true, k));
  const s = document.createElement("button");
  s.className = "view ghost"; s.textContent = "+ Save view"; s.title = "Save the current camera as a view (kept in this browser)";
  s.onclick = () => {
    const box = document.createElement("span");
    box.className = "saveview";
    box.innerHTML = `<input type="text" maxlength="24" value="View ${savedViews.length + 1}"><button>Save</button>`;
    s.replaceWith(box);
    const inp = box.querySelector("input"), ok = () => {
      const name = inp.value.trim() || `View ${savedViews.length + 1}`;
      savedViews.push({ name, position: camera.position.toArray().map((x) => +x.toFixed(2)), target: controls.target.toArray().map((x) => +x.toFixed(2)) });
      storeSaved(savedViews); renderViews();
    };
    inp.onkeydown = (e) => { if (e.key === "Enter") ok(); if (e.key === "Escape") renderViews(); };
    box.querySelector("button").onclick = ok;
    inp.focus(); inp.select();
  };
  $("#views").append(s);
}
renderViews();

// ---------- population: a modeled day, one point per person (js/population.js), loaded on first use ----------
let pop = null;
const PICK_PX = 6;   // a click or hover this close to a person (screen px) means the person
// hover with Alt held: the person an Alt + click would select is drawn bigger and the cursor turns into a pointer
let hoverAt = null;
renderer.domElement.addEventListener("pointermove", (e) => {
  if (!pop?.visible || e.buttons) return;
  if (!hoverAt) requestAnimationFrame(() => {
    const i = hoverAt.alt ? pop.nearest(hoverAt.x, hoverAt.y, PICK_PX) : -1;
    pop.hover(i);
    renderer.domElement.style.cursor = i >= 0 ? "pointer" : "";
    hoverAt = null; invalidate();
  });
  hoverAt = { x: e.clientX, y: e.clientY, alt: e.altKey };
});
// pressing / releasing Alt with the mouse still: show / hide the marker at once
for (const ev of ["keydown", "keyup"]) addEventListener(ev, (e) => {
  if (e.key !== "Alt" || !pop?.visible || !lastHover) return;
  e.preventDefault();
  const i = ev === "keydown" ? pop.nearest(lastHover.x, lastHover.y, PICK_PX) : -1;
  pop.hover(i); renderer.domElement.style.cursor = i >= 0 ? "pointer" : ""; invalidate();
});
let lastHover = null;
renderer.domElement.addEventListener("pointermove", (e) => { lastHover = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener("pointerleave", () => { pop?.hover(-1); renderer.domElement.style.cursor = ""; invalidate(); });
$("#popOn").onchange = async (e) => {
  const on = e.target.checked;
  if (on && !pop) {
    e.target.disabled = true;
    status("Loading population…");
    const { createPopulation } = await import("./population.js");
    pop = await createPopulation({ cfg, scene, camera, renderer, layers, thinning: lidarMeta.thinning, onInfo: personTag });
    status("");
    e.target.disabled = false;
  }
  $("#popBox").hidden = !on;
  pop?.setVisible(on);
  setWhiteCloud(on && $("#popWhite").checked);
  if (!on) for (const s of [...selection]) if (s.key.startsWith("pop:")) deselect(s.key);
  invalidate();
};
$("#popWhite").onchange = (e) => setWhiteCloud(e.target.checked && $("#popOn").checked);
// its own controls (time, play, day, attendance ...) change the picture: draw again
for (const ev of ["input", "change", "click"]) $("#popSec").addEventListener(ev, () => invalidate());
// a clicked person's modeled day (population.js story()) as a floating tag that follows them
let popSelecting = false;
function personTag(html, pos) {
  const d = document.createElement("div"); d.innerHTML = html;
  const h2 = d.querySelector("h2"), num = h2?.querySelector("span")?.textContent || "";
  const title = (h2?.firstChild?.textContent || "Person").trim();
  const rows = [...d.querySelectorAll("tr")].map((tr) => [...tr.children].map((c) => c.textContent));
  const day = d.querySelector(".label")?.textContent || "";
  for (const t of (d.querySelector(".trips")?.innerHTML || "").split("<br>").filter(Boolean)) {
    const x = document.createElement("div"); x.innerHTML = t;
    const [time, ...rest] = x.textContent.split(" "); rows.push([time, rest.join(" ")]);
  }
  const note = d.querySelector(".note")?.textContent || "";
  popSelecting = true;
  select(`pop:${num}`, { centre: pos, topY: pos.y, height: 0 }, () => tagHTML(`Modeled person ${num}`, title, day, rows, note), [], false);
  popSelecting = false;
}

// ---------- click for details: a design mesh, else the LiDAR point under the cursor ----------
const ray = new THREE.Raycaster();
const SKIP_KEYS = new Set(["layer", "name", "scatter5"]);
let down = null;
renderer.domElement.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  ray.setFromCamera(new THREE.Vector2((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1), camera);
  // Alt + click picks the person within PICK_PX on screen (user, 2026-10-09: a plain click is for buildings / points)
  if (pop?.visible && e.altKey) { if (pop.pickIndex(pop.nearest(e.clientX, e.clientY, PICK_PX))) return; }
  const visible = (o) => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
  const add = e.shiftKey;     // shift + click: add to / take out of the selection
  const layerOf = (o) => { for (; o; o = o.parent) if (o.userData.layer) return o.userData.layer; };
  // over the point cloud only the design meshes are clickable (they are drawn on top of it)
  const hit = ray.intersectObject(model, true).find((h) => visible(h.object) && (mode !== "cloud" || designLayers.has(layerOf(h.object))));
  if (mode === "cloud" && !hit) return pickLidar();
  if (!hit) return add ? undefined : hideInfo();
  let node = hit.object;
  while (node && !node.userData.layer) node = node.parent;
  node = node || hit.object;
  const en = entityOfName.get(node.name), a = anchorOfNode(node) || pointAnchor(hit.point);
  if (en) return select(`m:${en.id}`, a, entityTag(en), [], add);
  select(`m:${node.uuid}`, a, objectTag(node, hit.point, null), [], add);

  // LiDAR: the clicked point's object label -> its entity or object; highlight all its points
  function pickLidar() {
    ray.params.Points.threshold = 0.6;
    const hit = ray.intersectObjects(lidarGroup.children.filter((p) => p.visible), false)[0];
    if (!hit) return add ? undefined : hideInfo();
    const id = hit.object.userData.part.ob[hit.index], name = lidar.objNames[id];
    const node = model.getObjectByName(name) || { name: name === "_other" ? "Unassigned LiDAR points" : name,
                                                  userData: { layer: lidar.objLayers[id] } };
    // layers with "highlight": false in config.json (e.g. Terrain) show their info but are not lit
    const lit = name !== "_other" && cfg.layers[lidar.objLayers[id]]?.highlight !== false;
    const ent = lidar.objEntity[id];
    if (ent >= 0) {
      const objs = lidar.entityObjs.get(ent);
      return select(`e:${ent}`, anchorOf(new Set(objs)) || pointAnchor(hit.point), entityTag(ENTITIES.entities[ent]), objs, add);
    }
    if (lit && !NOT_OBJECTS.has(name)) {
      const set = new Set([id]);
      return select(`o:${id}`, anchorOf(set) || pointAnchor(hit.point), objectTag(node, hit.point, set), [id], add);
    }
    select(`p:${hit.point.toArray().map((v) => v.toFixed(1))}`, pointAnchor(hit.point), objectTag(node, hit.point, null), [], add);
  }
});
function fmt(v) { return typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : String(v); }
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---------- floating tags (user, 2026-10-08, after reference images) ----------
// Each selected object gets a label with all its information, joined by a leader line to the object's centre. The line
// starts at the centre (projected every frame) and ends where the label sits: up and to the right by default, pulled in so
// the label is always fully inside the window (and clear of the left panel and of the other labels). Drawn in screen space:
// an SVG overlay for the lines, HTML for the labels. Shift + click adds / removes objects; a plain click selects one.
const svgNS = "http://www.w3.org/2000/svg";
const leadSvg = document.createElementNS(svgNS, "svg"); leadSvg.id = "leads"; document.body.append(leadSvg);
const _tv = new THREE.Vector3();
const selection = [];     // { key, objs, a (anchor), build, el, line }
let detailsOpen = false;   // Details start closed on every new label (user, 2026-10-08: not remembered)

// centre, top, height above ground and plan radius of a set of LiDAR objects
function anchorOf(objSet) {
  let maxY = -1e9, minY = 1e9, sx = 0, sz = 0, n = 0;
  for (const p of lidar.parts) for (let i = 0; i < p.n; i++) if (objSet.has(p.ob[i])) {
    const y = p.pos[3 * i + 1]; if (y > maxY) maxY = y; if (y < minY) minY = y;
    sx += p.pos[3 * i]; sz += p.pos[3 * i + 2]; n++;
  }
  if (!n) return null;
  // height = height above ground of the highest points (LiDAR hag): right on slopes too (Angels Flight)
  let hagTop = -1e9;
  for (const p of lidar.parts) if (p.hag) for (let i = 0; i < p.n; i++) if (objSet.has(p.ob[i]) && p.pos[3 * i + 1] > maxY - 1.5) hagTop = Math.max(hagTop, p.hag[i] * 0.1);
  const height = hagTop > -1e8 ? hagTop : maxY - minY;
  return { centre: new THREE.Vector3(sx / n, (Math.max(minY, maxY - height) + maxY) / 2, sz / n), topY: maxY, height };
}
function anchorOfNode(node) {
  const bb = new THREE.Box3().setFromObject(node); if (bb.isEmpty()) return null;
  return { centre: bb.getCenter(new THREE.Vector3()), topY: bb.max.y, height: bb.max.y - bb.min.y };
}
function tagHTML(kicker, title, sub, rows, note) {
  return `<i class="x" title="Close">×</i><div class="k">${esc(kicker)}</div><div class="t">${esc(title)}</div>`
    + (sub ? `<div class="a">${esc(sub)}</div>` : "")
    + (rows.length || note ? `<details class="dd"${detailsOpen ? " open" : ""}><summary>Details</summary>`
      + `<dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`
      + (note ? `<p class="nt">${esc(note)}</p>` : "") + "</details>" : "");
}
function fillTag(s) {
  s.el.innerHTML = s.build(s.a);
  s.el.querySelector(".x").onclick = (ev) => { ev.stopPropagation(); deselect(s.key); };
  const dd = s.el.querySelector(".dd");
  if (dd) dd.ontoggle = () => {
    invalidate();   // the label grows / shrinks: place it again
  };
}
function select(key, a, build, objs, add) {
  if (!add) clearSelection();
  const old = selection.find((s) => s.key === key);
  if (old) { if (add) deselect(key); return; }            // shift + click on a selected object: take it out
  const el = document.createElement("div"); el.className = "tag"; document.body.append(el);
  const line = document.createElementNS(svgNS, "line"); leadSvg.append(line);
  const s = { key, a, build, objs, el, line };
  fillTag(s); selection.push(s);
  if (lidar && mode === "cloud") paintCloud();
  invalidate(); wake();
}
// a tag and its line fade out over 0.5 s, then go (user, 2026-10-10: Esc should not make them vanish at once)
function fadeAway(s) {
  for (const n of [s.el, s.line]) { n.style.transition = "opacity .5s ease"; n.style.opacity = "0"; n.style.pointerEvents = "none"; }
  setTimeout(() => { s.el.remove(); s.line.remove(); }, 500);
}
function deselect(key) {
  const i = selection.findIndex((s) => s.key === key); if (i < 0) return;
  const [s] = selection.splice(i, 1); fadeAway(s);
  if (s.key.startsWith("pop:") && !popSelecting) pop?.clearSelection();
  if (lidar && mode === "cloud") paintCloud();
  invalidate();
}
function clearSelection() {
  for (const s of selection.splice(0)) { fadeAway(s); if (s.key.startsWith("pop:") && !popSelecting) pop?.clearSelection(); }
  if (lidar && mode === "cloud") paintCloud();
  invalidate();
}
function refreshTags() { for (const s of selection) fillTag(s); invalidate(); }
// after every render: project each centre, place its label inside the window, draw its line
function updateTags() {
  const W = innerWidth, H = innerHeight, M = 16, placed = [];
  const ui = $("#ui").getBoundingClientRect(), uiOn = ui.width > 0;   // also while it is faded out: labels do not jump when it returns
  leadSvg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  for (const s of selection) {
    _tv.copy(s.a.centre).project(camera);
    const sx = ((_tv.x + 1) / 2) * W, sy = ((1 - _tv.y) / 2) * H;
    const off = _tv.z > 1 || sx < -40 || sx > W + 40 || sy < -40 || sy > H + 40;    // its centre is not in view
    s.el.style.display = off ? "none" : ""; s.line.style.display = off ? "none" : "";
    if (off) continue;
    const w = s.el.offsetWidth, h = s.el.offsetHeight;
    // side (user, 2026-10-08): objects on the right half of the screen get their label up-left, on the left half up-right,
    // so labels spread outwards instead of all piling up on one side. The line ends at the label's lower corner on the
    // object's side (where the accent line is). bx, by = the label's left edge and bottom.
    const overlaps = (bx, by) => placed.find((r) => bx < r.x + r.w + 8 && bx + w + 8 > r.x && by - h < r.y + 8 && by + 8 > r.y - r.h);
    const place = (left) => {
      let bx = left ? sx - 70 - w : sx + 70, by = sy - 90;
      const fit = () => {
        bx = Math.min(Math.max(bx, M), W - M - w); by = Math.min(Math.max(by, M + h), H - 36);
        if (uiOn && bx < ui.right + 12 && by - h < ui.bottom && by > ui.top) bx = ui.right + 12;   // clear of the left panel
        bx = Math.min(bx, W - M - w);
      };
      fit();
      for (let k = 0; k < 8; k++) {   // clear of the labels placed before (shift + click selections)
        const hit = overlaps(bx, by); if (!hit) break;
        by = hit.y - hit.h - 10 >= M + h ? hit.y - hit.h - 10 : hit.y + h + 10; fit();
      }
      return [bx, by];
    };
    let left = sx > W / 2;
    let [bx, by] = place(left);
    if (overlaps(bx, by)) { const alt = place(!left); if (!overlaps(...alt)) { left = !left; [bx, by] = alt; } }
    placed.push({ x: bx, y: by, w, h });
    s.el.classList.toggle("left", left);
    s.el.style.transform = `translate(${bx}px, ${by}px) translateY(-100%)`;
    const ex = left ? bx + w : bx;
    s.line.setAttribute("x1", sx); s.line.setAttribute("y1", sy); s.line.setAttribute("x2", ex); s.line.setAttribute("y2", by);
  }
}
// a plain object (tree, car, wall ...), or a point of the ground / unassigned
function objectTag(node, point, objSet) {
  const L = layers.get(node.userData.layer);
  return (a) => {
    const rows = [];
    if (a.height > 0.5) rows.push(["Height", len(a.height)]);
    rows.push(["Elevation", len(objSet || node.isObject3D ? a.topY : point.y)]);
    for (const [k, v] of Object.entries(node.userData)) {
      if (SKIP_KEYS.has(k) || v === null || typeof v === "object") continue;
      if (/_m$/.test(k) && typeof v === "number") rows.push([k.replace(/_m$/, "").replace(/_/g, " "), len(v, 2)]);
      else rows.push([k.replace(/_/g, " "), fmt(v)]);
    }
    return tagHTML(L?.cfg.label || node.userData.layer || "", node.name, "", rows);
  };
}
// an entity (a whole building / landmark). Use = our own description (typed by hand after checking Google Earth / Maps);
// for automatic entities the assessor's class. "Land use (assessor)" only when it says more than Use.
function entityTag(e) {
  return (a) => {
    const pc = e.parcel;
    const use = e.status === "auto" ? (pc?.use || e.use) : e.use;
    const kicker = [use, pc?.year_built].filter(Boolean).join(" · ");
    const rows = [["Height", len(a.height)], ["Roof elevation", len(a.topY)]];
    if (pc?.units) rows.push(["Units", pc.units]);
    if (pc?.use && e.status !== "auto" && pc.use.toLowerCase() !== String(use).toLowerCase()) rows.push(["Land use (assessor)", pc.use]);
    rows.push(["Source", e.status === "auto" ? "LA County Assessor parcel (automatic, not checked by hand)"
      : `Checked in Google Earth / Maps${e.confidence ? `, ${e.confidence} confidence` : ""}${pc ? "; LA County Assessor" : ""}`]);
    return tagHTML(kicker || "Building", e.name, e.address || "", rows, e.note);
  };
}
function pointAnchor(point) { return { centre: point.clone(), topY: point.y, height: 0 }; }
function hideInfo() { clearSelection(); }

// ---------- misc ui ----------
function collapse(on) { $("#ui").classList.toggle("collapsed", on); $("#toggle").textContent = on ? "+" : "–"; }
$("#toggle").onclick = () => collapse(!$("#ui").classList.contains("collapsed"));
// the panel's scrollbar shows while scrolling and fades out (CSS) once it has been still for a moment
let sbTimer = 0;
$("#ui").addEventListener("scroll", () => {
  $("#ui").classList.add("scrolling");
  clearTimeout(sbTimer); sbTimer = setTimeout(() => $("#ui").classList.remove("scrolling"), 400);
}, { passive: true });
if (innerWidth < 560) collapse(true);  // phones: start with the panel folded
addEventListener("resize", () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); invalidate(); });

// ---------- Display settings (panel section; values start from config.json "lidar", URL ?px= ?keep= ?cap= ?size=) ----------
// Each row: key, label, slider range, read, write (null = applies on reload), tooltip. Add new settings here.
const DISPLAY = [
  ["px", "Point spacing (px)", 0.4, 4, 0.1, () => LOD_PX, (v) => { LOD_PX = v; }, "on-screen gap the LiDAR LOD aims for: smaller = denser, heavier"],
  ["keep", "Density contrast", 0, 1, 0.05, () => LOD_KEEP, null, "how much of the LiDAR's dense-to-sparse fade survives on screen (0 flat, 1 as in the data); applies on reload"],
  ["cap", "Point cap (millions)", 1, 15, 0.5, () => LOD_CAP / 1e6, (v) => { LOD_CAP = v * 1e6; }, "most LiDAR points drawn at once"],
  ["size", "Point size", 0.05, 1.5, 0.05, () => lidar?.material.size ?? cfg.lidar.size, (v) => { if (lidar) lidar.material.size = v; }, "disk size of each LiDAR point (default = the average LiDAR spacing)"],
];
const DISPLAY_DEFAULT = { px: CFG_LIDAR.lodPixels ?? 1.2, keep: CFG_LIDAR.lodKeepDensity ?? 0.8, cap: (CFG_LIDAR.pointCap ?? 6e6) / 1e6, size: CFG_LIDAR.size ?? 0.25 };
const dispVal = {};
$("#disp").innerHTML = DISPLAY.map(([k, label, lo, hi, st, , , tip]) =>
  `<div class="set" title="${tip}"><div class="top"><span id="dl_${k}">${label}</span><span class="v" id="dv_${k}"></span></div>`
  + `<input id="dr_${k}" type="range" min="${lo}" max="${hi}" step="${st}"></div>`).join("")
  + '<div class="row"><button id="disp_default" class="ghost" title="Back to the defaults in config.json">Reset</button>'
  + '<button id="disp_apply" class="ghost" title="Reload with these values (needed for Density contrast)">Apply</button></div>'

  + '<div class="note" id="disp_note">Spacing, cap and size change live; contrast needs Apply.</div>';
function setDisplay(k, v) {
  dispVal[k] = v; const r = $(`#dr_${k}`); r.value = v;
  $(`#dv_${k}`).textContent = (k === "size" ? toUnit(+v) : +v).toFixed(2);   // lengths in the display units
  r.style.setProperty("--p", `${(100 * (r.value - r.min)) / (r.max - r.min)}%`);   // filled part of the track
}
function syncDisplay() { for (const [k, , , , , get] of DISPLAY) setDisplay(k, +get()); }
for (const [k, , , , , , set] of DISPLAY) {
  $(`#dr_${k}`).oninput = (e) => { setDisplay(k, +e.target.value); if (set) { set(dispVal[k]); lodEasing = true; invalidate(); } };
}
syncDisplay();
const reloadWith = (vals) => {
  const u = new URLSearchParams(location.search);
  for (const k of ["px", "keep", "cap", "size"]) {
    if (vals && vals[k] !== DISPLAY_DEFAULT[k]) u.set(k, k === "cap" ? Math.round(vals[k] * 1e6) : vals[k]); else u.delete(k);
  }
  location.search = u.toString();
};
$("#disp_apply").onclick = () => reloadWith(dispVal);
$("#disp_default").onclick = () => {
  if (Math.abs(LOD_KEEP - DISPLAY_DEFAULT.keep) > 1e-9) return reloadWith(null);   // contrast is baked in at load: reload
  for (const [k, , , , , , set] of DISPLAY) { setDisplay(k, DISPLAY_DEFAULT[k]); if (set) set(DISPLAY_DEFAULT[k]); }
  const u = new URLSearchParams(location.search); ["px", "keep", "cap", "size"].forEach((k) => u.delete(k));
  history.replaceState(null, "", u.toString() ? "?" + u : location.pathname);
  lodEasing = true; invalidate();
  $("#disp_note").textContent = "Back to the defaults in config.json.";
};
// ---------- layer counts: objects per layer in the point cloud (buildings counted as entities) ----------
// Point cloud: objects of the layer in the cloud, buildings counted as entities (a building of several parts = 1);
// Terrain / Other / Street furniture are not objects -> no number. Mesh: objects of the layer in the model.
function layerCounts() {
  const counts = new Map();
  if (mode === "cloud" && lidar) {
    const seen = new Map();
    lidar.objNames.forEach((nm, k) => {
      if (NOT_OBJECTS.has(nm) || !lidar.objCount[k]) return;
      const lay = lidar.objLayers[k], ent = lidar.objEntity[k];
      const key = ent >= 0 && /^Buildings/.test(lay) ? `e${ent}` : `o${k}`;
      if (!seen.has(lay)) seen.set(lay, new Set());
      seen.get(lay).add(key);
    });
    for (const [lay, s] of seen) counts.set(lay, s.size);
  } else {
    for (const L of ordered) if (L.objects.length) counts.set(L.name, L.objects.length);
  }
  for (const L of ordered) if (L.countEl) L.countEl.textContent = counts.has(L.name) ? counts.get(L.name).toLocaleString() : "";
}

// ---------- units switch (m / ft): segmented control like Mode / Color, kept in this browser ----------
function setUnits(u, instant = false) {
  units = u;
  try { localStorage.setItem("y1-viewer-units", u); } catch { /* private mode */ }
  document.querySelectorAll("#units button").forEach((b) => b.classList.toggle("on", b.dataset.u === u));
  moveThumb(instant, "#units");
  const dl = $("#dl_size"); if (dl) dl.textContent = `Point size (${u})`;
  if (dispVal.size !== undefined) setDisplay("size", dispVal.size);
  cloudTip();
  refreshTags();
}
document.querySelectorAll("#units button").forEach((b) => (b.onclick = () => setUnits(b.dataset.u)));
$("#dispSec").addEventListener("toggle", () => moveThumb(true, "#units"));
addEventListener("resize", () => moveThumb(true, "#units"));
setUnits(units, true);

// ---------- idle: after 10 s without input the panels and the hint fade out (CSS body.idle), any input brings them back.
// Not while the pointer is over a panel or a text field has the focus (user, 2026-10-08) ----------
const IDLE_MS = 10000;   // 10 s (user, 2026-10-09; was 5 s)
let idleTimer = 0;
const overPanel = () => document.querySelector("#ui:hover, #info:hover") !== null;
addEventListener("keydown", (e) => { if (e.key === "Escape" && !typing()) clearSelection(); });
const typing = () => /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "") && document.activeElement.type !== "range";
function wake(ms = IDLE_MS) {
  if (typeof ms !== "number") ms = IDLE_MS;    // called as an event listener
  document.body.classList.remove("idle");
  if (typeof wakeTags === "function") wakeTags();
  clearTimeout(idleTimer);
  idleTimer = setTimeout(function sleep() {
    if (overPanel() || typing()) { idleTimer = setTimeout(sleep, 1000); return; }
    document.body.classList.add("idle");
  }, ms);
}
for (const ev of ["pointermove", "pointerdown", "wheel", "keydown", "touchstart", "focusin"]) addEventListener(ev, wake, { passive: true });
// the floating tags fade after 10 s without input (user, 2026-10-08), like the panels
let tagTimer = 0;
function wakeTags() {
  document.body.classList.remove("idle-tags"); clearTimeout(tagTimer);
  tagTimer = setTimeout(function sleep() {
    if (document.querySelector(".tag:hover")) { tagTimer = setTimeout(sleep, 1000); return; }
    document.body.classList.add("idle-tags");
  }, 10000);
}
for (const ev of ["pointermove", "pointerdown", "wheel", "keydown", "touchstart", "focusin"]) addEventListener(ev, wakeTags, { passive: true });
wakeTags();
wake();

await setMode("cloud");
if (urlq.get("earth")) setEarthView(urlq.get("earth"));   // ?earth=<Google Earth URL>: the same camera here
status("");
let lodEasing = true;
// ---------- adaptive glass: light or dark panel depending on what is right behind it ----------
// After a render (the drawing buffer is still valid), read the canvas under each floating element, average its luminance
// and give the element .on-light (bright picture behind: light glass, dark text) or .on-dark. Hysteresis (to light above
// GLASS_HI, back to dark below GLASS_LO, on 0-255) keeps it from flickering; at most every GLASS_EVERY ms, and only once
// the camera has been still for GLASS_SETTLE ms.
const GLASS_HI = 150, GLASS_LO = 110, GLASS_EVERY = 250, GLASS_SETTLE = 200;
const glassEls = ["#ui", "#info", "#hint"].map((q) => $(q));
let glassBuf = new Uint8Array(0);
function adaptGlass(now) {
  // reading pixels back stalls the GPU pipeline (100+ ms frames during a view change), so only when the camera is still
  // ... and not while the population plays (the picture changes every frame; checked again once it stops)
  if (tween || pop?.state.playing || now - lastMove < GLASS_SETTLE || now - glassAt < GLASS_EVERY) { glassPending = true; return; }
  glassAt = now; glassPending = false;
  const gl = renderer.getContext(), cv = renderer.domElement, sx = cv.width / cv.clientWidth, sy = cv.height / cv.clientHeight;
  for (const el of glassEls) {
    if (!el || el.offsetParent === null && getComputedStyle(el).position !== "fixed") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || getComputedStyle(el).display === "none") continue;
    const x = Math.max(0, Math.floor(r.left * sx)), w = Math.min(cv.width - x, Math.ceil(r.width * sx));
    const yTop = Math.max(0, Math.floor(r.top * sy)), h = Math.min(cv.height - yTop, Math.ceil(r.height * sy));
    if (w < 1 || h < 1) continue;
    if (glassBuf.length < w * h * 4) glassBuf = new Uint8Array(w * h * 4);
    gl.readPixels(x, cv.height - yTop - h, w, h, gl.RGBA, gl.UNSIGNED_BYTE, glassBuf);
    let sum = 0, k = 0;
    const step = Math.max(1, Math.floor(Math.sqrt((w * h) / 2000)));   // ~2000 samples per element
    for (let yy = 0; yy < h; yy += step) for (let xx = 0; xx < w; xx += step) {
      const o = 4 * (yy * w + xx);
      sum += 0.2126 * glassBuf[o] + 0.7152 * glassBuf[o + 1] + 0.0722 * glassBuf[o + 2]; k++;
    }
    const lum = sum / k, light = el.classList.contains("on-light"), dark = el.classList.contains("on-dark");
    const toLight = light ? lum > GLASS_LO : dark ? lum > GLASS_HI : lum > (GLASS_HI + GLASS_LO) / 2;
    el.classList.toggle("on-light", toLight); el.classList.toggle("on-dark", !toLight);
  }
}
let glassPending = false;
setInterval(() => { if (glassPending) { dirty = true; } }, GLASS_EVERY);   // re-check once the camera stops
renderer.setAnimationLoop((now) => {
  if (tween) { stepTween(now); dirty = true; lastMove = now; }
  if (controls.update()) { dirty = true; lastMove = now; }   // damping keeps moving the camera after the drag ends
  // LiDAR level of detail: recomputed whenever the view changed or a chunk is still easing to its target
  if (lidar && mode === "cloud" && (dirty || lodEasing)) { lodEasing = updateLod(); if (lodEasing) dirty = true; }
  // the population plays on its own clock: draw while it plays or after one of its settings changed
  if (pop?.visible) { const was = pop.state.dirty; pop.tick(now); if (was || pop.state.playing) dirty = true; }
  if (!dirty) return;
  dirty = false;
  renderer.render(scene, camera);
  updateTags();
  adaptGlass(now);
});
window.__viewer = {
  layers, get mode() { return mode; }, setMode, get lidar() { return lidar; }, get population() { return pop; },
  camera, controls, renderer, lidarGroup, invalidate,   // debugging / performance checks
  // debugging / screenshots: select entities by id, e.g. selectEntities(["E001", "E005"])
  selectEntities(ids) {
    clearSelection();
    for (const id of ids) {
      const i = ENTITIES.entities.findIndex((e) => e.id === id), objs = lidar.entityObjs.get(i);
      if (objs) select(`e:${i}`, anchorOf(new Set(objs)), entityTag(ENTITIES.entities[i]), objs, true);
    }
  },
  // debugging / palette trials: setLayerColors({ Terrain: "#..." }, "#highlight")
  setLayerColors(map, highlight) {
    for (const [k, v] of Object.entries(map)) (cfg.layers[k] ||= {}).color = v;
    if (highlight) HILITE.set(highlight);
    if (lidar && mode === "cloud") paintCloud();
  },
};
