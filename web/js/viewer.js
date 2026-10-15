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
// (2026-10-15, load time) the small files are all asked for at once, then read where they are needed (they used to be
// fetched one after another: ~1.5 s before the point cloud even started)
const ask = (u) => (u ? fetch(u).catch(() => null) : Promise.resolve(null));
const PRE = { entities: ask(cfg.entities), facades: ask(cfg.facades?.meta), designs: ask(cfg.designs), ghosts: ask(cfg.ghosts?.data),
              lidarMeta: ask(cfg.lidar.meta) };
// ---------- display units: every length goes through len() (user, 2026-10-08: m / ft switch in the panel; ft is the
// default, config.json "units" can change it; the data and all files stay in metres) ----------
const FT = 0.3048;
let units = (() => { try { return localStorage.getItem("y1-viewer-units") || cfg.units || "ft"; } catch { return cfg.units || "ft"; } })();
const toUnit = (m) => (units === "ft" ? m / FT : m);
const len = (m, digits = 1) => `${toUnit(m).toFixed(digits)} ${units}`;
// building / landmark entities (which LiDAR objects make up one real building, and what it is): optional
const ENTITIES = await PRE.entities.then((r) => (r?.ok ? r.json() : null)).catch(() => null);
const entityOfName = new Map();
for (const e of ENTITIES?.entities ?? []) for (const p of e.parts) entityOfName.set(p, e);
// Display settings (panel section): ?px= ?keep= ?cap= ?size= override config.json "lidar" for this page only (lodPixels,
// lodKeepDensity, pointCap, size), so settings can be tried before they go into config.json
const urlq = new URLSearchParams(location.search);
// ?seed=N (for checks, 2026-10-14): Math.random becomes a fixed sequence, so two loads draw the same LOD priorities
// and can be compared point by point
if (urlq.has("seed")) { let sd = +urlq.get("seed") || 1; Math.random = () => (sd = (sd * 16807) % 2147483647) / 2147483647; }
// (the ?perf panel, defined here so a click during loading finds it; see perfFrame)
const PERF = urlq.has("perf") ? { acc: {}, n: 0, last: 0, t0: performance.now(), el: null, click: null } : null;
if (PERF) {
  PERF.el = document.createElement("div");
  PERF.el.style.cssText = "position:fixed;left:8px;bottom:28px;z-index:9;font:11px/1.35 ui-monospace,Consolas,monospace;color:#cfe;background:rgba(0,0,0,.6);padding:6px 8px;border-radius:6px;white-space:pre;pointer-events:none";
  document.body.append(PERF.el);
}
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

// ---------- depth of field (user, 2026-10-14: a game-like DOF, option B, in Guided and Free, a switch in the panel) ----------
// The picture is drawn into a target with its depth, then a full-screen pass blurs each pixel by how far it is from the
// focus: the distance from the camera to what it looks at (controls.target: in Guided the shot's subject, in Free the
// point it turns round). Sharp within focusRange of it (a share of the focus distance), blurred towards maxBlurPx in
// front and behind (aperture: how fast). Gathered on a golden-angle disc; a sample only counts where its own blur
// reaches it, so a sharp subject does not bleed into the blurred ground behind it. config.json dof
const DOF = { on: true, aperture: 0.7, focusRange: 0.35, maxBlurPx: 3, ...(cfg.dof || {}) };
if (urlq.has("dof")) DOF.on = urlq.get("dof") !== "0";
const dofTarget = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
dofTarget.depthTexture = new THREE.DepthTexture(1, 1);
const dofQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
  uniforms: { tColor: { value: dofTarget.texture }, tDepth: { value: dofTarget.depthTexture }, texel: { value: new THREE.Vector2() },
              near: { value: camera.near }, far: { value: camera.far }, focus: { value: 500 }, aperture: { value: DOF.aperture },
              range: { value: DOF.focusRange }, maxBlur: { value: DOF.maxBlurPx } },
  vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
  fragmentShader: `#include <packing>
    uniform sampler2D tColor, tDepth; uniform vec2 texel; uniform float near, far, focus, aperture, range, maxBlur;
    varying vec2 vUv;
    float coc(vec2 uv) {   // blur radius in px at uv
      float vz = -perspectiveDepthToViewZ(texture2D(tDepth, uv).x, near, far);
      return clamp(max(abs(vz - focus) - range * focus, 0.0) / vz * aperture, 0.0, 1.0) * maxBlur;
    }
    void main() {
      vec4 c0 = texture2D(tColor, vUv); float r0 = coc(vUv);
      // the picture's depth, so the overlay (people) is still hidden by the buildings; pushed back a hair so a person standing
      // on ground points (the same depth, give or take the copy) still shows
      gl_FragDepth = min(texture2D(tDepth, vUv).x + 4e-6, 1.0);
      if (any(isnan(c0)) || any(isinf(c0))) c0 = vec4(0.0, 0.0, 0.0, 1.0);   // a broken pixel must not spread
      if (r0 < 0.5) { gl_FragColor = c0; } else {
        vec4 sum = c0; float wsum = 1.0;
        for (int i = 0; i < 32; i++) {
          float fi = float(i) + 0.5, r = sqrt(fi / 32.0) * r0, a = fi * 2.39996;
          vec2 uv = vUv + vec2(cos(a), sin(a)) * r * texel;
          vec4 s = texture2D(tColor, uv); float w = smoothstep(r - 1.0, r, coc(uv));
          if (any(isnan(s)) || any(isinf(s))) continue;   // a NaN (e.g. pow of a negative in some shader) would blur into a black smear
          sum += s * w; wsum += w;
        }
        gl_FragColor = sum / wsum;
      }
      #include <colorspace_fragment>
    }`,
  depthTest: true, depthFunc: THREE.AlwaysDepth, depthWrite: true }));   // with the test off, WebGL would not write the depth
const dofScene = new THREE.Scene(), dofCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
dofQuad.frustumCulled = false; dofScene.add(dofQuad);
function dofResize() {
  const v = renderer.getDrawingBufferSize(new THREE.Vector2());
  dofTarget.setSize(v.x, v.y); dofQuad.material.uniforms.texel.value.set(1 / v.x, 1 / v.y);
}
dofResize();
{ const box = document.querySelector("#dofOn");   // the panel switch (Views)
  if (box) { box.checked = DOF.on; box.onchange = () => { DOF.on = box.checked; invalidate(); }; } }
renderer.info.autoReset = false;   // two renders a frame with DOF: the frame's counts are reset once, in the loop
// Layer 1 (OVERLAY): the people, their trails and markers (population.js) are drawn after the pass, sharp, against the
// depth the pass writes back
camera.layers.enable(1);
function renderFrame() {
  if (!DOF.on) { renderer.render(scene, camera); return; }
  const U = dofQuad.material.uniforms, dpr = renderer.getPixelRatio();
  U.focus.value = camera.position.distanceTo(controls.target); U.near.value = camera.near; U.far.value = camera.far;
  U.maxBlur.value = DOF.maxBlurPx * dpr; U.aperture.value = DOF.aperture; U.range.value = DOF.focusRange;
  camera.layers.disable(1);
  renderer.setRenderTarget(dofTarget); renderer.render(scene, camera);
  renderer.setRenderTarget(null); renderer.render(dofScene, dofCam);
  camera.layers.set(1);
  const ac = renderer.autoClear, bg = scene.background;
  renderer.autoClear = false; scene.background = null;
  renderer.render(scene, camera);
  renderer.autoClear = ac; scene.background = bg; camera.layers.enable(0);
}

// ---------- overlays: the design files ----------
const draco = new DRACOLoader().setDecoderPath("https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/");
const model = new THREE.Group();   // everything drawn as geometry over the point cloud
scene.add(model);

// ---------- "white point cloud" (user, 2026-10-09): an option of the population layer; the point cloud fades to white,
// a little transparent, so the people stand out. One shared uniform, eased over --t-out.
// the site's shared durations (CSS --t-feedback / --t-in / --t-out / --t-idle in viewer.html), in ms, for JS animations
const tms = (name) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) * 1000 || 0;
// a change of colour mode cross-fades: the shader mixes the previous colours (color0)
// into the new ones as uColorMix goes 0 -> 1 over --t-out
const COLOR_MIX = { value: 1 };
let mixAnim = 0;
function crossFade() {
  const t0 = performance.now(), dur = tms("--t-out");
  COLOR_MIX.value = 0;
  cancelAnimationFrame(mixAnim);
  const step = (now) => {
    const k = dur ? Math.min((now - t0) / dur, 1) : 1;
    COLOR_MIX.value = k * k * (3 - 2 * k);
    invalidate();
    if (k < 1) mixAnim = requestAnimationFrame(step);
  };
  mixAnim = requestAnimationFrame(step);
}
// the selection is separate from the colours (aSel, paintSelection): a 1-byte mark per point, so selecting does not copy
// or re-upload the colours, and Highlight people leaves the selected object in its highlight colour
const SEL_K = { value: 1 };   // 0 -> 1 over --t-out after each change of selection
let selAnim = 0;
const FOCUS = { value: 0 };
const FOCUS_GREY = { value: cfg.population?.whiteCloud?.white ?? 0.8 }, FOCUS_ALPHA = { value: cfg.population?.whiteCloud?.opacity ?? 0.5 };
const focusMats = [];
function withFocus(shader) {
  shader.uniforms.uFocus = FOCUS; shader.uniforms.uFocusGrey = FOCUS_GREY; shader.uniforms.uFocusAlpha = FOCUS_ALPHA;
  shader.uniforms.uTimeOn = TIME.on; shader.uniforms.uTimeGrey = TIME.grey; shader.uniforms.uTimeAlpha = TIME.alpha;
  // vSel (from pointMaterial's vertex shader): a selected object keeps its highlight under Highlight people
  // vBuild, vGhost (Time module): buildings (white, set in the vertex shader) and the unbuilt towers are not greyed,
  // and the rest goes a darker, fainter grey than for Highlight people, so the buildings stand out
  shader.fragmentShader = "uniform float uFocus, uFocusGrey, uFocusAlpha, uTimeOn, uTimeGrey, uTimeAlpha;\nvarying float vSel, vBuild, vGhost;\n" + shader.fragmentShader.replace("#include <color_fragment>",
    `#include <color_fragment>
  float fk = uFocus * (1.0 - vSel) * (1.0 - vBuild) * (1.0 - vGhost);
  diffuseColor.rgb = mix(diffuseColor.rgb, vec3(mix(uFocusGrey, uTimeGrey, uTimeOn)), fk);
  diffuseColor.a *= mix(1.0, mix(uFocusAlpha, uTimeAlpha, uTimeOn), fk);`);
}
let focusAnim = 0;
function setWhiteCloud(on) {
  const from = FOCUS.value, to = on ? 1 : 0, t0 = performance.now();
  if (on) for (const m of focusMats) if (!m.userData.alwaysTransparent && !m.transparent) { m.transparent = true; m.needsUpdate = true; }
  cancelAnimationFrame(focusAnim);
  const step = (now) => {
    const dur = tms("--t-out"), k = dur ? Math.min((now - t0) / dur, 1) : 1, e = k * k * (3 - 2 * k);
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
  const fm = await (await PRE.facades).json();
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
  const list = await (await PRE.designs).json();
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

// unbuilt schemes on Y-1 (user, 2026-10-13: research into the viewer): each tower as points scattered at random over its
// walls and roof (not coloured by use, no drawn storey lines), as dense as the towers around it; the points join the
// LiDAR when it loads (loadLidar), so they are drawn, thinned and highlighted as every building is. An invisible prism
// per tower answers clicks in the mesh view.
const ghostPts = [];   // { name, base, layer, pos: three.js order }
const ghostYears = new Map();   // unbuilt layer -> [[from, to], ...]: shown with the Time module, in those years
const ghostLabels = [];   // the Time module's labels for the unbuilt towers (updateTimeTags)
try {
  const G = cfg.ghosts, gd = await (await PRE.ghosts).json();
  let seed = G.seed ?? 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);   // the same scatter on every visit
  for (const sc of gd.schemes) (ghostYears.get(sc.layer || "Unbuilt") ?? ghostYears.set(sc.layer || "Unbuilt", []).get(sc.layer || "Unbuilt")).push(sc.years);
  for (const sc of gd.schemes) for (const t of sc.towers) {
    const ring = t.ring;   // [x east, y north], metres
    const pos = [], H = t.top_z - t.base_z;
    // the floor lines of every band: most points gather on them, as on the walls the LiDAR saw and on the estimated
    // facades (synth_facades.py: inBands of the points within bandM of a floor line), so the storeys show without drawn lines
    const floors = [];
    for (const b of t.bands) {
      const per = (b.z[1] - b.z[0]) / Math.max(1, b.levels[1] - b.levels[0] + 1);
      for (let z = b.z[0]; z < b.z[1] - 0.01; z += per) floors.push(z);
    }
    const D = sc.density;
    for (let i = 0; i < ring.length; i++) {                      // walls, at random
      const [ax, an] = ring[i], [bx, bn] = ring[(i + 1) % ring.length], L = Math.hypot(bx - ax, bn - an);
      for (let k = Math.round(D.wall_per_m2 * L * H); k > 0; k--) {
        const s = rnd();
        const z = rnd() < G.inBands ? floors[Math.floor(rnd() * floors.length)] + (rnd() - 0.5) * G.bandM : t.base_z + rnd() * H;
        pos.push(ax + (bx - ax) * s, z, -(an + (bn - an) * s));
      }
    }
    let minX = Infinity, maxX = -Infinity, minN = Infinity, maxN = -Infinity;
    for (const [x, n] of ring) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minN = Math.min(minN, n); maxN = Math.max(maxN, n); }
    const inside = (x, n) => { let c = false; for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) {
      if ((ring[a][1] > n) !== (ring[b][1] > n) && x < ((ring[b][0] - ring[a][0]) * (n - ring[a][1])) / (ring[b][1] - ring[a][1]) + ring[a][0]) c = !c; } return c; };
    for (let k = Math.round(D.roof_per_m2 * t.area_m2); k > 0;) {   // roof
      const x = minX + rnd() * (maxX - minX), n = minN + rnd() * (maxN - minN);
      if (inside(x, n)) { pos.push(x, t.top_z, -n); k--; }
    }
    ghostPts.push({ name: t.name, base: t.base_z, layer: sc.layer || "Unbuilt", years: sc.years, pos: new Float32Array(pos) });
    ghostLabels.push({ key: `g:${t.name}`, name: t.name.replace(/ \(schematic\)$/, ""), kind: "unbuilt", year: sc.years[0], end: sc.years[1],
                       box: [minX, t.base_z, -maxN, maxX, t.top_z, -minN], h: t.top_z - t.base_z });
    const shape = new THREE.Shape(ring.map(([x, n]) => new THREE.Vector2(x, n)));
    const prism = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: t.top_z - t.base_z, bevelEnabled: false }),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false }));
    prism.rotation.x = -Math.PI / 2; prism.position.y = t.base_z;
    const grp = new THREE.Group();
    grp.name = t.name;
    grp.userData = { layer: sc.layer || "Unbuilt", ghost: { scheme: sc, tower: t } };
    grp.add(prism);
    model.add(grp);
  }
} catch (e) { /* no ghosts file */ }

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
const lidarMeta = await (await PRE.lidarMeta).json();
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
const lidarGroup = new THREE.Group();
scene.add(lidarGroup);
let lidar = null;
const loadTimes = {};   // ms from the start of loadLidar, by stage (__viewer.loadTimes; for performance checks)
// after the cloud is up (L5, 2026-10-14): the first time a stage is passed (ms from the start of loadLidar), what a few
// one-off steps take ("…, ms"), and for the first two minutes the long frames and long tasks (> 50 ms) with their times
let loadT0 = 0;
const ltick = (k) => { loadTimes[k] = Math.round(performance.now() - loadT0); };
const lonce = (k) => { if (loadT0 && !(k in loadTimes)) ltick(k); };
const ldur = (k, t) => { loadTimes[k] = (loadTimes[k] || 0) + Math.round(performance.now() - t); };
loadTimes.longFrames = []; loadTimes.longTasks = [];
try {
  const lt = new PerformanceObserver((l) => { for (const e of l.getEntries()) if (loadT0 && e.startTime - loadT0 < 120000) loadTimes.longTasks.push([Math.round(e.startTime - loadT0), Math.round(e.duration)]); });
  lt.observe({ type: "longtask", buffered: true });
  setTimeout(() => lt.disconnect(), 180000);
} catch { /* no long-task timing in this browser */ }
let lidarDensityMatch = null, lidarPlazaPoints = 0, lidarGroundFill = 0;   // object -> ground / own density, for the moved structures (loadLidar)

// the Time module (user, 2026-10-13): off = today; on = the year of its slider. TIME feeds the point shader.
const TIME = { on: { value: 0 }, year: { value: 2026 }, dim: { value: cfg.time?.undatedDim ?? 0.4 },
               build: { value: cfg.time?.buildYears ?? 5 }, front: { value: cfg.time?.front ?? 0.25 },
               grey: { value: cfg.time?.contextGrey ?? 0.45 }, alpha: { value: cfg.time?.contextOpacity ?? 0.35 } };
const ghostShown = (name) => TIME.on.value > 0.5 && (ghostYears.get(name) || []).some(([a, b]) => TIME.year.value >= a && TIME.year.value < b + 1);
function applyVisibility() {
  for (const L of ordered) {
    if (ghostYears.has(L.name)) {   // unbuilt: its own toggle, and only with the Time module, in its years
      const on = Boolean(L.visible && ghostShown(L.name));
      for (const o of L.objects) o.visible = on;
      for (const p of L.lidarParts || []) p.visible = on && mode === "cloud";
      L.row?.classList.toggle("out", !ghostShown(L.name));
      continue;
    }
    // strict booleans: three.js only skips objects whose visible === false (undefined still renders)
    // the Y-1 outline overlay stays on in the raw LiDAR, where there are no toggles
    const showMesh = Boolean(L.visible && L.cfg.overlay);   // overlays (the designs) are drawn over the cloud
    for (const o of L.objects) o.visible = showMesh;
    for (const p of L.lidarParts || []) p.visible = Boolean(L.visible && mode === "cloud");
  }
  invalidate();
}

// ---------- render on demand: only when something changed (camera, colours, visibility, size) ----------
let dirty = true;
function invalidate() { dirty = true; }
controls.addEventListener("change", () => { dirty = true; });

$("#layers").innerHTML = "";
for (const L of ordered) {
  const row = document.createElement("label");
  row.className = "layer";
  const n = "";   // filled by layerCounts(): objects in the point cloud
  // the dot is the toggle: filled = shown, ring = hidden (the checkbox stays for keyboard / screen readers, visually hidden);
  // it shows the layer colour when the point cloud is coloured by layer, a neutral dot otherwise
  const sw = `<i class="sw" style="--c:${L.cfg.color || "var(--muted)"}"></i>`;
  const ghost = ghostYears.has(L.name);
  if (ghost) L.visible = true;   // shown whenever the Time module is on and the year is theirs
  const yrs = ghost ? ghostYears.get(L.name).map(([a, b]) => `${a}–${b}`).join(", ") : n;
  row.innerHTML = `<input type="checkbox" ${L.visible ? "checked" : ""}>${sw}<span class="nm">${L.cfg.label || L.name}</span><span class="n">${yrs}</span>`;
  L.countEl = ghost ? null : row.querySelector(".n");
  L.row = row;
  row.querySelector("input").onchange = (e) => { L.visible = e.target.checked; applyVisibility(); };
  // the unbuilt schemes have no row (user, 2026-10-13): they always show with the Time module, in their years
  if (!ghost) $("#layers").append(row);
}

// ---------- point material: size in metres (perspective), never smaller than 1 px ----------
function pointMaterial(sizeMetres) {
  const mat = new THREE.PointsMaterial({ size: sizeMetres, vertexColors: true, sizeAttenuation: true });
  focusMats.push(mat);
  mat.onBeforeCompile = (shader) => {
    withFocus(shader);
    shader.uniforms.uColorMix = COLOR_MIX; shader.uniforms.uSelK = SEL_K; shader.uniforms.uHi = { value: HILITE };
    shader.uniforms.uTimeOn = TIME.on; shader.uniforms.uYear = TIME.year; shader.uniforms.uDim = TIME.dim;
    shader.uniforms.uBuild = TIME.build; shader.uniforms.uFront = TIME.front;
    // aSel: 0 not selected, 1 being deselected, 2 being selected, 3 selected
    shader.vertexShader = "attribute vec3 color0;\nattribute float aSel;\nattribute float aSize;\nattribute float aYear;\nattribute float aRise;\nuniform float uColorMix, uSelK, uTimeOn, uYear, uDim, uBuild, uFront, uFocus;\nuniform vec3 uHi;\nvarying float vSel, vBuild, vGhost;\n" +
      shader.vertexShader.replace("#include <color_vertex>", `#include <color_vertex>
  vColor.rgb = mix(color0, vColor.rgb, uColorMix);
  float sw = aSel > 2.5 ? 1.0 : aSel > 1.5 ? uSelK : aSel > 0.5 ? 1.0 - uSelK : 0.0;
  vColor.rgb = mix(vColor.rgb, uHi, sw);
  vSel = sw; vBuild = 0.0; vGhost = 0.0;`);
    shader.vertexShader = shader.vertexShader.replace(
      "#include <fog_vertex>", "gl_PointSize = max(gl_PointSize * aSize / 64.0, 1.0);\n"
      // the Time module (user, 2026-10-13: buildings go up from the ground, slowly and softly, and stay once built):
      // over the uBuild years before its year a building rises, its points shown up to an eased height with a wide
      // soft front (aRise: the point's height in its building, 0 at the foot, 1 at the top). Buildings and landmarks
      // are white, opaque, over the faint grey of the rest; an undated one stays, a dimmer white; the unbuilt towers
      // keep their colour, rising the same way over their first years and sinking back over their last ones. The ground
      // filled under a building (aYear 10000 + its year) is ordinary ground, always drawn (user, 2026-10-13: in every mode).
      + "if (aYear > 9999.5) { }\n"
      + "else if (uTimeOn > 0.5) {\n"
      + "  if (aYear < -99.5) {\n"
      + "    float c = -aYear, s = floor(c / 100.0 + 0.001), sp = c - 100.0 * s + 1.0; s += 1800.0;\n"
      + "    float up = min(uBuild, 0.6 * sp), dn = min(1.5, 0.3 * sp);\n"
      + "    float p = min(clamp((uYear - s) / up, 0.0, 1.0), clamp((s + sp - uYear) / dn, 0.0, 1.0)); p = p * p * (3.0 - 2.0 * p);\n"
      + "    float tk = clamp((p * (1.0 + uFront) - aRise) / uFront, 0.0, 1.0); tk = tk * tk * (3.0 - 2.0 * tk);\n"
      + "    gl_PointSize *= tk; if (tk < 0.01) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);\n"
      + "    vGhost = 1.0;\n"
      + "  } else if (aYear > 0.5) {\n"
      + "    float p = clamp((uYear - aYear + uBuild) / uBuild, 0.0, 1.0); p = p * p * (3.0 - 2.0 * p);\n"
      + "    float tk = clamp((p * (1.0 + uFront) - aRise) / uFront, 0.0, 1.0); tk = tk * tk * (3.0 - 2.0 * tk);\n"
      + "    gl_PointSize *= tk; if (tk < 0.01) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);\n"
      + "    vColor.rgb = mix(vColor.rgb, mix(vec3(1.0), vColor.rgb, vSel), uFocus); vBuild = 1.0;\n"
      + "  } else if (aYear < -0.5) { vColor.rgb = mix(vColor.rgb, mix(vec3(uDim), vColor.rgb, vSel), uFocus); vBuild = 1.0; }\n"
      + "}\n#include <fog_vertex>");
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
// Prepared in the background from the home page (prerender), the browser holds back new workers until the reader
// arrives (user, 2026-10-12: Model still had to load). Then the page downloads and decodes the file itself, in short
// steps (laz-core.js, shared with the worker), so the cloud is ready when the reader comes; otherwise a worker does it.
const LAZPERF = "https://cdn.jsdelivr.net/npm/laz-perf@0.0.7/lib/web/";
const loadScript = (src) => new Promise((ok, fail) => {
  const el = Object.assign(document.createElement("script"), { src, onload: ok, onerror: () => fail(new Error(`could not load ${src}`)) });
  document.head.append(el);
});
async function decodeLaz(url, meta) {
  const abs = new URL(url, location.href).href;   // absolute: a worker resolves relative URLs against js/
  if (document.prerendering) {
    const res = await fetch(abs);
    if (!res.ok) throw new Error(`LiDAR file ${url}: HTTP ${res.status}`);
    const file = new Uint8Array(await res.arrayBuffer());
    await loadScript(LAZPERF + "laz-perf.js");
    await loadScript(new URL("./laz-core.js", import.meta.url).href);
    // yield between steps with a message, not a timer: a hidden page's timers are slowed to about one a second
    const step = () => new Promise((r) => { const c = new MessageChannel(); c.port1.onmessage = () => r(); c.port2.postMessage(0); });
    return self.lazDecode(file, meta, self.createLazPerf, LAZPERF, status, step);
  }
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL("./laz-worker.js", import.meta.url));
    w.onmessage = (e) => {
      if (e.data.progress) return status(e.data.progress);
      w.terminate();
      if (e.data.error) reject(new Error(e.data.error)); else resolve(e.data);
    };
    w.postMessage({ url: abs, meta });
  });
}
async function loadLidar() {
  status("Loading LiDAR…");
  const meta = lidarMeta;
  const base = cfg.lidar.meta.replace(/[^/]*$/, "");
  const objAttr = meta.attributes?.object;
  const T0 = (loadT0 = performance.now()), tick = ltick;   // load profile
  loadTimes.startAt = Math.round(T0);   // ms after the page started
  let { n, pos: P, cls: C, inten: I, obj, hag: HG } = await decodeLaz(base + meta.file, meta);
  tick("decode (fetch + LAZ)");
  status("Preparing LiDAR…");
  // config.json mergeLayers folds LiDAR layers into others in the viewer (user, 2026-10-10: street furniture and the
  // unassigned points draw as Terrain); the objects keep their own names
  const MERGE = cfg.mergeLayers || {};
  const objNames = objAttr?.names ?? ["_other"], objLayers = (objAttr?.layers ?? ["_other"]).map((l) => MERGE[l] ?? l);
  // config.json landmarks (user, 2026-10-10): the listed entities draw as Landmarks, all their parts (one thing, one
  // colour: also the LARIAC part of Angels Flight); every other object of the Landmarks layer draws as Buildings
  if (cfg.landmarks) {
    const lm = new Set();
    for (const L of cfg.landmarks) {
      // one entry per designated monument; it can span several entities (Times Mirror Square: a block of five), and an
      // entity can carry two (Forve-Pettebone and the Roxie share a lot): the first names it, the reasons add up
      for (const part of L.parts ?? [L.part]) {
        const e = entityOfName.get(part); if (!e) continue;
        const first = !lm.has(e); lm.add(e);
        if (first && L.name && (e.status === "auto" || L.rename)) {   // automatic entities are named by their address
          if (!e.address && /^\d/.test(e.name)) e.address = e.name;
          e.name = L.name;
        }
        e.landmark = e.landmark && !first ? `${e.landmark}; ${L.basis}` : L.basis;
        if (first && L.built) e.built = [L.built, L.builtSource];
        if (L.builtAs) { e.builtAs = L.builtAs; e.builtAsSource = L.builtAsSource; }
        if (L.now) e.nowFixed = L.now;
      }
    }
    objNames.forEach((nm, k) => {
      if (lm.has(entityOfName.get(nm))) objLayers[k] = "Landmarks";
      else if (objLayers[k] === "Landmarks") objLayers[k] = "Buildings";
    });
  }
  tick("landmarks");
  // estimated facade points join the measured ones as ordinary building points: the object of their nearest return,
  // that object's mean intensity, class "building"; after this nothing tells them apart
  if (facadeData?.obj) {
    const nameIdx = new Map(objNames.map((nm, k) => [nm, k]));
    const map = facadeData.names.map((nm) => nameIdx.get(nm) ?? -1);
    const sum = new Float64Array(objNames.length), cnt = new Uint32Array(objNames.length);
    for (let i = 0; i < n; i++) { sum[obj[i]] += I[i]; cnt[obj[i]]++; }
    tick("  facades: mean intensity per object");
    const keep = [];
    for (let j = 0; j < facadeData.n; j++) if (map[facadeData.obj[j]] >= 0) keep.push(j);
    const m = keep.length, N2 = n + m;
    const P2 = new P.constructor(3 * N2), C2 = new C.constructor(N2), I2 = new I.constructor(N2), O2 = new obj.constructor(N2);
    const H2 = HG ? new HG.constructor(N2) : null;
    tick("  facades: keep list + new arrays");
    P2.set(P); C2.set(C); I2.set(I); O2.set(obj); if (H2) H2.set(HG);
    tick("  facades: copy the 10M points");
    keep.forEach((j, k) => {
      const i = n + k, o = map[facadeData.obj[j]];
      P2[3 * i] = facadeData.pos[3 * j]; P2[3 * i + 1] = facadeData.pos[3 * j + 1]; P2[3 * i + 2] = facadeData.pos[3 * j + 2];
      C2[i] = 6; O2[i] = o; I2[i] = cnt[o] ? Math.round(sum[o] / cnt[o]) : 128;
      if (H2) H2[i] = facadeData.hag[j];
    });
    P = P2; C = C2; I = I2; obj = O2; HG = H2; n = N2;
    facadeData = null;   // memory
    tick("  facades: write the new points");
  }
  // the unbuilt towers' points join as objects of their own (layer Unbuilt), named as their towers
  const ghostObjYears = new Map();   // object -> the years of its scheme
  if (ghostPts.length) {
    const m = ghostPts.reduce((a, g) => a + g.pos.length / 3, 0), N2 = n + m;
    const P2 = new P.constructor(3 * N2), C2 = new C.constructor(N2), I2 = new I.constructor(N2), O2 = new obj.constructor(N2);
    const H2 = HG ? new HG.constructor(N2) : null;
    P2.set(P); C2.set(C); I2.set(I); O2.set(obj); if (H2) H2.set(HG);
    tick("  unbuilt: copy the 10M points");
    let i = n;
    for (const g of ghostPts) {
      const o = objNames.length; objNames.push(g.name); objLayers.push(g.layer); ghostObjYears.set(o, g.years);
      for (let j = 0; j < g.pos.length; j += 3, i++) {
        P2[3 * i] = g.pos[j]; P2[3 * i + 1] = g.pos[j + 1]; P2[3 * i + 2] = g.pos[j + 2];
        C2[i] = 6; O2[i] = o; I2[i] = 128; if (H2) H2[i] = Math.round((g.pos[j + 1] - g.base) * 10);
      }
    }
    P = P2; C = C2; I = I2; obj = O2; HG = H2; n = N2;
    ghostPts.length = 0;   // memory
  }
  // config.json claims: a landmark takes the points of other objects right next to its own (user, 2026-10-10: part of
  // the Angels Flight upper station lies inside the Two California Plaza outline and was drawn as the tower). A point of
  // a `from` layer within marginM of a point of a `layer` object joins that object.
  for (const CL of cfg.claims || []) {
    const lay = objAttr?.layers ?? [], g = CL.marginM, own = new Map();
    const key = (x, y, z) => ((Math.floor(x / g) + 4096) * 8192 + Math.floor(y / g) + 4096) * 8192 + Math.floor(z / g) + 4096;
    // (2026-10-15, load time: this step took ~2 s) per object flags instead of comparing layer names point by point, and
    // a coarse 8 m plan grid round the claiming points, so only points near them are looked up; same result
    const isOwn = new Uint8Array(objNames.length), isFrom = new Uint8Array(objNames.length), from = new Set(CL.from);
    for (let k = 0; k < objNames.length; k++) { isOwn[k] = lay[k] === CL.layer ? 1 : 0; isFrom[k] = from.has(lay[k]) ? 1 : 0; }
    const CG = 8, near = new Set(), ck = (x, z) => (Math.floor(x / CG) + 32768) * 65536 + Math.floor(z / CG) + 32768;
    for (let i = 0; i < n; i++) if (isOwn[obj[i]]) {
      own.set(key(P[3 * i], P[3 * i + 1], P[3 * i + 2]), obj[i]);
      const cx = Math.floor(P[3 * i] / CG), cz = Math.floor(P[3 * i + 2] / CG);
      for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) near.add((cx + dx + 32768) * 65536 + cz + dz + 32768);
    }
    if (!own.size) continue;
    for (let i = 0; i < n; i++) {
      if (!isFrom[obj[i]] || !near.has(ck(P[3 * i], P[3 * i + 2]))) continue;
      const x = Math.floor(P[3 * i] / g), y = Math.floor(P[3 * i + 1] / g), z = Math.floor(P[3 * i + 2] / g);
      search: for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
        const o = own.get(((x + dx + 4096) * 8192 + y + dy + 4096) * 8192 + z + dz + 4096);
        if (o !== undefined) { obj[i] = o; break search; }
      }
    }
  }
  tick("landmark claims");
  // config.json plazas: the open ground around a tower that the building outline takes in (user, 2026-10-10, after Two
  // California Plaza: LARIAC draws the tower and its Watercourt plaza as one outline) goes back to the ground. In an
  // object of the layer at least minBuildingM tall, a cellM plan cell whose highest return is under maxHagM above the
  // ground has no building over it: a plaza, steps, a terrace at street level. Its points become ground points (object
  // Terrain), so they are coloured, picked and counted as the ground.
  const PZ = cfg.plazas, terrainObj = objNames.indexOf("Terrain");
  if (PZ && HG && terrainObj >= 0) {
    const top = new Float32Array(objNames.length).fill(-1e9), lay = objAttr?.layers ?? [];
    for (let i = 0; i < n; i++) { const o = obj[i]; if (lay[o] === PZ.layer && HG[i] / 10 > top[o]) top[o] = HG[i] / 10; }
    const cm = PZ.cellM, keyOf = (o, i) => o * 4294967296 + (Math.floor(P[3 * i] / cm) + 32768) * 65536 + Math.floor(P[3 * i + 2] / cm) + 32768;
    const tall = (o) => lay[o] === PZ.layer && top[o] >= PZ.minBuildingM;
    const col = new Map();   // (object, cell) -> [highest return above the ground, its height, plaza?]
    for (let i = 0; i < n; i++) {
      const o = obj[i]; if (!tall(o)) continue;
      const k = keyOf(o, i), h = HG[i] / 10, c = col.get(k);
      if (!c) col.set(k, [h, P[3 * i + 1], false]); else if (h > c[0]) { c[0] = h; c[1] = P[3 * i + 1]; }
    }
    for (const c of col.values()) c[2] = c[0] < PZ.maxHagM;
    // the plaza's edges: a cell next to the plaza whose top is no higher than the plaza (within PZ.edgeM) - the walls
    // and steps down to a lower street, where the ground below makes them look tall - joins it, PZ.grow cells out
    for (let g = 0; g < (PZ.grow ?? 0); g++) {
      const add = [];
      for (const [k, c] of col) {
        if (c[2]) continue;
        for (let dx = -1; dx <= 1 && !c[2]; dx++) for (let dz = -1; dz <= 1; dz++) {
          const nb = col.get(k + dx * 65536 + dz);
          if (nb && nb[2] && c[1] <= nb[1] + PZ.edgeM) { add.push(c); break; }
        }
      }
      for (const c of add) c[2] = true;
    }
    let moved = 0;
    for (let i = 0; i < n; i++) {
      const o = obj[i]; if (!tall(o)) continue;
      if (col.get(keyOf(o, i))[2]) { obj[i] = terrainObj; moved++; }
    }
    lidarPlazaPoints = moved;   // for checks (__viewer)
  }
  // config.json splitLayers sends some objects of a layer elsewhere (user, 2026-10-10: of the LiDAR-only structures,
  // the bridges, raised walkways, street and plaza decks and canopies draw with the ground and streets; the rest are
  // building parts and join Buildings through mergeLayers). An object goes when its entity's checked use names it
  // (s.uses, e.g. the Grand Avenue deck), or by shape: thin (s.maxThickM between the 5th and 95th percentile of its
  // heights, so a railing or lamp post does not make a deck "thick") and held s.minHagM-s.maxHagM above the ground.
  const rawLayers = objAttr?.layers ?? ["_other"], moved = new Map();   // moved: object -> its split rule
  for (const [raw, s] of Object.entries(cfg.splitLayers || {})) {
    if (!HG || raw.startsWith("_")) continue;
    const ys = new Map(), hs = new Float64Array(objNames.length);
    for (let i = 0; i < n; i++) {
      const o = obj[i]; if (rawLayers[o] !== raw) continue;
      (ys.get(o) ?? ys.set(o, []).get(o)).push(P[3 * i + 1]);
      hs[o] += HG[i] / 10;
    }
    const byUse = s.uses ? new RegExp(s.uses, "i") : null;
    for (const [o, y] of ys) {
      if (objLayers[o] === "Landmarks") continue;   // a landmark keeps all its parts
      y.sort((p, q) => p - q);
      const at = (f) => y[Math.round(f * (y.length - 1))], h = hs[o] / y.length;
      const use = entityOfName.get(objNames[o])?.use ?? "";
      if ((byUse && byUse.test(use)) || (at(0.95) - at(0.05) < s.maxThickM && h >= s.minHagM && h <= s.maxHagM)) {
        objLayers[o] = s.to; if (s.matchDensity) moved.set(o, s);
      }
    }
  }
  // the moved objects are drawn as densely as the ground around them (user, 2026-10-10, option A): the LiDAR has about
  // half the returns on a deck that it has on the street, and far from Y-1 each object keeps its own random share of
  // points while the ground thins smoothly, so a deck looked darker or brighter than the street in the same colour.
  // Per object: f = mean ground returns per 2 m cell around it (its box + 20 m, cells it covers left out) / its own
  // mean per cell (over cells with returns); f < 1 drops points at random down to the ground's density, f > 1 draws its points sqrt(f) times
  // larger (at most matchDensity.maxSize) so they cover the same share of the screen. Only the drawing changes.
  tick("claims + plazas + split layers");
  let sizeK = new Uint8Array(n).fill(64), drop = new Uint8Array(n);   // point size x 64; 1 = not drawn
  if (moved.size) {
    const CM = 2, PAD = 10, cellOf = (x, z) => (Math.floor(x / CM) + 32768) * 65536 + Math.floor(z / CM) + 32768;
    const own = new Map(), box = new Map();
    for (let i = 0; i < n; i++) {
      const o = obj[i]; if (!moved.has(o)) continue;
      const x = P[3 * i], z = P[3 * i + 2], c = cellOf(x, z);
      let m = own.get(o); if (!m) own.set(o, (m = new Map()));
      m.set(c, (m.get(c) || 0) + 1);
      let b = box.get(o); if (!b) box.set(o, (b = [x, z, x, z]));
      if (x < b[0]) b[0] = x; if (z < b[1]) b[1] = z; if (x > b[2]) b[2] = x; if (z > b[3]) b[3] = z;
    }
    const ground = new Map();    // cells around the moved objects -> ground returns
    for (const [o, b] of box) {
      const m = own.get(o);
      for (let x = Math.floor(b[0] / CM) - PAD; x <= Math.floor(b[2] / CM) + PAD; x++)
        for (let z = Math.floor(b[1] / CM) - PAD; z <= Math.floor(b[3] / CM) + PAD; z++) {
          const c = (x + 32768) * 65536 + z + 32768; if (!m.has(c)) ground.set(c, 0);
        }
    }
    const groundRaw = new Set([...moved.values()].map((s) => s.to));
    for (let i = 0; i < n; i++) {
      if (!groundRaw.has(rawLayers[obj[i]])) continue;
      const c = cellOf(P[3 * i], P[3 * i + 2]), v = ground.get(c);
      if (v !== undefined) ground.set(c, v + 1);
    }
    const mean = (a) => a.reduce((p, q) => p + q, 0) / a.length;
    const f = new Map(), seed = (i) => { let h = (i * 2654435761) >>> 0; h ^= h >>> 15; return (h % 10007) / 10007; };
    for (const [o, b] of box) {
      const m = own.get(o), g = [];
      for (let x = Math.floor(b[0] / CM) - PAD; x <= Math.floor(b[2] / CM) + PAD; x++)
        for (let z = Math.floor(b[1] / CM) - PAD; z <= Math.floor(b[3] / CM) + PAD; z++) {
          const v = ground.get((x + 32768) * 65536 + z + 32768); if (v) g.push(v);
        }
      if (g.length >= 10 && m.size >= 3) f.set(o, mean(g) / mean([...m.values()]));
    }
    for (let i = 0; i < n; i++) {
      const k = f.get(obj[i]); if (k === undefined) continue;
      if (k < 1) drop[i] = seed(i) > k ? 1 : 0;
      else sizeK[i] = Math.round(64 * Math.min(Math.sqrt(k), moved.get(obj[i]).matchDensity.maxSize ?? 2.5));
    }
    lidarDensityMatch = f;   // for checks (__viewer)
  }
  // per object: the year its building was built (the landmark's own year, else the Assessor's), -1 for a building with
  // none, 0 for what is not a building (ground, trees, cars: always there for the Time module); an unbuilt tower:
  // -(100 * (first year - 1800) + years it was alive), read back in the shader
  const objYear = new Int16Array(objNames.length);
  objNames.forEach((nm, k) => {
    const gy = ghostObjYears.get(k);
    if (gy) { objYear[k] = -(100 * (gy[0] - 1800) + Math.min(gy[1] - gy[0], 99)); return; }
    if (objLayers[k] !== "Buildings" && objLayers[k] !== "Landmarks") return;
    const e = entityOfName.get(nm), y = e ? parseInt(e.built?.[0] ?? e.parcel?.year_built, 10) : NaN;
    objYear[k] = y > 1000 ? y : -1;
  });
  tick("density match");
  // the ground under the buildings (user, 2026-10-13: in 1867 the cloud showed black holes where today's buildings
  // stand, the LiDAR seeing their roofs and not the ground). ESTIMATED: in every 2 m cell a building covers and
  // the ground has no return, points at random at the ground's own density around it (the mean of the cells with ground
  // returns within groundFill.radiusM), at the building's ground height (its points' height less their height above the
  // ground). They draw as ground, always (user, 2026-10-13: the holes show in the other modes too, e.g. under Highlight
  // people); per-point year code 10000 + the building's year (ptYear), kept for the Time module.
  let ptYear = null;
  const GF = cfg.time?.groundFill;
  if (GF && HG && terrainObj >= 0) {
    const CM = GF.cellM ?? 2, groundL = objLayers[terrainObj];
    let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
    for (let i = 0; i < n; i++) { const x = P[3 * i], z = P[3 * i + 2]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (z < z0) z0 = z; if (z > z1) z1 = z; }
    const W = Math.ceil((x1 - x0) / CM) + 1, H = Math.ceil((z1 - z0) / CM) + 1, cellOf = (i) => Math.floor((P[3 * i] - x0) / CM) * H + Math.floor((P[3 * i + 2] - z0) / CM);
    const tc = new Uint16Array(W * H);
    let isum = 0, icnt = 0;
    for (let i = 0; i < n; i++) if (objLayers[obj[i]] === groundL) { const c = cellOf(i); if (tc[c] < 65535) tc[c]++; isum += I[i]; icnt++; }
    const cy = new Int16Array(W * H), gsum = new Float32Array(W * H), gn = new Uint16Array(W * H);   // earliest year over the cell
    for (let i = 0; i < n; i++) {
      const y0 = objYear[obj[i]]; if (y0 === 0 || y0 < -99) continue;   // every building, dated or not (undated: year 1)
      const y = y0 > 0 ? y0 : 1;
      const c = cellOf(i); if (tc[c]) continue;
      if (!cy[c] || y < cy[c]) cy[c] = y;
      gsum[c] += P[3 * i + 1] - HG[i] / 10; if (gn[c] < 65535) gn[c]++;
    }
    // summed-area tables of the ground counts and of the cells holding any, for the mean around each cell
    const S = new Int32Array((W + 1) * (H + 1)), Z = new Int32Array((W + 1) * (H + 1)), ix = (a, b) => a * (H + 1) + b;
    for (let a = 0; a < W; a++) for (let b = 0; b < H; b++) {
      const c = a * H + b;
      S[ix(a + 1, b + 1)] = tc[c] + S[ix(a, b + 1)] + S[ix(a + 1, b)] - S[ix(a, b)];
      Z[ix(a + 1, b + 1)] = (tc[c] ? 1 : 0) + Z[ix(a, b + 1)] + Z[ix(a + 1, b)] - Z[ix(a, b)];
    }
    const rc = Math.round((GF.radiusM ?? 20) / CM), box = (T, a0, b0, a1, b1) => T[ix(a1, b1)] - T[ix(a0, b1)] - T[ix(a1, b0)] + T[ix(a0, b0)];
    let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const add = [];   // x, y, z, year
    for (let a = 0; a < W; a++) for (let b = 0; b < H; b++) {
      const c = a * H + b; if (!cy[c]) continue;
      // the ground's density around it, within radiusM - or, deep under a large building or landmark where nothing
      // within that is ground (user, 2026-10-15: black under Disney Hall and the big buildings), within wider radii
      let k = 0, d = 0;
      for (const r of [rc, ...(GF.widerM ?? [60, 150]).map((m) => Math.round(m / CM))]) {
        const a0 = Math.max(a - r, 0), b0 = Math.max(b - r, 0), a1 = Math.min(a + r + 1, W), b1 = Math.min(b + r + 1, H);
        k = box(Z, a0, b0, a1, b1); if (k) { d = box(S, a0, b0, a1, b1) / k; break; }
      }
      if (!k) continue;
      const y = gsum[c] / gn[c];
      for (let m = Math.floor(d + rnd()); m > 0; m--) add.push(x0 + (a + rnd()) * CM, y, z0 + (b + rnd()) * CM, cy[c]);
    }
    const m = add.length / 4, N2 = n + m, iMean = icnt ? Math.round(isum / icnt) : 128;
    const P2 = new P.constructor(3 * N2), C2 = new C.constructor(N2), I2 = new I.constructor(N2), O2 = new obj.constructor(N2), H2 = new HG.constructor(N2);
    const S2 = new Uint8Array(N2).fill(64), D2 = new Uint8Array(N2);
    P2.set(P); C2.set(C); I2.set(I); O2.set(obj); H2.set(HG); S2.set(sizeK); D2.set(drop);
    ptYear = new Int16Array(N2);
    for (let i = 0; i < n; i++) ptYear[i] = objYear[obj[i]];
    for (let k = 0; k < m; k++) {
      const i = n + k;
      P2[3 * i] = add[4 * k]; P2[3 * i + 1] = add[4 * k + 1]; P2[3 * i + 2] = add[4 * k + 2];
      C2[i] = 2; O2[i] = terrainObj; I2[i] = iMean; H2[i] = 0; ptYear[i] = 10000 + add[4 * k + 3];
    }
    P = P2; C = C2; I = I2; obj = O2; HG = H2; n = N2;
    lidarGroundFill = m;   // for checks (__viewer)
    sizeK = S2; drop = D2;
  }
  if (!ptYear) { ptYear = new Int16Array(n); for (let i = 0; i < n; i++) ptYear[i] = objYear[obj[i]]; }
  tick("ground fill");
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
  // per object: the height of its lowest and highest point, so each point knows how far up its building it is (aRise)
  // (2026-10-15) robust: the 0.5 % and 99.5 % heights, so a few stray points (wires, birds) above or below a building do
  // not stretch its rise; points past them simply come first / last
  const objLo = new Float32Array(objNames.length).fill(1e9), objHi = new Float32Array(objNames.length).fill(-1e9);
  { const hs = new Map();
    for (let i = 0; i < n; i++) {
      const o = obj[i]; if (objYear[o] === 0 || objYear[o] === -1) continue;
      let a = hs.get(o); if (!a) hs.set(o, (a = [])); if (a.length < 6000 || (i & 3) === 0) a.push(P[3 * i + 1]);
    }
    for (const [o, a] of hs) { a.sort((p, q) => p - q); objLo[o] = a[Math.floor(0.005 * (a.length - 1))]; objHi[o] = a[Math.ceil(0.995 * (a.length - 1))]; }
  }
  tick("LOD priority + years + rise heights");
  // bucket point indices by layer and LOD chunk, each chunk sorted by draw priority q (the first k points are the ones
  // to keep when thinning). (L1, 2026-10-14: this took ~2.6 s with a string key per point and a comparison sort per
  // chunk; now numeric chunk ids, a counting pass, and one stable radix sort of all points by q's bits, then by chunk:
  // the same chunks in the same order, their points in the same order, ties in q as before in index order.) q >= 0, so
  // its float bits sort as unsigned integers
  const cellM = lodCell(), layerNames = [...layerIdx.keys()];
  let cx0 = Infinity, cz0 = Infinity, cx1 = -Infinity, cz1 = -Infinity;
  for (let i = 0; i < n; i++) {
    if (drop[i]) continue;
    const cx = Math.floor(P[3 * i] / cellM), cz = Math.floor(P[3 * i + 2] / cellM);
    if (cx < cx0) cx0 = cx; if (cx > cx1) cx1 = cx; if (cz < cz0) cz0 = cz; if (cz > cz1) cz1 = cz;
  }
  const cw = cx1 - cx0 + 1, ch = cz1 - cz0 + 1, slot = new Int32Array(layerNames.length * cw * ch).fill(-1);
  const chunkOf = new Int32Array(n), chunkSlot = [];   // point -> chunk id (-1 dropped); chunk id -> its slot
  let kept = 0;
  for (let i = 0; i < n; i++) {
    if (drop[i]) { chunkOf[i] = -1; continue; }
    const sl = (objL[obj[i]] * cw + Math.floor(P[3 * i] / cellM) - cx0) * ch + Math.floor(P[3 * i + 2] / cellM) - cz0;
    let id = slot[sl]; if (id < 0) { id = slot[sl] = chunkSlot.length; chunkSlot.push(sl); }   // ids in order of first point
    chunkOf[i] = id; kept++;
  }
  // the keys travel with the indices (reading q at random for every point and pass was the slow part)
  const nChunks = chunkSlot.length, qBits = new Uint32Array(q.buffer, q.byteOffset, n);
  let A = new Uint32Array(kept), B = new Uint32Array(kept), KA = new Uint32Array(kept), KB = new Uint32Array(kept);
  for (let i = 0, k = 0; i < n; i++) if (chunkOf[i] >= 0) { A[k] = i; KA[k++] = qBits[i]; }
  for (const [shift, size] of [[0, 2048], [11, 2048], [22, 1024]]) {   // LSD radix by q, stable
    const cnt = new Uint32Array(size + 1), mask = size - 1;
    for (let k = 0; k < kept; k++) cnt[((KA[k] >>> shift) & mask) + 1]++;
    for (let d = 0; d < size; d++) cnt[d + 1] += cnt[d];
    for (let k = 0; k < kept; k++) { const key = KA[k], at = cnt[(key >>> shift) & mask]++; B[at] = A[k]; KB[at] = key; }
    [A, B] = [B, A]; [KA, KB] = [KB, KA];
  }
  const chunkStart = new Uint32Array(nChunks + 1);   // then by chunk, stable: within a chunk, by q
  for (let k = 0; k < kept; k++) { const c = chunkOf[A[k]]; KA[k] = c; chunkStart[c + 1]++; }
  for (let c = 0; c < nChunks; c++) chunkStart[c + 1] += chunkStart[c];
  { const at = chunkStart.slice(0, nChunks); for (let k = 0; k < kept; k++) B[at[KA[k]]++] = A[k]; }
  const order = B;
  tick("  chunks: buckets + sort by q");
  let tCopy = 0, tGeo = 0;   // L1 (2026-10-14): where the chunk step's time goes
  const parts = [];
  for (let c = 0; c < nChunks; c++) {
    const name = layerNames[Math.floor(chunkSlot[c] / (cw * ch))], cell = cellM;
    const idx = order.subarray(chunkStart[c], chunkStart[c + 1]), m = idx.length;
    let tt = performance.now();
    const pos = new Float32Array(m * 3), zs = new Float32Array(m), cls = new Uint8Array(m), inten = new Uint8Array(m), ob = new Uint16Array(m);
    const qs = new Float32Array(m), hag = HG ? new Int16Array(m) : null;   // height above ground, 0.1 m (Houdini LAZ)
    const sz = new Uint8Array(m), yr = new Int16Array(m), rise = new Uint8Array(m);
    for (let j = 0; j < m; j++) {
      const i = idx[j];
      sz[j] = sizeK[i]; yr[j] = ptYear[i];
      if ((yr[j] > 0 && yr[j] < 10000) || yr[j] < -99) { const o = obj[i]; rise[j] = Math.round(255 * (P[3 * i + 1] - objLo[o]) / Math.max(objHi[o] - objLo[o], 0.1)); }
      pos[3 * j] = P[3 * i]; pos[3 * j + 1] = P[3 * i + 1]; pos[3 * j + 2] = P[3 * i + 2];
      zs[j] = P[3 * i + 1]; cls[j] = C[i]; inten[j] = I[i]; ob[j] = obj[i]; qs[j] = q[i];
      if (hag) hag[j] = HG[i];
    }
    tCopy += performance.now() - tt; tt = performance.now();
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const col = new Float32Array(m * 3);
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.setAttribute("color0", new THREE.BufferAttribute(new Uint8Array(m * 3), 3, true));   // the colours before a change
    g.setAttribute("aSel", new THREE.BufferAttribute(new Uint8Array(m), 1));               // selection mark (paintSelection)
    g.setAttribute("aSize", new THREE.BufferAttribute(sz, 1));                             // point size x 64 (density match)
    g.setAttribute("aYear", new THREE.BufferAttribute(yr, 1));                             // year built (Time module)
    g.setAttribute("aRise", new THREE.BufferAttribute(rise, 1, true));                     // height in its building, 0-1
    g.computeBoundingSphere();
    const pts = new THREE.Points(g, material);
    pts.frustumCulled = true;
    pts.userData.part = { name, pos, hag, zs, cls, inten, ob, col, n: m, cell: +cell, q: qs };
    lidarGroup.add(pts);
    parts.push(pts.userData.part);
    const L = layers.get(name);
    if (L) (L.lidarParts ||= []).push(pts);
    tGeo += performance.now() - tt;
  }
  Object.assign(loadTimes, { "  chunks: copy into arrays, ms": Math.round(tCopy), "  chunks: geometry + scene, ms": Math.round(tGeo), "  chunks: count": parts.length });
  tick("chunks (sort + geometry)");
  const objCount = new Uint32Array(objNames.length);
  for (let i = 0; i < n; i++) objCount[obj[i]]++;
  // per object: the chunks holding its points, so a click looks at a few chunks instead of all 9M points (user, 2026-10-12:
  // the highlight and label came late; selecting took ~100 ms of scanning)
  const objParts = Array.from({ length: objNames.length }, () => []), stamp = new Int32Array(objNames.length).fill(-1);
  parts.forEach((p, j) => { for (let i = 0; i < p.n; i++) { const k = p.ob[i]; if (stamp[k] !== j) { stamp[k] = j; objParts[k].push(j); } } });
  // per object: its entity (index into ENTITIES.entities, -1 = none); per entity: its objects
  const objEntity = new Int32Array(objNames.length).fill(-1), entityObjs = new Map();
  const entIndex = new Map((ENTITIES?.entities ?? []).map((e, i) => [e, i]));
  objNames.forEach((nm, k) => {
    const e = entityOfName.get(nm);
    if (e) { const i = entIndex.get(e); objEntity[k] = i; (entityObjs.get(i) ?? entityObjs.set(i, []).get(i)).push(k); }
  });
  lidar = { parts, material, objNames, objLayers, objCount, objEntity, entityObjs, objParts, litParts: new Set(), count: n,
            // by layer only (user, 2026-10-10: the Color menu is gone); ?color=height / class / intensity / object still
            // works for checking the data
            how: urlq.get("color") ?? "layer", selected: -1, selMask: new Uint8Array(objNames.length) };
  tick("index (objects, entities)");
  status("");
}

// ---------- level of detail for the LiDAR (screen-space, continuous) ----------
// Each point is drawn when its priority q (random x the local density of its layer, set in loadLidar) is below the density the
// screen can show at the chunk's distance, (focal / d)^2 / LOD_PX^2 returns per m2: a point in dense ground is kept with a
// lower probability than one in sparse ground, so neighbouring points end up at most ~LOD_PX pixels apart everywhere and the
// thinning has no steps at chunk borders. Chunks hold their points sorted by q, so this is a draw range. The count depends
// only on where the camera is, never on whether it is moving, so nothing pops when a drag or zoom stops; counts also ease
// towards their target over a few frames. A total cap protects slow machines.
let LOD_PX = cfg.lidar.lodPixels ?? 1.2, LOD_CAP = cfg.lidar.pointCap ?? 6e6;
let lodGap = LOD_PX;   // the on-screen gap the cap needed last frame (start of the next search)
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
  // over the cap: widen the allowed on-screen gap (binary search) instead of thinning everything, so near chunks stay complete.
  // The search starts from the last frame's gap (the view changes little between frames): ~6 counts instead of 21, each a
  // pass over all chunks (2.2 -> ~0.6 ms a frame, measured 2026-10-12 with 1,430 chunks), to 0.5 % of the gap.
  let px = LOD_PX;
  if (count(px) > LOD_CAP) {
    let lo = Math.max(LOD_PX, lodGap / 1.05), hi = Math.max(lo * 1.05, lodGap * 1.05);
    while (lo > LOD_PX && count(lo) <= LOD_CAP) { hi = lo; lo = Math.max(LOD_PX, lo / 1.25); }
    while (hi < 64 && count(hi) > LOD_CAP) { lo = hi; hi = Math.min(64, hi * 1.25); }
    while (hi / lo > 1.005) { const mid = Math.sqrt(lo * hi); if (count(mid) > LOD_CAP) lo = mid; else hi = mid; }
    px = hi;
  }
  lodGap = px;
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
  // the colours on screen become the start of a cross-fade (the first painting has none: no fade)
  const fade = lidar.painted;
  if (fade) for (const pts of lidarGroup.children) {
    const c = pts.geometry.attributes.color.array, c0 = pts.geometry.attributes.color0;
    for (let k = 0; k < c.length; k++) c0.array[k] = c[k] * 255;
    c0.needsUpdate = true;
  }
  lidar.how = how;
  for (const part of lidar.parts) {
    const { zs, cls, inten, ob, col, n } = part, b = layerColor(part.name), base = [b.r, b.g, b.b];
    for (let i = 0; i < n; i++) {
      let c;
      if (how === "layer") c = base;
      else if (how === "height") c = ramp((zs[i] - 78) / 60);
      else if (how === "object") c = objColor(ob[i]);
      else if (how === "class") c = cls[i] === 2 ? [0.72, 0.6, 0.42] : zs[i] > 140 ? [0.55, 0.58, 0.62] : [0.3, 0.52, 0.36];
      else { const v = 0.15 + (inten[i] / 255) * 0.85; c = [v, v, v]; }
      col.set(c, 3 * i);
    }
  }
  for (const p of lidarGroup.children) p.geometry.attributes.color.needsUpdate = true;
  if (fade) crossFade(); else COLOR_MIX.value = 1;
  lidar.painted = true;
  document.body.classList.toggle("linked", mode === "cloud" && how === "layer");   // layer legend swatches
  invalidate();
}
// the selection lights the clicked object, or all objects of its entity (a whole building); shift + click adds.
// Only the chunks holding the new or the last selection are visited, and only the marks of points whose state changes are
// written. The highlight eases in / out with the label: over --t-in on the CSS "ease" curve (user, 2026-10-12: in step
// with the label; it used --t-out with a slow-starting curve and lagged behind).
const cssEase = (x) => {   // cubic-bezier(.25, .1, .25, 1): solve the curve's x(t) = x by bisection, return y(t)
  const bz = (t, p1, p2) => 3 * (1 - t) * (1 - t) * t * p1 + 3 * (1 - t) * t * t * p2 + t * t * t;
  let lo = 0, hi = 1;
  for (let i = 0; i < 20; i++) { const m = (lo + hi) / 2; if (bz(m, 0.25, 0.25) < x) lo = m; else hi = m; }
  return bz((lo + hi) / 2, 0.1, 1);
};
function paintSelection() {
  if (!lidar) return;
  const mask = lidar.selMask, touched = new Set(lidar.litParts);
  mask.fill(0);
  for (const s of selection) for (const k of s.objs) { mask[k] = 1; for (const j of lidar.objParts[k]) touched.add(j); }
  lidar.litParts.clear();
  for (const j of touched) {
    const pts = lidarGroup.children[j], part = pts.userData.part, a = pts.geometry.attributes.aSel, v = a.array, ob = part.ob;
    let changed = false, lit = false;
    for (let i = 0; i < part.n; i++) {
      const was = v[i] >= 2, is = mask[ob[i]] === 1, nv = is ? (was ? 3 : 2) : was ? 1 : 0;
      if (nv !== v[i]) { v[i] = nv; changed = true; }
      if (nv) lit = true;
    }
    if (changed) a.needsUpdate = true;
    if (lit) lidar.litParts.add(j);
  }
  const t0 = performance.now(), dur = tms("--t-in");
  SEL_K.value = 0;
  cancelAnimationFrame(selAnim);
  const step = (now) => {
    const k = dur ? Math.min((now - t0) / dur, 1) : 1;
    SEL_K.value = cssEase(k);
    invalidate();
    if (k < 1) selAnim = requestAnimationFrame(step);
  };
  selAnim = requestAnimationFrame(step);
}

// ---------- modes ----------
let busy = false;
// a segmented control's thumb slides under its selected button (no animation for the first placement);
// used by Mode (#modes)
function moveThumb(instant, sel = "#modes") {
  const th = $(`${sel} .thumb`), on = $(`${sel} button.on`);
  if (th && on && !on.offsetWidth) return;   // section hidden or folded: placed when shown
  if (!th || !on) return;
  th.classList.toggle("instant", !!instant);
  th.style.width = `${on.offsetWidth}px`;
  th.style.transform = `translateX(${on.offsetLeft}px)`;
  if (instant) requestAnimationFrame(() => th.classList.remove("instant"));
}
addEventListener("resize", () => moveThumb(true));
$("#modes").closest("details")?.addEventListener("toggle", () => moveThumb(true));   // re-measure after unfolding
// one mode, "cloud" (the LiDAR points, coloured by layer); the mode machinery stays for
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
  lonce("after: colours painted");
  applyVisibility();
  document.querySelectorAll("#modes button").forEach((b) => { b.disabled = false; b.classList.toggle("on", b.dataset.mode === m); });
  layerCounts();
  lonce("after: visibility + layer counts");
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
const PICK_LIDAR_PX = 5;   // a click this close to a LiDAR point (screen px) picks it (pickLidar)
// hover with Alt held: the person an Alt + click would select is drawn bigger and the cursor turns into a pointer
let hoverAt = null;
renderer.domElement.addEventListener("pointermove", (e) => {
  if (!pop?.visible || e.buttons) return;
  if (!hoverAt) requestAnimationFrame(() => {
    const i = hoverAt.alt ? pop.nearest(hoverAt.x, hoverAt.y, PICK_PX, hoverAt.shift) : -1;
    pop.hover(i);
    renderer.domElement.style.cursor = i >= 0 ? "pointer" : "";
    hoverAt = null; invalidate();
  });
  hoverAt = { x: e.clientX, y: e.clientY, alt: e.altKey, shift: e.shiftKey };
});
// pressing / releasing Alt with the mouse still: show / hide the marker at once
for (const ev of ["keydown", "keyup"]) addEventListener(ev, (e) => {
  if (e.key !== "Alt" || !pop?.visible || !lastHover) return;
  e.preventDefault();
  const i = ev === "keydown" ? pop.nearest(lastHover.x, lastHover.y, PICK_PX, e.shiftKey) : -1;
  pop.hover(i); renderer.domElement.style.cursor = i >= 0 ? "pointer" : ""; invalidate();
});
let lastHover = null;
renderer.domElement.addEventListener("pointermove", (e) => { lastHover = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener("pointerleave", () => { pop?.hover(-1); renderer.domElement.style.cursor = ""; invalidate(); });
let popStartT = null;   // seconds of the day to start at when People next comes on (set by the Guided film)
let popShownAt = 0;     // when the people were first shown (load profile: the frames right after)
// the population is made once, hidden (population.js), by whichever comes first: People turned on, or the load ahead of
// time (below); both wait for the same promise
let popLoading = null;
function loadPop() {
  return (popLoading ??= (async () => {
    const tP = performance.now(); lonce("people: load started");
    const { createPopulation } = await import("./population.js");
    pop = await createPopulation({ cfg, scene, camera, renderer, layers, thinning: lidarMeta.thinning, onInfo: personTag,
      onDrop: (i) => { popSelecting = true; deselect(`pop:${i}`); popSelecting = false; } });   // Shift + Alt + click took i out
    ldur("people: load + create, ms", tP);
    return pop;
  })());
}
$("#popOn").onchange = async (e) => {
  const on = e.target.checked;
  if (on && !pop) {
    e.target.disabled = true;
    status("Loading population…");
    await loadPop();
    status("");
    e.target.disabled = false;
  }
  $("#popBox").hidden = !on;
  // a start time asked for (the Guided film): set before they show, so nobody appears at the old time first
  if (on && pop && popStartT !== null) { const r = $("#popTime"); r.value = popStartT; r.dispatchEvent(new Event("input")); popStartT = null; }
  pop?.setVisible(on);
  if (on && pop) { lonce("people: first shown"); popShownAt ||= performance.now(); }
  updateWhite();
  if (!on) for (const s of [...selection]) if (s.key.startsWith("pop:")) deselect(s.key);
  invalidate();
};
// the cloud turns grey for Highlight people, and with the Time module (user, 2026-10-13: as Population does)
let whiteNow = false;
function updateWhite() {
  // (user, 2026-10-14: Highlight people removed; the grey cloud is now the History module's only)
  const want = $("#timeOn").checked;
  if (want !== whiteNow) { whiteNow = want; setWhiteCloud(want); }
}
// the History module's Tags switch (user, 2026-10-14): the tags fade out and back in
$("#timeTags").onchange = (e) => { tlLayer.classList.toggle("off", !e.target.checked); };
// ---------- Time module ----------
// buildings with a year, for the count under the slider
const datedYears = (ENTITIES?.entities ?? []).map((e) => parseInt(e.built?.[0] ?? e.parcel?.year_built, 10)).filter((y) => y > 1000).sort((a, b) => a - b);
const undatedN = (ENTITIES?.entities ?? []).length - datedYears.length;
function setYear(y) {
  const r = $("#timeRange");
  TIME.year.value = y; r.value = y;
  r.style.setProperty("--p", `${(100 * (y - r.min)) / (r.max - r.min)}%`);
  $("#timeYear").textContent = Math.floor(y);
  let k = 0; while (k < datedYears.length && datedYears[k] <= y) k++;
  $("#timeCounts").textContent = `${k.toLocaleString()} of ${datedYears.length.toLocaleString()} dated buildings standing · ${undatedN} undated`;
  applyVisibility();
}
// History on / off. resume: where the History view was left ({ year } or { cine, at }), to go on from there
function setHistory(on, resume) {
  $("#timeOn").checked = on; $("#timeBox").hidden = !on;
  TIME.on.value = on ? 1 : 0;
  updateWhite();
  if (!on) { stopPlay(); setYear(2026); return; }
  if (resume?.cine) {   // the film was playing: it goes on, eased in from where the camera is now
    setYear(2026);
    cine = resume.cine; cine.t0 += performance.now() - resume.at; cine.pausedAt = 0;
    if (cine.phase === "cut") cine.phase = "shot";
    rejoin = { from: camPose(), t0: performance.now() }; controls.enableDamping = false; timeState();
    return;
  }
  setYear(resume ? resume.year : 1867);   // (user, 2026-10-13) it starts in 1867 and plays, the camera going round
  // no people while the buildings go up (user, 2026-10-15): they come on with the film, after its first wide shot
  peopleOff();
  startPlay(true);
}
$("#timeOn").onchange = (e) => setHistory(e.target.checked);
// moving the year by hand. In the Guided camera it is a pause (user, 2026-10-15: after the end, going back in time
// left the people on and the camera standing still): no people before 2026, and a few seconds after the last input
// the opening goes on from that year (from 2026: the film), as after any pause
let scrubbed = false;
$("#timeRange").oninput = (e) => {
  stopPlay(); setYear(+e.target.value);
  if (viewMode === "history") { scrubbed = true; pauseInput = performance.now(); if (+e.target.value < 2025.9) peopleOff(); timeState(); }
};
function peopleOff() { if ($("#popOn").checked) { $("#popOn").checked = false; $("#popOn").onchange({ target: $("#popOn") }); } }
function goOnGuided() {   // after a scrub: from the slider's year, or the film from 2026
  scrubbed = false;
  if (+$("#timeRange").value >= 2025.9) startCine(); else startPlay(true);
}
// the camera tour while it plays from 1867 (user, 2026-10-13): round the site and slowly out, so the whole of it comes
// into view as it is built. From the current heading; config.json time.tour: turn (degrees), distance and tilt (degrees
// from straight down) at the start and the end. Any drag or scroll hands the camera back.
let tour = null;
const TOUR = { turnDeg: 220, r0: 420, r1: 820, tilt0: 64, tilt1: 52, target: [0, 95, 0], ...(cfg.time?.tour || {}) };
// ---------- the opening, plan B (user, 2026-10-14): the camera goes where the city is being built ----------
// The opening is cut into shots by years (config.json time.openingShots). For each, ahead of time: the buildings that
// go up in its years, weighted by height; the densest cluster of them (the spot with the most height within
// clusterM), framed closer when it is tight and farther when it is spread out; a shot marked y1 also keeps Y-1 in the
// frame (the unbuilt towers' years). The camera holds each shot's framing through the middle of its years and eases
// (quintic) to the next across the change, always turning the same way at an even speed; the last shot pulls out to the
// whole site. All as a function of the year (yearTime), so a pause holds the camera too. openingMode "A" = the old tour.
const OPEN = { mode: "B", turnDeg: 160, clusterM: 300, shots: [
  { from: 1867, to: 1910 }, { from: 1910, to: 1935 }, { from: 1935, to: 1980 }, { from: 1980, to: 2000, y1: true },
  { from: 2000, to: 2026, y1: true }], ...(cfg.time?.openingB || {}), mode: cfg.time?.openingMode ?? "B" };
let openAnchors = null;   // [{ hs, he, pose }]: held from hs to he seconds into the opening
const yearT = [];         // seconds into the opening at 1867 + 0.05 k
function yearTime(y) {
  if (!yearT.length) { let t = 0; for (let u = 1867; u <= 2026.05; u += 0.05) { yearT.push(t); t += 0.05 / rate(u); } }
  const f = Math.min(Math.max((y - 1867) / 0.05, 0), yearT.length - 1), k = Math.floor(f);
  return yearT[k] + (yearT[Math.min(k + 1, yearT.length - 1)] - yearT[k]) * (f - k);
}
function buildOpening() {
  const tB = performance.now();
  if (!tlItems) tlBuild();
  const pts = tlOcc.filter((o) => o.year > 0).map((o) => ({ x: (o.box[0] + o.box[3]) / 2, z: (o.box[2] + o.box[5]) / 2, y0: o.box[1], h: o.box[4] - o.box[1], year: o.year }));
  const Y1 = TOUR.target, Rc = OPEN.clusterM, wide = { target: TOUR.target, r: CINE.wideR, phi: CINE.wideTilt * D2R };
  const frame = (sh) => {
    const ps = pts.filter((p) => p.year >= sh.from && p.year < sh.to);
    if (!ps.length) return wide;
    let best = ps[0], bw = -1;   // the densest spot: most height within clusterM
    for (const p of ps) { let w = 0; for (const q of ps) if (Math.hypot(p.x - q.x, p.z - q.z) < Rc) w += q.h; if (w > bw) { bw = w; best = p; } }
    const cl = ps.filter((q) => Math.hypot(best.x - q.x, best.z - q.z) < Rc), W = cl.reduce((s, q) => s + q.h, 0);
    let cx = cl.reduce((s, q) => s + q.x * q.h, 0) / W, cz = cl.reduce((s, q) => s + q.z * q.h, 0) / W;
    const spread = Math.sqrt(cl.reduce((s, q) => s + q.h * ((q.x - cx) ** 2 + (q.z - cz) ** 2), 0) / W);
    const hmax = Math.max(...cl.map((q) => q.h)), gy = cl.reduce((s, q) => s + q.y0 * q.h, 0) / W;
    let r = Math.min(Math.max(1.8 * spread + 1.2 * hmax + 120, 250), 1300), ty = gy + 0.3 * hmax;
    if (sh.y1) {   // Y-1 in the frame too
      const d = Math.hypot(cx - Y1[0], cz - Y1[2]);
      cx = (cx + Y1[0]) / 2; cz = (cz + Y1[2]) / 2; ty = (ty + Y1[1]) / 2; r = Math.min(Math.max(r, 1.1 * d + 300), 1300);
    }
    const k = (r - 250) / (1300 - 250);
    return { target: [cx, ty, cz], r, phi: (66 - 16 * k) * D2R };
  };
  const end = playDur;
  openAnchors = OPEN.shots.map((sh, i) => {
    const t0 = yearTime(sh.from), t1 = yearTime(sh.to), q = 0.25 * (t1 - t0);
    return { hs: i === 0 ? 0 : t0 + q, he: i === OPEN.shots.length - 1 ? t0 + 2 * q : t1 - q, pose: frame(sh) };
  });
  openAnchors.push({ hs: end, he: end, pose: wide });   // and out to the whole site at the end
  ldur("opening shots (with tags data), ms", tB);
}
function openingPose(frac) {
  const t = frac * playDur, A = openAnchors;
  let P = A[A.length - 1].pose;
  for (let i = 0; i < A.length; i++) {
    if (t <= A[i].he) {
      if (i === 0 || t >= A[i].hs) { P = A[i].pose; break; }
      const a = A[i - 1], e = ease5((t - a.he) / Math.max(A[i].hs - a.he, 1e-3)), b = A[i].pose, p0 = a.pose;
      P = { target: p0.target.map((v, j) => v + (b.target[j] - v) * e), r: Math.exp(Math.log(p0.r) + (Math.log(b.r) - Math.log(p0.r)) * e), phi: p0.phi + (b.phi - p0.phi) * e };
      break;
    }
  }
  return { ...P, th: tour.th + (tour.turn ?? OPEN.turnDeg * D2R) * frac };
}
function startTour(frac0 = 0) {
  const th = sphOf(camera.position, controls.target).th;
  if (OPEN.mode === "B") {   // fly to where the opening is at this year
    // eased in from wherever the camera is (the same easing as after a pause), while the years already run
    buildOpening();
    // turning so that the opening ends on the film's first heading (time.cinema.shots[0].az), the same way round
    const az0 = (CINE.shots || [])[0]?.az, fwd = (a, b) => (((b - a) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    let turn = OPEN.turnDeg * D2R;
    if (az0 != null) { turn = fwd(th, az0 * D2R) / Math.max(1 - frac0, 0.1); if (turn < 90 * D2R) turn += 2 * Math.PI * (1 - frac0 > 0.1 ? 1 : 0); }
    tour = { th: th - turn * frac0, t: 0, turn }; rejoin = { from: camPose(), t0: performance.now() };
    return;
  }
  const tgt = new THREE.Vector3().fromArray(TOUR.target);
  _sph.set(TOUR.r0, (TOUR.tilt0 * Math.PI) / 180, th);
  goTo({ target: TOUR.target, position: tgt.clone().add(_off.setFromSpherical(_sph)).toArray() });
  tour = { th, t: 0 };
}
function tourPose(frac) {
  if (OPEN.mode === "B" && openAnchors) return openingPose(frac);
  const e = frac * frac * (3 - 2 * frac);
  return { target: TOUR.target, r: TOUR.r0 + (TOUR.r1 - TOUR.r0) * e, phi: ((TOUR.tilt0 + (TOUR.tilt1 - TOUR.tilt0) * e) * Math.PI) / 180,
           th: tour.th + (TOUR.turnDeg * Math.PI / 180) * frac };
}
function stepTour(dt, frac) {
  if (!tour || tween) return;
  controls.enableDamping = false;
  tour.frac = frac;
  camApply(tourPose(frac));
  invalidate();
}
function endTour() { if (tour) { tour = null; controls.enableDamping = true; } }
// Space pauses and resumes the opening and the film after it (user, 2026-10-13). While paused the camera is free; on
// resume the tour or film picks up from wherever the camera was left: its heading moves to the camera's, and distance,
// tilt and target ease over rejoinS seconds from the camera's to the shot's, so there is no jump.
let paused = false, rejoin = null;
const REJOIN_S = cfg.time?.rejoinS ?? 2.5;
const camPose = () => { const a = sphOf(camera.position, controls.target); return { target: controls.target.toArray(), r: a.r, phi: a.phi, th: a.th, fov: camera.fov }; };
// the field of view (vertical, degrees) of the Guided camera's poses; a pose without one has FOV0 (user, 2026-10-15: a
// dolly zoom on Y-1; the FOV only ever changes together with the distance, eased like the rest of the move)
const FOV0 = camera.fov;
function setFov(f) { if (Math.abs(camera.fov - f) > 1e-3) { camera.fov = f; camera.updateProjectionMatrix(); } }
const wrapA = (d) => Math.atan2(Math.sin(d), Math.cos(d));
function camApply(P) {
  if (rejoin) {
    const k = Math.min((performance.now() - rejoin.t0) / (REJOIN_S * 1000), 1), e = k * k * (3 - 2 * k), A = rejoin.from;
    P = { target: A.target.map((v, j) => v + (P.target[j] - v) * e), r: Math.exp(Math.log(A.r) + (Math.log(P.r) - Math.log(A.r)) * e),
          phi: A.phi + (P.phi - A.phi) * e, th: A.th + wrapA(P.th - A.th) * e, fov: (A.fov ?? FOV0) + ((P.fov ?? FOV0) - (A.fov ?? FOV0)) * e };
    if (k >= 1) rejoin = null;
  }
  setFov(P.fov ?? FOV0);
  controls.target.fromArray(P.target);
  _sph.set(P.r, P.phi, P.th);
  camera.position.copy(controls.target).add(_off.setFromSpherical(_sph));
  camera.lookAt(controls.target);
}
function setPaused(on) {
  if (on === paused) return;
  paused = on;
  timeState();
  if (on) { controls.enableDamping = true; if (cine) cine.pausedAt = performance.now(); cutEl.classList.remove("on"); return; }
  // resume: the shot's heading turns to the camera's, then everything else eases in
  const U = camPose(), now = performance.now();
  if (cine) {
    if (cine.pausedAt) { cine.t0 += now - cine.pausedAt; cine.pausedAt = 0; }
    if (cine.phase === "cut") cine.phase = "shot";
    // the film keeps its own headings (2026-10-15: each shot is framed from where its subject is clear); the rejoin
    // eases the camera back to it
  } else if (tour) tour.th += wrapA(U.th - tourPose(tour.frac ?? 0).th);
  if (cine || tour) { rejoin = { from: U, t0: now }; controls.enableDamping = false; }
}
addEventListener("keydown", (e) => {
  // typing in a text field: not ours; a focused checkbox or button (Through time, Play) would take the Space itself
  const t = document.activeElement, texty = t?.tagName === "TEXTAREA" || t?.tagName === "SELECT" || (t?.tagName === "INPUT" && !/^(checkbox|range|button|radio)$/.test(t.type));
  if (e.code !== "Space" || texty || !($("#timeOn").checked || cine)) return;
  t?.blur?.();
  e.preventDefault();   // not a click on the focused checkbox, not a page scroll
  if (playing || cine) setPaused(!paused);
  else if (scrubbed && viewMode === "history") goOnGuided();
  else if ($("#timeOn").checked) startPlay(false);   // stopped (the slider was moved, or the end): play
});
// a drag or scroll while the camera plays pauses it (user, 2026-10-13: it used to hand the camera back for good and the
// orbit never came back): a look around, after which it goes on by itself (autoResumeS) or with Space
for (const ev of ["pointerdown", "wheel"]) renderer.domElement.addEventListener(ev, () => { if (!paused && (tour || cine)) setPaused(true); }, { passive: true });
// years a second (user, 2026-10-15: the opening in about 53 s, the time where the building is): see RATE_TABLE below;
// 0.9 while an unbuilt scheme is on the site; config.json time.rates
const ghostSpans = [...ghostYears.values()].flat();
const RATES = { early: 7.5, late: 1.9, unbuilt: 0.9, ...(cfg.time?.rates || {}) };
// (user, 2026-10-15: time where the building is) years a second by period, config.json time.rates.table [[from, rate], ...]:
// quick through the empty early years, slower for the 1900-1930 boom and the towers of 1960-1980, quick again in between;
// the unbuilt schemes' years always at rates.unbuilt
const RATE_TABLE = (RATES.table || [[1867, RATES.early], [1950, RATES.late]]).slice().sort((p, q) => p[0] - q[0]);
const rate = (y) => {
  if (ghostSpans.some(([a, b]) => y >= a - 0.5 && y < b + 1)) return RATES.unbuilt;
  let r = RATE_TABLE[0][1]; for (const [from, v] of RATE_TABLE) if (y >= from) r = v; return r;
};
let playDur = 0;
for (let y = 1867; y < 2026; y += 0.05) playDur += 0.05 / rate(y);
let playing = null;
function stopPlay() { if (playing) cancelAnimationFrame(playing); playing = null; paused = false; rejoin = null; endTour(); endCine(); timeState(); }
// no Play button (user, 2026-10-13): Space plays, pauses and goes on; the panel only says which
function timeState() {
  const el = $("#timePlay"); if (!el) return;
  el.textContent = paused || scrubbed ? "Paused · Space" : playing || cine ? "Playing · Space to pause" : "Space to play";
}
function startPlay(withTour) {
  if (playing) stopPlay();
  let y = +$("#timeRange").value >= 2025.9 ? 1867 : +$("#timeRange").value, last = performance.now(), el = 0;
  if (withTour || y <= 1867) startTour(yearTime(y) / playDur);
  timeState();
  const step = (now) => {   // about a minute in all
    const dt = Math.min(Math.max((now - last) / 1000, 0), 0.1); last = now;   // a frame stamped before the start: 0
    if (paused) { playing = requestAnimationFrame(step); return; }
    el += dt;
    y = Math.min(2026, y + dt * rate(y));
    setYear(y);
    stepTour(dt, Math.min((OPEN.mode === "B" ? yearTime(y) : el) / playDur, 1));   // plan B: by the year
    if (y >= 2026) {   // the end: if the camera was left to the tour, it goes on filming (startCine)
      playing = null; timeState();
      const toured = Boolean(tour); endTour(); if (toured && CINE.on !== false) startCine();
      return;
    }
    playing = requestAnimationFrame(step);
  };
  playing = requestAnimationFrame(step);
  timeState();
}
$("#timePlay").onclick = () => (paused ? setPaused(false) : playing || cine ? setPaused(true) : startPlay(false));
// paused and left alone (user, 2026-10-13): it goes on by itself after autoResumeS seconds without a drag, scroll or key
const AUTO_RESUME_S = cfg.time?.autoResumeS ?? 4;
let pauseInput = 0;
for (const ev of ["pointerdown", "wheel", "keydown"]) addEventListener(ev, () => { pauseInput = performance.now(); }, { passive: true, capture: true });
addEventListener("pointermove", (e) => { if (e.buttons) pauseInput = performance.now(); }, { passive: true, capture: true });
setInterval(() => {
  const idle = AUTO_RESUME_S > 0 && performance.now() - pauseInput > AUTO_RESUME_S * 1000;
  if (paused && idle) setPaused(false);
  else if (scrubbed && idle && viewMode === "history" && !playing && !cine) goOnGuided();
}, 250);
setYear(2026);

// ---------- after the opening: the camera keeps filming (user, 2026-10-13) ----------
// When the opening has played to the end with the camera untouched, the camera goes on as a loop of shots, the way a
// film is cut: a wide establishing orbit of the whole site; a cut to a hero tower, low and close, craning up as it arcs
// round it; a flight back out to the whole site; a crane down onto Y-1; and so on. Every shot moves (an arc, a push, a
// crane), eases in and out, and lasts shotS seconds; into a close-up it cuts (a short dip to black), out of one it flies
// (blendS). The labels settle to one faint opacity; the hero of a shot comes up. Any drag or scroll hands the camera
// back. config.json time.cinema.
const CINE = { shotS: 10, blendS: 3.5, heroes: 4, heroWithinM: 700, wideR: 1300, wideTilt: 46, labelOpacity: 0.6,
               heroNames: ["Angels Flight"], ...(cfg.time?.cinema || {}) };
let cine = null;
const cutEl = document.createElement("div"); cutEl.id = "cut"; document.body.append(cutEl);
const D2R = Math.PI / 180;
function cineShots() {
  // the film by groups of places near each other (user, 2026-10-13), config.json time.cinema.shots in order: each shot
  // frames the box round its members (entity names, or "Angels Knoll" for the parcel) and lights their tags.
  // type: wide (the whole site, high), crane (down onto the group), low (at about the middle of its height, looking a
  // little up, arcing round), orbit (an oblique arc over a spread-out group), track (the view moves from one member to
  // another, low). cut: a dip to black into the shot (otherwise the camera flies there).
  const wide = { target: TOUR.target, r: [CINE.wideR, CINE.wideR * 0.9], tilt: [CINE.wideTilt, CINE.wideTilt + 4], turn: 25, keys: [] };
  const find = (n) => (tlItems || []).find((it) => it.name.toLowerCase() === n.toLowerCase());
  const boxOf = (items) => {
    const b = [1e9, 1e9, 1e9, -1e9, -1e9, -1e9];
    for (const it of items) for (let j = 0; j < 3; j++) { b[j] = Math.min(b[j], it.box[j]); b[j + 3] = Math.max(b[j + 3], it.box[j + 3]); }
    return { cx: (b[0] + b[3]) / 2, cz: (b[2] + b[5]) / 2, y0: b[1], h: b[4] - b[1], ext: Math.max(b[3] - b[0], b[5] - b[2], 40) };
  };
  const out = [];
  for (const def of CINE.shots || []) {
    const az = def.az == null ? null : def.az * D2R;   // the shot's heading at its start (0 = from the south, 90 = east)
    if (def.type === "wide") { out.push({ ...wide, s: def.s, az, hold: def.hold }); continue; }
    const items = (def.members || []).map(find).filter(Boolean);
    if (!items.length) continue;
    const g = boxOf(items), keys = items.map((it) => it.key), base = { keys, cut: Boolean(def.cut), s: def.s, az, hold: def.hold };
    const n0 = out.length;   // (overrides below apply to the shot pushed now)
    // a crane with a dolly zoom (dolly: [fov from, fov to]): it lowers (tilt) and backs away as the view narrows
    if (def.type === "crane" && def.dolly) out.push({ ...base, turn: 30, tilt: def.tilt ?? [40, 70], target: [g.cx, g.y0 + 0.3 * g.h, g.cz],
      r: [Math.max(3 * g.ext, 420)], fov: def.dolly, dolly: true });
    else if (def.type === "crane") out.push({ ...base, turn: 40, tilt: [28, 58], target: [g.cx, g.y0 + 0.3 * g.h, g.cz], r: [Math.max(4 * g.ext, 600), Math.max(1.6 * g.ext, 240)] });
    else if (def.type === "low") out.push({ ...base, turn: 35, tilt: [92, 82], target: [g.cx, g.y0 + 0.6 * g.h, g.cz], r: [Math.max(1.9 * g.ext, 1.5 * g.h, 220), Math.max(1.25 * g.ext, 1.0 * g.h, 150)] });
    // reveal (user, 2026-10-15): the one shot that uses occlusion. Moderately low over its group, it starts from a
    // heading where a tower stands in front and arcs (turn) until the group is in the clear, then holds on it
    else if (def.type === "reveal") out.push({ ...base, turn: 60, tilt: [74, 66], target: [g.cx, g.y0 + 0.3 * g.h, g.cz], r: [Math.max(3.2 * g.ext, 380), Math.max(2.6 * g.ext, 320)] });
    else if (def.type === "orbit") out.push({ ...base, turn: 45, tilt: [56, 48], target: [g.cx, g.y0 + 0.3 * g.h, g.cz], r: [Math.max(2.4 * g.ext, 380), Math.max(1.9 * g.ext, 300)] });
    else if (def.type === "track") {
      const A = find(def.from) ? boxOf([find(def.from)]) : g, B = find(def.to) ? boxOf([find(def.to)]) : g;
      out.push({ ...base, turn: 20, tilt: [80, 72], target: [A.cx, A.y0 + 12, A.cz], target1: [B.cx, B.y0 + 0.5 * B.h, B.cz], r: [160, 120] });
    }
    // per-shot framing (2026-10-15, people for scale in the tower shots): aim = the height looked at, as a share of the
    // group's height; tilt = [from, to] degrees from straight down; dist = a factor on the distance
    const o = out[n0];
    if (o && out.length > n0 && !o.target1) {
      if (def.aim != null) o.target = [o.target[0], g.y0 + def.aim * g.h, o.target[2]];
      if (def.tilt) o.tilt = def.tilt;
      if (def.dist) o.r = o.r.map((x) => x * def.dist);
    }
  }
  // a shot may set its own turn (degrees over the shot), e.g. a short arc so the next shot's heading follows on
  (CINE.shots || []).filter((d) => d.type === "wide" || (d.members || []).some(find)).forEach((d, k) => { if (d.turn != null && out[k]) out[k].turn = d.turn; });
  return out.length ? out : [wide];
}
// smoother camera (user, 2026-10-14): the arc turns at an even speed, always the same way round, so it never stops or
// turns back; distance, tilt and the point looked at ease with a quintic (no jolt at either end)
const ease5 = (t) => { t = Math.min(Math.max(t, 0), 1); return t * t * t * (t * (6 * t - 15) + 10); };
// a shot = its move (s seconds) + a hold (user, 2026-10-15, after Ozu and Deakins: time to read the tags and to see the
// people move): the arc slows over holdEaseS to holdDrift of its speed (never quite still) and the framing rests
const shotMove = (sh) => sh.s ?? CINE.shotS;
const shotHold = (sh) => sh.hold ?? (sh.keys?.length ? CINE.holdS ?? 2 : 0);
const shotLen = (sh) => shotMove(sh) + shotHold(sh);
const shotW = (sh, dir) => (dir * sh.turn * D2R) / shotMove(sh);   // its turning speed while it moves, radians a second
const shotWEnd = (sh, dir) => shotW(sh, dir) * (shotHold(sh) > 0 ? CINE.holdDrift ?? 0.1 : 1);   // at its end
function cinePose(sh, t, th0, dir) {
  const S = shotMove(sh), H = shotHold(sh), tau = t * (S + H), e = ease5(Math.min(tau / S, 1));
  const target = sh.target1 ? sh.target.map((v, j) => v + (sh.target1[j] - v) * e) : sh.target;
  const w0 = shotW(sh, dir), wd = w0 * (CINE.holdDrift ?? 0.1), D = Math.min(CINE.holdEaseS ?? 1.2, H || 1e-6);
  let a;
  if (tau <= S) a = w0 * tau;
  else { const x = tau - S; a = w0 * S + (x < D ? w0 * x - ((w0 - wd) * x * x) / (2 * D) : ((w0 + wd) * D) / 2 + wd * (x - D)); }
  const fov = sh.fov ? sh.fov[0] + (sh.fov[1] - sh.fov[0]) * e : FOV0;
  // a dolly zoom (after Vertigo): the camera backs away as the view narrows, by just as much, so the subject keeps its
  // size on screen and what stands behind it grows
  const r = sh.dolly ? (sh.r[0] * Math.tan((sh.fov[0] * D2R) / 2)) / Math.tan((fov * D2R) / 2)
                     : Math.exp(Math.log(sh.r[0]) + (Math.log(sh.r[1]) - Math.log(sh.r[0])) * e);
  return { target, r, phi: (sh.tilt[0] + (sh.tilt[1] - sh.tilt[0]) * e) * D2R, th: th0 + a, fov };
}
const cineApply = (P) => camApply(P);
// where the film's camera is meant to be now (also for the rejoin after a pause)
function cineNow(now) {
  const c = cine, sh = c.shots[c.i];
  if (c.phase === "blend" && c.from) {
    // the flight between two shots: the heading keeps turning, its speed going evenly from the last shot's to the next
    // one's (th0 of the next shot was set so that they meet), the rest eases (quintic)
    // (2026-10-15: each shot has its own heading az) the heading goes forward from where the last shot ended to the next
    // one's az, its position and speed both continuous at either end (cubic Hermite over c.blendT seconds)
    const T = c.blendT ?? CINE.blendS, tau = Math.min((now - c.t0) / 1000, T), k = tau / T, e = ease5(k);
    const A = c.from, B = cinePose(sh, 0, c.th0, c.dir), w0 = c.wFrom ?? 0, w1 = shotW(sh, c.dir);
    const s = k, h00 = 2 * s ** 3 - 3 * s * s + 1, h10 = s ** 3 - 2 * s * s + s, h01 = -2 * s ** 3 + 3 * s * s, h11 = s ** 3 - s * s;
    return { target: A.target.map((v, j) => v + (B.target[j] - v) * e), r: Math.exp(Math.log(A.r) + (Math.log(B.r) - Math.log(A.r)) * e),
             phi: A.phi + (B.phi - A.phi) * e, th: h00 * A.th + h10 * T * w0 + h01 * c.th0 + h11 * T * w1,
             fov: (A.fov ?? FOV0) + ((B.fov ?? FOV0) - (A.fov ?? FOV0)) * e, k };
  }
  const len = shotLen(sh) * 1000;
  return { ...cinePose(sh, Math.min((now - c.t0) / len, 1), c.th0, c.dir), k: (now - c.t0) / len };
}
function startCine() {
  const shots = cineShots(); if (!shots.length) return;
  controls.enableDamping = false;
  let th = sphOf(camera.position, controls.target).th;
  if (shots[0].az != null) th += wrapA(shots[0].az - th);   // the opening ends on it; a small step if it was left elsewhere
  cine = { shots, i: 0, phase: "shot", t0: performance.now(), th0: th, dir: 1, from: null, op0: performance.now() };
  timeState();
}
function endCine() {
  if (!cine) return;
  cine = null; cutEl.classList.remove("on"); controls.enableDamping = true; invalidate();
  timeState();
}
function nextShot(now, P) {   // now: the exact time the last shot ended
  const c = cine;
  // after the last shot the film goes back to shot loopFrom (2026-10-15: from the Y-1 reveal straight to the Y-1 track,
  // the opening's wide shot and crane only once), always the same way round
  const nextI = c.i + 1 < c.shots.length ? c.i + 1 : Math.min(CINE.loopFrom ?? 0, c.shots.length - 1);
  const prev = c.shots[c.i], sh = c.shots[nextI];
  c.i = nextI;
  if (sh.cut) {   // dip to black, jump, come up on the new shot
    c.th0 = P.th; c.phase = "cut"; c.t0 = now; cutEl.classList.add("on");
  } else {
    c.wFrom = shotWEnd(prev, c.dir);
    const w1 = shotW(sh, c.dir), wm = Math.max(Math.abs(c.wFrom), Math.abs(w1)) || 0.05;   // the faster of the two
    // the flight's length: at least blendS, and long enough that the camera never goes faster than maxFlyMS on average
    const B0 = cinePose(sh, 0, sh.az ?? P.th, c.dir), pos = (Q) => { _sph.set(Q.r, Q.phi, Q.th); return _off.setFromSpherical(_sph).clone().add(_tv.fromArray(Q.target)); };
    const dist = pos(P).distanceTo(pos({ ...B0, th: P.th }));
    let T = Math.min(Math.max(CINE.blendS, dist / (CINE.maxFlyMS ?? 150)), 12);
    if (sh.az == null) c.th0 = P.th + ((c.wFrom + w1) / 2) * T;   // no heading of its own: where the even speed lands
    else {
      let d = ((sh.az - P.th) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);   // forward to its heading
      if (d > 1.9 * Math.PI) d = 0;            // just past it: take it as reached
      T = Math.min(Math.max(T, d / (1.6 * wm)), 12);   // a long turn is not hurried
      // always forward on the way: the Hermite's middle speed 1.5 d / T - (w0 + w1) / 4 stays positive with some margin;
      // when the shot's heading is too near, it starts a little past it
      d = Math.max(d, 0.25 * (Math.abs(c.wFrom) + Math.abs(w1)) * T);
      c.th0 = P.th + d;
    }
    c.blendT = T; c.phase = "blend"; c.from = P;
    c.t0 = now;
  }
}
// People comes on peopleDelayS into shot peopleAfter (user, 2026-10-15: 2 s into the first wide shot, once the camera
// has settled after the opening), the film going on with them; its day starts before dawn (peopleStartH), most people
// at home, and the city wakes up as they set out. The clock is set before they show (popStartT).
function peopleOnNow() {
  if ($("#popOn").checked) return;
  popStartT = (CINE.peopleStartH ?? 5) * 3600;
  $("#popOn").checked = true; $("#popOn").onchange({ target: $("#popOn") });
}
function stepCine(now) {
  const c = cine, sh = c.shots[c.i];
  if (paused) return;
  if (!c.peopleDone && CINE.thenPeople !== false && c.i === (CINE.peopleAfter ?? 0) && c.phase === "shot" && now - c.t0 > (CINE.peopleDelayS ?? 2) * 1000) {
    c.peopleDone = true; peopleOnNow();
  }
  if (c.phase === "cut") {
    if (now - c.t0 < 280) return;   // the screen is going dark
    c.phase = "shot"; c.t0 = now; cutEl.classList.remove("on"); rejoin = null;
  }
  let P = cineNow(now);
  // a phase that ended during this frame hands over at its exact end time, and this frame already shows the next one
  // (2026-10-15: the camera stood still for a frame at every change of shot)
  if (c.phase === "blend" && P.k >= 1) {
    const end = c.t0 + c.blendT * 1000; c.phase = "shot"; c.t0 = end; c.from = null; P = cineNow(now);   // the flight ended on th0
  } else if (c.phase === "shot" && P.k >= 1) {
    const end = c.t0 + shotLen(sh) * 1000, E = cinePose(sh, 1, c.th0, c.dir);
    nextShot(end, E);
    if (c.phase !== "cut") P = cineNow(now);
  }
  cineApply(P);
}
function handBack() { endTour(); endCine(); }

// its own controls (time, play, day, attendance ...) change the picture: draw again
for (const ev of ["input", "change", "click"]) $("#popSec").addEventListener(ev, () => invalidate());
// a clicked person's modeled day (population.js story()) as a floating tag that follows them. how: "only" (Alt + click),
// "add" (Shift + Alt + click: one more label), "refresh" (same person, new day: the label's text only)
let popSelecting = false;
function personTag(html, pos, i, how = "only") {
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
  const key = `pop:${i}`, build = () => tagHTML(`Modeled person ${num}`, title, day, rows, note);
  if (how === "refresh") { const s = selection.find((x) => x.key === key); if (s) { s.build = build; fillTag(s); invalidate(); } return; }
  popSelecting = true;
  select(key, { centre: pos, topY: pos.y, height: 0 }, build, [], how === "add");
  popSelecting = false;
}

// ---------- click for details: a design mesh, else the LiDAR point under the cursor ----------
const ray = new THREE.Raycaster();
const SKIP_KEYS = new Set(["layer", "name", "scatter5"]);
let down = null;
renderer.domElement.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
renderer.domElement.addEventListener("pointerup", (e) => {
  if (PERF) PERF.clickAt = performance.now();
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  ray.setFromCamera(new THREE.Vector2((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1), camera);
  // Alt + click picks the person within PICK_PX on screen (user, 2026-10-09: a plain click is for buildings / points)
  // Shift + Alt + click adds the person (any person, also the faded ones) or takes them out (user, 2026-10-12)
  // (no one near: nothing happens, rather than adding the ground or a building to the selection)
  if (pop?.visible && e.altKey) { if (pop.pickIndex(pop.nearest(e.clientX, e.clientY, PICK_PX, e.shiftKey), e.shiftKey) || e.shiftKey) return; }
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
  if (node.userData.ghost) return select(`g:${node.name}`, a, ghostTag(node.userData.ghost), [], add);
  if (en) return select(`m:${en.id}`, a, entityTag(en), [], add);
  select(`m:${node.uuid}`, a, objectTag(node, hit.point, null), [], add);

  // LiDAR: the clicked point's object label -> its entity or object; highlight all its points
  // The click takes the nearest drawn point within PICK_LIDAR_PX on screen (at least 0.6 m), so a click between the
  // points of a thinned, far building still finds it (user, 2026-10-12: clicks on buildings were often missed; the old
  // fixed 0.6 m is less than a pixel gap seen from far away). Where a facade has no returns (glass) the click still
  // goes through to what is behind.
  function pickLidar() {
    const perPx = (d) => (2 * d * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / innerHeight;
    const tol = (d) => Math.max(0.6, perPx(d) * PICK_LIDAR_PX);
    ray.params.Points.threshold = tol(camera.position.distanceTo(controls.target) * 2);
    const hit = ray.intersectObjects(lidarGroup.children.filter((p) => p.visible), false).find((h) => h.distanceToRay <= tol(h.distance));
    if (!hit) return add ? undefined : hideInfo();
    const id = hit.object.userData.part.ob[hit.index], name = lidar.objNames[id];
    const node = model.getObjectByName(name) || { name: name === "_other" ? "Unassigned LiDAR points" : name,
                                                  userData: { layer: lidar.objLayers[id] } };
    // layers with "highlight": false in config.json (e.g. Terrain) show their info but are not lit
    const lit = name !== "_other" && cfg.layers[lidar.objLayers[id]]?.highlight !== false;
    if (node.userData?.ghost) return select(`o:${id}`, anchorOf(new Set([id])) || pointAnchor(hit.point), ghostTag(node.userData.ghost), [id], add);
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
  const js = new Set(); for (const k of objSet) for (const j of lidar.objParts[k]) js.add(j);   // only the chunks holding them
  const ps = [...js].map((j) => lidar.parts[j]);
  for (const p of ps) for (let i = 0; i < p.n; i++) if (objSet.has(p.ob[i])) {
    const y = p.pos[3 * i + 1]; if (y > maxY) maxY = y; if (y < minY) minY = y;
    sx += p.pos[3 * i]; sz += p.pos[3 * i + 2]; n++;
  }
  if (!n) return null;
  // height = height above ground of the highest points (LiDAR hag): right on slopes too (Angels Flight)
  let hagTop = -1e9;
  for (const p of ps) if (p.hag) for (let i = 0; i < p.n; i++) if (objSet.has(p.ob[i]) && p.pos[3 * i + 1] > maxY - 1.5) hagTop = Math.max(hagTop, p.hag[i] * 0.1);
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
  // refilled in place (units switch): an open Details stays open (user, 2026-10-10)
  const wasOpen = s.el.querySelector(".dd")?.open;
  s.el.innerHTML = s.build(s.a);
  if (wasOpen) s.el.querySelector(".dd")?.setAttribute("open", "");
  s.el.querySelector(".x").onclick = (ev) => { ev.stopPropagation(); deselect(s.key); };
  const dd = s.el.querySelector(".dd");
  if (dd) dd.ontoggle = () => {
    invalidate();   // the label grows / shrinks: place it again
  };
}
function select(key, a, build, objs, add) {
  if (PERF?.clickAt) { PERF.click = performance.now() - PERF.clickAt; PERF.clickAt = 0; }
  if (!add) clearSelection(false);   // painted once below: the old object fades out while the new one fades in
  const old = selection.find((s) => s.key === key);
  if (old) { if (add) deselect(key); return; }            // shift + click on a selected object: take it out
  const el = document.createElement("div"); el.className = "tag"; document.body.append(el);
  const line = document.createElementNS(svgNS, "line"); leadSvg.append(line);
  // fade in over --t-in (the label's CSS transition); the line follows
  el.style.opacity = "0"; line.style.opacity = "0"; line.style.transition = "opacity var(--t-in) ease";
  requestAnimationFrame(() => requestAnimationFrame(() => { el.style.opacity = ""; line.style.opacity = ""; }));
  const s = { key, a, build, objs, el, line };
  fillTag(s); selection.push(s);
  if (lidar && mode === "cloud") paintSelection();
  invalidate(); wake();
}
// a tag and its line fade out over --t-out, then go (user, 2026-10-10: Esc should not make them vanish at once)
function fadeAway(s) {
  for (const n of [s.el, s.line]) { n.style.transition = "opacity var(--t-out) ease"; n.style.opacity = "0"; n.style.pointerEvents = "none"; }
  setTimeout(() => { s.el.remove(); s.line.remove(); }, tms("--t-out"));
}
function deselect(key) {
  const i = selection.findIndex((s) => s.key === key); if (i < 0) return;
  const [s] = selection.splice(i, 1); fadeAway(s);
  if (s.key.startsWith("pop:") && !popSelecting) pop?.deselectPerson(+s.key.slice(4));
  if (lidar && mode === "cloud") paintSelection();
  invalidate();
}
function clearSelection(paint = true) {
  for (const s of selection.splice(0)) { fadeAway(s); if (s.key.startsWith("pop:") && !popSelecting) pop?.clearSelection(); }
  if (paint && lidar && mode === "cloud") paintSelection();
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
// ---------- Time module: labels on the buildings going up ----------
// (user, 2026-10-13: the buildings that go up get their name and year, floating, after the Connections page's blob
// tracking) a tracking frame locks on to each building as it starts to rise and grows with it, a readout beside it
// (name, year, height); only named buildings and landmarks (user, 2026-10-13: 300 labels by address were a mess). A
// building once labelled keeps its frame and text after it is finished, fading slowly (fadeYears) to doneOpacity; once
// the opening is over and the camera films (startCine) they all settle to one opacity, so the buildings stand out, and
// the hero of a shot comes up (user, 2026-10-13). A text with no free place hides (it keeps its place while it can,
// so labels do not hop about). No connecting curves. At most
// time.labels.max new ones going up at once, the tallest first; unbuilt towers always. Screen space, after every render.
const TL = { max: 8, holdYears: 2, minHeightM: 25, noHeight: ["Angels Flight"], ...(cfg.time?.labels || {}) };
const tlLayer = document.createElement("div"); tlLayer.id = "tlabels"; document.body.append(tlLayer);
let tlItems = null;   // { key, name, kind, year, end, box: [x0, y0, z0, x1, y1, z1], h, ent }
let tlOcc = [];       // every building's box, for the labels' line of sight: { box, year (0 = undated), ent }
// the Y-1 parcel (population.json y1: [x east, y north]), for the Angels Knoll label and shot
let y1Ring = null;
if (cfg.population?.meta) fetch(cfg.population.meta).then((r) => r.json()).then((m) => { y1Ring = m.y1?.[0] ?? null; }).catch(() => {});
const tlShown = new Map();   // key -> { el }
const tlEver = new Set();    // labelled once: kept while the year is past its start
let tlLast = 0, tlMaskKey = "";
function tlBuild() {
  const tT = performance.now();
  tlItems = [];
  const filmNames = new Set((CINE.shots || []).flatMap((d) => d.members || []).map((n) => n.toLowerCase()));
  const ents = ENTITIES?.entities ?? [], nE = ents.length, B = new Float32Array(nE * 6);
  for (let i = 0; i < nE; i++) B.set([1e9, 1e9, 1e9, -1e9, -1e9, -1e9], 6 * i);
  // each entity's box from the 1 % / 99 % of its points along x and z and 0.5 % / 99.5 % in height (2026-10-15: a few
  // stray points made low buildings look 30 m tall, their tags and line-of-sight boxes too large)
  const acc = new Map();
  for (const p of lidar.parts) for (let i = 0; i < p.n; i++) {
    const e = lidar.objEntity[p.ob[i]]; if (e < 0 || lidar.objLayers[p.ob[i]] === "Terrain") continue;
    let a = acc.get(e); if (!a) acc.set(e, (a = [[], [], []]));
    if (a[0].length < 8000 || (i & 3) === 0) { a[0].push(p.pos[3 * i]); a[1].push(p.pos[3 * i + 1]); a[2].push(p.pos[3 * i + 2]); }
  }
  const pct = (v, q) => v[Math.min(v.length - 1, Math.max(0, Math.round(q * (v.length - 1))))];
  for (const [e, a] of acc) {
    for (const v of a) v.sort((p, q) => p - q);
    B.set([pct(a[0], 0.01), pct(a[1], 0.005), pct(a[2], 0.01), pct(a[0], 0.99), pct(a[1], 0.995), pct(a[2], 0.99)], 6 * e);
  }
  ents.forEach((e, i) => {
    const y = parseInt(e.built?.[0] ?? e.parcel?.year_built, 10), o = 6 * i;
    if (B[o] > 1e8) return;
    // an entity spread over more than maxExtentM is a data error, not a building (user, 2026-10-15: A0003 "411 N Boylston
    // St" has one part scattered over 2 km, so its box hid half the site): no tag, no line-of-sight box
    if (Math.max(B[o + 3] - B[o], B[o + 5] - B[o + 2]) > (TL.maxExtentM ?? 600)) return;
    const h = B[o + 4] - B[o + 1], box = Array.from(B.subarray(o, o + 6));
    if (h >= 6) tlOcc.push({ box, year: y > 1000 ? y : 0, ent: i });
    if (!(y > 1000) && !filmNames.has(e.name.toLowerCase())) return;   // undated: only the film's members (always there)
    if (TL.namedOnly !== false && e.status === "auto" && !e.landmark) return;   // automatic entities are only an address
    if (h < TL.minHeightM && !filmNames.has(e.name.toLowerCase())) return;   // a member of a film shot: tagged anyway
    // keep: a building the film is about (a member of time.cinema.shots) keeps its tag once built; the others show
    // theirs while they go up and fade out after (user, 2026-10-15: too many tags during the building)
    tlItems.push({ key: `e${i}`, name: e.name, kind: "built", year: y > 1000 ? y : 0, box, h, ent: i, keep: filmNames.has(e.name.toLowerCase()) });
  });
  // Angels Knoll, the Y-1 parcel: a frame over its ground (the terrain points inside the parcel)
  if (y1Ring) {
    const ring = y1Ring.map(([x, n]) => [x, -n]);
    let x0 = 1e9, z0 = 1e9, x1 = -1e9, z1 = -1e9, lo = 1e9, hi = -1e9;
    for (const [x, z] of ring) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z); }
    const inside = (x, z) => { let c = false; for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) {
      if ((ring[a][1] > z) !== (ring[b][1] > z) && x < ((ring[b][0] - ring[a][0]) * (z - ring[a][1])) / (ring[b][1] - ring[a][1]) + ring[a][0]) c = !c; } return c; };
    for (const p of lidar.parts) {
      if (p.name !== "Terrain" && p.name !== lidar.objLayers[lidar.objNames.indexOf("Terrain")]) continue;
      for (let i = 0; i < p.n; i++) {
        const x = p.pos[3 * i], z = p.pos[3 * i + 2]; if (x < x0 || x > x1 || z < z0 || z > z1 || !inside(x, z)) continue;
        const y = p.pos[3 * i + 1]; if (y < lo) lo = y; if (y > hi) hi = y;
      }
    }
    if (hi > lo) tlItems.push({ key: "site:y1", name: "Angels Knoll", kind: "site", sub: "Parcel Y-1", box: [x0, lo, z0, x1, hi, z1], h: hi - lo });
  }
  for (const g of ghostLabels) tlItems.push(g);
  lonce("tags data (tlBuild) at"); ldur("tags data (tlBuild), ms", tT);
}
const tlEase = (t) => { t = Math.min(Math.max(t, 0), 1); return t * t * (3 - 2 * t); };
// 1 if the line from the camera to (x, y, z) passes no standing building (other than `own`), else 0. Boxes drawn in to
// 80 % in plan: a building's box is larger than the building (it is not turned with it)
function tlSees(x, y, z, own, Y) {
  const o = camera.position, dx = x - o.x, dy = y - o.y, dz = z - o.z;
  for (const b of tlOcc) {
    if (b.ent === own || (b.year && b.year > Y)) continue;
    const [x0, y0, z0, x1, y1, z1] = b.box, mx = (x1 - x0) * 0.1, mz = (z1 - z0) * 0.1;
    let t0 = 0, t1 = 0.97;
    for (const [oo, d, lo, hi] of [[o.x, dx, x0 + mx, x1 - mx], [o.y, dy, y0, y1], [o.z, dz, z0 + mz, z1 - mz]]) {
      if (Math.abs(d) < 1e-9) { if (oo < lo || oo > hi) { t0 = 2; break; } continue; }
      let a = (lo - oo) / d, c = (hi - oo) / d; if (a > c) [a, c] = [c, a];
      if (a > t0) t0 = a; if (c < t1) t1 = c; if (t0 > t1) break;
    }
    if (t0 <= t1) return 0;
  }
  return 1;
}
function updateTimeTags() {
  const Y = TIME.year.value, Bd = TIME.build.value, on = TIME.on.value > 0.5 && lidar && mode === "cloud";
  if (on && !tlItems) tlBuild();
  const W = innerWidth, H = innerHeight;
  // who is up now: rising (or finished within holdYears), or labelled before; unbuilt towers while on the site
  const live = [], kept = [];
  if (on) for (const it of tlItems) {
    let p, a, txt = true;
    if (it.kind === "site" || (it.kind === "built" && !it.year)) {   // Angels Knoll, undated members: quiet, and only
      // once the building is over (2026), so no tag stands on a site before its time (user, 2026-10-15)
      if (Y < 2025) continue;
      p = 1; a = (TL.doneOpacity ?? 0.7) * Math.min(1, Y - 2025); kept.push({ it, p, a, txt, rising: false }); continue;
    } else if (it.kind === "unbuilt") {
      const sp = it.end - it.year + 1, up = Math.min(Bd, 0.6 * sp), dn = Math.min(1.5, 0.3 * sp);
      if (Y < it.year || Y >= it.year + sp) continue;
      p = tlEase(Math.min((Y - it.year) / up, (it.year + sp - Y) / dn)); a = Math.min(1, (Y - it.year) / 0.4, (it.year + sp - Y) / dn);
    } else {
      if (Y < it.year - Bd) { tlEver.delete(it.key); continue; }
      const ever = it.keep && (tlEver.has(it.key) || Y > it.year);   // only the film's buildings stay, labelled or not while rising
      const outY = it.year + TL.holdYears + (TL.fadeOutYears ?? 1.5);   // the others: gone by then
      if (!ever && Y > (it.keep ? it.year + TL.holdYears : outY)) continue;
      p = tlEase((Y - it.year + Bd) / Bd);
      const done = Y > it.year + TL.holdYears, fade = tlEase((Y - it.year) / (TL.fadeYears ?? 8));
      a = Math.min(1, (Y - it.year + Bd) / 0.4) * (1 + ((TL.doneOpacity ?? 0.7) - 1) * fade);
      if (!it.keep) a *= Math.min(1, Math.max(0, (outY - Y) / (TL.fadeOutYears ?? 1.5)));   // fading out once built
      if (ever) { kept.push({ it, p, a, txt, rising: !done }); continue; }
    }
    live.push({ it, p, a, txt, rising: true });
  }
  live.sort((u, v) => (v.it.kind === "unbuilt") - (u.it.kind === "unbuilt") || v.it.h - u.it.h);
  const keep = kept.concat(live.slice(0, TL.max)), keys = new Set(keep.map((l) => l.it.key));
  for (const l of keep) if (l.it.kind !== "unbuilt") tlEver.add(l.it.key);
  for (const [k, s] of tlShown) if (!keys.has(k)) {   // gone: fade out, then leave
    tlShown.delete(k); s.el.classList.add("out");
    setTimeout(() => s.el.remove(), 450);
  }
  const placed = [], ui = $("#ui").getBoundingClientRect();
  // the left panel, while it shows (it fades out when idle): whatever part of a tag lies under it is dimmed to
  // hiddenOpacity by a mask over the tag layer, as a building in front would (user, 2026-10-13: tags showed through the
  // frosted panel; a fade by the share under it was too weak), and no text goes under it
  const uiOp = ui.width > 0 ? +getComputedStyle($("#ui")).opacity : 0, uiOn = uiOp > 0.5;
  if (uiOp > 0.01 && on) {
    // an SVG mask the size of the window: opaque, with the panel's rounded rectangle at 1 - k (rebuilt only on change)
    const k = (1 - (TL.hiddenOpacity ?? 0.15)) * uiOp, rad = parseFloat(getComputedStyle($("#ui")).borderTopLeftRadius) || 0;
    const key = [W, H, ui.left, ui.top, ui.width, ui.height, rad, k.toFixed(2)].map((v) => Math.round(+v * 100) / 100).join();
    if (key !== tlMaskKey) {
      tlMaskKey = key;
      const [x, y, w, h] = [ui.left, ui.top, ui.width, ui.height].map((v) => v.toFixed(1)), r0 = rad.toFixed(1);
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><path fill-rule="evenodd" d="M0 0H${W}V${H}H0Z`
        + `M${+x + +r0} ${y}H${+x + +w - +r0}A${r0} ${r0} 0 0 1 ${+x + +w} ${+y + +r0}V${+y + +h - +r0}A${r0} ${r0} 0 0 1 ${+x + +w - +r0} ${+y + +h}`
        + `H${+x + +r0}A${r0} ${r0} 0 0 1 ${x} ${+y + +h - +r0}V${+y + +r0}A${r0} ${r0} 0 0 1 ${+x + +r0} ${y}Z"/>`
        + `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r0}" fill-opacity="${(1 - k).toFixed(3)}"/></svg>`;
      tlLayer.style.maskImage = tlLayer.style.webkitMaskImage = `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
      tlLayer.style.maskSize = tlLayer.style.webkitMaskSize = "100% 100%";
      tlLayer.style.maskRepeat = tlLayer.style.webkitMaskRepeat = "no-repeat";
    }
  } else if (tlMaskKey) { tlMaskKey = ""; tlLayer.style.maskImage = tlLayer.style.webkitMaskImage = "none"; }
  if (uiOp > 0.01 && uiOp < 0.99) invalidate();   // the panel is fading in or out: follow it
  const underUi = (x0, y0, x1, y1) => {
    if (!uiOn) return 0;
    const w = Math.max(0, Math.min(x1, ui.right) - Math.max(x0, ui.left)), h = Math.max(0, Math.min(y1, ui.bottom) - Math.max(y0, ui.top));
    return (w * h) / Math.max((x1 - x0) * (y1 - y0), 1);
  };
  // texts placed in order of importance: going up and unbuilt first, then the tallest; a text with no free place hides
  const lit = new Set(cine ? cine.shots[cine.i].keys || [] : []);   // the tags of the shot's group
  const rank = (l) => (lit.has(l.it.key) ? -1 : l.it.kind === "unbuilt" ? 0 : l.rising ? 1 : 2);
  const now = performance.now(), dt = Math.min((now - (tlLast || now)) / 1000, 0.1); tlLast = now;
  for (const { it, p, a: a0, txt } of keep.sort((u, v) => rank(u) - rank(v) || v.it.h - u.it.h)) {
    // while filming: every label at one opacity, the shot's hero full
    const hero = lit.has(it.key);
    let a = cine ? (hero ? 1 : CINE.labelOpacity) : a0;
    // depth (user, 2026-10-13: labels sat over the buildings, near and far alike): a label whose building is hidden
    // behind a standing building fades (lines of sight to its top and its middle against the other buildings' boxes,
    // drawn in a little); far ones are quieter; near ones are drawn over far ones
    const [bx0, by0, bz0, bx1, by1, bz1] = it.box, cx = (bx0 + bx1) / 2, cz = (bz0 + bz1) / 2, ty = by0 + (by1 - by0) * Math.max(p, 0.02);
    const dist = camera.position.distanceTo(_tv.set(cx, (by0 + ty) / 2, cz));
    // four lines of sight (top, three quarters, middle, a quarter up), so a building half hidden gives a half, and the
    // share is eased (tag.seen) rather than flipping as a line grazes a corner (user, 2026-10-13: tags flickered)
    // (user, 2026-10-13: from above the tags were nearly invisible) a building whose top can be seen counts as seen:
    // lines to its lower parts cross the neighbours' boxes from above, though the roof is in plain view
    const hy = ty - by0;
    const seen = tlSees(cx, ty, cz, it.ent, Y) ? 1
      : (tlSees(cx, by0 + 0.75 * hy, cz, it.ent, Y) + tlSees(cx, by0 + 0.5 * hy, cz, it.ent, Y) + tlSees(cx, by0 + 0.25 * hy, cz, it.ent, Y)) / 4;
    const ref = camera.position.distanceTo(controls.target);
    let s = tlShown.get(it.key);
    if (!s) {
      const el = document.createElement("div"); el.className = "tblob" + (it.kind === "unbuilt" ? " ghost" : "");
      // no height for what is not a building (user, 2026-10-13: Angels Flight's is the rise of its track)
      const noH = (TL.noHeight || []).some((n) => n.toLowerCase() === it.name.toLowerCase());
      el.innerHTML = `<i><b>${esc(it.name)}</b>${it.kind === "site" ? esc(it.sub) : [it.kind === "unbuilt" ? `Unbuilt · ${it.year}–${it.end}` : it.year ? `Built ${it.year}` : "", noH ? "" : len(it.h)].filter(Boolean).join(" · ")}</i>`;
      tlLayer.append(el);
      // the lock-on plays once: after it the frame is "locked", so showing it again does not replay it
      el.addEventListener("animationend", () => el.classList.add("locked"), { once: true });
      tlShown.set(it.key, (s = { el, seen }));
    }
    const ease = (tau) => 1 - Math.exp(-dt / tau);   // exponential easing, tau seconds
    s.seen += (seen - s.seen) * ease(0.35);
    a *= (TL.hiddenOpacity ?? 0.15) + (1 - (TL.hiddenOpacity ?? 0.15)) * s.seen;
    a *= Math.min(1, Math.max(TL.farOpacity ?? 0.75, 1 - 0.5 * (dist / ref - 1.2)));   // only past 1.2 x the view's distance
    a = Math.max(a, TL.minOpacity ?? 0.25);
    if (hero) a = Math.max(a, 0.6);
    // the frame: the building's box up to the height it has reached, projected
    const [x0, y0, z0, x1, y1, z1] = it.box, top = y0 + (y1 - y0) * Math.max(p, 0.02);
    let sx0 = 1e9, sy0 = 1e9, sx1 = -1e9, sy1 = -1e9, behind = false;
    for (const x of [x0, x1]) for (const y of [y0, top]) for (const z of [z0, z1]) {
      _tv.set(x, y, z).project(camera); if (_tv.z > 1) behind = true;
      const sx = ((_tv.x + 1) / 2) * W, sy = ((1 - _tv.y) / 2) * H;
      sx0 = Math.min(sx0, sx); sx1 = Math.max(sx1, sx); sy0 = Math.min(sy0, sy); sy1 = Math.max(sy1, sy);
    }
    // out of view: it fades out where it is (no display: none, which made it blink and replay its lock-on)
    const off = behind || sx1 < 0 || sx0 > W || sy1 < 0 || sy0 > H;
    if (off) a = 0;
    s.op = s.op === undefined ? a : s.op + (a - s.op) * ease(0.3);
    if (Math.abs(a - s.op) > 0.004) invalidate();
    s.el.style.opacity = s.op.toFixed(3);
    s.el.style.visibility = s.op < 0.01 ? "hidden" : "";
    if (behind) continue;   // its projection means nothing: it stays where it was while it fades
    const w = Math.max(sx1 - sx0, 6), h = Math.max(sy1 - sy0, 6);
    s.el.style.translate = `${sx0}px ${sy0}px`; s.el.style.width = `${w}px`; s.el.style.height = `${h}px`;
    s.el.style.zIndex = String(Math.max(1, Math.round(100000 - dist)));
    if (off) continue;
    // the readout: beside the frame's top, on the side away from the screen's centre, clear of the panel and the others
    const r = s.el.firstChild;
    if (!txt) { r.classList.add("hid"); continue; }
    if (!s.rw) { s.rw = r.offsetWidth; s.rh = r.offsetHeight; }   // measured once (its text does not change)
    // the text sits by the frame's top, but inside the window: a tower taller than the view keeps its text at the top
    // edge, beside it (user, 2026-10-13: the group's tags were out of sight in the low shots)
    const tyA = Math.min(Math.max(sy0, 10), Math.max(sy1 - 30, 10), H - 40);
    const rw = s.rw, rh = s.rh, pref = sx0 + w / 2 > W / 2 || (ui.width > 0 && sx0 < ui.right + 160);
    const free = (rx, ay) => rx > 4 && rx + rw < W - 4 && !underUi(rx, ay, rx + rw, ay + rh) && !placed.some((q) => rx < q.x + q.w + 4 && rx + rw + 4 > q.x && ay < q.y + q.h + 3 && ay + rh + 3 > q.y);
    let spot = null;
    const tries = [[pref, 0], [pref, rh + 4], [pref, -(rh + 4)], [!pref, 0], [!pref, rh + 4], [!pref, -(rh + 4)]];
    if (s.spot) tries.unshift([s.spot.left, s.spot.ry]);   // where it was, first
    for (const [left, ry] of tries) {
      const rx = left ? sx1 + 6 : sx0 - 6 - rw;
      if (!spot && free(rx, tyA + ry)) spot = { left, ry, rx };
    }
    // the text hides or comes back only after it has had (or lacked) a free place for a moment (hysteresis), and fades
    // (CSS). A shown text stays where it is; it moves only while hidden, so it never hops about.
    const shown = !r.classList.contains("hid");
    const oldFree = s.spot && free(s.spot.left ? sx1 + 6 : sx0 - 6 - rw, tyA + s.spot.ry);
    const want = shown ? Boolean(oldFree || (!s.spot && spot)) : Boolean(spot);
    s.wait = want === shown ? 0 : (s.wait || 0) + dt;
    if (s.wait > (want ? 0.5 : 0.35)) { r.classList.toggle("hid", !want); s.wait = 0; if (want) s.spot = spot; }
    else if (!s.spot && spot) s.spot = spot;
    if (r.classList.contains("hid") || !s.spot) continue;
    const sp = s.spot, rx = sp.left ? sx1 + 6 : sx0 - 6 - rw;
    r.classList.toggle("r", sp.left); r.style.top = `${tyA - sy0 + sp.ry}px`;
    placed.push({ x: rx, y: tyA + sp.ry, w: rw, h: rh });
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
// the assessor's use codes in plain words (the "Now" row of a landmark)
const ASSESSOR_USE = { "single": "condominiums", "five or more apartments": "apartments", "store combination": "shops with offices or apartments",
  "office buildings": "offices", "hotel & motels": "hotel", "department stores": "department store", "stores": "shops",
  "restaurants, cocktail lounges": "restaurant", "parking lots (commercial use properties)": "parking", "government parcel": "government",
  "churches": "church", "professional buildings": "offices", "theaters": "theatre" };
function entityTag(e) {
  return (a) => {
    const pc = e.parcel;
    const now = e.status === "auto" ? (pc?.use || e.use) : e.use;
    // a landmark shows what it was built as (config.json landmarks), and what it is now below
    const use = e.builtAs || now;
    // a landmark's year built from config.json (the assessor's is often a later remodel), else the assessor's
    const kicker = [use, e.built?.[0] ?? (e.landmark ? null : pc?.year_built)].filter(Boolean).join(" · ");   // a landmark without a looked-up year shows none
    const rows = [["Height", len(a.height)], ["Roof elevation", len(a.topY)]];
    if (e.landmark) rows.push(["Landmark", e.landmark]);   // config.json landmarks: why it is one
    if (e.built) rows.push(["Built", `${e.built[0]} · ${e.built[1]}`]);
    if (e.builtAsSource) rows.push(["Built as", `${e.builtAs} · ${e.builtAsSource}`]);
    if (e.builtAs) {
      const n = e.nowFixed || (e.status === "auto" ? ASSESSOR_USE[String(now).toLowerCase()] ?? `${now} (assessor)` : now);
      if (n && n.toLowerCase() !== e.builtAs.toLowerCase()) rows.push(["Now", n]);
    }
    if (pc?.units) rows.push(["Units", pc.units]);
    if (pc?.use && e.status !== "auto" && pc.use.toLowerCase() !== String(use).toLowerCase()) rows.push(["Land use (assessor)", pc.use]);
    rows.push(["Source", e.status === "auto" ? "LA County Assessor parcel (automatic, not checked by hand)"
      : `Checked in Google Earth / Maps${e.confidence ? `, ${e.confidence} confidence` : ""}${pc ? "; LA County Assessor" : ""}`]);
    return tagHTML(kicker || "Building", e.name, e.address || "", rows, e.note);
  };
}
// an unbuilt tower: the scheme, its size, its uses by level, where it comes from and what is assumed
function ghostTag({ scheme, tower: t }) {
  const FTM = 0.3048, uses = t.bands.filter((b) => b.use !== "podium" && b.use !== "top")
    .map((b) => `${b.use} ${b.levels[0] === b.levels[1] ? b.levels[0] : b.levels.join("–")}`).join(", ");
  return () => tagHTML("Unbuilt scheme", t.name, scheme.name, [
    ["Floors", String(t.floors)],
    ["Height", `${units === "ft" ? t.height_ft + " ft" : (t.height_ft * FTM).toFixed(1) + " m"} to the parapet`],
    ["Top", len(t.top_z)],
    ["Floor plate", units === "ft" ? `${Math.round(t.area_m2 * 10.7639).toLocaleString()} sq ft` : `${t.area_m2.toLocaleString()} m²`],
    ["Uses (levels)", uses],
    ["Source", scheme.source],
    ["Research", scheme.research.join(", ")],
  ], scheme.assumptions.join(" "));
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
addEventListener("resize", () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); dofResize(); invalidate(); });

// ---------- point settings: no panel any more (user, 2026-10-10); config.json "lidar" or the URL (?px= ?keep= ?cap= ?size=,
// read at the top) still set them ----------
// ---------- layer counts: objects per layer in the point cloud (buildings counted as entities) ----------
// Point cloud: objects of the layer in the cloud, buildings counted as entities (a building of several parts = 1);
// Terrain / Other / Street furniture are not objects -> no number. Mesh: objects of the layer in the model.
function layerCounts() {
  const counts = new Map();
  if (mode === "cloud" && lidar) {
    const seen = new Map();
    lidar.objNames.forEach((nm, k) => {
      const lay = lidar.objLayers[k], ent = lidar.objEntity[k];
      if (NOT_OBJECTS.has(nm) || !lidar.objCount[k] || cfg.layers[lay]?.highlight === false) return;   // ground: no number
      const key = ent >= 0 ? `e${ent}` : `o${k}`;   // an entity of several parts counts once
      if (!seen.has(lay)) seen.set(lay, new Set());
      seen.get(lay).add(key);
    });
    for (const [lay, s] of seen) counts.set(lay, s.size);
  } else {
    for (const L of ordered) if (L.objects.length) counts.set(L.name, L.objects.length);
  }
  for (const L of ordered) if (L.countEl) L.countEl.textContent = counts.has(L.name) ? counts.get(L.name).toLocaleString() : "";
}

// ---------- units switch (ft / m): a sliding switch the size of the Views buttons, kept in this browser ----------
function setUnits(u, instant = false) {
  units = u;
  try { localStorage.setItem("y1-viewer-units", u); } catch { /* private mode */ }
  document.querySelectorAll("#units button").forEach((b) => b.classList.toggle("on", b.dataset.u === u));
  moveThumb(instant, "#units");
  cloudTip();
  refreshTags();
}
document.querySelectorAll("#units button").forEach((b) => (b.onclick = () => setUnits(b.dataset.u)));
$("#unitsSec").addEventListener("toggle", () => moveThumb(true, "#units"));
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
  if (document.body.classList.contains("idle")) invalidate();   // the Time tags under the panel fade again
  document.body.classList.remove("idle");
  if (typeof wakeTags === "function") wakeTags();
  clearTimeout(idleTimer);
  idleTimer = setTimeout(function sleep() {
    if (overPanel() || typing()) { idleTimer = setTimeout(sleep, 1000); return; }
    document.body.classList.add("idle"); invalidate();   // the Time tags under the panel come back
  }, ms);
}
for (const ev of ["pointermove", "pointerdown", "wheel", "keydown", "touchstart", "focusin"]) addEventListener(ev, wake, { passive: true });
// prepared in the background from the home page (prerender): when the reader arrives, start the idle wait afresh (it
// may have run out while hidden) and fit the canvas to the window as it is now
if (document.prerendering) document.addEventListener("prerenderingchange", () => { wake(); dispatchEvent(new Event("resize")); invalidate(); }, { once: true });
// "home" steps back in history when the home page is the previous entry, so this page stays in the browser's
// back/forward cache and the home page's Model link can step forward to it, open at once (user, 2026-10-12)
document.querySelector('.sub a[href="./"]')?.addEventListener("click", (e) => {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || !window.navigation) return;
  const prev = navigation.entries()[navigation.currentEntry.index - 1];
  if (prev && new URL(prev.url).pathname === new URL(e.currentTarget.href).pathname) { e.preventDefault(); navigation.back(); }
});
addEventListener("pageshow", (e) => { if (e.persisted) { wake(); dispatchEvent(new Event("resize")); invalidate(); } });
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
// the opening (user, 2026-10-13): the viewer opens in the Time module, playing from 1867 with the camera tour;
// ?time=0 or config.json time.opening false opens on today
// Guided camera / Free camera (user, 2026-10-15): one switch at the top of the panel, the same model loaded once.
// History: the opening and the film (and A Day after the first wide shot); Free: today's model, the camera yours.
// Back to History, it goes on where it was left. ?time=0 or time.opening false opens in Free.
let viewMode = "free", historyLeft = null;
function setView(v) {
  if (v === viewMode) return;
  viewMode = v;
  document.querySelectorAll("#viewMode button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  document.body.classList.toggle("v-free", v === "free");
  moveThumb(false, "#viewMode");
  if (v === "free") {
    historyLeft = $("#timeOn").checked ? { year: TIME.year.value, cine: cine && !cine.people ? cine : null, at: performance.now() } : null;
    paused = false; setHistory(false);
    // the Free camera has the normal field of view: eased back over 0.8 s if a shot had changed it
    const f0 = camera.fov, t0 = performance.now();
    const ease = (now) => { const k = Math.min((now - t0) / 800, 1); setFov(f0 + (FOV0 - f0) * k * k * (3 - 2 * k)); invalidate(); if (k < 1) requestAnimationFrame(ease); };
    if (Math.abs(f0 - FOV0) > 0.01) requestAnimationFrame(ease);
  } else setHistory(true, historyLeft);
  invalidate();
}
document.querySelectorAll("#viewMode button").forEach((b) => (b.onclick = () => setView(b.dataset.v)));
addEventListener("resize", () => moveThumb(true, "#viewMode"));
setView(cfg.time?.opening !== false && urlq.get("time") !== "0" ? "history" : "free");
lonce("after: Guided / Free started");
// the population made ahead of time (2026-10-14: making it when the film turns People on, ~66 s in, stuttered):
// population.preloadS seconds after the cloud is up, when the browser is idle; hidden, and its 24 h chart worked out in
// slices, so People only has to show. false: made when People comes on, as before
if (cfg.population?.meta && cfg.population.preloadS !== false) setTimeout(() => {
  const go = () => { if (!pop) loadPop().then((p) => { p.prepare(); lonce("people: made ahead"); }).catch(() => {}); };
  window.requestIdleCallback ? requestIdleCallback(go, { timeout: 3000 }) : go();
}, (cfg.population.preloadS ?? 20) * 1000);
if (viewMode === "free") { document.querySelectorAll("#viewMode button").forEach((b) => b.classList.toggle("on", b.dataset.v === "free")); document.body.classList.add("v-free"); }
moveThumb(true, "#viewMode");
if (urlq.get("earth")) setEarthView(urlq.get("earth"));   // ?earth=<Google Earth URL>: the same camera here
status("");
let lodEasing = true;
// ?perf (2026-10-15, FPS and response): a small panel, bottom left, with the frame rate and where each frame's time goes
// (camera, LOD, people, render, tags), points and draw calls, and the time from the last click to its tag. Off by default.
const perfT = (k, f) => { if (!PERF) return f(); const t = performance.now(), r = f(); PERF.acc[k] = (PERF.acc[k] || 0) + performance.now() - t; return r; };
function perfFrame(now, drew) {
  if (!PERF) return;
  if (PERF.last) { const dt = now - PERF.last; PERF.acc.frame = (PERF.acc.frame || 0) + dt; PERF.max = Math.max(PERF.max || 0, dt); PERF.n++; }
  PERF.last = now; if (drew) PERF.drawn = (PERF.drawn || 0) + 1;
  if (now - PERF.t0 < 1000 || !PERF.n) return;
  const a = PERF.acc, n = PERF.n, f = (k) => ((a[k] || 0) / n).toFixed(1).padStart(5), info = renderer.info.render;
  PERF.el.textContent = `fps ${(1000 * n / (now - PERF.t0)).toFixed(0)}  frame ${f("frame")} ms (max ${PERF.max.toFixed(0)})  drawn ${PERF.drawn || 0}/${n}
`
    + `camera ${f("camera")}  lod ${f("lod")}  people ${f("people")}  render ${f("render")}  tags ${f("tags")} ms (CPU)
`
    + `points ${(info.points / 1e6).toFixed(2)} M  draw calls ${info.calls}  px ratio ${renderer.getPixelRatio()}`
    + (PERF.click ? `
last click -> tag ${PERF.click.toFixed(0)} ms` : "");
  PERF.acc = {}; PERF.n = 0; PERF.max = 0; PERF.drawn = 0; PERF.t0 = now;
}
// load profile: the first frame drawn after the cloud is up, and the long frames (> 50 ms) of the first two minutes, as
// [ms from the start of loadLidar, frame ms, render ms of that frame, tags ms, 1 = within 3 s of the people first shown]
let lfLast = 0, lfRender = 0, lfTags = 0;
function logFrame(now) {
  if (!loadT0 || !lidar || now - loadT0 > 120000) return;
  if (!("first frame drawn" in loadTimes) && lfRender) { ltick("first frame drawn"); loadTimes["first frame: render, ms"] = Math.round(lfRender); }
  if (lfLast && now - lfLast > 50) loadTimes.longFrames.push([Math.round(lfLast - loadT0), Math.round(now - lfLast), Math.round(lfRender), Math.round(lfTags), popShownAt && now - popShownAt < 3000 ? 1 : 0]);
  lfLast = now; lfRender = lfTags = 0;
}
renderer.setAnimationLoop((now) => {
  logFrame(now);
  perfT("camera", () => {
    if (tween) { stepTween(now); dirty = true; }
    if (cine) { stepCine(now); dirty = true; }
    if (controls.update()) dirty = true;   // damping keeps moving the camera after the drag ends
  });
  // LiDAR level of detail: recomputed whenever the view changed or a chunk is still easing to its target
  if (lidar && mode === "cloud" && (dirty || lodEasing)) perfT("lod", () => { lodEasing = updateLod(); if (lodEasing) dirty = true; });
  // the population plays on its own clock: draw while it plays or after one of its settings changed
  if (pop && (pop.visible || pop.state.fading)) perfT("people", () => { const was = pop.state.dirty; pop.tick(now); if (was || pop.state.playing || pop.state.fading) dirty = true; });
  if (!dirty) return perfFrame(now, false);
  dirty = false;
  const tR = performance.now();
  renderer.info.reset();
  perfT("render", renderFrame);
  const tG = performance.now();
  perfT("tags", () => { updateTags(); updateTimeTags(); });
  lfRender = tG - tR; lfTags = performance.now() - tG;
  perfFrame(now, true);
});
// shot study (for checking the film, user, 2026-10-15: foregrounds hiding what a shot is about): the poses of every
// shot of the opening and the film, and what stands between the camera and each of a shot's members
function tlBlockers(x, y, z, own, Y) {
  const o = camera.position, dx = x - o.x, dy = y - o.y, dz = z - o.z, hit = [];
  for (const b of tlOcc) {
    if (b.ent === own || (b.year && b.year > Y)) continue;
    const [x0, y0, z0, x1, y1, z1] = b.box, mx = (x1 - x0) * 0.1, mz = (z1 - z0) * 0.1;
    let t0 = 0, t1 = 0.97;
    for (const [oo, d, lo, hi] of [[o.x, dx, x0 + mx, x1 - mx], [o.y, dy, y0, y1], [o.z, dz, z0 + mz, z1 - mz]]) {
      if (Math.abs(d) < 1e-9) { if (oo < lo || oo > hi) { t0 = 2; break; } continue; }
      let a = (lo - oo) / d, c = (hi - oo) / d; if (a > c) [a, c] = [c, a];
      if (a > t0) t0 = a; if (c < t1) t1 = c; if (t0 > t1) break;
    }
    if (t0 <= t1) hit.push(ENTITIES.entities[b.ent]?.name ?? `#${b.ent}`);
  }
  return hit;
}
const shotStudy = {
  list() {
    if (!tlItems) tlBuild();
    if (!openAnchors) { tour = tour || { th: 0, t: 0 }; buildOpening(); }
    const film = cineShots();
    return { opening: OPEN.shots.map((sh, i) => ({ i, years: `${sh.from}-${sh.to}`, pose: openAnchors[i].pose })),
             film: film.map((sh, i) => ({ i, members: (sh.keys || []).map((k) => tlItems.find((t) => t.key === k)?.name), sh })) };
  },
  // put the camera where film shot i is at t (0..1), heading th (radians); returns what hides each member
  film(i, t, th = 0.6) {
    const sh = cineShots()[i]; endCine(); endTour();
    camApply(cinePose(sh, t, th, 1)); invalidate();
    return (sh.keys || []).map((k) => {
      const it = tlItems.find((q) => q.key === k), [x0, y0, z0, x1, y1, z1] = it.box, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      const top = tlBlockers(cx, y1, cz, it.ent, 2026), mid = tlBlockers(cx, (y0 + y1) / 2, cz, it.ent, 2026);
      return { name: it.name, top, mid };
    });
  },
  // run the film on a fake clock (fps frames a second) from heading th, round once: heading, its speed, the camera's
  // speed, and per shot the share of its members' tops and middles in clear view at the middle of the shot
  simulate(th = 330 * D2R, fps = 30) {
    endCine(); endTour();
    const keep = CINE.thenPeople; CINE.thenPeople = false;
    camApply({ target: TOUR.target, r: CINE.wideR, phi: CINE.wideTilt * D2R, th });
    startCine();
    let now = cine.t0, last = null, lastPos = null, lastI = 0; const rows = [], seen = {};
    const n = cine.shots.length;
    for (let f = 0; f < fps * 400; f++) {
      now += 1000 / fps; stepCine(now);
      const P = sphOf(camera.position, controls.target), pos = camera.position.clone();
      const w = last == null ? 0 : wrapA(P.th - last) * fps / D2R, v = lastPos ? pos.distanceTo(lastPos) * fps : 0;
      rows.push({ t: f / fps, i: cine.i, ph: cine.phase, w, v }); last = P.th; lastPos = pos;
      const sh = cine.shots[cine.i], len = shotLen(sh) * 1000, el = now - cine.t0;
      const share = () => { let ok = 0, tot = 0;
        for (const k of sh.keys) { const it = tlItems.find((q) => q.key === k), [x0, y0, z0, x1, y1, z1] = it.box, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
          tot += 2; if (!tlBlockers(cx, y1, cz, it.ent, 2026).length) ok++; if (!tlBlockers(cx, (y0 + y1) / 2, cz, it.ent, 2026).length) ok++; }
        return +(ok / tot).toFixed(2); };
      if (cine.phase === "shot" && (sh.keys || []).length) {   // at its start, middle and end
        const s3 = (seen[cine.i] ??= [null, null, null]);
        if (s3[0] === null) s3[0] = share();
        if (s3[1] === null && el > len / 2) s3[1] = share();
        if (s3[2] === null && el > len - 1000 / fps - 1) s3[2] = share();
      }
      if (lastI === n - 1 && cine.i !== n - 1) break;
      lastI = cine.i;
    }
    CINE.thenPeople = keep; endCine();
    const ws = rows.slice(1).map((r) => r.w);
    return { seconds: rows.length / fps, minTurnDegS: Math.min(...ws).toFixed(2), maxTurnDegS: Math.max(...ws).toFixed(2),
             maxSpeedMS: Math.round(Math.max(...rows.map((r) => r.v))), seen, rows };
  },
  // try a shot definition (as in config.json time.cinema.shots) at t from heading thDeg: how much of its members is in
  // clear view, and how they sit in the frame (share of the screen their boxes cover, distance of their centre from the
  // middle, share of them inside the window)
  tryDef(def, t = 0.5, thDeg = 0) {
    if (!tlItems) tlBuild();
    const keep = CINE.shots; CINE.shots = [def]; const sh = cineShots()[0]; CINE.shots = keep;
    endCine(); endTour(); camApply(cinePose(sh, t, thDeg * D2R, 1)); camera.updateMatrixWorld(); invalidate();
    const W = innerWidth, H = innerHeight; let ok = 0, tot = 0, bx0 = 1e9, by0 = 1e9, bx1 = -1e9, by1 = -1e9, inside = 0, corners = 0;
    for (const k of sh.keys || []) {
      const it = tlItems.find((q) => q.key === k), [x0, y0, z0, x1, y1, z1] = it.box, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      tot += 2; if (!tlBlockers(cx, y1, cz, it.ent, 2026).length) ok++; if (!tlBlockers(cx, (y0 + y1) / 2, cz, it.ent, 2026).length) ok++;
      for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) {
        _tv.set(x, y, z).project(camera); const sx = (_tv.x + 1) / 2 * W, sy = (1 - _tv.y) / 2 * H; corners++;
        if (_tv.z < 1 && sx >= 0 && sx <= W && sy >= 0 && sy <= H) inside++;
        bx0 = Math.min(bx0, sx); bx1 = Math.max(bx1, sx); by0 = Math.min(by0, sy); by1 = Math.max(by1, sy);
      }
    }
    const cov = (Math.min(bx1, W) - Math.max(bx0, 0)) * (Math.min(by1, H) - Math.max(by0, 0)) / (W * H);
    const off = Math.hypot((bx0 + bx1) / 2 / W - 0.5, (by0 + by1) / 2 / H - 0.5);
    // where the group's foot (its lowest point, at its centre) is on the screen: 0 = top, 1 = bottom (people for scale)
    let gx = 0, gz = 0, gy = 1e9; for (const k of sh.keys || []) { const b = tlItems.find((q) => q.key === k).box; gx += (b[0] + b[3]) / 2; gz += (b[2] + b[5]) / 2; gy = Math.min(gy, b[1]); }
    _tv.set(gx / (sh.keys || [1]).length, gy, gz / (sh.keys || [1]).length).project(camera);
    return { seen: +(ok / tot).toFixed(2), cover: +Math.max(cov, 0).toFixed(2), offCentre: +off.toFixed(2), inFrame: +(inside / corners).toFixed(2), foot: +((1 - _tv.y) / 2).toFixed(2) };
  },
  opening(i, th = 0.6) {
    const P = openAnchors[i].pose; endCine(); endTour(); camApply({ ...P, th }); invalidate();
    return P;
  },
};
window.__viewer = {
  shotStudy,
  layers, get mode() { return mode; }, setMode, get lidar() { return lidar; }, get population() { return pop; },
  camera, controls, renderer, lidarGroup, invalidate, get densityMatch() { return lidarDensityMatch; }, get plazaPoints() { return lidarPlazaPoints; }, get groundFill() { return lidarGroundFill; }, get timeLabels() { return tlItems; }, loadTimes, get openAnchors() { return openAnchors; }, updateTimeTags, startCine, get cine() { return cine; }, dof: { DOF, target: dofTarget, quad: dofQuad, renderFrame },   // debugging / performance checks
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
