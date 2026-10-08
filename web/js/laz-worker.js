// Decode the site LiDAR LAZ off the main thread with laz-perf (LASzip compiled to WebAssembly).
// Expects LAS point format 0 (+ optional extra bytes described in the meta JSON), coordinates in the local site frame
// (x east, y north from the site origin, z NAVD88). Posts back typed arrays in three.js order (x east, y up, z -north).
const LAZPERF = "https://cdn.jsdelivr.net/npm/laz-perf@0.0.7/lib/web/";
importScripts(LAZPERF + "laz-perf.js");

self.onmessage = async (e) => {
  const { url, meta } = e.data;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`LiDAR file ${url}: HTTP ${res.status}`);
    const total = +res.headers.get("content-length") || 0;
    const reader = res.body.getReader(), chunks = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value); got += value.length;
      if (total) self.postMessage({ progress: `Loading LiDAR… ${Math.round((got / total) * 100)}%` });
    }
    const file = new Uint8Array(got);
    for (let o = 0, i = 0; i < chunks.length; o += chunks[i].length, i++) file.set(chunks[i], o);

    let stage = "wasm";
    const M = await createLazPerf({ locateFile: (f) => LAZPERF + f });
    stage = "malloc";
    const filePtr = M._malloc(file.length);
    M.HEAPU8.set(file, filePtr);
    stage = "open";
    const laz = new M.LASZip();
    try { laz.open(filePtr, file.length); } catch (err) { throw new Error(`laz-perf ${stage} failed (${err}); file ${file.length} bytes, heap ${M.HEAPU8.length}, first bytes ${[...file.slice(0, 4)]}`); }
    const n = laz.getCount(), len = laz.getPointLength();
    const ptPtr = M._malloc(len);

    const hdr = new DataView(file.buffer);   // LAS 1.2 header: scale factors at 131/139/147, offsets at 155/163/171
    const sx = hdr.getFloat64(131, true), sy = hdr.getFloat64(139, true), sz = hdr.getFloat64(147, true);
    const ox = hdr.getFloat64(155, true), oy = hdr.getFloat64(163, true), oz = hdr.getFloat64(171, true);
    const ex = meta.extra_bytes || {};
    const offObj = ex.object?.offset, offSeg = ex.segment?.offset, offHag = ex.hag?.offset;

    const pos = new Float32Array(n * 3), cls = new Uint8Array(n), inten = new Uint8Array(n);
    const obj = new Uint16Array(n), seg = new Uint8Array(n), hag = new Int16Array(n);
    let heap = new DataView(M.HEAPU8.buffer);
    for (let i = 0; i < n; i++) {
      laz.getPoint(ptPtr);
      if (heap.buffer !== M.HEAPU8.buffer) heap = new DataView(M.HEAPU8.buffer);   // the WASM heap may grow
      const x = heap.getInt32(ptPtr, true) * sx + ox, y = heap.getInt32(ptPtr + 4, true) * sy + oy, z = heap.getInt32(ptPtr + 8, true) * sz + oz;
      pos[3 * i] = x; pos[3 * i + 1] = z; pos[3 * i + 2] = -y;
      inten[i] = Math.min(heap.getUint16(ptPtr + 12, true), 255);
      cls[i] = heap.getUint8(ptPtr + 15);
      if (offObj !== undefined) obj[i] = heap.getUint16(ptPtr + offObj, true);
      if (offSeg !== undefined) seg[i] = heap.getUint8(ptPtr + offSeg);
      if (offHag !== undefined) hag[i] = heap.getInt16(ptPtr + offHag, true);
      if (i % 500000 === 0) self.postMessage({ progress: `Decoding LiDAR… ${Math.round((i / n) * 100)}%` });
    }
    M._free(ptPtr); M._free(filePtr); laz.delete();
    self.postMessage({ done: true, n, pos, cls, inten, obj, seg, hag }, [pos.buffer, cls.buffer, inten.buffer, obj.buffer, seg.buffer, hag.buffer]);
  } catch (err) {
    self.postMessage({ error: String(err && err.message || err) });
  }
};
