"""O sitio como MEIO de propagacao, nao como planta.

Tres parametros em cada ponto da reconstrucao, decimada a 1/3 da resolucao
linear (voxel de 3 cm sobre nuvem de ~1 cm — 6,34 M pontos viram 443.892
superfelas):

  ABSORCAO      alpha, dB por METRO de material atravessado. Unidade fisica,
                com valor de literatura para conferir (ITU-R P.2040, 2,4 GHz).
                E o que substituiria o `W*k` que esta no ar, que e dB por
                "cruzamento de segmento" numa planta idealizada: sem unidade,
                sem espessura, sem movel.
  REFLECTANCIA  Gamma, fracao de POTENCIA refletida na incidencia normal,
                |(1-sqrt(er))/(1+sqrt(er))|^2. Fica no mapa e NAO no ajuste —
                ver `reflexo()` no fim do arquivo.
  RAIO          a cobertura de cada ponto: distancia ate o 4o vizinho, o disco
                que faz a nuvem decimada cobrir a mesma superficie da cheia.
                Mediana 3,0 cm (a propria grade — a nuvem e densa), p99 4,2 cm,
                max 27,8 cm: so 0,14% passa de 6 cm, e sao as sombras do LiDAR
                (atras de movel, o alto do armario, o vao da geladeira).

A CLASSE vem da nuvem, NUNCA do ajuste: material por ponto seriam 4x10^5
parametros contra ~15 enlaces medidos, quatro ordens de grandeza pior que o
padrao direcional que ja foi reprovado. O ajuste ve UM alpha por classe.

Duas armadilhas resolvidas, as duas medidas:
 1. A nuvem inteira e QUENTE (RGB medio 147/130/109 — luz incandescente). Sem
    grey-world, 49% do sitio medido virou "madeira". Depois dele o piso da sala
    da R-B = +75 e o do WC -40, e as classes separam sozinhas.
 2. A COR nao separa azulejo de parede pintada — as duas sao frias e claras.
    Quem separa e o comodo, e para isso a planta serve mesmo estando 50 cm
    errada na geometria.

VEREDITO (2026-09-06): reprovado na transferencia, nos dois instrumentos.
Reproduzir: `python modelo/testa_material.py`. Resumo no fim de `demo()`.
"""
import os, sys, numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
from rtls import sitio as PL
from rtls.modelo import nuvem as NV
from rtls import ajuste as AJ

MAPA = os.path.join(AQUI, "mapa_material.npz")
VOX = 0.03          # 1/3 da resolucao linear da nuvem
N_MIN = 2           # pontos por voxel para ser superficie (1 e ruido do LiDAR)
K_VIZ = 4           # vizinhos que o disco de raio r tem de cobrir
Z_TETO = 2.60
X0, Y0 = -0.60, PL.Y_MIN - 0.60
X1, Y1 = PL.X_MAX + 0.60, PL.Y_MAX + 0.60

# nome, alpha dB/m, permissividade relativa (ITU-R P.2040-3, 2,4 GHz)
MAT = {1: ("parede",   22.0, 5.3),    # tijolo furado + reboco pintado
       2: ("azulejo",  30.0, 6.0),    # ceramica/porcelanato — so no WC e na cozinha
       3: ("madeira",   8.0, 2.0),    # porta, guarda-roupa, movel
       4: ("tecido",    3.0, 1.5),    # colchao, roupa, sofa
       5: ("metal",   300.0, 1.0)}    # geladeira, maquina: opaco
NCL = len(MAT)

# --- traçado -----------------------------------------------------------------
PASSO = 0.01        # amostragem do raio, 1/3 do voxel
R_ANT = 0.12        # ignorar a casca colada na propria ancora (ela esta na parede)
CORRIDA = 0.12      # teto do comprimento de UMA travessia. A casca varrida tem ~3 cm;
                    # 12 cm ja admite incidencia de 75 graus. Corrida maior e raio
                    # RASANTE — passa a 3 cm da parede e o voxel diz "dentro".
                    # Medido: travessia real da 0,02-0,11 m, rasante da 0,30-0,54 m.


def gama(er):
    s = np.sqrt(er)
    return float(((1 - s) / (1 + s)) ** 2) if er > 1.0 else 1.0


def _grade(P=None, C=None):
    """Nuvem -> grades (nz,ny,nx) de contagem, momentos e cor balanceada."""
    if P is None:
        P, C = NV.ler()
    Q = NV.planta(P).astype(np.float64)
    C = C.astype(np.float32)
    C = C * (C.mean() / C.mean(0))                       # grey-world
    m = ((Q[:, 0] > X0) & (Q[:, 0] < X1) & (Q[:, 1] > Y0) & (Q[:, 1] < Y1) &
         (Q[:, 2] > 0.015) & (Q[:, 2] < Z_TETO))
    Q, C = Q[m], C[m]
    nx = int((X1 - X0) / VOX) + 1; ny = int((Y1 - Y0) / VOX) + 1
    nz = int(Z_TETO / VOX) + 1
    lin = ((Q[:, 2] / VOX).astype(np.int32) * ny +
           ((Q[:, 1] - Y0) / VOX).astype(np.int32)) * nx + \
          ((Q[:, 0] - X0) / VOX).astype(np.int32)
    G, f = nz * ny * nx, (nz, ny, nx)
    n = np.bincount(lin, minlength=G).astype(np.float32)
    S = np.stack([np.bincount(lin, Q[:, a], minlength=G) for a in range(3)], -1)
    M = np.stack([np.bincount(lin, Q[:, a] * Q[:, b], minlength=G)
                  for a in range(3) for b in range(a, 3)], -1)   # xx xy xz yy yz zz
    K = np.stack([np.bincount(lin, C[:, a], minlength=G) for a in range(3)], -1)
    return n.reshape(f), S.reshape(f + (3,)), M.reshape(f + (6,)), K.reshape(f + (3,))


def normais(n, S, M, w=2):
    """Normal por voxel: autovetor menor da covariancia numa janela (2w+1)^3."""
    b = lambda A: ndimage.uniform_filter(A, size=2 * w + 1, mode="constant")
    nb = b(n)
    Sb = np.stack([b(S[..., a]) for a in range(3)], -1)
    Mb = np.stack([b(M[..., a]) for a in range(6)], -1)
    ok = nb > 1e-6
    mu = np.zeros_like(Sb); mu[ok] = Sb[ok] / nb[ok, None]
    q = np.zeros_like(Mb); q[ok] = Mb[ok] / nb[ok, None]
    i, j = np.triu_indices(3)
    Cv = np.zeros(n.shape + (3, 3), np.float32)
    Cv[..., i, j] = q - mu[..., i] * mu[..., j]
    Cv[..., j, i] = Cv[..., i, j]
    return np.linalg.eigh(Cv)[1][..., 0]


def molhado(nx, ny):
    """Mascara (ny,nx) dos comodos revestidos de ceramica."""
    x = np.arange(nx) * VOX + X0 + VOX / 2
    y = np.arange(ny) * VOX + Y0 + VOX / 2
    m = np.zeros((ny, nx), bool)
    for nome in ("wc", "cozinha"):
        p = np.array(PL.COMODOS[nome])                   # +25 cm: a parede e a borda
        m |= ((x[None, :] > p[:, 0].min() - 0.25) & (x[None, :] < p[:, 0].max() + 0.25) &
              (y[:, None] > p[:, 1].min() - 0.25) & (y[:, None] < p[:, 1].max() + 0.25))
    return m


def classifica(casca, cor, z, N, mol=None):
    """Classe por voxel de casca. Regras da nuvem, zero ajuste."""
    R, B = cor[..., 0], cor[..., 2]
    V = cor.max(-1); mn = cor.min(-1)
    sat = np.where(V > 1, (V - mn) / np.maximum(V, 1), 0.0)
    q = R - B                                            # quente: madeira +, ceramica -
    vert = np.abs(N[..., 2]) < 0.5                       # normal horizontal = parede
    cls = np.zeros(casca.shape, np.uint8)
    cls[casca] = 1                                       # default: parede
    cls[casca & (q > 30) & (sat > 0.28)] = 3             # madeira: quente E saturada
    frio = casca & (q < -18) & (V > 110)                 # frio e claro: superficie dura
    cls[frio] = 1
    if mol is not None:
        cls[frio & mol[None, :, :]] = 2                  # ...ceramica so no WC/cozinha
    cls[casca & (V < 60)] = 4                            # escuro: tecido, colchao, roupa
    cls[casca & (sat < 0.10) & (V > 90) & (V < 165) & vert & (z > 0.2)] = 5   # metal
    return cls


def constroi(salvar=True):
    n, S, M, K = _grade()
    casca = n >= N_MIN
    nz, ny, nx = casca.shape
    N = normais(n, S, M)
    cor = np.zeros_like(K); o = n > 0; cor[o] = K[o] / n[o, None]
    z = (np.arange(nz) * VOX + VOX / 2)[:, None, None] * np.ones((1, ny, nx), np.float32)
    cls = classifica(casca, cor, z, N, molhado(nx, ny))
    k = np.array(np.nonzero(casca))                      # (3, Ns) em (iz, iy, ix)
    P = np.stack([k[2] * VOX + X0 + VOX / 2, k[1] * VOX + Y0 + VOX / 2,
                  k[0] * VOX + VOX / 2], 1).astype(np.float32)
    c = cls[tuple(k)]
    d, _ = cKDTree(P).query(P, k=K_VIZ + 1, workers=-1)
    if salvar:                      # so o que NAO se deriva: 0,4 MB em vez de 7,9
        np.savez_compressed(MAPA, grade_cls=cls, raio=d[:, -1].astype(np.float32),
                            vox=VOX, origem=np.array([X0, Y0, 0.0]))
    return carrega()


def carrega(npz=MAPA):
    """-> dict(grade_cls, vox, origem, xyz, cls, raio, alpha, gamma).
    O arquivo guarda so a grade de classe e o raio; xyz/alpha/gamma saem da grade
    e da tabela MAT, que e literatura e nao ajuste — nao ha o que versionar nelas."""
    z = np.load(npz)
    g, vox, org = z["grade_cls"], float(z["vox"]), z["origem"]
    k = np.array(np.nonzero(g))                       # (3, Ns) em (iz, iy, ix)
    c = g[tuple(k)]
    A = np.array([0.0] + [MAT[i][1] for i in range(1, 6)], np.float32)
    G = np.array([0.0] + [gama(MAT[i][2]) for i in range(1, 6)], np.float32)
    return dict(grade_cls=g, vox=vox, origem=org, cls=c, raio=z["raio"],
                xyz=(k[::-1].T * vox + org + vox / 2).astype(np.float32),
                alpha=A[c], gamma=G[c])


def caminho(cls, vox, org, a, b):
    """Quanto material o enlace a<->b atravessa.
    -> (l[NCL] metros por classe, k[NCL] travessias por classe, d, n_rasantes)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = float(np.linalg.norm(b - a))
    t = np.arange(0, d, PASSO) + PASSO / 2
    S = a + (b - a) / d * t[:, None]
    i = ((S[:, 0] - org[0]) / vox).astype(int)
    j = ((S[:, 1] - org[1]) / vox).astype(int)
    kk = ((S[:, 2] - org[2]) / vox).astype(int)
    nz, ny, nx = cls.shape
    ok = ((t > R_ANT) & (t < d - R_ANT) & (i >= 0) & (i < nx) &
          (j >= 0) & (j < ny) & (kk >= 0) & (kk < nz))
    c = np.zeros(len(t), np.uint8)
    c[ok] = cls[kk[ok], j[ok], i[ok]]
    s = c > 0
    ini = np.flatnonzero(np.diff(np.r_[0, s.astype(int)]) == 1)
    fim = np.flatnonzero(np.diff(np.r_[s.astype(int), 0]) == -1) + 1
    l, k, rasantes = np.zeros(NCL), np.zeros(NCL), 0
    for p, q in zip(ini, fim):
        cl = np.bincount(c[p:q], minlength=NCL + 1)[1:].argmax()
        comp = (q - p) * PASSO
        rasantes += comp > CORRIDA
        l[cl] += min(comp, CORRIDA); k[cl] += 1
    return l, k, d, rasantes


# --- figura -------------------------------------------------------------------
PX = 0.02                                # pixel da vista top-down
H0, H1 = 0.15, 2.30                      # faixa que um enlace horizontal cruza
SAIDA = os.path.join(os.path.dirname(AQUI), "img", "10_material.png")
CORES = ["#c96f4a", "#6fb3d2", "#a8802f", "#7d5ba6", "#d9d9d9"]   # as 5 classes


def _celulas(P, v, x0, y0, nx, ny, moda=False):
    cel = (np.clip(((P[:, 1] - y0) / PX).astype(int), 0, ny - 1) * nx +
           np.clip(((P[:, 0] - x0) / PX).astype(int), 0, nx - 1))
    n = np.bincount(cel, minlength=ny * nx)
    ok = n > 0
    out = np.full(ny * nx, np.nan)
    if moda:
        m = np.stack([np.bincount(cel[v == c], minlength=ny * nx) for c in range(6)], 1)
        out[ok] = m[ok].argmax(1)
    else:
        out[ok] = np.bincount(cel, v, minlength=ny * nx)[ok] / n[ok]
    return out.reshape(ny, nx)


def figura(saida=SAIDA):
    """Top-down ortografica: ortofoto + classe + os 3 parametros.
    Sem o SSD montado sai sem a ortofoto — os 4 paineis do mapa nao dependem dela."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    z = carrega()
    P, al, ga, r, cl = z["xyz"], z["alpha"], z["gamma"], z["raio"], z["cls"]
    x0, y0 = X0, Y0
    nx = int((X1 - X0) / PX) + 1
    ny = int((Y1 - Y0) / PX) + 1
    ext = [x0, x0 + nx * PX, y0, y0 + ny * PX]
    f = (P[:, 2] > H0) & (P[:, 2] < H1)

    orto = None
    try:                                              # a ortofoto quer a nuvem cheia
        Pc, Cc = NV.ler()
        Q = NV.planta(Pc)
        m = ((Q[:, 2] > 0.02) & (Q[:, 2] < H1) & (Q[:, 0] > ext[0]) & (Q[:, 0] < ext[1]) &
             (Q[:, 1] > ext[2]) & (Q[:, 1] < ext[3]))
        Q, Cc = Q[m], Cc[m]
        cel = (np.clip(((Q[:, 1] - y0) / PX).astype(int), 0, ny - 1) * nx +
               np.clip(((Q[:, 0] - x0) / PX).astype(int), 0, nx - 1))
        o = np.lexsort((Q[:, 2], cel))                # o de cima ganha o pixel
        ult = np.r_[cel[o][1:] != cel[o][:-1], True]
        orto = np.zeros((ny * nx, 3), np.uint8)
        orto[cel[o][ult]] = Cc[o][ult]
        orto = orto.reshape(ny, nx, 3)
    except (FileNotFoundError, OSError):
        pass

    A = _celulas(P[f], al[f], x0, y0, nx, ny)
    G = _celulas(P[f], ga[f], x0, y0, nx, ny)
    R = _celulas(P[f], r[f], x0, y0, nx, ny) * 100
    K = _celulas(P[f], cl[f].astype(float), x0, y0, nx, ny, moda=True)
    cmk = ListedColormap(CORES)
    paineis = [(K, cmk, "CLASSE", (0.5, 5.5)),
               (A, "inferno", f"ABSORCAO  alpha dB/m  ({H0:.2f}-{H1:.2f} m)", (0, 60)),
               (G, "viridis", "REFLECTANCIA  Gamma (Fresnel, incidencia normal)", (0, 0.4)),
               (R, "magma", "RAIO de cobertura (cm) — 4o vizinho", (2, 12))]
    if orto is not None:
        paineis.insert(0, (orto, None, "ortofoto — o sitio como ele e", None))

    fig, ax = plt.subplots(1, len(paineis), figsize=(5.4 * len(paineis), 9.5),
                           facecolor="#0d0d10")
    for a, (im, cm, tit, lim) in zip(ax, paineis):
        a.set_facecolor("#0d0d10")
        h = a.imshow(np.ma.masked_invalid(im) if im.ndim == 2 else im, origin="lower",
                     extent=ext, cmap=cm, interpolation="nearest",
                     vmin=lim and lim[0], vmax=lim and lim[1])
        if cm is not None:
            cb = fig.colorbar(h, ax=a, fraction=0.035, pad=0.02,
                              ticks=range(1, 6) if cm is cmk else None)
            if cm is cmk:
                cb.ax.set_yticklabels([f"{MAT[i][0]}  {MAT[i][1]:.0f} dB/m" for i in range(1, 6)])
            cb.ax.tick_params(colors="#bbb", labelsize=8)
            cb.outline.set_edgecolor("#444")
        for t, (px, py, _) in PL.ANCORAS.items():
            n = PL.INSTALADO.get(t)
            if n is None:
                continue
            a.plot(px, py, "o", ms=8, mfc="none", mec="#ff2d55", mew=1.8)
            a.text(px + 0.13, py, f"a{n}", color="#ff2d55", fontsize=9, va="center")
        a.plot(*PL.ROTEADOR[:2], "s", ms=8, mfc="none", mec="#00e5ff", mew=1.8)
        a.text(PL.ROTEADOR[0] + 0.13, PL.ROTEADOR[1], "AP", color="#00e5ff",
               fontsize=9, va="center")
        a.set_title(tit, color="#eee", fontsize=11, pad=10)
        a.tick_params(colors="#888", labelsize=8)
        for sp in a.spines.values():
            sp.set_color("#333")
        a.set_aspect("equal")
    ax[0].set_ylabel("y (m)", color="#888")
    fig.suptitle(f"Mapa de material da reconstrucao — {len(P)} superfelas de "
                 f"{VOX*100:.0f} cm (1/3 da resolucao linear da nuvem de 6,34 M pontos)",
                 color="#eee", fontsize=13, y=0.97)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(saida, dpi=115, facecolor="#0d0d10")
    print(f"-> {saida}  grade {nx}x{ny} de {PX*100:.0f} cm"
          f"{'' if orto is not None else '  (sem ortofoto: SSD nao montado)'}")
    print(f"alpha mediana {np.nanmedian(A):.1f} dB/m   Gamma {np.nanmedian(G):.3f}   "
          f"raio {np.nanmedian(R):.1f} cm")


def reflexo():
    """Por que a REFLECTANCIA fica no mapa e nao no ajuste.

    RSSI e a soma de multipercursos com FASE. Um tracador deterministico preve
    interferencia a partir da geometria, e o padrao de franjas anda meio
    comprimento de onda a cada 6 cm em 2,4 GHz. A nuvem tem costura de 40 mm e
    erro angular de 0,72 grau — a fase prevista e ruido. O que SOBREVIVE a media
    e a POTENCIA agregada das reflexoes, que e o que faz o WC ser audivel
    apesar de 3 paredes; isso entra como fator de Rice, nao como raios somados,
    e so depois que o termo DIRETO ganhar do W*k. Ajustar reflexao em cima de um
    termo direto reprovado e a mesma armadilha de 05 e 06/09."""
    raise NotImplementedError(reflexo.__doc__)


def demo():
    # 1. caminho() num meio sintetico: laje de `parede` de 10 cm no meio do vao
    cls = np.zeros((10, 40, 40), np.uint8)
    cls[:, :, 20:24] = 1                                  # 4 voxels = 12 cm em x
    org = np.array([0.0, 0.0, 0.0])
    a = np.array([0.05, 0.15, 0.15]); b = np.array([1.15, 0.15, 0.15])
    l, k, d, ras = caminho(cls, VOX, org, a, b)
    assert k[0] == 1 and ras == 0, (k, ras)
    assert abs(l[0] - 0.12) < 0.02, l                     # travessia perpendicular
    assert l[1:].sum() == 0, l
    # reciprocidade: a geometria nao sabe quem transmite
    l2, k2, _, _ = caminho(cls, VOX, org, b, a)
    assert np.allclose(l, l2) and np.allclose(k, k2), (l, l2)
    # o teto da corrida corta o rasante: raio DENTRO da laje, 1 m de comprimento
    a3 = np.array([0.62, 0.05, 0.15]); b3 = np.array([0.62, 1.15, 0.15])
    l3, k3, _, ras3 = caminho(cls, VOX, org, a3, b3)
    assert ras3 == 1 and l3[0] <= CORRIDA + 1e-9, (l3, ras3)

    # 2. classifica() nas regras que o balanco de branco tornou separaveis
    f = np.ones((1, 1, 1), bool)
    z = np.full((1, 1, 1), 1.0, np.float32)
    N = np.zeros((1, 1, 1, 3), np.float32); N[..., 2] = 1.0        # normal vertical
    def cl(rgb, mol=None, n=N):
        return int(classifica(f, np.array(rgb, np.float32).reshape(1, 1, 1, 3), z, n, mol)[0, 0, 0])
    seco = np.zeros((1, 1), bool); mol = np.ones((1, 1), bool)
    assert cl([180, 150, 120]) == 3, "quente e saturado = madeira"
    assert cl([120, 138, 160], seco) == 1, "frio e claro fora do WC = parede pintada"
    assert cl([120, 138, 160], mol) == 2, "o mesmo pixel DENTRO do WC = azulejo"
    assert cl([40, 42, 45]) == 4, "escuro = tecido"
    Nh = np.zeros((1, 1, 1, 3), np.float32); Nh[..., 0] = 1.0      # normal horizontal
    assert cl([120, 122, 124], seco, Nh) == 5, "cinza fosco vertical = metal"

    # 3. Gamma de Fresnel: metal reflete tudo, madeira quase nada, e a ordem bate
    assert gama(1.0) == 1.0 and abs(gama(2.0) - 0.029) < 1e-3
    g = [gama(MAT[i][2]) for i in range(1, 6)]
    assert g[4] > g[1] > g[0] > g[2] > g[3], g

    print("material ok:", " ".join(f"{MAT[i][0]}(a={MAT[i][1]:.0f} G={gama(MAT[i][2]):.3f})"
                                   for i in range(1, 6)))
    if os.path.exists(MAPA):
        z = carrega()
        c = z["cls"]
        print(f"mapa: {len(c)} superfelas de {VOX*100:.0f} cm   "
              f"raio mediana {np.median(z['raio'])*100:.1f} cm  "
              f"p99 {np.percentile(z['raio'],99)*100:.1f} cm")
        for i in range(1, 6):
            print(f"   {MAT[i][0]:9s} {int((c==i).sum()):>7d} ({100*(c==i).mean():4.1f}%)  "
                  f"altura media {z['xyz'][c==i][:,2].mean():.2f} m")
        # e o que o mapa diz dos enlaces reais, com a planta ao lado
        m = carrega()
        g, vox, org = m["grade_cls"], m["vox"], m["origem"]
        num = {v: k for k, v in PL.INSTALADO.items()}
        print("   enlace     d      travessias  material  rasantes  W_planta")
        for a, b in ((1, 3), (2, 4), (3, 4), (1, 6), (5, 3)):
            pa, pb = PL.ANCORAS[num[a]], PL.ANCORAS[num[b]]
            l, k, d, ras = caminho(g, vox, org, pa, pb)
            W = AJ.paredes_entre(np.array(pa[:2]), np.array(pb[:2]))
            print(f"   a{a}<->a{b}  {d:5.2f} m   {k.sum():5.0f}     {l.sum()*100:5.1f} cm  "
                  f"{ras:5d}     {W:5d}")
        print("""   a2<->a4 a 6,10 m atravessa MENOS material (15 cm) que a3<->a4 a
   2,23 m (16 cm) — e nem assim explica a anomalia conhecida: a2<->a4 le
   -77 dBm, 1 dB mais QUENTE que a3<->a4 a 2,7x menos distancia. Nem a
   planta nem a nuvem produzem isso; e guia de onda no corredor.""")
    print("""
VEREDITO 2026-09-06 — o material da nuvem NAO entra no ao vivo:
  malha, 8 pares limpos (12 dos 28 enlaces censurados abaixo de -90 dBm),
    leave-one-PAIR-out (o par nao dirigido, senao 3|1 entrega 1|3 de graca):
      planta W*k   LOPO 5,29 dB      nuvem alpha*l  LOPO 6,77 dB   (-0,93 +- 1,46)
  campanha, leave-one-point-out com o modelo NO AR como controle:
      planta W*k   LOPO 5,87 dB      nuvem alpha*l  LOPO 6,71 dB   (-0,99 +- 0,87)
  Os dois instrumentos concordam e nenhum promove. O alpha por CLASSE (5
  parametros) e pior ainda: ajuste rms 1,87 e LOPO 32,96 — overfit puro, e TRES
  alphas saem NEGATIVOS (parede, azulejo, tecido), a mesma assinatura do W
  negativo de 05/09. O invariante que o ajuste nao ve — a ordem dos alphas
  contra a literatura — da correlacao de postos +0,10, ou seja, nada.
  A malha nao podia decidir de qualquer jeito: 8 pares contra um vies por
  ancora de 16,5 dB, maior que o efeito inteiro sob teste.""")

# ---- casca lowpoly para o painel 3D -------------------------------------------
LP_PASSO = 4                      # 4 x 3 cm = cubo de 12 cm
LP_BIN = os.path.join(os.path.dirname(AQUI), "painel", "lowpoly.bin")


def lowpoly(passo=LP_PASSO, saida=LP_BIN):
    """So as faces EXPOSTAS dos cubos ocupados — a casca, nao o volume.

    SEM DIFFUSE de proposito: a cor de cada face e a CLASSE de material e o
    sombreado e so a normal. Textura da foto esconde justamente o que se quer
    olhar aqui, que e a geometria que o modelo usa.

    Formato (little-endian):
      'LP01' | u16 nx ny nz | f32 vox x0 y0 z0 | u32 n | n x 5 bytes
    e cada face e (ix, iy, iz, dir 0..5 = +x -x +y -y +z -z, classe 1..5).
    """
    import struct
    z = np.load(MAPA)
    g, vox, org = z["grade_cls"], float(z["vox"]) * passo, z["origem"]
    r = passo
    nz, ny, nx = [(s + r - 1) // r for s in g.shape]
    assert max(nx, ny, nz) < 256, (nx, ny, nz)          # 1 byte por indice
    pad = np.zeros((nz * r, ny * r, nx * r), np.uint8)
    pad[:g.shape[0], :g.shape[1], :g.shape[2]] = g
    b = pad.reshape(nz, r, ny, r, nx, r).transpose(0, 2, 4, 1, 3, 5).reshape(nz, ny, nx, -1)
    cont = np.stack([(b == c).sum(-1) for c in range(1, NCL + 1)])
    occ = cont.sum(0) > 0
    cls = (cont.argmax(0) + 1).astype(np.uint8)

    def vizinho(eixo, d):
        """Ocupacao do vizinho em indice+d ao longo de `eixo` (fora da grade = ar)."""
        v = np.zeros_like(occ)
        aqui, la = [slice(None)] * 3, [slice(None)] * 3
        aqui[eixo], la[eixo] = ((slice(0, -1), slice(1, None)) if d > 0
                                else (slice(1, None), slice(0, -1)))
        v[tuple(aqui)] = occ[tuple(la)]
        return v

    # grade e (iz, iy, ix): eixo 0 = z, 1 = y, 2 = x
    faces = []
    for dirc, (eixo, d) in enumerate([(2, +1), (2, -1), (1, +1), (1, -1), (0, +1), (0, -1)]):
        kz, ky, kx = np.nonzero(occ & ~vizinho(eixo, d))
        f = np.empty((len(kx), 5), np.uint8)
        f[:, 0], f[:, 1], f[:, 2] = kx, ky, kz
        f[:, 3] = dirc
        f[:, 4] = cls[kz, ky, kx]
        faces.append(f)
    F = np.concatenate(faces)
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    with open(saida, "wb") as fp:
        fp.write(b"LP01" + struct.pack("<3H4fI", nx, ny, nz, vox,
                                       *map(float, org), len(F)) + F.tobytes())
    print(f"-> {saida}  cubo {vox*100:.0f} cm  grade {nx}x{ny}x{nz}  "
          f"{int(occ.sum())} cubos  {len(F)} faces  {os.path.getsize(saida)/1024:.0f} KB")
    return F


def _testa_lowpoly():
    """Um cubo solto tem 6 faces; um bloco 2x2x2, 24. Se a vizinhanca inverter um
    sinal a casca vira o volume inteiro e a conta estoura."""
    o = np.zeros((5, 5, 5), bool); o[2, 2, 2] = True
    def nv(occ, eixo, d):
        v = np.zeros_like(occ); a, l = [slice(None)]*3, [slice(None)]*3
        a[eixo], l[eixo] = ((slice(0,-1), slice(1,None)) if d > 0 else (slice(1,None), slice(0,-1)))
        v[tuple(a)] = occ[tuple(l)]; return v
    conta = lambda occ: sum(int((occ & ~nv(occ, e, d)).sum())
                            for e, d in [(0,1),(0,-1),(1,1),(1,-1),(2,1),(2,-1)])
    assert conta(o) == 6, conta(o)
    o2 = np.zeros((5, 5, 5), bool); o2[1:3, 1:3, 1:3] = True
    assert conta(o2) == 24, conta(o2)



if __name__ == "__main__":
    if "figura" in sys.argv:
        figura()
    elif "lowpoly" in sys.argv:
        _testa_lowpoly(); lowpoly()
    else:
        _testa_lowpoly(); demo()
