"""Minimal pure-Python PDF text extractor.

Written because the machine has no pdftotext, poppler, pypdf, mutool or Ghostscript.
Parses object streams, resolves per-font ToUnicode CMaps and decodes Tj/TJ runs.
Recovers text only - it does not preserve table geometry.
"""
import re, zlib, sys

def get_objects(data):
    objs = {}
    for m in re.finditer(rb'(\d+)\s+(\d+)\s+obj\b', data):
        num = int(m.group(1)); start = m.end()
        e = data.find(b'endobj', start)
        objs[num] = data[start:e if e > 0 else start + 200000]
    for num, body in list(objs.items()):
        if b'/ObjStm' in body[:400]:
            sm = re.search(rb'stream\r?\n', body)
            if not sm: continue
            raw = body[sm.end():body.find(b'endstream', sm.end())]
            try: dec = zlib.decompress(raw)
            except Exception: continue
            try:
                n = int(re.search(rb'/N\s+(\d+)', body).group(1))
                first = int(re.search(rb'/First\s+(\d+)', body).group(1))
            except Exception: continue
            hdr = dec[:first].split()
            for i in range(n):
                try: onum = int(hdr[2*i]); off = int(hdr[2*i+1])
                except Exception: break
                end = int(hdr[2*i+3]) + first if 2*i+3 < len(hdr) else len(dec)
                objs[onum] = dec[first+off:end]
    return objs

def stream_of(objs, num):
    body = objs.get(num, b'')
    sm = re.search(rb'stream\r?\n', body)
    if not sm: return b''
    raw = body[sm.end():body.find(b'endstream', sm.end())]
    if b'/FlateDecode' in body[:sm.start()]:
        try: return zlib.decompress(raw)
        except Exception:
            try: return zlib.decompressobj().decompress(raw)
            except Exception: return b''
    return raw

def parse_tounicode(dec):
    cmap = {}
    for m in re.finditer(rb'beginbfchar(.*?)endbfchar', dec, re.S):
        for a, b in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            try: cmap[int(a, 16)] = ''.join(chr(int(b[i:i+4], 16)) for i in range(0, len(b), 4))
            except Exception: pass
    for m in re.finditer(rb'beginbfrange(.*?)endbfrange', dec, re.S):
        for a, b, c in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            lo, hi, dst = int(a, 16), int(b, 16), int(c, 16)
            for i in range(min(hi - lo + 1, 65535)): cmap[lo + i] = chr(dst + i)
    return cmap

def font_maps(objs):
    out = {}
    for num, body in objs.items():
        if b'/Font' in body and b'/ToUnicode' in body:
            m = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', body)
            if m: out[num] = parse_tounicode(stream_of(objs, int(m.group(1))))
    return out

def resources_fonts(objs, resbody):
    out, fd = {}, None
    m = re.search(rb'/Font\s*(\d+)\s+\d+\s+R', resbody)
    if m: fd = objs.get(int(m.group(1)), b'')
    else:
        m2 = re.search(rb'/Font\s*<<(.*?)>>', resbody, re.S)
        if m2: fd = m2.group(1)
    if fd:
        for nm, on in re.findall(rb'/([A-Za-z0-9#+._-]+)\s+(\d+)\s+\d+\s+R', fd):
            out[nm.decode('latin1')] = int(on)
    return out

def decode_text(content, fonts, fmaps):
    cur, out = None, []
    pat = rb'/([A-Za-z0-9#+._-]+)\s+[\d.]+\s+Tf|\[(.*?)\]\s*TJ|\((?:\\.|[^()\\])*\)\s*Tj|<([0-9A-Fa-f\s]+)>\s*Tj|(T\*|ET)'
    for tok in re.finditer(pat, content, re.S):
        if tok.group(1):
            cur = fmaps.get(fonts.get(tok.group(1).decode('latin1'), -1)); continue
        if tok.group(4):
            out.append('\n'); continue
        payload = tok.group(2) if tok.group(2) is not None else tok.group(0)
        s = ''
        for hm in re.finditer(rb'<([0-9A-Fa-f\s]+)>|\(((?:\\.|[^()\\])*)\)|(-?[\d.]+)', payload):
            if hm.group(1):
                h = re.sub(rb'\s', b'', hm.group(1)).decode('latin1')
                if cur:
                    for i in range(0, len(h) - 1, 4): s += cur.get(int(h[i:i+4], 16), '')
                else:
                    for i in range(0, len(h) - 1, 2): s += chr(int(h[i:i+2], 16))
            elif hm.group(2) is not None:
                lit = re.sub(rb'\\([nrt()\\])',
                             lambda m: {b'n': b'\n', b'r': b'', b't': b'\t'}.get(m.group(1), m.group(1)),
                             hm.group(2))
                s += ''.join(cur.get(c, chr(c)) for c in lit) if cur else lit.decode('latin1')
            elif hm.group(3):
                try:
                    if float(hm.group(3)) < -80: s += ' '
                except Exception: pass
        out.append(s)
    return ''.join(out)

def extract(path):
    data = open(path, 'rb').read()
    objs = get_objects(data); fmaps = font_maps(objs)
    pages = sorted([n for n, b in objs.items()
                    if re.search(rb'/Type\s*/Page\b', b) and b'/Contents' in b])
    res = []
    for num in pages:
        body = objs[num]
        rm = re.search(rb'/Resources\s+(\d+)\s+\d+\s+R', body)
        resbody = objs.get(int(rm.group(1)), b'') if rm else body
        cm = re.search(rb'/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)', body)
        if not cm: continue
        cnums = [int(x) for x in re.findall(rb'(\d+)\s+\d+\s+R', cm.group(1))]
        res.append(decode_text(b''.join(stream_of(objs, c) for c in cnums),
                               resources_fonts(objs, resbody), fmaps))
    return res

if __name__ == '__main__':
    for i, t in enumerate(extract(sys.argv[1]), 1):
        print(f"\n===== PAGE {i} =====\n{re.sub(chr(10)+'+', chr(10), t).strip()}")
