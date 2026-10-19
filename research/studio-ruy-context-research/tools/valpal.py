import math, itertools, sys
BAND={'light':(0.43,0.77),'dark':(0.48,0.67)}; CHROMA_FLOOR=0.10
CVD_TARGET, CVD_FLOOR, NORMAL_FLOOR, CONTRAST_MIN = 8.0, 6.0, 15.0, 3.0
SURF={'light':'#fcfcfb','dark':'#1a1a19'}
MACHADO={'protan':[[0.152286,1.052583,-0.204868],[0.114503,0.786281,0.099216],[-0.003882,-0.048116,1.051998]],
         'deutan':[[0.367322,0.860646,-0.227968],[0.280085,0.672501,0.047413],[-0.011820,0.042940,0.968881]],
         'tritan':[[1.255528,-0.076749,-0.178779],[-0.078411,0.930809,0.147602],[0.004733,0.691367,0.303900]]}
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
def sim(h,kind):
    M=MACHADO[kind]; v=lin(h)
    return [max(0.0,min(1.0,sum(M[i][j]*v[j] for j in range(3)))) for i in range(3)]
def dE(c1,c2):
    a=oklab(c1); b=oklab(c2); return 100*math.dist(a,b)
def run(pal, mode, pairs='adjacent', extra=()):
    surf=SURF[mode]; lo,hi=BAND[mode]; fails=[]; warns=[]
    print(f"\n== mode {mode} | surface {surf} | pairs {pairs} ==")
    for h in pal:
        L,C,_=oklch(h); ct=contrast(h,surf)
        st=[]
        if not(lo<=L<=hi): st.append(f"L {L:.3f} OUT[{lo},{hi}] FAIL"); fails.append(h)
        if C<CHROMA_FLOOR: st.append(f"C {C:.3f} FAIL"); fails.append(h)
        if ct<CONTRAST_MIN: st.append(f"contrast {ct:.2f} WARN(relief)"); warns.append(h)
        print(f"  {h}  L={L:.3f} C={C:.3f} contrast={ct:.2f}  {' '.join(st) or 'ok'}")
    idx=list(range(len(pal)))
    pl=[(i,i+1) for i in idx[:-1]] if pairs=='adjacent' else list(itertools.combinations(idx,2))
    pl=list(pl)+list(extra)
    worstN=1e9; worstC=1e9
    for i,j in pl:
        a,b=pal[i],pal[j]
        n=dE(lin(a),lin(b))
        p=dE(sim(a,'protan'),sim(b,'protan')); d=dE(sim(a,'deutan'),sim(b,'deutan'))
        c=min(p,d); worstN=min(worstN,n); worstC=min(worstC,c)
        flag=''
        if n<NORMAL_FLOOR: flag+=' NORMAL-FAIL'; fails.append((a,b))
        if c<CVD_FLOOR: flag+=' CVD-FAIL'; fails.append((a,b))
        elif c<CVD_TARGET: flag+=' CVD-WARN'
        if flag: print(f"   pair {a}/{b}: normal {n:.1f}  cvd {c:.1f} {flag}")
    print(f"  worst normal dE {worstN:.1f} (floor {NORMAL_FLOOR})   worst CVD dE {worstC:.1f} (target {CVD_TARGET}, floor {CVD_FLOOR})")
    print("  RESULT:", "FAIL" if fails else ("PASS (with relief WARNs)" if warns else "PASS"))
    return not fails
LIGHT="#2a78d6,#eb6834,#1baf7a,#eda100,#e87ba4,#008300,#6250d6".split(',')
DARK ="#3987e5,#d95926,#199e70,#c98500,#d55181,#008300,#9085e9".split(',')
ok1=run(LIGHT,'light','adjacent',extra=[(6,0)])   # +wrap pair violet<->blue
ok2=run(DARK ,'dark' ,'adjacent',extra=[(6,0)])
print("\nOVERALL:", "PASS" if (ok1 and ok2) else "FAIL")

def circ_ok(order, pal, mode):
    worstN=1e9; worstC=1e9
    for k in range(len(order)):
        a=pal[order[k]]; b=pal[order[(k+1)%len(order)]]
        n=dE(lin(a),lin(b))
        c=min(dE(sim(a,'protan'),sim(b,'protan')), dE(sim(a,'deutan'),sim(b,'deutan')))
        worstN=min(worstN,n); worstC=min(worstC,c)
    return worstN, worstC

def search():
    best=[]
    base=list(range(7))
    for perm in itertools.permutations(base[1:]):      # fix slot 0 to kill rotations
        order=(0,)+perm
        if order[1] > order[-1]:                        # kill reflections
            continue
        nL,cL = circ_ok(order,LIGHT,'light')
        nD,cD = circ_ok(order,DARK ,'dark')
        if min(nL,nD)>=NORMAL_FLOOR and min(cL,cD)>=CVD_FLOOR:
            best.append((min(cL,cD), min(nL,nD), order))
    best.sort(reverse=True)
    print(f"\npassing circular orders: {len(best)}")
    for c,n,o in best[:6]:
        print(f"  order {o}  worstCVD {c:.1f}  worstNormal {n:.1f}")
    return best
best = search()
