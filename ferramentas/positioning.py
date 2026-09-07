"""Motor de posicionamento indoor por RSSI. Referencia minima e correta.
Rodar: python3 positioning.py   (auto-teste no final)"""
import numpy as np

# ---------- 1. path loss log-distance: RSSI = A - 10*n*log10(d) ----------
def rssi_to_dist(rssi, A=-45.0, n=2.8, d_max=40.0):
    """A = RSSI a 1 m; n = expoente do ambiente. Calibrados no local (ver fit_path_loss)."""
    r = np.asarray(rssi, float)
    d = 10.0 ** ((A - r) / (10.0 * n))
    return np.where(np.isfinite(d), np.clip(d, 0.3, d_max), np.nan)

def fit_path_loss(rssi_obs, dist_obs):
    """Regressao linear de RSSI vs log10(d) -> (A, n). Alimentada pela campanha de calibracao."""
    r, d = np.asarray(rssi_obs, float), np.asarray(dist_obs, float)
    m = np.isfinite(r) & (d > 0)
    x = np.log10(d[m])
    slope, A = np.polyfit(x, r[m], 1)      # r = A + slope*log10(d)
    return float(A), float(-slope / 10.0)  # n = -slope/10

# ---------- 2. multilateracao linearizada (mínimos quadrados) ----------
def multilaterate(anchors, dists, w=None):
    """anchors (N,2), dists (N,). Linearizacao subtraindo a equacao da ancora de referencia.
    A ancora mais proxima e a referencia: menor erro relativo de distancia."""
    P, d = np.asarray(anchors, float), np.asarray(dists, float)
    m = np.isfinite(d) & np.isfinite(P).all(axis=1)
    P, d = P[m], d[m]
    if len(d) < 3:
        return None, np.inf                      # ancoras insuficientes -> nao inventa posicao
    k = int(np.argmin(d))                        # referencia
    idx = [i for i in range(len(d)) if i != k]
    A = 2.0 * (P[idx] - P[k])
    b = (d[k]**2 - d[idx]**2) + (P[idx]**2).sum(1) - (P[k]**2).sum()
    if w is not None:
        sw = np.sqrt(np.asarray(w, float)[m][idx])[:, None]
        A, b = A * sw, b * sw[:, 0]
    try:
        xy, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None, np.inf
    resid = float(np.sqrt(np.mean((np.linalg.norm(P - xy, axis=1) - d) ** 2)))
    return xy, resid

def multilaterate_robust(anchors, dists, tol=4.0):
    """RANSAC: consenso entre subconjuntos de 3 ancoras, depois refit nos inliers.
    Rejeicao por residuo global NAO serve aqui: o proprio outlier enviesa o ajuste
    de referencia e o algoritmo acaba descartando a ancora boa."""
    from itertools import combinations
    P, d = np.asarray(anchors, float), np.asarray(dists, float)
    m = np.isfinite(d) & np.isfinite(P).all(axis=1)
    P, d = P[m], d[m]
    if len(d) < 3:
        return None, np.inf
    if len(d) == 3:
        return multilaterate(P, d)
    best_in, best_xy = None, None
    for c in combinations(range(len(d)), 3):
        xy, _ = multilaterate(P[list(c)], d[list(c)])
        if xy is None or not np.isfinite(xy).all():
            continue
        inl = np.abs(np.linalg.norm(P - xy, axis=1) - d) < tol
        if best_in is None or inl.sum() > best_in.sum():
            best_in, best_xy = inl, xy
    if best_xy is None:
        return multilaterate(P, d)
    if best_in.sum() >= 3:
        xy, res = multilaterate(P[best_in], d[best_in])
        if xy is not None:
            return xy, res
    return best_xy, np.inf

# ---------- 3. Kalman de velocidade constante ----------
class TrackKF:
    """Estado [x, y, vx, vy]. q: aceleracao (m/s^2) - pedestre ~0.5. r: ruido de medida (m)."""
    def __init__(self, xy, q=0.5, r=3.0):
        self.x = np.array([xy[0], xy[1], 0.0, 0.0])
        self.P = np.diag([r**2, r**2, 4.0, 4.0])
        self.q, self.r = q, r
        self.H = np.hstack([np.eye(2), np.zeros((2, 2))])

    def step(self, z, dt):
        F = np.eye(4); F[0, 2] = F[1, 3] = dt
        G = np.array([[dt**2/2, 0], [0, dt**2/2], [dt, 0], [0, dt]])
        Q = G @ (self.q**2 * np.eye(2)) @ G.T
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        if z is None or not np.isfinite(z).all():
            return self.x[:2]                     # so prediz: cobre gap de medida
        R = self.r**2 * np.eye(2)
        S = self.H @ self.P @ self.H.T + R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        y = np.asarray(z, float) - self.H @ self.x
        if y @ np.linalg.inv(S) @ y > 13.8:       # gate qui-quadrado 2gl, p=0.001
            return self.x[:2]                     # rejeita salto impossivel
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P
        return self.x[:2]

# ---------- auto-teste ----------
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    anc = np.array([[0,0],[20,0],[0,15],[20,15],[10,7.5]], float)
    truth = np.array([7.0, 5.0])

    # distancias exatas
    d = np.linalg.norm(anc - truth, axis=1)
    xy, _ = multilaterate(anc, d)
    assert np.allclose(xy, truth, atol=1e-6), xy
    print(f"exato          {xy.round(3)}  erro {np.linalg.norm(xy-truth):.4f} m")

    # ida e volta pelo modelo de propagacao
    A, n = -45.0, 2.8
    rssi = A - 10*n*np.log10(d)
    assert np.allclose(rssi_to_dist(rssi, A, n), d, rtol=1e-6)

    # calibracao recupera os parametros
    dc = rng.uniform(1, 25, 400)
    rc = A - 10*n*np.log10(dc) + rng.normal(0, 4, 400)
    Ah, nh = fit_path_loss(rc, dc)
    assert abs(Ah-A) < 1.5 and abs(nh-n) < 0.2, (Ah, nh)
    print(f"calibracao     A={Ah:.2f} (real {A})  n={nh:.2f} (real {n})")

    # ruido realista de 4 dB + uma ancora com multipath de +15 dB
    errs, errs_kf = [], []
    kf = None
    for t in range(60):
        r = A - 10*n*np.log10(d) + rng.normal(0, 4.0, len(d))
        r[2] -= 15.0
        dm = rssi_to_dist(r, A, n)
        est, _ = multilaterate_robust(anc, dm)
        if est is None: continue
        errs.append(np.linalg.norm(est - truth))
        kf = kf or TrackKF(est)
        errs_kf.append(np.linalg.norm(kf.step(est, 1.0) - truth))
    print(f"cru   mediana {np.median(errs):.2f} m   p90 {np.percentile(errs,90):.2f} m")
    print(f"kalman mediana {np.median(errs_kf):.2f} m   p90 {np.percentile(errs_kf,90):.2f} m")
    assert np.median(errs_kf) < np.median(errs), "kalman deveria reduzir o erro"

    # ancoras insuficientes / NaN nao podem virar posicao inventada
    assert multilaterate(anc[:2], d[:2])[0] is None
    assert multilaterate(anc, np.array([d[0], np.nan, np.nan, np.nan, np.nan]))[0] is None
    print("guardas de ancora insuficiente / NaN: ok")
