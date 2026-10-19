/* LA Museum Economy — revenue of six museums as proportional discs of drifting points.
 *
 * One point = $100,000. Points are the same size at the same density in every disc, so a
 * disc's area is proportional to its revenue and the six compare on sight.
 *
 * Figures: audited statements (MoMA, LACMA, FAMSF) and IRS returns read line by line
 * (MOCA + Petersen Form 990 Part VIII; the Broad Form 990-PF Parts I and XV-A).
 * Breakdowns exist only where the source itemises them on the same basis as its parent.
 */

/* fixed palette slots; the circular order was chosen by running every arrangement
   through a colour-vision validator and keeping one that clears all seven seams */
const STREAMS = [
  { key: "gifts",  name: "Gifts and grants",          v: "--s0" },
  { key: "govt",   name: "Government",                v: "--s1" },
  { key: "invest", name: "Investment and endowment",  v: "--s2" },
  { key: "adm",    name: "Admissions",                v: "--s3" },
  { key: "memb",   name: "Membership",                v: "--s4" },
  { key: "shops",  name: "Shops, food and auxiliary", v: "--s5" },
  { key: "other",  name: "Other",                     v: "--s6" },
];
const ORDER = [0, 1, 2, 6, 5, 4, 3];

const MUSEUMS = [
  { name: "MoMA", city: "New York City", period: "FY2025 (Jun)", reported: 282.8,
    v: { gifts: 66.9, govt: 0, invest: 64.1, adm: 42.4, memb: 14.7, shops: 86.5, other: 8.2 },
    b: { shops: { note: "On the IRS basis, which totals $86.9M against the audited $86.5M.", parts: [
        { name: "Retail and publishing", val: 83.31,
          det: "Museum Store and Design Store on W 53rd, SoHo, and Design Stores in Tokyo, Kyoto, Osaka, Fukuoka and Seoul. MoMA does not split stores from publishing." },
        { name: "Corporate events", val: 2.26 },
        { name: "Restaurants", val: 1.37,
          det: "The Modern and its Bar Room, Café 2, Terrace Café, the espresso bar and the Garden Bar. Filed under the food-service-contractors code, and no restaurant entity appears in Schedule R." },
      ] } } },

  { name: "LACMA", city: "Los Angeles", period: "FY2025 (Jun)", reported: 266.5,
    v: { gifts: 121.2, govt: 36.7, invest: 52.4, adm: 4.3, memb: 3.4, shops: 1.5, other: 49.0 },
    b: { govt: { note: "LACMA is a county institution, which is why this slice exists at all.", parts: [
          { name: "County operating contract", val: 36.723,
            det: "Not a grant. Museum Associates, the nonprofit, operates a museum the County of Los Angeles owns, on County land, under contract — so the County is paying for a public museum to be run. The 990 books it as program service revenue on line 2a, beside admissions and parking, not as a contribution. No other museum here has an equivalent." },
          { name: "Government grants", val: 1.360,
            det: "Ordinary grants, the kind MOCA also competes for. On the audited basis these sit inside gifts and grants rather than here, so the two parts total slightly more than the slice." },
        ] },
        other: { note: "Most of this is one unexplained line.", parts: [
          { name: "All other program service revenue", val: 40.898,
            det: "Unitemised on the 990 and unexplained in Schedule O. LACMA's program service revenue jumped from $45.3M to $87.2M year over year, a $41.9M swing matching this almost exactly, which fits the insurance settlement the audited statements mention — but the filing never says so." },
          { name: "Parking", val: 3.422 },
          { name: "Exhibition revenue", val: 0.953 },
          { name: "Special projects", val: 0.488 },
          { name: "Royalties and misc.", val: 0.241 },
        ] } } },

  { name: "de Young + Legion of Honor", city: "San Francisco", period: "FY2025 (Jun)", reported: 84.1,
    v: { gifts: 33.8, govt: 21.4, invest: 4.8, adm: 6.9, memb: 11.7, shops: 3.1, other: 2.4 } },

  { name: "MOCA", city: "Los Angeles", period: "FY2025 (Jun)", reported: 29.6,
    /* the $4.78M realised gain is moved out of "other" and shown with the endowment,
       where it belongs: the 990 separates them only because gains sit on line 7 */
    v: { gifts: 21.107, govt: 0.150, invest: 6.519, adm: 0.834, memb: 0.911, shops: 0.448, other: 0.811 },
    b: { gifts: { note: "Contributions have nearly doubled in five years, from $12.0M in 2020.", parts: [
          { name: "Contributions", val: 18.183,
            det: "Public support is 85.8% of total support, up from 76.8%, so this is broad rather than one patron. Fourteen works of art also came in as gifts, carrying no revenue value, with $669,447 of publicly traded securities." },
          { name: "Fundraising events, donation portion", val: 2.924,
            det: "The gala grossed $3.08M. The IRS splits it: the part above what guests received is a donation and counts here, which is why the event line itself reads as a loss." },
        ] },
        invest: { note: "A $181.1M endowment sits behind these two lines.", parts: [
          { name: "Net gain on securities", val: 4.784,
            det: "$45.09M sold against a $40.31M basis — portfolio turnover, not a disposal." },
          { name: "Interest and dividends", val: 1.735,
            det: "The endowment ended the year at $181,127,729 and earned $13.25M, of which $8.02M was unrealised and never reaches the 990. MOCA drew $8,641,000 from it for facilities and programmes — nearly four times everything it earns from the public." },
        ] },
        govt: { parts: [
          { name: "Government grants", val: 0.150,
            det: "Down from $592,690 the year before. MOCA is a freestanding nonprofit competing for ordinary grants, not a county institution like LACMA, and it reports no public facilities furnished without charge." },
        ] },
        other: { parts: [
          { name: "Other income", val: 0.435,
            det: "Unexplained. Schedule O covers only governance, and Schedule A asks for this to be itemised in Part VI, which was left as boilerplate. It has doubled: $139K, $78K, $217K, $204K, then $435K." },
          { name: "Travelling exhibition fees", val: 0.200 },
          { name: "Rent", val: 0.150,
            det: "MOCA owns the Grand Avenue land — bought from the CRA for $100,000 in 2015, after a 99-year rent-free lease from 1983. The Geffen Contemporary is leased, carried as $9.9M of leasehold improvements." },
          { name: "Royalties", val: 0.019 },
          { name: "Workshop and reproduction fees", val: 0.006 },
        ] } } },

  { name: "The Broad", city: "Los Angeles", period: "CY2024", reported: 27.8,
    v: { gifts: 10.741, govt: 0, invest: 1.242, adm: 1.025, memb: 0, shops: 3.952, other: 12.725 },
    b: { other: { parts: [
          { name: "GAAP discount on pledges", val: 11.631,
            det: "An accounting entry — the unwinding of present-value discount on multi-year pledges — not cash from running the museum." },
          { name: "Program-related services", val: 0.600 },
          { name: "Rents", val: 0.455 },
          { name: "Reimbursements", val: 0.037 },
          { name: "Advertising", val: 0.002 },
        ] },
        shops: { parts: [
          { name: "Parking", val: 2.406, det: "The garage under the plaza." },
          { name: "Shop, gross profit", val: 1.546, det: "$3.34M of sales against $1.79M cost of goods." },
        ] } } },

  { name: "Petersen Automotive", city: "Los Angeles", period: "CY2024", reported: 28.0,
    v: { gifts: 8.312, govt: 0, invest: 1.638, adm: 9.782, memb: 2.202, shops: 4.388, other: 2.218 },
    b: { gifts: { parts: [
          { name: "Contributions", val: 6.286 },
          { name: "Fundraising events, donation portion", val: 2.026 },
        ] },
        memb: { parts: [
          { name: "Dues", val: 1.949 },
          { name: "Membership events", val: 0.253 },
        ] },
        shops: { parts: [
          { name: "Parking", val: 2.902, det: "$1.04M of it taxed as unrelated business income." },
          { name: "Shop, net of cost of goods", val: 1.486, det: "$2.87M of sales against $1.38M cost of goods." },
        ] },
        other: { parts: [
          { name: "Rents", val: 2.132, det: "The filing does not say what is rented; event space is the likely bulk." },
          { name: "Other income", val: 0.086 },
        ] } } },
];

const PER     = 0.1;    /* $M one point stands for */
const UNIT_A  = 24.5;   /* px^2 of disc per point at scale 1 */
const DOT_R   = 1.75;
const TAU     = Math.PI * 2;
const DIVE_MS = 2000;   /* the dive lasts two seconds */
/* the neon ramp, dark to light; sub-discs draw from it in a spread order */
const RAMP      = ["--s0", "--s4", "--s6", "--s1", "--s3", "--s5", "--s2"];
const RAMP_PICK = [6, 2, 4, 0, 5, 1, 3];

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (m) => m >= 1 ? "$" + m.toFixed(1) + "M" : "$" + Math.round(m * 1000) + "K";
const total = (m) => STREAMS.reduce((s, k) => s + (m.v[k.key] || 0), 0);

/* integer points per part, largest remainder, every non-zero part gets at least one */
function allocate(vals) {
  const ex = vals.map(v => v / PER);
  const base = ex.map(e => Math.max(e > 0 ? 1 : 0, Math.floor(e)));
  let left = Math.round(ex.reduce((a, b) => a + b, 0)) - base.reduce((a, b) => a + b, 0);
  const rank = ex.map((e, i) => [e - Math.floor(e), i]).sort((a, b) => b[0] - a[0]);
  for (let k = 0; left > 0 && k < rank.length; k++) { base[rank[k][1]]++; left--; }
  return base;
}

const rng = (seed) => { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); };

/* Vogel spiral fills a disc evenly; sorting by angle turns contiguous runs into
   wedges with soft edges. Points are stored on the unit disc and scaled at draw. */
function cloud(counts, seed) {
  const N = counts.reduce((a, b) => a + b, 0);
  const rand = rng(seed);
  const GA = Math.PI * (3 - Math.sqrt(5));
  const pts = [];
  for (let k = 0; k < N; k++) pts.push({ r: Math.sqrt((k + 0.5) / N), th: (k * GA) % TAU });
  pts.sort((a, b) => a.th - b.th);

  const out = [], bounds = [];
  let i = 0;
  for (let w = 0; w < counts.length; w++) {
    const n = counts[w];
    if (!n) { bounds.push(null); continue; }
    bounds.push([pts[i].th, pts[i + n - 1].th]);
    for (let k = 0; k < n; k++) {
      const p = pts[i++];
      out.push({ ux: p.r * Math.cos(p.th), uy: p.r * Math.sin(p.th), w,
                 p1: rand() * TAU, p2: rand() * TAU, sp: .5 + rand() * .7, am: .5 + rand() * .9 });
    }
  }
  /* hit-test boundaries: midway between the last point of one wedge and the first of the next */
  const live = bounds.map((b, w) => b && { w, a: b[0], b: b[1] }).filter(Boolean);
  const edges = live.map((cur, k) => {
    const nxt = live[(k + 1) % live.length];
    let gapEnd = nxt.a; if (gapEnd < cur.b) gapEnd += TAU;
    return { w: cur.w, to: (cur.b + gapEnd) / 2 };
  });
  return { pts: out, N, edges };
}

/* ---------------------------------------------------------------- the six */
const stage = document.querySelector(".stage");
const cv = document.getElementById("cv"), ctx = cv.getContext("2d");
const capWrap = document.getElementById("caps");

const PIES = MUSEUMS.map((m, i) => {
  const vals = STREAMS.map(s => m.v[s.key] || 0);
  const counts = new Array(STREAMS.length).fill(0);
  const ordered = ORDER.map(si => vals[si]);
  const alloc = allocate(ordered);
  ORDER.forEach((si, k) => { counts[si] = alloc[k]; });
  /* cloud wants the counts in wedge order */
  const c = cloud(ORDER.map(si => counts[si]), m.name.length * 7919 + i * 131);
  c.edges.forEach(e => { e.si = ORDER[e.w]; });
  return { m, vals, counts, cloud: c, baseR: Math.sqrt(UNIT_A * c.N / Math.PI), sum: total(m) };
});

/* where each disc sits in the 3-column grid (user, 2026-10-19): the site's own
   neighbours and LACMA on the top row, the rest below */
const GRID = ["MOCA", "LACMA", "The Broad",
              "MoMA", "Petersen Automotive", "de Young + Legion of Honor"];
PIES.sort((a, b) => GRID.indexOf(a.m.name) - GRID.indexOf(b.m.name));

const caps = PIES.map(p => {
  const d = document.createElement("div");
  d.className = "cap";
  d.innerHTML = `<div class="nm">${p.m.name}</div><div class="ct">${p.m.city}</div>`
              + `<div class="tt"></div><div class="st">&nbsp;</div>`;
  capWrap.appendChild(d);
  return d;
});

let DPR = 1, W = 0, H = 0, layout = [];

function place() {
  DPR = Math.min(devicePixelRatio || 1, 2);
  W = stage.clientWidth; H = stage.clientHeight;
  cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);

  const cols = W > 900 ? 3 : (W > 560 ? 2 : 1);
  const rows = Math.ceil(PIES.length / cols);
  const cw = W / cols, ch = H / rows;
  const maxBase = Math.max(...PIES.map(p => p.baseR));
  const k = Math.min(cw * 0.40, ch * 0.33) / maxBase;   /* one scale for all: area stays proportional */

  layout = PIES.map((p, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    const r = p.baseR * k, y = row * ch + ch * 0.46;
    return { x: (col + .5) * cw, y, r, capY: y + r + 16 };
  });
  layout.forEach((L, i) => { caps[i].style.left = L.x + "px"; caps[i].style.top = L.capY + "px"; });
  DOT = Math.max(0.85, DOT_R * k);
}
let DOT = DOT_R;

let COL = [];
const readColours = () => { COL = STREAMS.map(s => css(s.v)); };

let hoverPie = -1, hoverStream = -1;

function drawDisc(c, L, p, t, dim) {
  for (let w = 0; w < ORDER.length; w++) {
    const si = ORDER[w];
    if (!p.counts[si]) continue;
    c.beginPath();
    for (const d of p.cloud.pts) {
      if (d.w !== w) continue;
      const x = L.x + d.ux * L.r + Math.sin(t * d.sp + d.p1) * d.am;
      const y = L.y + d.uy * L.r + Math.cos(t * d.sp * 1.13 + d.p2) * d.am;
      c.moveTo(x + DOT, y);
      c.arc(x, y, DOT, 0, TAU);
    }
    c.globalAlpha = dim && dim !== si ? 0.28 : 1;
    c.fillStyle = COL[si];
    c.fill();
  }
  c.globalAlpha = 1;
}

let t0 = performance.now();
function frame(now) {
  const t = (now - t0) / 1000;
  ctx.clearRect(0, 0, W, H);
  PIES.forEach((p, i) => {
    const dim = (i === hoverPie && hoverStream >= 0) ? hoverStream : 0;
    drawDisc(ctx, layout[i], p, t, dim);
  });
  if (drillOpen) drillFrame(t);
  if (window.__mocaDraw) window.__mocaDraw(t);
  requestAnimationFrame(frame);
}

/* ------------------------------------------------------------------ hover */
function hit(mx, my) {
  for (let i = 0; i < PIES.length; i++) {
    const L = layout[i], dx = mx - L.x, dy = my - L.y;
    const d = Math.hypot(dx, dy);
    if (d > L.r + 5) continue;
    let a = Math.atan2(dy, dx); if (a < 0) a += TAU;
    const edges = PIES[i].cloud.edges;
    for (const e of edges) {
      const to = e.to > TAU ? e.to - TAU : e.to;
      const prev = edges[(edges.indexOf(e) - 1 + edges.length) % edges.length];
      let from = prev.to > TAU ? prev.to - TAU : prev.to;
      const inside = from < to ? (a > from && a <= to) : (a > from || a <= to);
      if (inside) return [i, e.si];
    }
    return [i, PIES[i].cloud.edges[0].si];
  }
  return [-1, -1];
}

function paintCaps() {
  caps.forEach((c, i) => {
    const on = i === hoverPie;
    c.classList.toggle("on", on);
    if (!on) return;
    const p = PIES[i];
    c.querySelector(".tt").textContent = fmt(p.sum) + " total";
    const st = c.querySelector(".st");
    if (hoverStream >= 0 && p.vals[hoverStream]) {
      st.innerHTML = `<span style="color:${COL[hoverStream]}">●</span> `
        + STREAMS[hoverStream].name + " &nbsp;" + fmt(p.vals[hoverStream]);
    } else st.innerHTML = "&nbsp;";
  });
}

cv.addEventListener("pointermove", (e) => {
  const r = cv.getBoundingClientRect();
  const [i, si] = hit(e.clientX - r.left, e.clientY - r.top);
  hoverPie = i; hoverStream = si;
  const drillable = i >= 0 && si >= 0 && PIES[i].m.b && PIES[i].m.b[STREAMS[si].key];
  cv.style.cursor = drillable ? "pointer" : "default";
  paintCaps();
});
cv.addEventListener("pointerleave", () => { hoverPie = hoverStream = -1; paintCaps(); });

/* -------------------------------------------------------------- drill-down */
const drill = document.getElementById("drill");
const dcv = document.getElementById("dcv"), dctx = dcv.getContext("2d");
const dh = document.getElementById("dh"), dsub = document.getElementById("dsub");
const dval = document.getElementById("dval"), ddet = document.getElementById("ddet");

let drillOpen = null, dLayout = null, dHover = -1, dAnim = 0, diveT0 = 0;

function openDrill(i, si) {
  const m = PIES[i].m, spec = m.b && m.b[STREAMS[si].key];
  if (!spec) return;
  const vals = spec.parts.map(p => p.val);
  const counts = allocate(vals);
  const c = cloud(counts, m.name.length * 104729 + si);
  c.edges.forEach((e, k) => { e.si = e.w; });
  drillOpen = { pie: PIES[i], si, spec, vals, counts, cloud: c,
                baseR: Math.sqrt(UNIT_A * c.N / Math.PI), from: layout[i] };
  dHover = -1; dAnim = 0; diveT0 = performance.now();
  const L0 = layout[i];
  stage.style.transformOrigin = `${L0.x}px ${L0.y}px`;

  dh.textContent = m.name + " · " + STREAMS[si].name;
  dsub.textContent = spec.note || "";
  dval.innerHTML = "&nbsp;"; ddet.innerHTML = "&nbsp;";
  drill.hidden = false;
  requestAnimationFrame(() => drill.classList.add("show"));
  sizeDrill();
}
function closeDrill() {
  if (drillOpen) drillOpen.closing = true;   /* stop the dive writing to the stage */
  drill.classList.remove("show");
  stage.style.transition = "transform .7s cubic-bezier(.2,.7,.3,1), opacity .7s ease";
  stage.style.transform = "none";
  stage.style.opacity = "1";
  setTimeout(() => {
    drill.hidden = true; drillOpen = null;
    stage.style.transition = ""; stage.style.transformOrigin = "";
  }, 700);
}
function sizeDrill() {
  dcv.width = Math.round(innerWidth * DPR); dcv.height = Math.round(innerHeight * DPR);
  dctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  const cap = Math.min(innerWidth * 0.34, innerHeight * 0.30);
  const N = drillOpen ? drillOpen.cloud.N : 1;
  /* grow with the count, but never so small it reads as an afterthought */
  const r = Math.max(Math.min(cap, 90), Math.min(cap, Math.sqrt(120 * N / Math.PI)));
  const spacing = Math.sqrt(Math.PI * r * r / Math.max(1, N));
  dLayout = { x: innerWidth / 2, y: innerHeight * 0.40, r,
              dot: Math.max(2.2, Math.min(6.5, spacing * 0.33)) };
}

/* The dive: the field of discs rushes past the viewer while the chosen wedge
   comes forward out of it. Two seconds, time-based so it holds at any framerate. */
function drillFrame(t) {
  const d = drillOpen; if (!d || !dLayout) return;
  if (d.closing) { dctx.clearRect(0, 0, innerWidth, innerHeight); return; }
  const p = Math.min(1, (performance.now() - diveT0) / DIVE_MS);
  const ease = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;  /* in-out cubic */
  const rush = Math.pow(p, 1.7);                                           /* the field accelerates away */

  stage.style.transition = "none";
  stage.style.transform = `scale(${(1 + 5.5 * rush).toFixed(3)})`;
  stage.style.opacity = String(Math.max(0, 1 - p * 1.7));

  /* the sub-disc comes from the clicked wedge, far away and small, and arrives */
  const z = 0.06 + 0.94 * ease;
  const L = { x: d.from.x + (dLayout.x - d.from.x) * ease,
              y: d.from.y + (dLayout.y - d.from.y) * ease,
              r: dLayout.r * z };

  dctx.clearRect(0, 0, innerWidth, innerHeight);
  const keep = DOT; DOT = Math.max(0.6, (dLayout.dot || 3.1) * z);
  for (let w = 0; w < d.counts.length; w++) {
    if (!d.counts[w]) continue;
    dctx.beginPath();
    for (const q of d.cloud.pts) {
      if (q.w !== w) continue;
      const x = L.x + q.ux * L.r + Math.sin(t * q.sp + q.p1) * q.am * 1.4;
      const y = L.y + q.uy * L.r + Math.cos(t * q.sp * 1.13 + q.p2) * q.am * 1.4;
      dctx.moveTo(x + DOT, y); dctx.arc(x, y, DOT, 0, TAU);
    }
    dctx.globalAlpha = (dHover >= 0 && dHover !== w ? 0.25 : 1) * Math.min(1, 0.25 + ease);
    dctx.fillStyle = css(RAMP[RAMP_PICK[w % RAMP_PICK.length]]);
    dctx.fill();
  }
  dctx.globalAlpha = 1; DOT = keep;
  d.screen = L;
  d.settled = p >= 1;
}

dcv.addEventListener("pointermove", (e) => {
  const d = drillOpen; if (!d || !d.screen) return;
  const dx = e.clientX - d.screen.x, dy = e.clientY - d.screen.y;
  let w = -1;
  if (Math.hypot(dx, dy) <= d.screen.r + 6) {
    let a = Math.atan2(dy, dx); if (a < 0) a += TAU;
    const edges = d.cloud.edges;
    for (let k = 0; k < edges.length; k++) {
      const to = edges[k].to > TAU ? edges[k].to - TAU : edges[k].to;
      const pr = edges[(k - 1 + edges.length) % edges.length].to;
      const from = pr > TAU ? pr - TAU : pr;
      if (from < to ? (a > from && a <= to) : (a > from || a <= to)) { w = edges[k].w; break; }
    }
    if (w < 0) w = d.cloud.edges[0].w;
  }
  dHover = w;
  if (w >= 0) {
    const part = d.spec.parts[w];
    dval.innerHTML = `<span style="color:${COL[ORDER[w % ORDER.length]]}">●</span> `
      + part.name + " &nbsp;" + fmt(part.val);
    ddet.textContent = part.det || "";
    dcv.style.cursor = "default";
  } else { dval.innerHTML = "&nbsp;"; ddet.innerHTML = "&nbsp;"; }
});
dcv.addEventListener("click", () => { if (dHover < 0) closeDrill(); });
addEventListener("keydown", (e) => { if (e.key === "Escape" && drillOpen) closeDrill(); });

cv.addEventListener("click", (e) => {
  const r = cv.getBoundingClientRect();
  const [i, si] = hit(e.clientX - r.left, e.clientY - r.top);
  if (i >= 0 && si >= 0) openDrill(i, si);
});

/* ------------------------------------------------------------------ table */
const tbl = document.getElementById("tbl");
tbl.innerHTML =
  `<thead><tr><th>Museum</th><th>Period</th>` +
  ORDER.map(i => `<th><i style="background:var(${STREAMS[i].v})"></i>${STREAMS[i].name}</th>`).join("") +
  `<th>Shown</th><th>Reported</th></tr></thead><tbody>` +
  MUSEUMS.slice().sort((a, b) => total(b) - total(a)).map(m =>
    `<tr><td>${m.name}</td><td>${m.period}</td>` +
    ORDER.map(i => { const x = m.v[STREAMS[i].key] || 0; return `<td>${x ? x.toFixed(1) : "&mdash;"}</td>`; }).join("") +
    `<td class="tot">${total(m).toFixed(1)}</td><td>${m.reported.toFixed(1)}</td></tr>`).join("") +
  `</tbody>`;

document.getElementById("tnote").innerHTML =
  "&ldquo;Shown&rdquo; is the sum of the positive streams; &ldquo;reported&rdquo; is the total on the face of the document, "
+ "after the negative lines that are left out &mdash; LACMA &minus;$2.0M on an interest-rate swap, MOCA &minus;$1.22M of net "
+ "fundraising events, the Broad &minus;$1.88M on asset sales, the Petersen &minus;$0.55M on events and asset sales. "
+ "These six do not share one fiscal year: the Broad and the Petersen file on the calendar year. "
+ "The Broad&rsquo;s largest line is $11.63M of GAAP discount on pledges, an accounting entry rather than cash.";

/* -------------------------------------------------------------------- boot */
readColours();
place();
addEventListener("resize", () => { place(); if (drillOpen) sizeDrill(); });
requestAnimationFrame(frame);

/* ==========================================================================
   MOCA on its own. Clicking a stream writes its detail into the right half.
   The shops entry is the long one: what that bucket does NOT contain for MOCA.
   Every absence below was checked as a zero-occurrence search of the full
   return, not inferred.
   ========================================================================== */
const MOCA_DETAIL = {
  shops: {
    amt: "$448,319 net · $887,343 gross",
    paras: [
      "The whole slice is a single line of the return — Part VIII line 10, the museum store. "
      + "<b>$887,343</b> of sales against <b>$439,024</b> of cost of goods, leaving <b>$448,319</b>. "
      + "Sales rose 12% on the year and the net rose 21%, as the margin went from 46.5% to 50.5%.",
      "The category name is mine, built so six museums could be compared. For the others it carries "
      + "real weight: parking at the Broad and the Petersen, restaurants and corporate events at MoMA. "
      + "For MOCA it is the shop and nothing else."
    ],
    head: "What it does not include",
    bullets: [
      "<b>Food service of any kind.</b> No restaurant, café, catering or concession line exists. "
      + "MoMA books $1,366,179 under the food-service-contractors code; LACMA reports food services of $152,765.",
      "<b>Parking.</b> The largest absence by value. The Broad takes $2,406,170 from its garage, the "
      + "Petersen $2,902,316, LACMA $3,421,711. MOCA reports none — notable under California Plaza, "
      + "where the parking structure was part of the original CRA bargain.",
      "<b>Corporate events and venue hire.</b> MoMA books $2,263,124. MOCA has no earned equivalent; its "
      + "only event revenue is the gala, which IRS splitting rules turn into a reported loss of −$1,224,600.",
      "<b>Publishing.</b> MOCA's own mission statement names it — “exhibitions, educational programs, and "
      + "publishing” — but no publishing revenue line appears anywhere. Whatever it earns is folded "
      + "undifferentiated into that one inventory figure, or is not material.",
      "<b>Satellite or off-site stores.</b> MoMA runs eight, from W 53rd and SoHo to Tokyo, Kyoto, Osaka, "
      + "Fukuoka and Seoul, plus a New Jersey distribution centre. MOCA discloses none. Schedule F confirms "
      + "its only foreign activity is investments — zero offices and zero employees in every region.",
      "<b>Unrelated business income from retail.</b> The Broad splits its shop $166,134 unrelated against "
      + "$1,379,476 related; the Petersen's parking throws off $1,037,790. MOCA's $448,319 sits entirely in "
      + "the exempt-function column. Its only unrelated income is $47,265 flowing through K-1s from offshore "
      + "funds — an investment artefact, not a business."
    ],
    tail: [
      "A few earned lines sit outside this bucket rather than being absent: rent of $149,634, travelling "
      + "exhibition fees of $200,000, royalties of $19,204, and workshop and reproduction fees of $6,258.",
      "The pattern holds across all of it. Free admission since 2020, no food, no parking, no events "
      + "business, one small store. Which is why the <b>$8,641,000</b> drawn from the endowment is close to "
      + "four times MOCA's entire earned income of roughly $2.3M."
    ]
  },
  gifts: {
    amt: "$21,107,353",
    paras: [
      "Contributions of <b>$18,183,479</b>, plus <b>$2,923,874</b> that the IRS carves out of the gala: the "
      + "part of each ticket above what guests actually received counts as a donation, which is why the event "
      + "line itself reads as a loss.",
      "Giving has nearly doubled in five years — $12.0M in 2020, $12.9M, $12.9M, $18.0M, then $22.2M. "
      + "Public support stands at <b>85.8%</b> of total support, up from 76.8%, so this is a broad base rather "
      + "than one patron, though donors above the 2% threshold did contribute $3.74M in excess of it.",
      "Fourteen works of art also arrived as gifts, carrying no revenue value because collection gifts are not "
      + "booked as income, alongside $669,447 of publicly traded securities."
    ]
  },
  invest: {
    amt: "$6,518,801",
    paras: [
      "Interest and dividends of <b>$1,735,029</b>, plus a realised gain of <b>$4,783,772</b> — $45.09M of "
      + "securities sold against a $40.31M basis, which is portfolio turnover rather than a disposal. The 990 "
      + "separates them only because gains sit on line 7; both are the endowment at work.",
      "That endowment closed the year at <b>$181,127,729</b> and earned <b>$13.25M</b>, of which $8.02M was "
      + "unrealised and never reaches the return at all. It is why MOCA's audited revenue is $36.9M against the "
      + "$29.6M the 990 reports.",
      "MOCA drew <b>$8,641,000</b> for facilities and programmes. It is 0% board-designated and 70.8% permanent, "
      + "so most of it genuinely cannot be spent down — unlike LACMA's $195M, which is 47.9% board-designated."
    ]
  },
  govt: {
    amt: "$150,291",
    paras: [
      "Down from <b>$592,690</b> the year before, a fall of about 75%.",
      "MOCA is a freestanding nonprofit competing for ordinary grants. LACMA's $36.7M is not comparable: "
      + "Museum Associates operates a museum the County owns, on County land, under contract, and the 990 books "
      + "that as program service revenue beside admissions and parking — not as a grant.",
      "MOCA also reports no public facilities furnished without charge. It owns the Grand Avenue land outright, "
      + "bought from the CRA for $100,000 in 2015 after a rent-free 99-year lease from 1983. The Geffen "
      + "Contemporary it leases, carried as $9.9M of leasehold improvements."
    ]
  },
  adm: {
    amt: "$833,856",
    paras: [
      "General admission has been free since January 2020, funded by a $10M gift. What remains is ticketed "
      + "special exhibitions and programmes.",
      "Sitting beside it in program service revenue are travelling exhibition fees of $200,000, workshop fees of "
      + "$3,374 and reproduction fees of $2,884 — $1,040,114 in total."
    ]
  },
  memb: {
    amt: "$910,993",
    paras: [
      "Broken out on line 1b of the return, up from $856,217 the year before.",
      "Membership is larger than admissions here, which is the usual shape for a free museum — though nothing "
      + "like the de Young, where $11.7M of membership runs well ahead of $6.9M of admissions."
    ]
  },
  other: {
    amt: "$811,000",
    paras: [
      "Mostly <b>$434,804</b> of “other income” that the filing never explains. Schedule O covers only "
      + "governance, and Schedule A asks for this line to be itemised in Part VI, which was left as boilerplate. "
      + "It has doubled: $139K, $78K, $217K, $204K, then $435K.",
      "If MOCA takes any café or venue-hire commission, this is the only line it could plausibly sit in. "
      + "That is a hypothesis from absence, not a finding.",
      "The rest is travelling exhibition fees of $200,000, rent of $149,634, royalties of $19,204, and workshop "
      + "and reproduction fees of $6,258."
    ]
  }
};

const mcv = document.getElementById("mcv");
if (mcv) {
  const mctx = mcv.getContext("2d");
  const mInfo = document.getElementById("mocaInfo");
  const mTot = document.getElementById("mocaTot");
  const MP = PIES.find(p => p.m.name === "MOCA");
  let mL = null, mDot = DOT_R, mHover = -1, mPicked = -1;

  function mPlace() {
    const w = mcv.clientWidth, h = mcv.clientHeight;
    mcv.width = Math.round(w * DPR); mcv.height = Math.round(h * DPR);
    mctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const r = Math.min(w * 0.40, h * 0.40);
    const k = r / MP.baseR;
    mL = { x: w / 2, y: h * 0.46, r, w, h };
    mDot = Math.max(1.4, DOT_R * k);
    mTot.textContent = fmt(MP.sum) + " total";
  }

  function mDraw(t) {
    if (!mL) return;
    mctx.clearRect(0, 0, mL.w, mL.h);
    const keep = DOT; DOT = mDot;
    const focus = mPicked >= 0 ? mPicked : mHover;
    drawDisc(mctx, mL, MP, t, focus >= 0 ? focus : 0);
    DOT = keep;
  }

  function mHit(mx, my) {
    const dx = mx - mL.x, dy = my - mL.y;
    if (Math.hypot(dx, dy) > mL.r + 6) return -1;
    let a = Math.atan2(dy, dx); if (a < 0) a += TAU;
    const edges = MP.cloud.edges;
    for (let k = 0; k < edges.length; k++) {
      const to = edges[k].to > TAU ? edges[k].to - TAU : edges[k].to;
      const pr = edges[(k - 1 + edges.length) % edges.length].to;
      const from = pr > TAU ? pr - TAU : pr;
      if (from < to ? (a > from && a <= to) : (a > from || a <= to)) return edges[k].si;
    }
    return edges[0].si;
  }

  function mShow(si) {
    const key = STREAMS[si].key, d = MOCA_DETAIL[key];
    if (!d) { mInfo.innerHTML = '<p class="prompt">Nothing itemised for this stream.</p>'; return; }
    let html = `<h2>${STREAMS[si].name}</h2><p class="amt">${d.amt}</p>`;
    html += d.paras.map(x => `<p>${x}</p>`).join("");
    if (d.head) html += `<h3>${d.head}</h3>`;
    if (d.bullets) html += "<ul>" + d.bullets.map(x => `<li>${x}</li>`).join("") + "</ul>";
    if (d.tail) html += d.tail.map(x => `<p>${x}</p>`).join("");
    mInfo.innerHTML = html;
    mInfo.scrollTop = 0;
  }

  mcv.addEventListener("pointermove", (e) => {
    const r = mcv.getBoundingClientRect();
    mHover = mHit(e.clientX - r.left, e.clientY - r.top);
    mcv.style.cursor = mHover >= 0 ? "pointer" : "default";
  });
  mcv.addEventListener("pointerleave", () => { mHover = -1; });
  mcv.addEventListener("click", (e) => {
    const r = mcv.getBoundingClientRect();
    const si = mHit(e.clientX - r.left, e.clientY - r.top);
    if (si < 0) { mPicked = -1; mInfo.innerHTML = '<p class="prompt">Select a stream.</p>'; return; }
    mPicked = si; mShow(si);
  });

  mPlace();
  addEventListener("resize", mPlace);
  window.__mocaDraw = mDraw;
}

/* the Scroll button on the opening pane */
const toPies = document.getElementById("toPies");
if (toPies) toPies.addEventListener("click", () =>
  document.getElementById("pies").scrollIntoView({ behavior: "smooth", block: "start" }));
