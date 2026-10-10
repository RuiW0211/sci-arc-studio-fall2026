// Population layer: a MODELED typical day on the site, one point per person.
// Data from site-model/scripts/prep_population.py (web/data/population.{json,bin}); nothing here is observed.
// Each person has weekday / weekend trips: spot (home desk, work desk, place) -> door node -> OSM network ->
// node -> spot. Between trips they stay where the last trip ended; "off site" hides them.
import * as THREE from "three";

const HIDDEN = 0, HOME = 1, WORK = 2, PLACE = 3;
const F_REV = 16, F_ATTEND = 32, F_EVENT = 64;
const BODY = 1.0;        // point height above the floor / ground, m
const VERT = 0.5;        // vertical metres count half (elevators are faster than walking)
const OFF = -1e5;

function hash(a, b) {
  let h = (Math.imul(a, 374761393) + Math.imul(b, 668265263)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
const hhmm = (s) => { const m = Math.floor(s / 60) % 1440; return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; };

export async function createPopulation({ cfg, scene, camera, renderer, layers, thinning, onInfo, onStatus }) {
  const pc = cfg.population;
  const meta = await (await fetch(pc.meta)).json();
  const buf = await (await fetch(pc.meta.replace(/[^/]*$/, "") + meta.bin)).arrayBuffer();
  const sec = (name) => {
    const s = meta.sections[name];
    const T = { float32: Float32Array, uint32: Uint32Array, uint16: Uint16Array, int16: Int16Array, uint8: Uint8Array }[s.type];
    return new T(buf, s.offset, s.count);
  };
  const nodes = sec("nodes"), pOff = sec("pathOffsets"), pNodes = sec("pathNodes");
  const type = sec("type"), mode = sec("mode"), sector = sec("sector"), rank = sec("rank");
  const homeBld = sec("homeBld"), workBld = sec("workBld"), homeSpot = sec("homeSpot"), workSpot = sec("workSpot");
  const distKm = sec("distKm"), bearing = sec("bearing"), tract = sec("tract");
  // people far from Y-1 are only partly written (prep_population.py); each stands for weight people in the counts
  const weight = meta.sections.weight ? sec("weight") : new Float32Array(A).fill(1);
  const days = {};
  for (const d of ["weekday", "weekend"]) {
    days[d] = { off: sec(`${d}.offsets`), t0: sec(`${d}.t0`), t1: sec(`${d}.t1`), path: sec(`${d}.path`),
                flags: sec(`${d}.flags`), purpose: sec(`${d}.purpose`), orig: sec(`${d}.orig`), dest: sec(`${d}.dest`) };
  }
  const A = meta.count, TU = meta.time_unit_s;
  // cumulative length along every path
  const pCum = new Float32Array(pNodes.length);
  for (let p = 0; p + 1 < pOff.length; p++) {
    let acc = 0;
    for (let k = pOff[p]; k < pOff[p + 1]; k++) {
      if (k > pOff[p]) { const a = 3 * pNodes[k - 1], b = 3 * pNodes[k]; acc += Math.hypot(nodes[b] - nodes[a], nodes[b + 1] - nodes[a + 1], nodes[b + 2] - nodes[a + 2]); }
      pCum[k] = acc;
    }
  }
  const lateral = new Float32Array(A);
  for (let i = 0; i < A; i++) lateral[i] = (hash(i, 7) - 0.5) * 3.6;  // spread across the sidewalk, m
  const eligible = new Set((meta.remoteEligible ?? []).map((s) => meta.sectors.indexOf(s)));

  // ---------- state ----------
  const st = { day: "weekday", t: (pc.start ?? 8.5) * 3600, speed: pc.speed ?? 300, playing: false,
               attendance: meta.officeAttendance, event: true, xray: true, neon: pc.neon ?? true, selected: -1, dirty: true };
  const present = new Uint8Array(A);
  function updatePresence() {
    for (let i = 0; i < A; i++) {
      const thr = meta.sectorAttendance ? meta.sectorAttendance[sector[i]] : eligible.has(sector[i]) ? st.attendance : meta.otherAttendance;
      present[i] = rank[i] < thr * 256 ? 1 : 0;
    }
  }
  updatePresence();
  const active = (D, i, k) => { const f = D.flags[k]; return !((f & F_ATTEND) && !present[i]) && !((f & F_EVENT) && !st.event); };
  const T_UNSH = meta.types.indexOf("unsheltered");
  const defaultSpot = (i) => (type[i] === 0 || type[i] === 2 || type[i] === T_UNSH ? HOME : HIDDEN);

  // where person i is at time T (seconds): {k: trip index or -1, moving, spot}
  function locate(D, i, T) {
    const lo = D.off[i], hi = D.off[i + 1], tu = T / TU;
    let last = -1, lastEnd = -1;
    for (let k = lo; k < hi; k++) {
      if (!active(D, i, k)) continue;
      if (D.t0[k] <= tu) { last = k; }
      if (lastEnd < 0 || D.t1[k] >= D.t1[lastEnd]) lastEnd = k;
    }
    if (last >= 0 && tu < D.t1[last]) return { k: last, moving: true };
    const k = last >= 0 ? last : lastEnd;  // before the first trip: where the day's last trip ended
    return { k, moving: false, spot: k >= 0 ? (D.flags[k] >> 2) & 3 : defaultSpot(i) };
  }

  const tmp = new THREE.Vector3();
  function spotPos(i, kind, node, out) {
    if (kind === HOME) return out.set(homeSpot[3 * i] / 10, homeSpot[3 * i + 1] / 10 + BODY, homeSpot[3 * i + 2] / 10);
    if (kind === WORK) return out.set(workSpot[3 * i] / 10, workSpot[3 * i + 1] / 10 + BODY, workSpot[3 * i + 2] / 10);
    const a = hash(i, node) * 6.283, r = 1.5 + hash(node, i) * 5;  // a spot beside the place's node
    return out.set(nodes[3 * node] + Math.cos(a) * r, nodes[3 * node + 1] + BODY, nodes[3 * node + 2] + Math.sin(a) * r);
  }
  const ends = (D, k) => {
    const p = D.path[k], rev = D.flags[k] & F_REV, a = pNodes[pOff[p]], b = pNodes[pOff[p + 1] - 1];
    return rev ? [b, a] : [a, b];
  };
  const S = new THREE.Vector3(), E = new THREE.Vector3();
  // position along trip k at fraction f: spot -> (lift) -> node A -> path -> node B -> (lift) -> spot
  function along(D, i, k, f, out) {
    const p = D.path[k], rev = D.flags[k] & F_REV, fk = D.flags[k] & 3, tk = (D.flags[k] >> 2) & 3;
    const [na, nb] = ends(D, k);
    const L = pCum[pOff[p + 1] - 1];
    let preH = 0, preV = 0, postH = 0, postV = 0;
    if (fk !== HIDDEN) { spotPos(i, fk, na, S); preV = Math.abs(S.y - nodes[3 * na + 1] - BODY); preH = Math.hypot(S.x - nodes[3 * na], S.z - nodes[3 * na + 2]); }
    if (tk !== HIDDEN) { spotPos(i, tk, nb, E); postV = Math.abs(E.y - nodes[3 * nb + 1] - BODY); postH = Math.hypot(E.x - nodes[3 * nb], E.z - nodes[3 * nb + 2]); }
    const total = preV * VERT + preH + L + postH + postV * VERT || 1;
    let s = f * total;
    if (fk !== HIDDEN) {
      if (s < preV * VERT) return out.set(S.x, S.y + (nodes[3 * na + 1] + BODY - S.y) * (s / (preV * VERT || 1)), S.z);
      s -= preV * VERT;
      if (s < preH) { const g = s / (preH || 1); return out.set(S.x + (nodes[3 * na] - S.x) * g, nodes[3 * na + 1] + BODY, S.z + (nodes[3 * na + 2] - S.z) * g); }
      s -= preH;
    }
    if (s <= L) {
      const q = rev ? L - s : s;
      let lo = pOff[p], hi = pOff[p + 1] - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (pCum[m] <= q) lo = m; else hi = m; }
      const a = 3 * pNodes[lo], b = 3 * pNodes[hi], seg = pCum[hi] - pCum[lo] || 1, g = Math.min(Math.max((q - pCum[lo]) / seg, 0), 1);
      const dx = nodes[b] - nodes[a], dz = nodes[b + 2] - nodes[a + 2], dl = Math.hypot(dx, dz) || 1, o = lateral[i];
      return out.set(nodes[a] + dx * g - (dz / dl) * o, nodes[a + 1] + (nodes[b + 1] - nodes[a + 1]) * g + BODY, nodes[a + 2] + dz * g + (dx / dl) * o);
    }
    s -= L;
    if (tk === HIDDEN) return out.set(nodes[3 * nb], nodes[3 * nb + 1] + BODY, nodes[3 * nb + 2]);
    if (s < postH) { const g = s / (postH || 1); return out.set(nodes[3 * nb] + (E.x - nodes[3 * nb]) * g, nodes[3 * nb + 1] + BODY, nodes[3 * nb + 2] + (E.z - nodes[3 * nb + 2]) * g); }
    s -= postH;
    const g = Math.min(s / (postV * VERT || 1), 1);
    return out.set(E.x, nodes[3 * nb + 1] + BODY + (E.y - nodes[3 * nb + 1] - BODY) * g, E.z);
  }
  let lastTrip = -1;  // the trip position() found the person moving on (for trails)
  function position(D, i, T, out) {
    const loc = locate(D, i, T);
    lastTrip = loc.moving ? loc.k : -1;
    if (loc.moving) { const k = loc.k; along(D, i, k, (T / TU - D.t0[k]) / Math.max(D.t1[k] - D.t0[k], 1), out); return 2; }
    if (loc.spot === HIDDEN) return 0;
    const node = loc.k >= 0 ? ends(D, loc.k)[1] : 0;
    spotPos(i, loc.spot, node, out);
    return loc.spot === PLACE || (loc.spot === HOME && type[i] === T_UNSH) ? 3 : 1;   // 1 indoors (home / work), 3 outdoors at a place or spot
  }

  // ---------- distance fade (user, 2026-10-08: "like the point cloud, dense to sparse"): the point cloud's own rule
  // (lidar_points.json "thinning", site-model/houdini/thinning.json). Within R0 of Y-1 everyone is drawn; farther out
  // each person is drawn with the share (R0 / d_eff)^P, d_eff = distance stretched by the person's own random jitter,
  // and fades out; the counts and the chart still include everyone.
  const TH = { r0: thinning?.full_density_radius_m ?? 250, p: thinning?.falloff_power ?? 2.7, jitter: 0.18,
               keepMin: thinning?.keep_min ?? 0.015, edgeEnd: thinning?.edge_end_m ?? 1230, edgeW: 300 };
  const hashU = (i, s) => { let h = Math.imul(i ^ s, 2654435761) >>> 0; h ^= h >>> 15; h = Math.imul(h, 2246822519) >>> 0; h ^= h >>> 13; return (h >>> 0) / 4294967296; };
  const uKeep = new Float32Array(A), uJit = new Float32Array(A);
  for (let i = 0; i < A; i++) { uKeep[i] = hashU(i, 0x9e37); uJit[i] = hashU(i, 0x85eb); }
  function share(x, z, i) {
    const d = Math.hypot(x, z);
    if (d <= TH.r0) return 1;
    const de = d * (1 + TH.jitter * (2 * uJit[i] - 1));
    let r = Math.min(1, (TH.r0 / Math.max(de, 1)) ** TH.p);
    if (r < TH.keepMin) return 0;
    return r * Math.min(Math.max((TH.edgeEnd - d) / TH.edgeW, 0), 1);
  }
  const drawn = (i) => share(pos[3 * i], pos[3 * i + 2], i) > 0;   // written people are drawn (thinned in prep)

  // ---------- points ----------
  const pos = new Float32Array(A * 3), col = new Float32Array(A * 3);
  // three display groups (user, 2026-10-09): hotel guests are drawn and counted with the visitors; the tag still says which
  const GROUP = meta.types.map((t) => (t === "hotel" ? meta.types.indexOf("visitor") : meta.types.indexOf(t)));
  const SHOWN = [...new Set(GROUP)];
  const colors = meta.types.map((t, k) => new THREE.Color(pc.colors?.[meta.types[GROUP[k]]] ?? "#888"));
  for (let i = 0; i < A; i++) colors[type[i]].toArray(col, 3 * i);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("aKeep", new THREE.BufferAttribute(uKeep, 1));
  geo.setAttribute("aJit", new THREE.BufferAttribute(uJit, 1));
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 100, 0), 900);
  const uniforms = { size: { value: pc.size ?? 0.7 }, scale: { value: 1 }, minPx: { value: 2.0 }, alpha: { value: 1 },
                    r0: { value: TH.r0 }, pw: { value: TH.p }, jit: { value: TH.jitter }, keepMin: { value: TH.keepMin },
                    edgeEnd: { value: TH.edgeEnd }, edgeW: { value: TH.edgeW } };
  const material = new THREE.ShaderMaterial({
    uniforms, vertexColors: true,
    // the same share() as above: a person outside their share is not drawn; the drawn ones fade with it
    vertexShader: `uniform float size; uniform float scale; uniform float minPx; uniform float r0; uniform float pw;
      uniform float jit; uniform float keepMin; uniform float edgeEnd; uniform float edgeW;
      attribute float aKeep; attribute float aJit; varying vec3 vC; varying float vFade;
      void main() { vC = color; float d = length(position.xz), s = 1.0;
        if (d > r0) { s = min(1.0, pow(r0 / max(d * (1.0 + jit * (2.0 * aJit - 1.0)), 1.0), pw));
          s = s < keepMin ? 0.0 : s * clamp((edgeEnd - d) / edgeW, 0.0, 1.0); }
        vFade = s > 0.0 ? 0.35 + 0.65 * sqrt(s) : 0.0;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = vFade > 0.0 ? max(size * scale / -mv.z, minPx) : 0.0; gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform float alpha; varying vec3 vC; varying float vFade;
      void main() { if (vFade <= 0.0 || length(gl_PointCoord - vec2(0.5)) > 0.5) discard; gl_FragColor = vec4(vC, alpha * vFade); }`,
    transparent: true,
  });
  const points = new THREE.Points(geo, material);
  points.frustumCulled = false;
  points.renderOrder = 2;
  scene.add(points);
  // the selected person: a bigger highlight point plus today's route
  const HILITE = new THREE.Color(cfg.linked?.highlight ?? "#FF3EA5");
  const selGeo = new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(3), 3));
  selGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(HILITE.toArray()), 3));
  const selMat = material.clone();
  selMat.uniforms = { size: { value: 2.2 }, scale: uniforms.scale, minPx: { value: 9 }, alpha: { value: 1 } };
  const selPoint = new THREE.Points(selGeo, selMat);
  selPoint.visible = false;
  selPoint.frustumCulled = false;
  selPoint.renderOrder = 3;
  scene.add(selPoint);
  const selPos = new THREE.Vector3();   // the selected person, where the viewer's floating tag points (kept up to date)
  // the person under the cursor (within PICK_PX on screen): drawn bigger, so a click visibly means "this person"
  const hovGeo = new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(3), 3));
  hovGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(HILITE.toArray()), 3));
  const hovMat = material.clone();
  hovMat.uniforms = { size: { value: 1.8 }, scale: uniforms.scale, minPx: { value: 7 }, alpha: { value: 0.85 } };
  const hovPoint = new THREE.Points(hovGeo, hovMat);
  hovPoint.visible = false; hovPoint.frustumCulled = false; hovPoint.renderOrder = 3;
  scene.add(hovPoint);
  let hovered = -1;
  const _p = new THREE.Vector3();
  /** The shown person nearest to a screen point (client px), if within maxPx; else -1. */
  function nearestOnScreen(cx, cy, maxPx) {
    const r = renderer.domElement.getBoundingClientRect(), w = r.width, h = r.height;
    let best = -1, bd = maxPx * maxPx;
    const dim = st.selected >= 0;    // while one person is isolated, only they and the bright others count
    for (let i = 0; i < A; i++) {
      if (pos[3 * i + 1] <= OFF / 2 || (dim && i !== st.selected) || !drawn(i)) continue;
      _p.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]).project(camera);
      if (_p.z > 1 || _p.z < -1) continue;
      const dx = (_p.x + 1) / 2 * w + r.left - cx, dy = (1 - _p.y) / 2 * h + r.top - cy, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  // route = a thin line, plus an optional neon "light wall" and floor trace (Tron light-cycle trail):
  // faint for the rest of the day, lit where the person has already been, brightest at their current spot
  const NEON = new THREE.Color(pc.routeColor ?? "#00E5FF");
  const routeU = { now: { value: 0 }, color: { value: NEON }, strength: { value: pc.neonStrength ?? 1 } };
  const neonVert = `attribute float aT; attribute float aA; varying float vT; varying float vA;
    void main() { vT = aT; vA = aA; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
  const neonFrag = (shape) => `uniform float now; uniform vec3 color; uniform float strength; varying float vT; varying float vA;
    void main() { float done = step(vT, now), head = done * exp(-(now - vT) / 150.0);
      float a = (${shape}) * (0.04 + 0.10 * done + 0.18 * head) * strength;
      gl_FragColor = vec4(mix(color, vec3(1.0), 0.5 * head), clamp(a, 0.0, 1.0)); }`;
  const neonMat = (shape) => new THREE.ShaderMaterial({ uniforms: routeU, vertexShader: neonVert, fragmentShader: neonFrag(shape),
    transparent: true, depthWrite: false, side: THREE.DoubleSide });
  const wall = new THREE.Mesh(new THREE.BufferGeometry(), neonMat("pow(1.0 - vA, 1.5) * (0.85 + 0.15 * step(0.5, fract(vA * 6.0)))"));
  const glow = new THREE.Mesh(new THREE.BufferGeometry(), neonMat("exp(-vA * vA * 4.0)"));
  const line = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: NEON, transparent: true, opacity: 0.7, depthTest: false }));
  const route = new THREE.Group();
  for (const o of [wall, glow, line]) { o.frustumCulled = false; o.renderOrder = 3; route.add(o); }
  route.visible = false;
  scene.add(route);
  const WALL_H = 2.4, GLOW_W = 1.4;

  // trails while playing: every moving person draws a short light wall behind them, in their type colour,
  // fading out over the last `tail` simulated seconds (longer at faster speeds)
  const MAXT = pc.maxTrails ?? 8000, TS = 6;  // people with a trail, segments per trail
  const tP = new Float32Array(MAXT * TS * 6 * 3), tC = new Float32Array(MAXT * TS * 6 * 3), tT = new Float32Array(MAXT * TS * 6), tA = new Float32Array(MAXT * TS * 6);
  const tGeo = new THREE.BufferGeometry();
  tGeo.setAttribute("position", new THREE.BufferAttribute(tP, 3).setUsage(THREE.DynamicDrawUsage));
  tGeo.setAttribute("color", new THREE.BufferAttribute(tC, 3).setUsage(THREE.DynamicDrawUsage));
  tGeo.setAttribute("aT", new THREE.BufferAttribute(tT, 1).setUsage(THREE.DynamicDrawUsage));
  tGeo.setAttribute("aA", new THREE.BufferAttribute(tA, 1).setUsage(THREE.DynamicDrawUsage));
  const trailU = { now: { value: 0 }, tail: { value: 600 }, strength: { value: pc.neonStrength ?? 1 } };
  const trails = new THREE.Mesh(tGeo, new THREE.ShaderMaterial({
    uniforms: trailU, vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide,
    vertexShader: `attribute float aT; attribute float aA; varying float vT; varying float vA; varying vec3 vC;
      void main() { vT = aT; vA = aA; vC = color; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform float now; uniform float tail; uniform float strength; varying float vT; varying float vA; varying vec3 vC;
      void main() { float age = clamp((now - vT) / tail, 0.0, 1.0);
        float a = pow(1.0 - vA, 1.5) * (1.0 - age) * 0.22 * strength;
        gl_FragColor = vec4(mix(vC, vec3(1.0), 0.35 * (1.0 - age)), a); }`,
  }));
  trails.frustumCulled = false;
  trails.renderOrder = 2;
  trails.visible = false;
  scene.add(trails);
  const ta = new THREE.Vector3(), tb = new THREE.Vector3();
  function buildTrails(movers) {
    const D = days[st.day], T = st.t, tail = Math.min(Math.max(st.speed * 0.8, 60), 2400);
    trailU.now.value = T; trailU.tail.value = tail;
    let v = 0;
    for (let m = 0; m < movers.length && m < MAXT * 2; m += 2) {
      const i = movers[m], k = movers[m + 1], T0 = D.t0[k] * TU, dur = Math.max((D.t1[k] - D.t0[k]) * TU, 1);
      const start = Math.max(T - tail, T0), c = colors[type[i]];
      along(D, i, k, (start - T0) / dur, ta);
      let tPrev = start;
      for (let s = 1; s <= TS; s++) {
        const tn = start + ((T - start) * s) / TS;
        along(D, i, k, (tn - T0) / dur, tb);
        if (Math.hypot(tb.x - ta.x, tb.z - ta.z) > 0.02) {
          const q = [[ta.x, ta.y - BODY, ta.z], [tb.x, tb.y - BODY, tb.z], [ta.x, ta.y - BODY + WALL_H, ta.z], [tb.x, tb.y - BODY + WALL_H, tb.z]];
          const qt = [tPrev, tn, tPrev, tn], qa = [0, 0, 1, 1];
          for (const j of [0, 1, 2, 2, 1, 3]) {
            tP.set(q[j], 3 * v); tC[3 * v] = c.r; tC[3 * v + 1] = c.g; tC[3 * v + 2] = c.b; tT[v] = qt[j]; tA[v] = qa[j]; v++;
          }
        }
        ta.copy(tb); tPrev = tn;
      }
    }
    tGeo.setDrawRange(0, v);
    for (const a of Object.values(tGeo.attributes)) a.needsUpdate = true;
  }

  // Y-1 outline (scene-local [x, north, z]) for the "on Y-1" count
  const y1 = (meta.y1 || []).map((ring) => ring.map(([x, n]) => [x, -n]));   // Y-1 parcel, written by prep_population.py
  const inY1 = (x, z) => y1.some((r) => { let c = false; for (let a = 0, b = r.length - 1; a < r.length; b = a++) { if ((r[a][1] > z) !== (r[b][1] > z) && x < ((r[b][0] - r[a][0]) * (z - r[a][1])) / (r[b][1] - r[a][1]) + r[a][0]) c = !c; } return c; });

  const counts = { total: 0, byType: meta.types.map(() => 0), indoors: 0, outdoors: 0, y1: 0 };
  function update() {
    const D = days[st.day], T = st.t;
    counts.total = counts.indoors = counts.outdoors = counts.y1 = 0;
    counts.byType.fill(0);
    const wantTrails = st.playing && st.neon && st.selected < 0 && points.visible, movers = [];
    for (let i = 0; i < A; i++) {
      const r = position(D, i, T, tmp);
      if (wantTrails && lastTrip >= 0) movers.push(i, lastTrip);
      if (r === 0) { pos[3 * i + 1] = OFF; continue; }
      pos[3 * i] = tmp.x; pos[3 * i + 1] = tmp.y; pos[3 * i + 2] = tmp.z;
      const w = weight[i];
      counts.total += w; counts.byType[type[i]] += w;
      if (r === 1) counts.indoors += w;
      else { counts.outdoors += w; if (inY1(tmp.x, tmp.z)) counts.y1 += w; }
    }
    geo.attributes.position.needsUpdate = true;
    trails.visible = wantTrails;
    if (wantTrails) buildTrails(movers);
    if (st.selected >= 0) {
      const ok = position(D, st.selected, T, tmp);
      selPoint.visible = points.visible && ok !== 0;
      selGeo.attributes.position.array.set([tmp.x, tmp.y, tmp.z]);
      selPos.copy(tmp);
      selGeo.attributes.position.needsUpdate = true;
    }
    if (hovered >= 0) {
      hovPoint.visible = points.visible && pos[3 * hovered + 1] > OFF / 2;
      hovGeo.attributes.position.array.set(pos.subarray(3 * hovered, 3 * hovered + 3));
      hovGeo.attributes.position.needsUpdate = true;
    }
    st.dirty = false;
    ui.refresh();
  }

  // 24 h curve for the current settings, by type (people on site per 15 min)
  function curve() {
    const D = days[st.day], out = meta.types.map(() => new Float32Array(96));
    for (let b = 0; b < 96; b++) {
      const T = (b + 0.5) * 900;
      for (let i = 0; i < A; i++) {
        const loc = locate(D, i, T);
        if (loc.moving || loc.spot !== HIDDEN) out[GROUP[type[i]]][b] += weight[i];   // display groups
      }
    }
    return out;
  }

  // ---------- see-through buildings (people indoors are visible in Model · Mesh) ----------
  const saved = new Map();
  function setXray(on) {
    const L = layers.get("Buildings");
    if (!L) return;
    for (const m of L.meshes) {
      if (!saved.has(m)) { saved.set(m, m.material); m.material = m.material.clone(); }
      const mat = m.material;
      if (on) { mat.transparent = true; mat.opacity = 0.22; mat.depthWrite = false; }
      else { const o = saved.get(m); mat.transparent = o.transparent; mat.opacity = o.opacity; mat.depthWrite = o.depthWrite; }
      mat.needsUpdate = true;
    }
  }

  // ---------- story for a clicked person ----------
  const B = meta.buildings, labelType = { resident: "Resident", worker: "Worker", hotel: "Hotel guest", visitor: "Visitor",
    unsheltered: "Person without shelter", passerby: "Passer-by" };
  const labelGroup = { resident: "Residents", worker: "Workers", visitor: "Visitors (incl. hotel guests)",
    unsheltered: "Without shelter", passerby: "Passers-by" };
  const compass = (deg) => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(deg / 45) % 8];
  const bname = (k) => (k >= 0 ? B[k].name || B[k].addr[0] || B[k].id : "–");
  const floorOf = (k, spot, i) => (k >= 0 ? Math.max(1, Math.round((spot[3 * i + 1] / 10 - B[k].base) / B[k].fh) + 1) : 0);
  const anchor = (a) => (a >= 0 ? meta.anchors[a] : "");
  function story(i) {
    const D = days[st.day], t = meta.types[type[i]], rows = [];
    const sl = meta.sectorLabels[sector[i]];
    if (workBld[i] >= 0) rows.push(["Works at", `${bname(workBld[i])}, floor ${floorOf(workBld[i], workSpot, i)}`]);
    if (sl) rows.push(["Industry", sl]);
    if (homeBld[i] >= 0) rows.push([t === "hotel" ? "Staying at" : "Lives at", `${bname(homeBld[i])}, floor ${floorOf(homeBld[i], homeSpot, i)}`]);
    else if (t === "worker") rows.push(["Lives", `about ${(distKm[i] / 100).toFixed(1)} km ${compass((bearing[i] / 255) * 360)} (tract ${meta.tracts[tract[i]].slice(5)})`]);
    else if (t === "unsheltered") rows.push(["Stays", "on the street in this tract (LAHSA 2025 street count, modeled spot)"]);
    else if (t === "passerby") rows.push(["Walks", "through the site, from one edge to another"]);
    if (mode[i]) rows.push(["Gets here by", meta.modes[mode[i]]]);
    const trips = [];
    let attendDep = false;
    for (let k = D.off[i]; k < D.off[i + 1]; k++) {
      if (D.flags[k] & F_ATTEND) attendDep = true;
      if (!active(D, i, k)) continue;
      const curb = !(D.dest[k] >= 0 || D.orig[k] >= 0) && (((D.flags[k] >> 2) & 3) === HIDDEN || (D.flags[k] & 3) === HIDDEN);
      const where = anchor(D.dest[k]) || anchor(D.orig[k]) || (curb ? (mode[i] === 5 ? "building garage" : "car / taxi at the door") : "");
      trips.push(`${hhmm(D.t0[k] * TU)} ${meta.purposes[D.purpose[k]]}${where ? ` · ${where}` : ""}`);
    }
    if (attendDep && !present[i]) rows.push(["Today", "working remotely today (office attendance, Kastle)"]);
    if (!trips.length && !(attendDep && !present[i])) rows.push(["Today", st.day === "weekend" && t === "worker" ? "not working today" : "stays put"]);
    const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
    const title = t === "worker" && eligible.has(sector[i]) ? "Office worker" : labelType[t];
    return `<h2>${esc(title)} <span style="font-weight:400;color:var(--muted)">#${i}</span></h2><table>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>` +
      (trips.length ? `<div class="label">Today (${st.day})</div><div class="trips">${trips.map(esc).join("<br>")}</div>` : "") +
      `<div class="note">Modeled person, not a real individual. Data: LODES, ACS, NHTS, Assessor, OSM.</div>`;
  }
  function select(i) {
    st.selected = i;
    // isolate the selected person: everyone else fades and loses their trail
    uniforms.alpha.value = i < 0 ? 1 : pc.isolateAlpha ?? 0.15;
    material.depthWrite = i < 0;
    st.dirty = true;
    if (i < 0) { selPoint.visible = route.visible = false; return; }
    // no route line (user, 2026-10-09: a modeled shortest path drawn as a line reads as a real track)
    onInfo(story(i), selPos);
    st.dirty = true;
  }

  // ---------- UI ----------
  const $ = (s) => document.querySelector(s);
  const chart = $("#popChart"), ctx = chart.getContext("2d");
  let curveData = null, curveTimer = 0;
  const recurve = () => { clearTimeout(curveTimer); curveTimer = setTimeout(() => { curveData = curve(); ui.drawChart(); }, 60); };
  const ui = {
    refresh() {
      $("#popClock").textContent = hhmm(st.t);
      $("#popTime").value = st.t;
      const c = counts;
      const byGroup = (g) => meta.types.reduce((s, _, k) => s + (GROUP[k] === g ? c.byType[k] : 0), 0);
      $("#popCounts").innerHTML = SHOWN.map((g) => `<span><i class="sw" style="display:inline-block;background:${pc.colors[meta.types[g]]}"></i>${labelGroup[meta.types[g]]} ${Math.round(byGroup(g)).toLocaleString()}</span>`).join("") +
        `<span class="tot">On site ${Math.round(c.total).toLocaleString()} · outdoors ${Math.round(c.outdoors).toLocaleString()} · on Y-1 ${Math.round(c.y1).toLocaleString()}</span>`;
      ui.drawChart();
    },
    drawChart() {
      const w = (chart.width = chart.clientWidth * devicePixelRatio), h = (chart.height = chart.clientHeight * devicePixelRatio);
      ctx.clearRect(0, 0, w, h);
      if (!curveData) return;
      let max = 1;
      for (let b = 0; b < 96; b++) { let s = 0; for (const c of curveData) s += c[b]; max = Math.max(max, s); }
      for (let k = curveData.length - 1; k >= 0; k--) {
        ctx.beginPath(); ctx.moveTo(0, h);
        for (let b = 0; b < 96; b++) { let s = 0; for (let j = 0; j <= k; j++) s += curveData[j][b]; ctx.lineTo(((b + 0.5) / 96) * w, h - (s / max) * (h - 2)); }
        ctx.lineTo(w, h); ctx.closePath(); ctx.fillStyle = pc.colors[meta.types[k]]; ctx.fill();
      }
      const fg = getComputedStyle(document.documentElement).getPropertyValue("--fg");
      ctx.fillStyle = fg; ctx.fillRect((st.t / 86400) * w - devicePixelRatio / 2, 0, devicePixelRatio, h);
      ctx.font = `${10 * devicePixelRatio}px -apple-system, sans-serif`; ctx.globalAlpha = 0.7;
      ctx.fillText(`peak ${Math.round(max).toLocaleString()}`, 3 * devicePixelRatio, 11 * devicePixelRatio); ctx.globalAlpha = 1;
    },
  };
  $("#popTime").oninput = (e) => { st.t = +e.target.value; st.dirty = true; };
  $("#popPlay").onclick = () => { st.playing = !st.playing; st.dirty = true; $("#popPlay").textContent = st.playing ? "Pause" : "Play"; };
  document.querySelectorAll("#popDay button").forEach((b) => (b.onclick = () => {
    st.day = b.dataset.d; st.dirty = true; recurve();
    document.querySelectorAll("#popDay button").forEach((x) => x.classList.toggle("on", x === b));
    if (st.selected >= 0) select(st.selected);
  }));
  $(`#popDay button[data-d='${st.day}']`).classList.add("on");
  $("#popMethod").innerHTML = methodHtml(meta);

  // ---------- public ----------
  let lastNow = 0;
  const api = {
    meta, state: st,
    setVisible(on) {
      points.visible = on;
      if (!on) { hovered = -1; hovPoint.visible = false; }
      selPoint.visible = on && st.selected >= 0;
      route.visible = false;
      setXray(on && st.xray);
      if (!on) trails.visible = false;
      if (on) { st.dirty = true; if (!curveData) recurve(); }
    },
    get visible() { return points.visible; },
    tick(now) {
      const dt = lastNow ? Math.min((now - lastNow) / 1000, 0.25) : 0;
      lastNow = now;
      uniforms.scale.value = renderer.domElement.height / (2 * Math.tan((camera.fov * Math.PI) / 360));
      if (!points.visible) return;
      if (st.playing) { st.t = (st.t + dt * st.speed) % 86400; st.dirty = true; }
      if (st.dirty) update();
      routeU.now.value = st.t;
    },
    // the person within maxPx of a screen point (client px), or -1 (user, 2026-10-08: screen distance, so picking a
    // person or a building behaves the same at every zoom)
    nearest(cx, cy, maxPx) { return points.visible ? nearestOnScreen(cx, cy, maxPx) : -1; },
    // hover marker: person index or -1
    hover(i) {
      if (i === hovered) return;
      hovered = i; hovPoint.visible = false;
      if (i >= 0) { hovGeo.attributes.position.array.set(pos.subarray(3 * i, 3 * i + 3)); hovGeo.attributes.position.needsUpdate = true; hovPoint.visible = true; }
    },
    // returns true if the click selected person i (from nearest); -1 clears a selected person
    pickIndex(i) {
      if (i < 0) { if (st.selected >= 0) select(-1); return false; }
      selPos.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]);
      select(i);
      return true;
    },
    clearSelection() { if (st.selected >= 0) select(-1); },
    select,  // select(i): show person i's day (debugging / links)
  };
  onStatus?.("");
  return api;
}

function methodHtml(meta) {
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const t = meta.totals;
  const src = Object.entries(meta.sources).map(([k, v]) => `<li><b>${esc(k)}</b>: ${esc(v)}</li>`).join("");
  const asm = Object.entries(meta.assumptions).map(([k, v]) => `<li><b>${esc(k)}</b>: ${esc(JSON.stringify(v.value))}. ${esc(v.note)}</li>`).join("");
  const fmt = (n) => Math.round(n).toLocaleString();
  const notPlaced = t.residents_by_rule?.["not placed"] ?? 0;
  const metro = meta.calibration?.metro ?? {};
  const rows = Object.entries(metro).filter(([, v]) => !v.transfer_hub)
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${fmt(v.model_boardings)}</td><td>${fmt(v.metro_boardings)}</td><td>${v.ratio}</td></tr>`).join("");
  const mSum = Object.values(metro).filter((v) => !v.transfer_hub);
  const ratio = (mSum.reduce((s, v) => s + v.model_boardings, 0) / mSum.reduce((s, v) => s + v.metro_boardings, 0)).toFixed(2);
  return `<p><b>A modeled typical day, not real-time or observed data.</b> Across both day types:
    ${fmt(t.by_type.worker)} jobs placed in buildings (LODES ${fmt(t.lodes_jobs_in_blocks)} jobs in the blocks touching the site,
    scaled by each block's share inside the 2.5 km square around Y-1), ${fmt(t.by_type.resident)} residents (2020 Census),
    ${fmt(t.by_type.hotel)} hotel guests and ${fmt(t.by_type.visitor)} visitors. Far from Y-1 only a share of people is drawn,
    thinned like the point cloud; each drawn person counts for the people it stands for, so the totals and the chart include everyone.
    Commute modes and arrival times come from CTPP (by tract where it is published), other trip times from NHTS;
    routes follow OpenStreetMap paths.</p>
    <p><b>Residents not placed</b>: ${fmt(notPlaced)} of the Census residents live in blocks near the edge whose buildings
    are not modelled (thinned out of the point cloud or missing from the building entities). They are left out rather than
    moved into other blocks' buildings.</p>
    <p><b>People added after the street-count check</b>: people without shelter (LAHSA 2025 street count by tract,
    dwellings at 1.75 people each; their daily walks are assumed), Little Tokyo visitors and passers-by who walk
    through the site from edge to edge. Nobody publishes counts of the last two: their daily numbers are fitted to the
    LADOT Walk &amp; Bike Counts (2023, 2025) on six blocks; three blocks (5th St, Grand Ave, Los Angeles St) are held
    out as a check (site-model/population/data/walk_check.json). Blocks at the site edge get too many passers-by,
    because they all enter and leave there.</p>
    <p><b>Metro check</b> (weekday): model rail trips leaving the site through each station's entrances, against Metro's
    FY2026 average weekday boardings.</p>
    <table><tr><th>Station</th><th>Model</th><th>Metro</th><th>Ratio</th></tr>${rows}
    <tr><td>Five stations</td><td></td><td></td><td>${ratio}</td></tr></table>
    <p>Riders take the line whose branch points toward home, then an entrance on that line, by walking distance and a
    weight per station. The line weight (metroLines.lineWeight), the station weights (stationWeight) and how far riders
    will walk past a nearer entrance (stationChoiceTemp) are fitted to these counts: <b>this table shows the fit, it is
    not an independent check</b> (the LADOT walk counts are). Little Tokyo/Arts District is not fitted, because most of its
    riders live beyond the modelled area. 7th St/Metro Center is a transfer hub and is not compared. The model has no
    transfers and no trips that only pass through the site.</p>
    <p><b>Sources</b></p><ul>${src}</ul><p><b>Assumptions</b> (site-model/population/data/assumptions.json)</p><ul>${asm}</ul>
    <p><b>Known limits</b>: LODES counts jobs where employers report them; office floor area is from the Assessor, not
    listings; arrival-time bins are City of LA averages within each tract's periods; hotel rooms are estimated from
    floor area (historic hotels with ballrooms come out high).</p>`;
}
