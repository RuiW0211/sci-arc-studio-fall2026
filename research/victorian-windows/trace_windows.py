#!/usr/bin/env python3
"""Pattern-book plates: one repeatable element from each of six American Victorian types.

Each plate draws a single element (window, cornice bracket, dormer, porch bay)
repeated in a row, in front elevation at true scale (centimetres; 1 m scale bar
on every plate). The rendering follows the sciagraphy convention of drafting:
light from the upper left at 45 degrees, so cast shadows fall down and to the
right by the projection depth of the element. Five greys carry the form, and
white is used for lines that read against a dark ground (glazing bars, tracery,
chamfers, cut edges). The wall behind is a flat tone; siding, gutters and spires
are left out.

    Gothic Revival   c. 1840-1870   lancet window: Y-tracery, quatrefoil, quarry glazing, hood mould with label stops
    Italianate       c. 1850-1885   paired scroll brackets on a frieze: raised panels, dentils, corona, cyma
    Second Empire    c. 1855-1885   mansard dormer: segmental pediment, keystone, pilasters, side scrolls, 2-over-2 sash
    Stick Style      c. 1860-1890   porch bay: chamfered posts, diagonal braces, stick frieze, X-braced rail
    Queen Anne       c. 1880-1910   Queen Anne sash: border lights, reeded casing, bullseye blocks, sunburst pediment
    Matta-Clark      after Conical Intersect (Paris, 1975)
                     a row of plain double-hung windows cut by an oblique cone. The cut
                     exposes the wall as layers (clapboard and sheathing, balloon-frame
                     studs at 40 cm centres, lath and plaster), then the dark room, then
                     daylight through the far wall. The cone's axis is oblique, so each
                     deeper layer's circle is smaller and shifted, and the rings read as
                     crescents, as in Matta-Clark's photographs.

The elements are composites drawn from the style vocabularies and period pattern
books, not measured surveys of particular buildings.

Outputs (in --out, default ./out):
    sheet.svg     all six plates
    <slug>.svg    one plate per element, larger

Standard library only. Run:  python3 trace_windows.py [--out DIR]
"""

import argparse
import math
from pathlib import Path

R3 = math.sqrt(3)

# Light paper, five greys, white. 'lit' is a surface facing the light; g5 is the deepest shade.
C = dict(paper="#ECEEEA", wall="#DCDFDA", lit="#F5F6F3", g2="#C6CBC6", g3="#A5ACA7",
         g4="#7A827D", g5="#4B524F", ink="#2C3230", white="#FFFFFF", muted="#6E7773")


# ---------------------------------------------------------------- geometry (y down, cm)

def arc(cx, cy, r, a0, a1, step=2.0):
    """Points on a circle; angles in degrees, counter-clockwise as seen on the page."""
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))),
             cy - r * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1)))) for i in range(n)]


def pointed_arc(x, top, w, e=0.0):
    """Equilateral pointed arch over an opening of width w whose apex is at `top`,
    offset outward by e (negative = inward). Runs right springing -> apex -> left springing."""
    spring = top + w * R3 / 2
    r = w + e
    a = math.degrees(math.acos((w / 2) / r))
    return arc(x, spring, r, 0, a) + arc(x + w, spring, r, 180 - a, 180)[1:]


def pointed(x, top, w, bottom, e=0.0):
    return [(x - e, bottom), (x + w + e, bottom)] + pointed_arc(x, top, w, e)


def round_arc(x, top, w, e=0.0):
    return arc(x + w / 2, top + w / 2, w / 2 + e, 0, 180)


def round_head(x, top, w, bottom, e=0.0):
    return [(x - e, bottom), (x + w + e, bottom)] + round_arc(x, top, w, e)


def segment(x0, x1, y, rise, e=0.0):
    """Shallow arc on the chord x0..x1 at height y, apex `rise` above it; offset by e."""
    c = (x1 - x0) / 2
    r = (c * c + rise * rise) / (2 * rise)
    cy = y - rise + r
    a = math.degrees(math.atan2(cy - y, c))
    return arc((x0 + x1) / 2, cy, r + e, 180 - a, a)


def foil(cx, cy, R, n=4, lobe=0.5):
    """Outline of n overlapping circles: trefoil, quatrefoil."""
    r = R * lobe
    d = R - r
    centres = [(cx + d * math.cos(math.pi / 2 + 2 * math.pi * k / n),
                cy - d * math.sin(math.pi / 2 + 2 * math.pi * k / n)) for k in range(n)]
    pts = []
    for i, (ax, ay) in enumerate(centres):
        for p in arc(ax, ay, r, 0, 360, 1.5):
            if all(math.hypot(p[0] - bx, p[1] - by) >= r - 1e-9
                   for j, (bx, by) in enumerate(centres) if j != i):
                pts.append(p)
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    return pts


def spiral(cx, cy, r0, r1, turns):
    n = int(turns * 72)
    return [(cx + (r0 + (r1 - r0) * i / n) * math.cos(2 * math.pi * turns * i / n),
             cy - (r0 + (r1 - r0) * i / n) * math.sin(2 * math.pi * turns * i / n)) for i in range(n + 1)]


def mirror(pts, cx):
    return [(2 * cx - x, y) for x, y in pts]


# ---------------------------------------------------------------- svg markup

def P(pts):
    return '<polygon points="' + " ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + '"/>'


def L(pts):
    return '<polyline points="' + " ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + '"/>'


def R(x, y, w, h):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/>'


def O(cx, cy, r):
    return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}"/>'


def ring(c_out, c_in):
    """An annulus (or crescent) between two circles, as an even-odd path."""
    def circ(cx, cy, r):
        return f"M{cx - r:.2f} {cy:.2f} a{r:.2f} {r:.2f} 0 1 0 {2 * r:.2f} 0 a{r:.2f} {r:.2f} 0 1 0 {-2 * r:.2f} 0Z"
    return f'<path fill-rule="evenodd" d="{circ(*c_out)} {circ(*c_in)}"/>'


class Scene:
    """Collects one plate's markup. Shapes are passed as fill-less markup and toned here."""

    def __init__(self, prefix):
        self.prefix, self.defs, self.body, self.n = prefix, [], [], 0

    def uid(self, name):
        self.n += 1
        return f"{self.prefix}-{name}{self.n}"

    def add(self, s):
        self.body.append(s)

    def fill(self, markup, tone, outline=False, op=1.0):
        line = (f' stroke="{C["ink"]}" stroke-opacity=".45" stroke-width=".6" '
                f'vector-effect="non-scaling-stroke"') if outline else ""
        self.add(f'<g fill="{C[tone]}" fill-opacity="{op}"{line}>{markup}</g>')

    def stroke(self, markup, tone, w, op=1.0):
        self.add(f'<g fill="none" stroke="{C[tone]}" stroke-width="{w}" stroke-opacity="{op}" '
                 f'stroke-linecap="round" stroke-linejoin="round">{markup}</g>')

    def cast(self, markup, dx, dy=None, tone="g3", op=0.55):
        """Cast shadow, down and to the right by the element's projection."""
        dy = dx if dy is None else dy
        self.add(f'<g transform="translate({dx} {dy})" fill="{C[tone]}" fill-opacity="{op}">{markup}</g>')

    def clip(self, markup):
        cid = self.uid("c")
        self.defs.append(f'<clipPath id="{cid}">{markup}</clipPath>')
        return cid

    def clipped(self, cid, inner):
        self.add(f'<g clip-path="url(#{cid})">')
        inner()
        self.add("</g>")

    def glazing(self, opening, glass, reflect):
        """Dark reveal, glass set back (shifted down-right so the reveal shadow shows
        upper-left), and a faint reflection band."""
        cid = self.clip(opening)
        self.fill(opening, "g5")
        self.clipped(cid, lambda: (self.fill(f'<g transform="translate(3 4)">{glass}</g>', "g4"),
                                   self.fill(P(reflect), "g3", op=0.35)))
        return cid


# ---------------------------------------------------------------- the six elements

def gothic_revival(S):
    W, H = 510, 330
    S.fill(R(0, 0, W, H), "wall")
    pat = S.uid("quarry")
    S.defs.append(f'<pattern id="{pat}" patternUnits="userSpaceOnUse" width="13" height="21">'
                  f'<path d="M0 0L13 21M13 0L0 21" stroke="{C["white"]}" stroke-width=".7" stroke-opacity=".45"/></pattern>')
    for i in range(3):
        cx, w, top, bot = 85 + 170 * i, 90, 40, 280
        x, spring = cx - w / 2, top + w * R3 / 2
        outer, inner = pointed_arc(x, top, w, 24), pointed_arc(x, top, w, 16)
        hood = (P(outer + inner[::-1]) + R(x - 38, spring, 22, 8) + R(x - 40, spring - 3, 10, 18)
                + R(x + w + 16, spring, 22, 8) + R(x + w + 30, spring - 3, 10, 18))
        surround = P(pointed(x, top, w, bot, 9))
        sill = R(cx - 62, bot, 124, 9)
        S.cast(hood, 7)
        S.cast(surround + sill, 5, op=0.45)
        S.fill(surround, "g2", outline=True)
        S.fill(hood, "lit", outline=True)
        S.stroke(L(outer), "white", 1.6)
        S.fill(sill, "lit", outline=True)
        S.stroke(L([(cx - 62, bot + 0.6), (cx + 62, bot + 0.6)]), "white", 1.2)

        opening = P(pointed(x, top, w, bot))
        glass = P(pointed(x, top, w, bot, -3))
        cid = S.glazing(opening, glass, [(x, bot - 70), (x + w, bot - 140), (x + w, bot - 118), (x, bot - 48)])
        S.clipped(cid, lambda: S.add(f'<g transform="translate(3 4)" fill="url(#{pat})">{glass}</g>'))
        # tracery: two sub-lancets on a central mullion, quatrefoil in a roundel above
        sub_spring = spring + 22
        sub_top = sub_spring - 38 * R3 / 2
        S.stroke(L(pointed_arc(x + 5, sub_top, 38)) + L(pointed_arc(x + 47, sub_top, 38)), "white", 3)
        S.stroke(L([(cx, sub_spring), (cx, bot)]), "white", 4)
        S.stroke(O(cx, top + 42, 12), "white", 2.6)
        S.stroke(P(foil(cx, top + 42, 9, 4, 0.58)), "white", 1.2)
    return W, H


def italianate(S):
    W, H = 520, 210
    S.fill(R(0, 0, W, H), "wall")
    pairs = [65 + 130 * i for i in range(-1, 5)]
    # raised panels between bracket pairs: bevels lit upper-left, shaded lower-right
    for X in pairs:
        px, py, pw, ph, b = X + 32, 84, 66, 54, 6
        S.fill(R(px, py, pw, ph), "g2", outline=True)
        S.fill(P([(px, py), (px + pw, py), (px + pw - b, py + b), (px + b, py + b)]), "white", op=0.85)
        S.fill(P([(px, py), (px + b, py + b), (px + b, py + ph - b), (px, py + ph)]), "white", op=0.5)
        S.fill(P([(px, py + ph), (px + b, py + ph - b), (px + pw - b, py + ph - b), (px + pw, py + ph)]), "g3")
        S.fill(P([(px + pw, py), (px + pw, py + ph), (px + pw - b, py + ph - b), (px + pw - b, py + b)]), "g3", op=0.8)
        S.fill(R(px + b, py + b, pw - 2 * b, ph - 2 * b), "wall")
    S.fill(R(0, 150, W, 7), "lit", outline=True)                              # frieze base moulding
    S.fill(R(0, 157, W, 4), "g3", op=0.7)
    S.fill(R(0, 63, W, 24), "g3", op=0.5)                                     # corona's shadow on the frieze
    for X in pairs:
        for bx in (X - 15, X + 15):
            body = (R(bx - 11, 63, 22, 10) + P([(bx - 9, 73), (bx + 9, 73), (bx + 7, 128), (bx - 7, 128)])
                    + O(bx, 134, 10)
                    + f'<path d="M{bx - 5} 144Q{bx - 6} 160 {bx} 167Q{bx + 6} 160 {bx + 5} 144Z"/>')
            S.cast(body, 14, op=0.5)
            S.fill(body, "lit", outline=True)
            S.stroke(L([(bx + 9, 74), (bx + 7, 127)]), "g3", 2)
            S.stroke(L([(bx + 1, 78), (bx + 1, 123)]), "g3", 1.4)
            S.stroke(L([(bx - 1.5, 78), (bx - 1.5, 123)]), "white", 1.2)
            S.fill(O(bx, 134, 8.5), "g2")
            S.stroke(L(spiral(bx, 134, 8, 1.2, 2.25)), "white", 1.1)
            S.stroke(L(arc(bx, 134, 9.5, -80, 10)), "g4", 1.4)
    # bed course with dentils, corona, cyma, fillet
    S.fill(R(0, 52, W, 11), "g4")
    S.fill("".join(R(x, 52, 6, 10) for x in range(0, W, 10)), "lit")
    S.stroke("".join(L([(x + 0.5, 52), (x + 0.5, 62)]) for x in range(0, W, 10)), "white", 0.8)
    S.fill(R(0, 46, W, 6), "g2", outline=True)
    S.fill(R(0, 22, W, 24), "lit", outline=True)
    S.stroke(L([(0, 23), (W, 23)]), "white", 1.4)
    S.stroke(L([(0, 44.5), (W, 44.5)]), "g3", 1.6)
    S.fill(R(0, 10, W, 6), "lit")
    S.fill(R(0, 16, W, 6), "g3")
    S.fill(R(0, 0, W, 10), "lit", outline=True)
    S.stroke(L([(0, 10.5), (W, 10.5)]), "white", 1)
    return W, H


def second_empire(S):
    W, H = 540, 310
    S.fill(R(0, 0, W, H), "g3")                                                # slate field
    S.fill(R(0, 0, W, 14), "lit", outline=True)                                 # curb
    S.fill(R(0, 14, W, 8), "g4", op=0.6)
    for i in range(3):
        cx = 90 + 180 * i
        ped_outer = segment(cx - 60, cx + 60, 86, 26)
        ped_inner = segment(cx - 60, cx + 60, 86, 26, -9)
        console_r = f'<path d="M{cx + 50} 172C{cx + 52} 214 {cx + 77} 218 {cx + 74} 246L{cx + 50} 250Z"/>'
        console_l = f'<path d="M{cx - 50} 172C{cx - 52} 214 {cx - 77} 218 {cx - 74} 246L{cx - 50} 250Z"/>'
        sill = R(cx - 58, 250, 116, 8) + R(cx - 41, 258, 9, 12) + R(cx + 32, 258, 9, 12)
        silhouette = R(cx - 50, 98, 100, 152) + P(ped_outer) + R(cx - 58, 86, 116, 12) + console_l + console_r
        S.cast(silhouette + sill, 22, tone="g5", op=0.45)                      # dormer's shadow on the slate
        S.fill(R(cx - 50, 98, 100, 152), "g2", outline=True)
        S.fill(P(ped_outer), "lit", outline=True)
        S.stroke(L(ped_outer), "white", 1.5)
        S.fill(P(ped_inner), "g2")
        S.stroke(f'<g transform="translate(2 4)">{L(ped_inner)}</g>', "g3", 5, op=0.7)
        S.fill(f'<ellipse cx="{cx}" cy="72" rx="10" ry="7"/>', "lit", outline=True)
        S.stroke(f'<ellipse cx="{cx}" cy="72" rx="6.5" ry="4"/>', "white", 1)
        S.fill(R(cx - 58, 86, 116, 12), "lit", outline=True)
        S.stroke(L([(cx - 58, 86.6), (cx + 58, 86.6)]), "white", 1.2)
        S.fill(R(cx - 58, 98, 116, 3), "g3", op=0.8)
        for sx in (cx - 50, cx + 38):                                          # pilasters with capitals
            S.fill(R(sx, 101, 12, 149), "lit", outline=True)
            S.fill(R(sx - 2, 101, 16, 7), "lit", outline=True)
            S.stroke(L([(sx + 1, 108), (sx + 1, 249)]), "white", 1.6)
            S.stroke(L([(sx + 10.5, 108), (sx + 10.5, 249)]), "g3", 1.6)
        for con, vx in ((console_r, cx + 67), (console_l, cx - 67)):
            S.fill(con, "lit", outline=True)
            S.fill(O(vx, 242, 7), "g2", outline=True)
            S.stroke(L(spiral(vx, 242, 6, 1, 1.75)), "white", 1)
        S.fill(P(round_head(cx - 33, 110, 66, 250, 5)), "lit", outline=True)
        S.stroke(L(round_arc(cx - 33, 110, 66, 5)), "white", 1.4)
        S.glazing(P(round_head(cx - 33, 110, 66, 250)), P(round_head(cx - 33, 110, 66, 250, -3)),
                  [(cx - 33, 230), (cx + 33, 170), (cx + 33, 188), (cx - 33, 248)])
        S.stroke(L(arc(cx, 143, 28, 0, 180)) + L([(cx - 28, 143), (cx - 28, 250)]) + L([(cx + 28, 143), (cx + 28, 250)]),
                 "white", 2.2)
        S.stroke(L([(cx, 113), (cx, 250)]), "white", 3)
        S.stroke(L([(cx - 33, 186), (cx + 33, 186)]), "white", 4)
        key = P([(cx - 8, 98), (cx + 8, 98), (cx + 5, 120), (cx - 5, 120)])
        S.cast(key, 3, op=0.5)
        S.fill(key, "lit", outline=True)
        S.stroke(L([(cx - 7.5, 99), (cx - 4.6, 119)]), "white", 1.2)
        S.cast(sill, 5, op=0.5)
        S.fill(sill, "lit", outline=True)
        S.stroke(L([(cx - 58, 250.6), (cx + 58, 250.6)]), "white", 1.2)
    S.fill(R(0, 286, W, 24), "lit", outline=True)                               # eave cornice
    S.stroke(L([(0, 287), (W, 287)]), "white", 1.4)
    return W, H


def stick_style(S):
    W, H = 560, 300
    S.fill(R(0, 0, W, H), "g4")                                                # porch in shade
    S.fill(R(0, 40, W, 60), "g5", op=0.45)
    for x, y, w, h in ((68, 120, 54, 92), (253, 112, 54, 168), (438, 120, 54, 92)):
        S.fill(R(x, y, w, h), "g5", op=0.5)                                     # back wall openings, deep in shade
        S.stroke(R(x - 4, y - 4, w + 8, h + 4), "g3", 1.2, op=0.6)
    S.fill(R(0, 280, W, 9), "g2", outline=True)
    S.stroke(L([(0, 280.6), (W, 280.6)]), "white", 1.2)
    S.fill(R(0, 289, W, 11), "g3")
    # stick frieze: plate, beam, vertical sticks and alternating diagonals
    S.fill(R(0, 10, W, 20), "g5")
    frieze = "".join(R(x - 2.5, 10, 5, 20) for x in range(0, W + 1, 30))
    frieze += "".join(P([(x, 30), (x + 4, 30), (x + 30, 10), (x + 26, 10)]) for x in range(0, W, 60))
    frieze += "".join(P([(x, 10), (x + 4, 10), (x + 30, 30), (x + 26, 30)]) for x in range(30, W, 60))
    S.fill(frieze, "lit")
    S.fill(R(0, 0, W, 10) + R(0, 30, W, 10), "lit", outline=True)
    S.stroke(L([(0, 0.6), (W, 0.6)]) + L([(0, 30.6), (W, 30.6)]), "white", 1.2)
    S.fill(R(0, 40, W, 9), "g5", op=0.6)
    posts = [6 + 180 * i for i in range(4)]
    members = ""
    for px in posts[:-1]:
        qx = px + 180
        members += P([(px + 14, 104), (px + 14, 116), (px + 90, 40), (px + 78, 40)])
        members += P([(qx, 104), (qx, 116), (qx - 76, 40), (qx - 64, 40)])
        members += R(px + 14, 190, 166, 8) + R(px + 14, 256, 166, 6)
        members += P([(px + 14, 198), (px + 20, 198), (qx, 251), (qx, 256), (qx - 6, 256), (px + 14, 203)])
        members += P([(qx, 198), (qx - 6, 198), (px + 14, 251), (px + 14, 256), (px + 20, 256), (qx, 203)])
        members += R(px + 94, 198, 4, 58)
    post_shapes = "".join(R(px, 40, 14, 240) + R(px - 4, 40, 22, 12) + R(px - 3, 262, 20, 18) for px in posts)
    S.cast(members, 30, 18, tone="g5", op=0.55)
    S.cast(post_shapes, 36, 20, tone="g5", op=0.55)
    S.fill(members, "lit", outline=True)
    for px in posts[:-1]:
        S.stroke(L([(px + 14, 190.6), (px + 180, 190.6)]), "white", 1.3)
        S.stroke(L([(px + 14, 104), (px + 78, 40)]) + L([(px + 180, 104), (px + 116, 40)]), "white", 1.1)
    S.fill(post_shapes, "lit", outline=True)
    for px in posts:                                                            # chamfers with stops
        S.fill(R(px, 72, 3, 166), "white")
        S.fill(R(px + 11, 72, 3, 166), "g3")
        S.fill(P([(px, 64), (px + 3, 72), (px, 72)]) + P([(px, 246), (px + 3, 238), (px, 238)]), "white")
        S.fill(P([(px + 14, 64), (px + 11, 72), (px + 14, 72)]) + P([(px + 14, 246), (px + 11, 238), (px + 14, 238)]), "g3")
        S.stroke(L([(px - 4, 40.6), (px + 18, 40.6)]), "white", 1.1)
    return W, H


def queen_anne(S):
    W, H = 540, 320
    S.fill(R(0, 0, W, H), "wall")
    for i in range(3):
        cx = 90 + 180 * i
        frame = (R(cx - 58, 70, 14, 205) + R(cx + 44, 70, 14, 205) + R(cx - 42, 52, 84, 18)
                 + R(cx - 60, 52, 18, 18) + R(cx + 42, 52, 18, 18) + R(cx - 66, 45, 132, 7)
                 + P([(cx - 66, 45), (cx + 66, 45), (cx, 12)]))
        sill = R(cx - 64, 275, 128, 9) + R(cx - 50, 284, 100, 14)
        S.cast(frame + sill, 6, op=0.5)
        S.fill(frame, "lit", outline=True)
        S.stroke(L([(cx - 66, 44.5), (cx, 11.5), (cx + 66, 44.5)]), "white", 1.6)
        tymp = P([(cx - 52, 45), (cx + 52, 45), (cx, 19)])
        S.fill(tymp, "g2")
        cid = S.clip(tymp)
        S.clipped(cid, lambda: S.stroke("".join(L([(cx, 45), (cx + 70 * math.cos(math.radians(a)),
                                                               45 - 70 * math.sin(math.radians(a)))])
                                                for a in range(15, 170, 10)), "white", 1.3))
        S.fill(O(cx, 45, 7), "lit", outline=True)
        S.fill(R(cx - 66, 45, 132, 7), "lit", outline=True)
        S.stroke(L([(cx - 66, 45.6), (cx + 66, 45.6)]), "white", 1.1)
        for sx in (cx - 58, cx + 44):                                          # reeded side casings
            S.stroke("".join(L([(sx + d, 72), (sx + d, 273)]) for d in (3.5, 7, 10.5)), "white", 1)
            S.stroke("".join(L([(sx + d + 1.4, 72), (sx + d + 1.4, 273)]) for d in (3.5, 7, 10.5)), "g3", 0.9)
        S.stroke("".join(L([(cx - 40, y), (cx + 40, y)]) for y in (56.5, 61, 65.5)), "white", 1)
        S.stroke("".join(L([(cx - 40, y + 1.3), (cx + 40, y + 1.3)]) for y in (56.5, 61, 65.5)), "g3", 0.9)
        for bx in (cx - 51, cx + 51):                                          # bullseye corner blocks
            S.fill(O(bx, 61, 7), "g2")
            S.stroke(O(bx, 61, 4.5), "white", 1.2)
            S.fill(O(bx, 61, 2), "g4")
        S.glazing(R(cx - 44, 70, 88, 205), R(cx - 44, 70, 88, 205),
                  [(cx - 44, 250), (cx + 44, 190), (cx + 44, 206), (cx - 44, 266)])
        # upper sash: border of small coloured lights round a large pane
        gx0, gx1, gy0, gy1, b = cx - 41, cx + 44, 74, 168, 11
        cells = []
        nx = 8
        for k in range(nx):
            cw = (gx1 - gx0) / nx
            cells += [(gx0 + k * cw, gy0, cw, b), (gx0 + k * cw, gy1 - b, cw, b)]
        ny = 6
        for k in range(ny):
            ch = (gy1 - gy0 - 2 * b) / ny
            cells += [(gx0, gy0 + b + k * ch, b, ch), (gx1 - b, gy0 + b + k * ch, b, ch)]
        S.fill("".join(R(*c) for j, c in enumerate(cells) if j % 2 == 0), "g2")
        S.fill("".join(R(*c) for j, c in enumerate(cells) if j % 2 == 1), "g3")
        grid = "".join(R(*c) for c in cells)
        S.stroke(grid, "white", 1.4)
        S.stroke(R(gx0 + b, gy0 + b, gx1 - gx0 - 2 * b, gy1 - gy0 - 2 * b), "white", 2.4)
        S.fill(R(cx - 44, 168, 88, 5), "white")
        S.stroke(R(cx - 40, 177, 82, 96), "white", 2)
        S.fill(R(cx - 64, 275, 128, 9), "lit", outline=True)
        S.stroke(L([(cx - 64, 275.6), (cx + 64, 275.6)]), "white", 1.2)
        S.fill(R(cx - 50, 284, 100, 14), "g2", outline=True)
    return W, H


def matta_clark(S):
    W, H = 600, 320
    S.fill(R(0, 0, W, H), "wall")
    for cx in (110, 300, 490):                                                  # plain 2-over-2 double-hung windows
        frame = (R(cx - 52, 62, 12, 180) + R(cx + 40, 62, 12, 180) + R(cx - 56, 48, 112, 14)
                 + R(cx - 58, 44, 116, 5) + R(cx - 56, 242, 112, 8))
        S.cast(frame, 5, op=0.5)
        S.fill(frame, "lit", outline=True)
        S.stroke(L([(cx - 58, 44.5), (cx + 58, 44.5)]) + L([(cx - 56, 242.6), (cx + 56, 242.6)]), "white", 1.2)
        S.glazing(R(cx - 40, 62, 80, 180), R(cx - 40, 62, 80, 180),
                  [(cx - 40, 225), (cx + 40, 165), (cx + 40, 180), (cx - 40, 240)])
        S.stroke(L([(cx, 62), (cx, 242)]), "white", 2.6)
        S.fill(R(cx - 40, 149, 80, 5), "white")
        S.stroke(R(cx - 37, 65, 74, 84) + R(cx - 37, 156, 74, 84), "white", 1.6)

    # the cone: each layer's cut circle shrinks and shifts with depth z (cm into the wall)
    c0, r0 = (232.0, 168.0), 138.0

    def layer(z):
        return (c0[0] + 1.8 * z, c0[1] - 0.5 * z, r0 - 1.6 * z)

    skin, cavity, plaster, room = layer(0), layer(5), layer(14), layer(16.5)
    S.fill(O(*skin), "g2")                                                      # clapboard and sheathing, cut
    S.stroke(O(*layer(2.2)), "g3", 1)
    S.fill(O(*cavity), "g4")                                                    # stud cavity
    stud_ring = S.clip(ring(cavity, plaster))
    S.clipped(stud_ring, lambda: (S.fill("".join(R(x, 0, 4.5, H) for x in range(80, 460, 40)), "lit"),
                                  S.stroke("".join(L([(x + 0.4, 0), (x + 0.4, H)]) for x in range(80, 460, 40)), "white", 0.9),
                                  S.stroke("".join(L([(x + 4.1, 0), (x + 4.1, H)]) for x in range(80, 460, 40)), "g3", 0.9)))
    S.fill(O(*plaster), "lit")                                                  # lath and plaster
    lath = S.clip(ring(plaster, room))
    S.clipped(lath, lambda: S.stroke("".join(L([(0, y), (W, y)]) for y in range(20, 320, 3)), "g3", 0.6))
    grad = S.uid("room")
    S.defs.append(f'<radialGradient id="{grad}" cx=".62" cy=".42" r=".6">'
                  f'<stop offset="0" stop-color="{C["g4"]}"/><stop offset="1" stop-color="{C["g5"]}"/></radialGradient>')
    S.add(f'<circle cx="{room[0]:.2f}" cy="{room[1]:.2f}" r="{room[2]:.2f}" fill="url(#{grad})"/>')
    far = (room[0] + 50, room[1] - 16)
    S.fill(O(far[0], far[1], 46), "g3")                                         # far wall, cut
    S.fill(O(far[0] + 3, far[1] - 1, 41), "lit")
    S.fill(O(far[0] + 5, far[1] - 2, 37), "white")                              # daylight
    # shade inside the cut along its upper-left lip, then the lip itself
    lip = S.clip(O(*skin))
    S.clipped(lip, lambda: S.fill(ring(skin, (skin[0] + 16, skin[1] + 16, skin[2])), "g5", op=0.35))
    S.stroke(L(arc(skin[0], skin[1], skin[2], 20, 250)), "white", 2.2)
    S.stroke(L(arc(skin[0], skin[1], skin[2], 250, 380)), "g4", 1.4)
    return W, H


PLATES = [
    ("gothic-revival", gothic_revival, "Gothic Revival", "c. 1840–1870", "Lancet window",
     "Y-tracery · quatrefoil roundel · quarry glazing · hood mould with label stops"),
    ("italianate", italianate, "Italianate", "c. 1850–1885", "Paired cornice brackets",
     "scroll volutes · pendant drops · raised panels · dentils · corona and cyma"),
    ("second-empire", second_empire, "Second Empire", "c. 1855–1885", "Mansard dormer",
     "segmental pediment · cartouche · keystone · pilasters · side scrolls · 2-over-2 sash"),
    ("stick-style", stick_style, "Stick Style", "c. 1860–1890", "Porch bay",
     "chamfered posts with stops · diagonal braces · stick frieze · X-braced rail"),
    ("queen-anne", queen_anne, "Queen Anne", "c. 1880–1910", "Queen Anne sash window",
     "border lights · reeded casing · bullseye blocks · sunburst pediment"),
    ("matta-clark", matta_clark, "After Matta-Clark", "Conical Intersect, 1975", "Double-hung window, cut",
     "clapboard and sheathing · studs at 40 cm · lath and plaster · room · daylight"),
]


# ---------------------------------------------------------------- layout

def plate(slug, fn, style, dates, element, parts, ox, oy, pw, ph, box_w, box_h):
    S = Scene(slug)
    W, H = fn(S)
    s = min(box_w / W, box_h / H)
    dx, dy = ox + (pw - W * s) / 2, oy + 66 + (box_h - H * s) / 2
    frame = S.clip(R(0, 0, W, H))
    t, m = C["ink"], C["muted"]
    out = [f'<defs>{"".join(S.defs)}</defs>',
           f'<g transform="translate({dx:.2f} {dy:.2f}) scale({s:.4f})"><g clip-path="url(#{frame})">',
           *S.body, "</g>",
           f'<rect width="{W}" height="{H}" fill="none" stroke="{t}" stroke-opacity=".25" '
           f'stroke-width=".8" vector-effect="non-scaling-stroke"/></g>',
           f'<text x="{ox + 18}" y="{oy + 30}" font-size="15" font-weight="600" fill="{t}">{element}</text>',
           f'<text x="{ox + 18}" y="{oy + 48}" font-size="11" fill="{m}">{style} · {dates}</text>',
           f'<text x="{ox + 18}" y="{oy + ph - 16}" font-size="10.5" fill="{m}">{parts}</text>']
    bx, by, bl = ox + pw - 18 - 100 * s, oy + ph - 36, 100 * s
    out.append(f'<path d="M{bx:.1f} {by} h{bl:.1f} M{bx:.1f} {by - 3} v6 M{bx + bl / 2:.1f} {by - 2} v4 '
               f'M{bx + bl:.1f} {by - 3} v6" stroke="{m}" stroke-width="1" fill="none"/>')
    out.append(f'<text x="{bx + bl:.1f}" y="{by - 7}" font-size="9.5" text-anchor="end" fill="{m}">1 m</text>')
    return "\n".join(out)


def svg_doc(w, h, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="-apple-system, system-ui, Helvetica, Arial, sans-serif">\n'
            f'<rect width="{w}" height="{h}" fill="{C["paper"]}"/>\n{body}\n</svg>\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pw, ph, cols = 500, 420, 3
    panels = []
    for i, p in enumerate(PLATES):
        panels.append(plate(*p, (i % cols) * pw, (i // cols) * ph, pw, ph, pw - 40, ph - 130))
        single = plate(*p, 0, 0, 1100, 820, 1040, 690)
        (args.out / f"{p[0]}.svg").write_text(svg_doc(1100, 820, single))
        print(f"{p[0]:16s} {p[4]}")
    rows = math.ceil(len(PLATES) / cols)
    (args.out / "sheet.svg").write_text(svg_doc(cols * pw, rows * ph, "\n".join(panels)))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
