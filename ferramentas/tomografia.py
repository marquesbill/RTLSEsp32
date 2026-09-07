"""Tomografia por radio: 6 ancoras em hexagono, corpo no meio atenua os enlaces.
Reconstroi a imagem de atenuacao por minimos quadrados regularizados.
Rodar: python3 tomografia.py"""
import numpy as np
from itertools import combinations
LAM = 3e8/2.44e9                      # 12.3 cm

def hexagono(R, n=6):
    a = np.arange(n)*2*np.pi/n
    return np.column_stack([R*np.cos(a), R*np.sin(a)])

def malha(R, passo):
    g = np.arange(-R, R+1e-9, passo)
    X, Y = np.meshgrid(g, g)
    P = np.column_stack([X.ravel(), Y.ravel()])
    return P[np.linalg.norm(P, axis=1) <= R*1.02], X.shape

def pesos(ANC, P, excesso=0.35):
    """Modelo de elipse de Fresnel (Wilson & Patwari): pixel pesa no enlace se a soma
    das distancias aos dois extremos excede o comprimento do enlace em menos de `excesso`."""
    L = list(combinations(range(len(ANC)), 2))
    W = np.zeros((len(L), len(P)))
    for k, (i, j) in enumerate(L):
        d = np.linalg.norm(ANC[i]-ANC[j])
        s = np.linalg.norm(P-ANC[i], axis=1) + np.linalg.norm(P-ANC[j], axis=1)
        W[k] = (s - d < excesso) / np.sqrt(d)          # 1/sqrt(d): enlace longo pesa menos
    return W, L

def corpo(P, xy, raio=0.25):
    return (np.linalg.norm(P-xy, axis=1) < raio).astype(float)

def reconstruir(W, y, alpha):
    """Forma dual: 15 enlaces << centenas de pixels, entao inverte 15x15."""
    A = W @ W.T + alpha*np.eye(len(W))
    return W.T @ np.linalg.solve(A, y)

def estimar(W, P, y, alpha):
    x = reconstruir(W, y, alpha)
    if x.max() <= 0: return None
    w = np.clip(x, 0, None)**3                          # centroide dos pixels mais fortes
    w[w < w.max()*0.5] = 0
    return (P*w[:,None]).sum(0)/w.sum()

def ensaio(R=4.0, passo=0.25, sigma=1.0, atenua=6.0, alpha=None, n=300, seed=0, dois=False):
    rng = np.random.default_rng(seed)
    ANC = hexagono(R); P, _ = malha(R, passo); W, L = pesos(ANC, P)
    alpha = alpha if alpha else 1e-2*np.trace(W@W.T)/len(L)
    errs = []
    for _ in range(n):
        while True:
            t = rng.uniform(-R, R, 2)
            if np.linalg.norm(t) < R*0.8: break
        x = corpo(P, t)*atenua
        if dois:
            while True:
                t2 = rng.uniform(-R, R, 2)
                if np.linalg.norm(t2) < R*0.8 and np.linalg.norm(t2-t) > 1.5: break
            x = x + corpo(P, t2)*atenua
        y = W @ x + rng.normal(0, sigma, len(L))
        e = estimar(W, P, y, alpha)
        if e is not None: errs.append(np.linalg.norm(e-t))
    a = np.array(errs)
    return np.median(a), np.percentile(a, 90)

if __name__ == "__main__":
    for R in (3.0, 4.0, 6.0):
        A = hexagono(R); d = [np.linalg.norm(A[i]-A[j]) for i,j in combinations(range(6),2)]
        fr = np.sqrt(LAM*(max(d)/2)**2/max(d))
        print(f"hexágono R={R} m: {len(d)} enlaces, {min(d):.1f}–{max(d):.1f} m, "
              f"1ª zona de Fresnel no meio do maior = {fr*100:.0f} cm de raio")
    print()
    print(f"{'ruído do enlace':>16s} {'mediana':>9s} {'p90':>8s}")
    for s in (0.3, 0.5, 1.0, 2.0, 3.0):
        m,p = ensaio(sigma=s); print(f"{s:14.1f}dB {m:8.2f}m {p:7.2f}m")
    print(f"\n{'tamanho (raio)':>16s} {'mediana':>9s} {'p90':>8s}")
    for R in (2.0, 3.0, 4.0, 6.0, 8.0):
        m,p = ensaio(R=R, passo=R/16, sigma=1.0); print(f"{R:14.1f}m {m:8.2f}m {p:7.2f}m")
    print(f"\n{'duas pessoas':>16s} {'mediana':>9s} {'p90':>8s}")
    m,p = ensaio(sigma=1.0, dois=True); print(f"{'':>16s} {m:8.2f}m {p:7.2f}m")
