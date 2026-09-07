"""Le a reconstrucao 3D e a encaixa no frame da planta.

Duas coisas, nenhuma delas escolhida a mao:

`ler()` — o .ply do Record3D em binario little-endian, 6,34 M pontos com RGB.
Corta o fantasma do espelho (uma copia da sala dobrada para z < -4,0; o plano do
espelho esta em -4,025 e sao 50.234 pontos, nao mais que isso).

`encaixa()` — qual eixo da nuvem vira x, qual vira y, os dois sinais e as duas
translacoes, por CORRELACAO da pegada vista de cima contra a mascara dos
comodos. Usa os 6,3 M de pontos em vez de 3 picos a dedo, e o maximo e unico
porque a planta e um L. Erro residual ~5 cm, do tamanho da espessura da parede.
"""
import os, sys, numpy as np
from scipy.signal import fftconvolve
AQUI = os.path.dirname(os.path.abspath(__file__))

from rtls import sitio as PL

# O caminho da nuvem NAO vive no codigo: e do usuario, e muda de sitio para sitio.
PLY = os.environ.get("RTLS_NUVEM", "")   # .ply do Record3D/LiDAR; ver docs/matematica/09-geometria-3d.md
PX = 0.02                        # 2 cm; o voxel da nuvem e 1 cm
Z_ESPELHO = -4.0                 # abaixo disso e a sala refletida no espelho
DT = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
               ("r", "u1"), ("g", "u1"), ("b", "u1")])


def ler(ply=PLY, sem_espelho=True):
    """-> (P (N,3) float32 no frame BRUTO da nuvem, C (N,3) uint8 RGB)."""
    with open(ply, "rb") as f:
        cab = b""
        while b"end_header" not in cab:
            cab += f.readline()
        d = np.fromfile(f, dtype=DT)
    P = np.stack([d["x"], d["y"], d["z"]], 1).astype(np.float32)
    C = np.stack([d["r"], d["g"], d["b"]], 1)
    if sem_espelho:
        m = P[:, 2] > Z_ESPELHO
        P, C = P[m], C[m]
    return P, C


def _mascara_planta():
    xs = np.arange(PL.X_MIN - 0.4, PL.X_MAX + 0.4, PX)
    ys = np.arange(PL.Y_MIN - 0.4, PL.Y_MAX + 0.4, PX)
    G = np.zeros((len(ys), len(xs)), np.float32)
    X, Y = np.meshgrid(xs, ys)
    Q = np.stack([X.ravel(), Y.ravel()], 1)
    for poly in PL.COMODOS.values():
        p = np.array(poly)
        G.ravel()[(Q[:, 0] >= p[:, 0].min()) & (Q[:, 0] <= p[:, 0].max()) &
                  (Q[:, 1] >= p[:, 1].min()) & (Q[:, 1] <= p[:, 1].max())] = 1.0
    return G, xs[0], ys[0]


def encaixa(P):
    """-> (sobreposicao, ix, sx, cx, iy, sy, cy):  x = sx*P[:,ix]+cx,  y = sy*P[:,iy]+cy."""
    M, x0, y0 = _mascara_planta()
    alto = P[(P[:, 1] > 0.15) & (P[:, 1] < 2.30)]        # sem piso e sem teto
    melhor = None
    for ix, iy in ((2, 0), (0, 2)):
        for sx in (1, -1):
            for sy in (1, -1):
                u, v = sx * alto[:, ix], sy * alto[:, iy]
                bu = np.arange(u.min(), u.max() + PX, PX)
                bv = np.arange(v.min(), v.max() + PX, PX)
                H, _, _ = np.histogram2d(v, u, bins=(bv, bu))
                H = (H > 3).astype(np.float32)            # ocupado, nao densidade
                c = fftconvolve(H, M[::-1, ::-1], mode="full")
                j = np.unravel_index(np.argmax(c), c.shape)
                cy = y0 - (bv[0] + (j[0] - M.shape[0] + 1) * PX)
                cx = x0 - (bu[0] + (j[1] - M.shape[1] + 1) * PX)
                if melhor is None or c[j] > melhor[0]:
                    melhor = (float(c[j]), ix, sx, float(cx), iy, sy, float(cy))
    return melhor


def planta(P):
    """Nuvem bruta -> coordenadas de planta (x, y, altura)."""
    _, ix, sx, cx, iy, sy, cy = encaixa(P)
    return np.stack([sx * P[:, ix] + cx, sy * P[:, iy] + cy, P[:, 1]], 1)


def _sintetica(comodos, semente=0, A=4.0, B=0.077):
    """Nuvem sintetica DENTRO de `comodos`, ja embaralhada para um frame bruto.
    -> (P bruto, q verdadeiro em coordenadas de planta). x = +P[:,2]+A, y = -P[:,0]+B."""
    rng = np.random.default_rng(semente)
    # a mascara e binaria com corte em 3 pontos por celula de 2 cm: com poucos
    # pontos a pegada fica esburacada e o pico da correlacao alarga. ~12 pontos
    # por celula (a nuvem real tem centenas).
    n = int(12 * sum(PL.area(v) for v in comodos.values()) / (PX * PX))
    # sem recuo nas bordas: uma pegada MENOR que a mascara desliza dentro dela e
    # a correlacao vira um plato — o argmax pega um canto do plato e o teste
    # falha por 0,1 m sem que haja nada errado no encaixe.
    q = rng.uniform([PL.X_MIN, PL.Y_MIN, 0.2], [PL.X_MAX, PL.Y_MAX, 2.2], (n, 3))
    q = q[[any(PL.dentro_poly(p[:2], c) for c in comodos.values()) for p in q]]
    return np.stack([B - q[:, 1], q[:, 2], q[:, 0] - A], 1).astype(np.float32), q


def demo():
    """Sem o .ply, testa o que o encaixe promete — e a simetria que ele NAO vence."""
    M, x0, y0 = _mascara_planta()
    # a mascara cobre a area do sitio (nao a forma dele: cada sitio tem a sua)
    area = sum(PL.area(v) for v in PL.COMODOS.values())
    assert abs(M.sum() * PX * PX - area) < 2.0, M.sum()

    # (1) planta ASSIMETRICA: o encaixe e unico e tem de acertar eixo, sinal e
    # translacao. Tira-se um comodo para virar um L — e o caso de 09 §9.2.
    todos = PL.COMODOS
    try:
        PL.COMODOS = {k: v for k, v in todos.items() if k != sorted(todos)[-1]}
        P, q = _sintetica(PL.COMODOS)
        A, B = 4.0, 0.077
        s, ix, sx, cx, iy, sy, cy = encaixa(P)
        assert (ix, sx, iy, sy) == (2, 1, 0, -1), (ix, sx, iy, sy)
        assert abs(cx - A) < 0.05 and abs(cy - B) < 0.05, (cx, cy)
        e = float(np.abs(planta(P) - q).max())
        assert e < 0.05, e
    finally:
        PL.COMODOS = todos
    print(f"encaixe ok em planta assimetrica: erro maximo {e * 100:.1f} cm")

    # (2) o mesmo sitio INTEIRO. Se a pegada for simetrica, o encaixe EMPATA e
    # nao ha correlacao que desempate — e por isso que 09 §9.2 manda usar a cor
    # ou a trajetoria da camera. O teste nao exige acerto: exige que o empate
    # apareca, senao o proximo a mexer aqui vai confiar num numero que nao existe.
    P, q = _sintetica(todos)
    s, ix, sx, cx, iy, sy, cy = encaixa(P)
    simetrica = (M == M[::-1, :]).mean() > 0.99 or (M == M[:, ::-1]).mean() > 0.99
    e = float(np.abs(planta(P) - q).max())
    if simetrica:
        assert e > 0.05, ("planta simetrica encaixou exato — bom demais para ser "
                          "verdade, confira a mascara", e)
        print(f"'{PL.NOME}' tem pegada simetrica: o encaixe empata "
              f"(erro {e:.2f} m). Desempate pela cor ou pela camera — 09 §9.2.")
    else:
        assert e < 0.05, e
        print(f"'{PL.NOME}' e assimetrico: encaixe unico, erro maximo {e * 100:.1f} cm")

    if os.path.exists(PLY):
        P, C = ler(); s, ix, sx, cx, iy, sy, cy = encaixa(P)
        print(f"nuvem real: {len(P)} pontos   x = {sx:+d}*P[:,{ix}] {cx:+.3f}   "
              f"y = {sy:+d}*P[:,{iy}] {cy:+.3f}   sobreposicao {s:.0f} celulas")
    else:
        print(f"(sem nuvem em RTLS_NUVEM — so os testes sinteticos rodaram)")



# ---- ortofoto para o painel ---------------------------------------------------
ORTO_PX = 0.01                   # 1 cm/px: o painel mostra ~100 px por metro
ORTO_TETO = 2.30                 # corta o teto, senao a vista de cima e o teto
ORTO_PNG = os.path.join(os.path.dirname(AQUI), "painel", "planta.png")


def orto(px=ORTO_PX, teto=ORTO_TETO, png=ORTO_PNG):
    """A planta REAL: vista de cima da nuvem registrada, sem o teto.

    O painel desenhava o retangulo idealizado da trena por cima de uma malha
    medida na casa de verdade. Isto poe a casa de verdade embaixo. Escreve o PNG
    e um JSON com o retangulo do mundo que ele cobre — quem desenha ja tem a
    transformada (X = mx + x*esc), so precisa saber onde a imagem comeca.
    """
    import json
    from matplotlib.image import imsave
    P, C = ler()
    Q = planta(P)
    x0, y0 = -0.60, PL.Y_MIN - 0.60
    x1, y1 = PL.X_MAX + 0.60, PL.Y_MAX + 0.60
    nx, ny = int((x1 - x0) / px), int((y1 - y0) / px)
    m = ((Q[:, 2] > 0.02) & (Q[:, 2] < teto) & (Q[:, 0] > x0) & (Q[:, 0] < x1)
         & (Q[:, 1] > y0) & (Q[:, 1] < y1))
    Q, C = Q[m], C[m]
    # linha 0 = y0: o SVG cresce y para baixo igual a imagem, entao nao inverte
    cel = (np.clip(((Q[:, 1] - y0) / px).astype(int), 0, ny - 1) * nx
           + np.clip(((Q[:, 0] - x0) / px).astype(int), 0, nx - 1))
    o = np.lexsort((Q[:, 2], cel))                     # dentro da celula, z crescente
    ult = np.r_[cel[o][1:] != cel[o][:-1], True]       # o mais ALTO de cada celula
    img = np.zeros((ny * nx, 4), np.uint8)
    img[cel[o][ult], :3] = C[o][ult]
    img[cel[o][ult], 3] = 255
    os.makedirs(os.path.dirname(png), exist_ok=True)
    imsave(png, img.reshape(ny, nx, 4))
    with open(os.path.splitext(png)[0] + ".json", "w") as f:
        json.dump({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "px": px,
                   "ancoras": {str(n): list(map(float, PL.ANCORAS[t]))
                               for t, n in PL.INSTALADO.items()},
                   "ap": list(map(float, PL.ROTEADOR))}, f)
    print(f"-> {png}  {nx}x{ny}px  {100*ult.sum()/(nx*ny):.0f}% de cobertura")


if __name__ == "__main__":
    orto() if "orto" in sys.argv else demo()
