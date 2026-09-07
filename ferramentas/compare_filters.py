"""Duas etapas (multilateracao+KF) vs filtro de particulas sobre RSSI cru, com e sem planta.
Rodar: python3 compare_filters.py"""
import numpy as np, time
from ferramentas.positioning import rssi_to_dist, multilaterate_robust, TrackKF

A0, N_EXP, SIGMA, WALL_DB, SENS = -45.0, 2.8, 6.0, 12.0, -92.0

# planta: predio 40x30, duas paredes internas em serpentina (vaos nas pontas)
WALLS = np.array([
    [[0,0],[40,0]], [[40,0],[40,30]], [[40,30],[0,30]], [[0,30],[0,0]],   # externas
    [[0,20],[30,20]],                                                      # vao em x>30
    [[10,10],[40,10]],                                                     # vao em x<10
], float)
ANC = np.array([[2,3],[20,2],[38,3],[2,17],[38,17],[2,27],[20,28],[38,27]], float)

def _ccw(a,b,c): return (c[...,1]-a[...,1])*(b[...,0]-a[...,0]) > (b[...,1]-a[...,1])*(c[...,0]-a[...,0])
def crosses(p,q,w0,w1):
    """Interseccao segmento-segmento, vetorizada em p,q."""
    return (_ccw(p,w0,w1)!=_ccw(q,w0,w1)) & (_ccw(p,q,w0)!=_ccw(p,q,w1))

def n_walls(p,q):
    return sum(int(crosses(np.asarray(p,float),np.asarray(q,float),w[0],w[1])) for w in WALLS[4:])

def blocked(p,q):
    """True se o movimento p->q atravessa qualquer parede (inclui externas)."""
    out=np.zeros(len(p),bool)
    for w in WALLS: out |= crosses(p,q,w[0],w[1])
    return out

def observe(xy, rng):
    """RSSI por ancora, com perda extra por parede atravessada e corte de sensibilidade."""
    d=np.maximum(np.linalg.norm(ANC-xy,axis=1),0.5)
    r=A0-10*N_EXP*np.log10(d)-WALL_DB*np.array([n_walls(a,xy) for a in ANC])
    r=r+rng.normal(0,SIGMA,len(ANC))
    return np.where(r>SENS, r, np.nan)

def path(dt=2.0, v=1.3):
    """Serpentina pelos tres corredores."""
    wp=np.array([[5,25],[35,25],[35,15],[5,15],[5,5],[35,5]],float); pts=[]
    for a,b in zip(wp[:-1],wp[1:]):
        L=np.linalg.norm(b-a); k=max(int(L/(v*dt)),1)
        pts += [a+(b-a)*i/k for i in range(k)]
    return np.array(pts)

# ---------- estimador 1: duas etapas ----------
def two_stage(obs, dt):
    est=[]; kf=None
    for r in obs:
        m=np.isfinite(r)
        xy,_=(None,0) if m.sum()<3 else multilaterate_robust(ANC[m], rssi_to_dist(r[m],A0,N_EXP))
        if xy is None: est.append(kf.step(None,dt)[:2] if kf else np.array([np.nan,np.nan])); continue
        kf = kf or TrackKF(xy, r=6.0)
        est.append(kf.step(xy,dt).copy())
    return np.array(est)

# ---------- estimador 2: particulas sobre RSSI cru ----------
def particle(obs, dt, n=600, use_map=True, q=0.6, seed=1, robust=True):
    """Verossimilhanca em dB (o ruido E gaussiano em dB, nao em metros).
    robust=True: piso no log-lik por ancora = equivalente PF do inlier/outlier do RANSAC."""
    rng=np.random.default_rng(seed)
    p=np.column_stack([rng.uniform(0,40,n), rng.uniform(0,30,n)])
    v=rng.normal(0,0.5,(n,2)); w=np.full(n,1/n); est=[]
    for r in obs:
        pn = p + v*dt + rng.normal(0,q*dt**2/2,(n,2))
        v  = v + rng.normal(0,q*dt,(n,2))
        if use_map:
            bad=blocked(p,pn); pn[bad]=p[bad]; v[bad]*=-0.3   # nao atravessa parede
        p=pn
        m=np.isfinite(r)
        if m.sum():
            d=np.maximum(np.linalg.norm(p[:,None,:]-ANC[None,m,:],axis=2),0.5)
            mu=A0-10*N_EXP*np.log10(d)
            ll=-0.5*((r[m]-mu)/SIGMA)**2
            if robust: ll=np.maximum(ll,-8.0)                 # cauda pesada p/ NLOS
            lw=np.log(w+1e-300)+ll.sum(1); lw-=lw.max()
            w=np.exp(lw); s=w.sum()
            w = np.full(n,1/n) if not np.isfinite(s) or s<=0 else w/s
        est.append(p.T@w)
        if 1.0/np.sum(w**2) < n/2:                            # reamostra por ESS
            idx=rng.choice(n,n,p=w); p,v,w=p[idx],v[idx],np.full(n,1/n)
    return np.array(est)

if __name__=="__main__":
    rng=np.random.default_rng(42); truth=path(); dt=2.0
    runs={k:[] for k in ("2 etapas (multilat+KF)","particulas, sem planta","particulas, com planta")}
    t={k:0.0 for k in runs}
    for trial in range(10):
        obs=np.array([observe(x,rng) for x in truth])
        heard=np.isfinite(obs).sum(1)
        for name,fn in (("2 etapas (multilat+KF)", lambda: two_stage(obs,dt)),
                        ("particulas, sem planta", lambda: particle(obs,dt,use_map=False,seed=trial)),
                        ("particulas, com planta", lambda: particle(obs,dt,use_map=True,seed=trial))):
            t0=time.perf_counter(); e=fn(); t[name]+=time.perf_counter()-t0
            runs[name].append(np.linalg.norm(e[10:]-truth[10:],axis=1))   # descarta convergencia
    print(f"ancoras ouvidas por amostra: mediana {np.median(heard):.0f} de {len(ANC)}   "
          f"passos={len(truth)}  sigma={SIGMA} dB  parede={WALL_DB} dB\n")
    print(f"{'estimador':26s} {'mediana':>9s} {'p90':>8s} {'p99':>8s} {'ms/dispositivo':>16s}")
    for k,v in runs.items():
        a=np.concatenate(v); a=a[np.isfinite(a)]
        print(f"{k:26s} {np.median(a):8.2f}m {np.percentile(a,90):7.2f}m "
              f"{np.percentile(a,99):7.2f}m {t[k]/10/len(truth)*1e3:15.2f}")
