"""Fingerprinting: mapa de radio medido no lugar do modelo de path loss.
O filtro de particulas continua igual — troca so a verossimilhanca (Tracker.loglik).
Rodar: python3 fingerprint.py"""
import numpy as np
from ferramentas import compare_filters as C
from rtls import tracker as T
from ferramentas.compare_filters import WALLS, path

BOUNDS=(0,0,40,30)
ANCH={"A1":(2.,3.),"A2":(38.,17.),"A3":(20.,28.),"A4":(20.,5.),"A5":(5.,17.),"A6":(33.,26.)}
AP=np.array(list(ANCH.values()))
C.ANC=AP; C.SIGMA=2.7; C.WALL_DB=12.0; C.SENS=-105.0
FLOOR=-100.0

def rssi_limpo(xy, wall_db=None):
    w = C.WALL_DB if wall_db is None else wall_db
    d=np.maximum(np.linalg.norm(AP-xy,axis=1),0.5)
    return C.A0-10*C.N_EXP*np.log10(d)-w*np.array([C.n_walls(a,xy) for a in AP])

def build_map(grid=1.0, n_amostras=None, seed=0, wall_db=None):
    """n_amostras = quantas leituras por ponto no levantamento (None = ideal, sem ruido).
    Ruido do levantamento cai com sqrt(N): 30 s do teclado a 12,7 Hz ~ 380 amostras."""
    rng=np.random.default_rng(seed)
    xs=np.arange(BOUNDS[0],BOUNDS[2]+1e-9,grid); ys=np.arange(BOUNDS[1],BOUNDS[3]+1e-9,grid)
    M=np.zeros((len(ys),len(xs),len(AP)))
    for j,y in enumerate(ys):
        for i,x in enumerate(xs):
            v=rssi_limpo(np.array([x,y]),wall_db)
            if n_amostras: v=v+rng.normal(0,C.SIGMA/np.sqrt(n_amostras),len(AP))
            M[j,i]=np.maximum(v,FLOOR)
    return M,xs,ys,grid

class FP(T.Tracker):
    """So o modelo de medida muda. Movimento, planta, reamostragem, ciclo de vida: iguais."""
    def __init__(self,*a,mapa=None,modo="absoluto",**k):
        super().__init__(*a,**k); self.M,self.xs,self.ys,self.g = mapa; self.modo=modo
    def loglik(self, P, ai, rssi, b=0.0):   # b: o offset por ancora do Tracker; o mapa medido ja o contem
        i=np.clip(((P[:,0]-BOUNDS[0])/self.g+0.5).astype(int),0,len(self.xs)-1)
        j=np.clip(((P[:,1]-BOUNDS[1])/self.g+0.5).astype(int),0,len(self.ys)-1)
        m=self.M[j,i][:,ai]
        if self.modo=="absoluto":
            dif = rssi - m
        else:                                   # diferencas: A (potencia de TX) se cancela
            k=int(np.argmax(rssi))
            dif = (rssi-rssi[k]) - (m-m[:,[k]])
        return np.maximum(-0.5*(dif/self.sigma)**2, self.ll_floor)

def run(cls, trials=10, cut=-85.0, **kw):
    truth=path(dt=1.0); reg=[]
    for tr in range(trials):
        rng=np.random.default_rng(400+tr)
        tk=cls(ANCH,T.Floorplan(WALLS,BOUNDS),sigma=6.0,seed=tr,**kw); e=[]
        for i,x in enumerate(truth):
            r=C.observe(x,rng)
            o={a:float(v) for a,v in zip(ANCH,r) if np.isfinite(v) and v>=cut}
            xy=tk.update(f"d{tr}",o,i*1.0)
            e.append(np.inf if xy is None else np.linalg.norm(xy-x))
        e=np.array(e[15:]); reg.append(e[np.isfinite(e)])
    a=np.concatenate(reg); return np.median(a), np.percentile(a,90)

if __name__=="__main__":
    print(f"{'metodo':>44s} {'mediana':>9s} {'p90':>8s}")
    m,p=run(T.Tracker); print(f"{'multilateracao (modelo de path loss)':>44s} {m:8.2f}m {p:7.2f}m")
    base=build_map(1.0)
    print(f"{'levantamento a cada 1,0 m':>44s} {'':>9s}")
    for modo in ("absoluto","diferenca"):
        m,p=run(FP,mapa=base,modo=modo); print(f"{'  fingerprint, '+modo:>44s} {m:8.2f}m {p:7.2f}m")
    print(f"\n{'densidade do levantamento (modo absoluto)':>44s}")
    for g in (0.5,1.0,2.0,3.0,5.0):
        M=build_map(g); n=M[0].shape[0]*M[0].shape[1]
        m,p=run(FP,mapa=M); print(f"{f'  grade {g} m ({n} pontos)':>44s} {m:8.2f}m {p:7.2f}m")
    print(f"\n{'ruido do levantamento (grade 1 m)':>44s}")
    for N,lab in ((None,"ideal"),(380,"30 s por ponto"),(40,"3 s por ponto"),(5,"amostra rapida")):
        M=build_map(1.0,n_amostras=N,seed=1)
        m,p=run(FP,mapa=M); print(f"{'  '+lab:>44s} {m:8.2f}m {p:7.2f}m")
    print(f"\n{'AMBIENTE MUDOU depois do levantamento':>44s}")
    for w,lab in ((12.0,"nada mudou"),(15.0,"parede +3 dB"),(18.0,"parede +6 dB"),(8.0,"porta aberta, -4 dB")):
        M=build_map(1.0,wall_db=12.0)          # mapa levantado com 12 dB
        C.WALL_DB=w                            # realidade mudou
        m,p=run(FP,mapa=M); print(f"{'  '+lab:>44s} {m:8.2f}m {p:7.2f}m")
    C.WALL_DB=12.0
