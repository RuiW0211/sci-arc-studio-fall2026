"""Build web/proposal/index.html from the English proposal (user, 2026-10-29: the proposal as a module of the site, laid out
like Methods: contents on the left, the text in the middle, the references each paragraph cites in the right margin).

The text is written in Markdown (docs/proposal/proposal_en.md, a copy of Rui's English key-points draft, the original;
on 2026-10-30 the stacked scheme replaced the 20-page woven one). Only the parts that file uses are read: "## n. Title"
sections (and "## Executive summary"), paragraphs, lists (nested by indent), tables, one-line images with an italic
caption line, **bold**, *italic*, `code`, links and [n] source numbers. "## Sources" is the reference list: an entry
starting with [n] becomes the target of every [n] in the text, and its first words (before the first link) are the short
form shown in the margin. "## Open items for Rui" is a note for Rui and is left out of the page. Images are copied next
to the page as figure-1.svg, figure-2.svg ... so no local file names reach the published copy.

The published text leaves out the names of files on Rui's computer (the research reports and the course syllabus the
working copy points to; user, 2026-10-29); public() removes them, and the copy in docs/proposal/ is written without them.

Rerun after changing the proposal:
  python docs/proposal_build.py                 (reads docs/proposal/proposal_en.md)
  python docs/proposal_build.py <file.md>       (copies <file.md> into docs/proposal/proposal_en.md first, without file names)
"""
import html
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPY = ROOT / "docs" / "proposal" / "proposal_en.md"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else COPY
OUT = ROOT / "web" / "proposal" / "index.html"


def public(md):
    """The text without references to local files: "(see `a.md`)", ", see `a.md` and `b.md`", "(`file.pdf`)"."""
    md = re.sub(r"\s*\(see `[^`]+`(?:(?:, | and )`[^`]+`)*\)", "", md)
    md = re.sub(r"[,;]? see `[^`]+`(?:(?:, | and )`[^`]+`)*", "", md)
    md = re.sub(r"\s*\(`[^`]+`\)", "", md)
    return md

LIST = re.compile(r"^( *)(- |\d+\. )(.*)$")
CITE = re.compile(r"\[(\d+)\]")
URL = re.compile(r"(https?://[^\s<>()]+[^\s<>().,;:])")
SKIP_TOC = {"Who runs it"}   # repeated on every page; the contents list the parts that differ


def inline(s, cites=True):
    """Markdown inline marks to HTML; [n] becomes a link to source n."""
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = URL.sub(lambda m: f'<a href="{m.group(1)}">{re.sub(r"^https?://(www\.)?", "", m.group(1)).split("/")[0]}</a>', s)
    if cites:
        s = CITE.sub(r'<a class="cite" href="#ref-\1">[\1]</a>', s)
    return s


def parse(lines):
    """Lines of one page to blocks: ("p", text), ("list", items), ("table", rows). An item is [marker, text, parts]; a part is a paragraph (str) or a nested list (list of items), in order."""
    blocks, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip() or ln.strip() == "---":
            i += 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s:|-]+\|$", lines[i].strip()):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("table", rows))
            continue
        if LIST.match(ln):
            root, stack = [], []   # stack of (indent, item)
            while i < len(lines):
                ln = lines[i]
                m = LIST.match(ln)
                if m:
                    ind = len(m.group(1))
                    item = [m.group(2).strip(), m.group(3), []]
                    while stack and stack[-1][0] >= ind:
                        stack.pop()
                    if not stack:
                        root.append(item)
                    else:
                        parts = stack[-1][1][2]
                        if not (parts and isinstance(parts[-1], list)):
                            parts.append([])
                        parts[-1].append(item)
                    stack.append((ind, item))
                    i += 1
                    continue
                if not ln.strip():
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines) and (LIST.match(lines[j]) and len(LIST.match(lines[j]).group(1)) > 0 or lines[j].startswith(" ")):
                        i = j
                        continue
                    break
                if ln.startswith(" ") and stack:   # a paragraph inside the item above
                    ind = len(ln) - len(ln.lstrip())
                    while len(stack) > 1 and stack[-1][0] >= ind:
                        stack.pop()
                    stack[-1][1][2].append(ln.strip())
                    i += 1
                    continue
                break
            blocks.append(("list", root))
            continue
        para = [ln.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not LIST.match(lines[i]) and not lines[i].startswith("|"):
            para.append(lines[i].strip())
            i += 1
        blocks.append(("p", " ".join(para)))
    return blocks


def block_text(b):
    if b[0] == "p":
        return b[1]
    if b[0] == "table":
        return " ".join(" ".join(r) for r in b[1])
    out = []
    def walk(items):
        for it in items:
            out.append(it[1])
            for part in it[2]:
                out.append(part) if isinstance(part, str) else walk(part)
    walk(b[1])
    return " ".join(out)


def render_items(items, refs_page=False):
    if not items:
        return ""
    tag = "ol" if items[0][0][0].isdigit() else "ul"
    out = [f"<{tag}>"]
    for mk, text, parts in items:
        rid = ""
        if refs_page:
            m = re.match(r"^\[(\d+)\]\s*(.*)$", text)
            if m:
                rid = f' id="ref-{m.group(1)}"'
                text = f'<span class="rn">[{m.group(1)}]</span> ' + inline(m.group(2), cites=False)
            else:
                text = inline(text, cites=False)
        else:
            text = inline(text)
        more = "".join(f"<p>{inline(p, not refs_page)}</p>" if isinstance(p, str) else render_items(p, refs_page) for p in parts)
        out.append(f"<li{rid}>{text}{more}</li>")
    out.append(f"</{tag}>")
    return "".join(out)


def render_block(b, refs_page=False):
    if b[0] == "table":
        head, *body = b[1]
        th = "".join(f"<th>{inline(c)}</th>" for c in head)
        tr = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
        return f'<div class="wrap"><table><tr>{th}</tr>{tr}</table></div>'
    if b[0] == "list":
        return render_items(b[1], refs_page)
    t = b[1]
    if refs_page:
        m = re.match(r"^\[(\d+)\]\s*(.*)$", t)
        if m:
            return f'<p id="ref-{m.group(1)}"><span class="rn">[{m.group(1)}]</span> {inline(m.group(2), cites=False)}</p>'
        return f"<p>{inline(t, cites=False)}</p>"
    img = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", t)
    if img:
        svg = OUT.parent / img.group(2)
        if svg.suffix == ".svg" and svg.exists():
            return f'<figure class="fig" role="img" aria-label="{html.escape(img.group(1))}">{inline_svg(svg)}</figure>'
        return f'<figure><img src="{html.escape(img.group(2))}" alt="{html.escape(img.group(1))}"></figure>'
    if re.match(r"^\*[^*].*\*$", t):   # a line all in italics, under a figure: its caption
        return f'<p class="caption">{inline(t)}</p>'
    lead = re.match(r"^\*\*(.+?)\*\*(.*)$", t)
    if lead and lead.group(2).strip():   # a paragraph opening with a bold phrase: a second-level entry in the contents
        label = re.sub(r"[.:]$", "", re.sub(r"\s*\(.*?\)\s*$", "", lead.group(1))).strip()
        if label not in SKIP_TOC:
            return f'<p class="lead" data-toc="{html.escape(label)}">{inline(t)}</p>'
    if lead and not lead.group(2).strip():
        label = re.sub(r"[.:]$", "", lead.group(1)).strip()   # a bold line over a list: also a part in the contents
        return f'<p class="lead" data-toc="{html.escape(label)}">{inline(t)}</p>'
    return f"<p>{inline(t)}</p>"


# the figures are drawn in fixed light colours (they also go into the md and Word copies); on the page each colour
# follows the site's theme: the same ramp, its dark steps in dark mode (user, 2026-10-30: the drawing goes dark too)
FIG_COLOURS = {   # drawn colour: (name, light, dark)
    "#FFFFFF": ("bg", "var(--bg)", "var(--bg)"),
    "#E1F5EE": ("teal-fill", "#E1F5EE", "#085041"),
    "#0F6E56": ("teal-line", "#0F6E56", "#5DCAA5"),
    "#085041": ("teal-text", "#085041", "#9FE1CB"),
    "#EEEDFE": ("purple-fill", "#EEEDFE", "#3C3489"),
    "#534AB7": ("purple-line", "#534AB7", "#AFA9EC"),
    "#3C3489": ("purple-text", "#3C3489", "#CECBF6"),
    "#5F5E5A": ("gray-line", "#5F5E5A", "#B4B2A9"),
    "#2C2C2A": ("gray-ink", "#2C2C2A", "#F1EFE8"),
    "#888780": ("gray-hatch", "#888780", "#5F5E5A"),
}


def fig_css():
    light = "".join(f"--f-{n}: {l}; " for n, l, d in FIG_COLOURS.values())
    dark = "".join(f"--f-{n}: {d}; " for n, l, d in FIG_COLOURS.values())
    rules = "\n".join(f'  .fig [fill="{c}" i] {{ fill: var(--f-{n}); }} .fig [stroke="{c}" i] {{ stroke: var(--f-{n}); }}'
                      for c, (n, l, d) in FIG_COLOURS.items())
    return (f"  :root {{ {light}}}\n"
            f"  @media (prefers-color-scheme: dark) {{ :root:not([data-theme=\"light\"]) {{ {dark}}} }}\n"
            f"  :root[data-theme=\"dark\"] {{ {dark}}}\n{rules}\n")


def inline_svg(path):
    """The SVG's markup, sized by its viewBox, with ids made unique to this figure."""
    svg = path.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r'(<svg\b[^>]*?)\s(?:width|height)="[^"]*"', r"\1", svg)
    svg = re.sub(r'(<svg\b[^>]*?)\s(?:width|height)="[^"]*"', r"\1", svg)
    pre = path.stem + "-"
    svg = re.sub(r'\bid="([^"]+)"', lambda m: f'id="{pre}{m.group(1)}"', svg)
    svg = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{pre}{m.group(1)})", svg)
    return svg.strip()


def short_ref(text):
    """The first words of a source entry, up to its first link, for the margin."""
    t = re.split(r"\s+https?://", text, maxsplit=1)[0].strip()
    t = re.sub(r"\s*\(`[^`]*`\)", "", re.sub(r"\*([^*]+)\*", r"\1", t))   # no local file names in the margin
    if not URL.search(text):
        t = re.split(r"(?<=.{40})\.\s", t, maxsplit=1)[0]
    t = t.rstrip(".; ")
    return t if len(t) <= 150 else t[:147].rsplit(" ", 1)[0] + "…"


def main():
    md = public(SRC.read_text(encoding="utf-8"))
    figs = []
    def fig(m):
        src = SRC.parent / m.group(2)
        name = f"figure-{len(figs) + 1}{src.suffix}"
        figs.append((src, name))
        return f"![{m.group(1)}]({name})"
    md = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", fig, md)
    for src, name in figs:
        for d in (COPY.parent, OUT.parent):
            d.mkdir(parents=True, exist_ok=True)
            if src.exists() and src.resolve() != (d / name).resolve():
                shutil.copyfile(src, d / name)
    if SRC.resolve() != COPY.resolve():
        COPY.parent.mkdir(parents=True, exist_ok=True)
        COPY.write_text(md, encoding="utf-8")
    left = sorted(set(re.findall(r"`([^`]+\.(?:md|json|pdf|py))`", md)))
    if left:
        print("file names still in the text:", left)
    lines = md.split("\n")
    date = re.search(r"updated (\d+ \w+ \d{4})", md) or re.search(r"Rui Wang, (\d+ \w+ \d{4})", md)   # the latest update, else the first date
    pages, cur = [], None
    for ln in lines:
        m = re.match(r"^## (?:(\d+)\. )?(.+)$", ln)
        if m:
            cur = [m.group(1) or "", m.group(2).strip(), []]
            pages.append(cur)
        elif cur is not None:
            cur[2].append(ln)
    pages = [pg for pg in pages if pg[1] != "Open items for Rui"]   # a note for Rui, not for readers
    sources = next(pg for pg in pages if pg[1] == "Sources")

    # the reference list
    refs = {}
    for b in parse(sources[2]):
        texts = [b[1]] if b[0] == "p" else []
        if b[0] == "list":
            def walk(items):
                for it in items:
                    texts.append(it[1])
                    for part in it[2]:
                        if isinstance(part, list):
                            walk(part)
            walk(b[1])
        for t in texts:
            m = re.match(r"^\[(\d+)\]\s*(.*)$", t)
            if m:
                url = URL.search(m.group(2))
                refs[m.group(1)] = (short_ref(m.group(2)), url.group(1) if url else "")

    body, missing = [], set()
    for n, title, pl in pages:
        is_refs = pl is sources[2]
        sid = "sources" if is_refs else f"sec-{n}" if n else "summary"
        num = f'<span class="n">{n}</span>' if n else ""
        sec = [f'<section id="{sid}">', f'<h2 class="label">{num}{html.escape(title)}</h2>']
        for b in parse(pl):
            h = render_block(b, refs_page=is_refs)
            nums = [] if is_refs else list(dict.fromkeys(CITE.findall(block_text(b))))
            if nums:
                side = []
                for k in nums:
                    if k not in refs:
                        missing.add(k); continue
                    s, u = refs[k]
                    s = html.escape(s)
                    side.append(f'<span><a href="#ref-{k}">[{k}]</a> ' + (f'<a href="{u}">{s}</a>' if u else s) + "</span>")
                h = f'<div class="blk"><aside class="note ref">{"".join(side)}</aside>{h}</div>'
            sec.append(h)
        sec.append("</section>")
        body.append("\n".join(sec))

    page = TEMPLATE.replace("{{FIGCSS}}", fig_css()).replace("{{DATE}}", date.group(1) if date else "").replace("{{BODY}}", "\n\n".join(body))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(pages)} sections, {len(figs)} figures, {len(refs)} sources" + (f"; cited but not listed: {sorted(missing, key=int)}" if missing else ""))


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proposal · Angels Knoll</title>
<link rel="stylesheet" href="../site.css">
<script src="../theme.js"></script>
<style>
  /* Proposal only; the header, colours, type scale and the columns come from site.css (as on Methods).
     Built by docs/proposal_build.py from docs/proposal/proposal_en.md: edit the text there, not here. */
  section { margin-top: 40px; font-size: 0.95rem; }   /* running text: the size of Methods' text */
  section > h2 { margin-bottom: 12px; }
  h2 .n { margin-right: 8px; }
  .content ul, .content ol { padding-left: 18px; margin: 0 0 12px; }   /* the spacing of Methods' lists */
  .content li { margin-bottom: 4px; }
  .content li > ul, .content li > ol, .content li > p { margin-top: 4px; margin-bottom: 0; }
  figure { margin: 8px 0 4px; }
  figure img { display: block; width: 100%; height: auto; background: #fff; border-radius: 4px; }
  figure.fig svg { display: block; width: 100%; height: auto; }
  p.caption { font-size: 0.8rem; color: var(--muted); margin-top: 4px; }
  /* figure colours, light and dark (FIG_COLOURS in the builder) */
{{FIGCSS}}  a.cite { color: var(--muted); text-decoration: none; font-variant-numeric: tabular-nums; }
  a.cite:hover { color: var(--text); }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; margin: 6px 0 12px; }
  th, td { text-align: left; padding: 5px 8px 5px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; }
  .wrap { overflow-x: auto; }
  /* the sources a paragraph cites, in the right margin on very wide screens (site.css); narrower, the [n] links lead
     to the list under Sources */
  .blk > .note.ref span { display: block; margin-bottom: 4px; }
  .blk > .note.ref a { color: inherit; }
  @media (max-width: 1399px) { .blk > .note.ref { display: none; } }
  #sources { font-size: 0.85rem; }
  #sources p, #sources li { word-break: break-word; scroll-margin-top: 24px; }
  #sources .rn { font-weight: 700; }
  #sources :target { background: var(--hover); }
  .worked { margin-top: 10px; font-size: 0.8rem; color: var(--faint); max-width: 520px; }
</style>
</head>
<body>
<main class="container m2">
  <aside class="side">
    <header class="header">
      <p class="eyebrow">Angels Knoll · Proposal · <a href="../" class="home">home</a></p>
      <h1>Proposal</h1>
      <p class="subtitle">Angels Knoll Development Proposal. One building on Parcel Y-1: 100% affordable homes above, MOCA below, and a childcare center that connects the two.</p>
      <p class="worked">Draft of {{DATE}}.</p>
    </header>
    <nav class="toc" id="toc" aria-label="Contents"></nav>
  </aside>
  <div class="content prose">

{{BODY}}

  </div>
  <footer class="footer">Rui Wang. Draft; the numbers in square brackets are the sources at the end.</footer>
</main>
<button id="themeToggle" class="theme-toggle" aria-label="Toggle dark mode">&#9680;</button>
<script>
// the contents: every section, and the parts of each section, the one being read marked (as on Methods)
(function () {
  const toc = document.getElementById("toc");
  const heads = [...document.querySelectorAll(".content h2, .content p.lead")];
  heads.forEach((h, k) => { if (!h.id) h.id = (h.closest("section")?.id || "s") + "-" + k; });
  toc.innerHTML = heads.map((h) => h.tagName === "H2"
    ? `<a href="#${h.id}">${h.textContent.replace(/^([\\d–-]+)/, "$1 ")}</a>`
    : `<a href="#${h.id}" class="sub">${h.dataset.toc}</a>`).join("");
  const links = new Map([...toc.querySelectorAll("a")].map((a) => [a.getAttribute("href").slice(1), a]));
  const mark = () => {
    let cur = heads[0];
    for (const h of heads) if (h.getBoundingClientRect().top < 120) cur = h;
    links.forEach((a, id) => a.classList.toggle("on", id === cur.id));
  };
  addEventListener("scroll", mark, { passive: true }); mark();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
