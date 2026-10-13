// Decode the site LiDAR LAZ off the main thread with laz-perf (LASzip compiled to WebAssembly); the decoding itself is
// in laz-core.js (the page uses it directly when prepared in the background, viewer.js).
const LAZPERF = "https://cdn.jsdelivr.net/npm/laz-perf@0.0.7/lib/web/";
importScripts(LAZPERF + "laz-perf.js", "laz-core.js");   // laz-core.js: the decoding itself (shared with viewer.js)

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

    const r = await self.lazDecode(file, meta, createLazPerf, LAZPERF, (msg) => self.postMessage({ progress: msg }));
    self.postMessage({ done: true, ...r }, [r.pos.buffer, r.cls.buffer, r.inten.buffer, r.obj.buffer, r.seg.buffer, r.hag.buffer]);
  } catch (err) {
    self.postMessage({ error: String(err && err.message || err) });
  }
};
