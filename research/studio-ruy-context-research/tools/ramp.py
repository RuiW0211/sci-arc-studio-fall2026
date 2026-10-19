import math, itertools
def hex2srgb(h):
    h=h.strip().lstrip('#'); return [int(h[i:i+2],16)/255 for i in (0,2,4)]
def s2lin(c): return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def lin(h): return [s2lin(c) for c in hex2srgb(h)]
def relLum(h):
    r,g,b=lin(h); return 0.2126*r+0.7152*g+0.0722*b
def contrast(a,b):
    x,y=sorted([relLum(a),relLum(b)],reverse=True); return (x+0.05)/(y+0.05)
def oklab(rgb):
    r,g,b=rgb
    l=(0.4122214708*r+0.5363325363*g+0.0514459929*b)**(1/3)
    m=(0.2119034982*r+0.6806995451*g+0.1073969566*b)**(1/3)
    s=(0.0883024619*r+0.2817188376*g+0.6299787005*b)**(1/3)
    return (0.2104542553*l+0.7936177850*m-0.0040720468*s,
            1.9779984951*l-2.4285922050*m+0.4505937099*s,
            0.0259040371*l+0.7827717662*m-0.8086757660*s)
def oklch(h):
    L,a,b=oklab(lin(h)); return L, math.hypot(a,b), math.degrees(math.atan2(b,a))%360
def dE(a,b): return 100*math.dist(oklab(lin(a)),oklab(lin(b)))

SURF="#0d0d0d"
# a neon-blue ramp, dark -> light, hue held in the cyan-blue band
RAMP=["#10498C","#0F5BA8","#1479D6","#1E96F5","#45B3FF","#7FCDFF","#B5E4FF"]
print(f"{'hex':9s} {'L':>6s} {'C':>6s} {'hue':>6s} {'contrast':>9s}  dL vs prev")
prev=None
for h in RAMP:
    L,C,H=oklch(h); ct=contrast(h,SURF)
    d = f"{L-prev:+.3f}" if prev is not None else "  -"
    flag = "" if (prev is None or L-prev>=0.06) else "  << dL<0.06"
    print(f"{h:9s} {L:6.3f} {C:6.3f} {H:6.1f} {ct:9.2f}  {d}{flag}")
    prev=L
print("\nlightest/darkest contrast floor (>=2:1 on dark):",
      f"{min(contrast(h,SURF) for h in RAMP):.2f}")

# categorical use: pick the circular order that maximises the worst adjacent dE
best=[]
for perm in itertools.permutations(range(1,7)):
    o=(0,)+perm
    if o[1]>o[-1]: continue
    worst=min(dE(RAMP[o[k]],RAMP[o[(k+1)%7]]) for k in range(7))
    best.append((worst,o))
best.sort(reverse=True)
print("\nbest circular orders (worst adjacent dE):")
for w,o in best[:4]: print(f"   {o}  worst dE {w:.1f}")
