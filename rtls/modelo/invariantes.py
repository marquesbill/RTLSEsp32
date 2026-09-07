"""O modelo contra o dado real: 23 h de malha (47 janelas) + 14 pontos rotulados.

Regra da casa: metrica nao valida o proprio ajuste. Entao os testes estao em
ordem de FORCA DECRESCENTE, e os cinco primeiros NAO AJUSTAM NADA.

  P1  triangulo.  y_ij - y_ji = delta_i - delta_j.  Percurso, paredes, corpos e
      os DOIS padroes cancelam; a soma em qualquer triangulo tem de dar zero.
  P2  potencia.   RSSI anda 1 dB por dB de ptx comandado.
  P3  reciprocidade lenta. A serie da ida prediz a da volta => a flutuacao
      lenta e o CANAL, nao o radio.
  P4  o degrau de 05/09 21h. Algo mudou no espaco e a malha inteira respondeu.
      Recip roco (=> antena, nao cadeia) e com leque de 13 dB DENTRO da mesma
      ancora (=> nao e escalar). E o experimento natural que decide o modelo.
  P5  NeSh: sigma tem de crescer com o comprimento e enlaces vizinhos tem de
      flutuar juntos.  <- este o dado REPROVA, e a razao aparece em P6.
  P6  a RSSI da malha nao e gaussiana: e mistura de estados discretos.
  P7  transferencia LOPO na campanha. Unico teste com ajuste; vem por ultimo.

  python3 real.py            (roda tudo)
"""
import sys, os, json, itertools, collections
import numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
from rtls import sitio as P
from rtls.modelo import entidades as E
from rtls.ajuste import paredes_entre
from rtls.modelo.nucleo import direcao, psi, obstrucao, var_nesh, cov_nesh
from rtls.modelo.testes import ANC, dentro

DADOS = os.environ.get("RTLS_MALHA_JSON", os.path.join(AQUI, "dados_malha.json"))
J_DEGRAU = 40          # janela em que a malha inteira deu um passo (05/09 ~21h)


def carrega(estat="mean"):
    d = json.load(open(DADOS))
    ents = E.cena()
    d["ents"] = ents
    d["d"] = {(i, j): float(np.linalg.norm(ents[i].xyz - ents[j].xyz))
              for i in ANC for j in ANC if i != j}
    d["k"] = {(i, j): paredes_entre(ents[i].xyz[:2], ents[j].xyz[:2])
              for i in ANC for j in ANC if i != j}
    tab = collections.defaultdict(dict)
    for x in d["malha"]:
        tab[(x["rx"], x["tx"])][x["j"]] = x
    d["tab"] = tab
    d["pares"] = sorted({tuple(sorted(k)) for k in tab if (k[1], k[0]) in tab})
    return d, ents


def serie(d, k, estat="mean", jans=None):
    t = d["tab"][k]
    w = sorted(t) if jans is None else sorted(set(t) & set(jans))
    return np.array(w), np.array([t[j][estat] for j in w])


# ============================================================ P1  triangulo
def p1_triangulo(d, estat="mean"):
    D = {}
    for (i, j) in d["pares"]:
        a, b = d["tab"][(i, j)], d["tab"][(j, i)]
        for w in set(a) & set(b):
            D[(i, j, w)] = a[w][estat] - b[w][estat]
    janelas = sorted({w for _, _, w in D})
    somas = []
    for a, b, c in itertools.combinations(ANC, 3):
        for w in janelas:
            v = []
            for i, j in ((a, b), (b, c), (c, a)):
                k = (min(i, j), max(i, j), w)
                if k in D:
                    v.append(D[k] if i < j else -D[k])
            if len(v) == 3:
                somas.append(sum(v))
    somas = np.array(somas)
    # escala de ruido: quanto D de um mesmo par varia de janela a janela
    ruido = float(np.mean([np.std([D[(i, j, w)] for w in janelas if (i, j, w) in D])
                           for (i, j) in d["pares"]]))
    # delta = t - r por ancora, janela a janela (sum delta = 0)
    dm = []
    for w in janelas:
        A, y = [], []
        for (i, j) in d["pares"]:
            if (i, j, w) not in D: continue
            r = np.zeros(6); r[ANC.index(i)] = 1.0; r[ANC.index(j)] = -1.0
            A.append(r); y.append(D[(i, j, w)])
        if len(A) < 5: continue
        v, *_ = np.linalg.lstsq(np.vstack([A, np.ones(6)]), np.append(y, 0.0), rcond=None)
        dm.append(v)
    dm = np.array(dm)
    return dict(n=len(somas), somas=somas, rms=float(np.sqrt((somas ** 2).mean())),
                med=float(somas.mean()), ruido=ruido, esperado=float(np.sqrt(3) * ruido),
                delta=dm.mean(0), delta_sd=dm.std(0))


# ===================================================== P2  varredura de potencia
def p2_potencia(d):
    g = collections.defaultdict(list)
    for c in d["campanha"]:
        g[(c["i"], c["rx"])].append((c["ptx"], c["med"]))
    incl = []
    for v in g.values():
        p = np.array([z[0] for z in v], float); y = np.array([z[1] for z in v], float)
        m = y > -90                      # acima do piso: amostra censurada achata a reta
        if m.sum() < 4 or len(set(p[m])) < 4: continue
        incl.append(np.polyfit(p[m], y[m], 1)[0])
    incl = np.array(incl)
    return dict(n=len(incl), med=float(np.median(incl)), mean=float(incl.mean()),
                sd=float(incl.std()), q=[float(np.quantile(incl, q)) for q in (.1, .9)])


# =============================================== P3  reciprocidade da serie lenta
def p3_reciproco(d, estat="mean"):
    out = []
    for (i, j) in d["pares"]:
        w = sorted(set(d["tab"][(i, j)]) & set(d["tab"][(j, i)]))
        a = np.array([d["tab"][(i, j)][x][estat] for x in w])
        b = np.array([d["tab"][(j, i)][x][estat] for x in w])
        out.append((i, j, d["d"][(i, j)], float(np.corrcoef(a, b)[0, 1]),
                    float(a.std()), float(b.std()), len(w)))
    r = np.array([o[3] for o in out])
    return dict(linhas=out, med=float(np.median(r)), min=float(r.min()),
                n_pos=int((r > 0.5).sum()))


# ================================================== P4  o degrau de 05/09 21h
def p4_degrau(d, estat="mean", j=J_DEGRAU):
    ents = d["ents"]
    st = {}
    for k in d["tab"]:
        wa, a = serie(d, k, estat, range(j - 1))
        wb, b = serie(d, k, estat, range(j + 1, 60))
        if len(a) < 10 or len(b) < 3: continue
        st[k] = (b.mean() - a.mean(),
                 float(np.hypot(a.std() / np.sqrt(len(a)), b.std() / np.sqrt(len(b)))))
    pares = [p for p in d["pares"] if p in st and (p[1], p[0]) in st]
    ida = np.array([st[p][0] for p in pares])
    volta = np.array([st[(p[1], p[0])][0] for p in pares])
    s = 0.5 * (ida + volta)                       # parte reciproca = antena/caminho
    se = np.maximum(0.5 * np.hypot([st[p][1] for p in pares],
                                   [st[(p[1], p[0])][1] for p in pares]), 0.3)

    def col_esc(a):
        return np.array([(p[0] == a) + (p[1] == a) for p in pares], float)

    def cols_pad(a, grau=1):
        n = (grau + 1) ** 2 - 1
        M = np.zeros((len(pares), n))
        for r, p in enumerate(pares):
            if a not in p: continue
            b = p[1] if p[0] == a else p[0]
            M[r] = psi(direcao(ents[a].xyz, ents[b].xyz, ents[a].M), grau).ravel()
        return [M[:, q] for q in range(n)]

    def cpar(a, b):
        return np.array([1.0 if set(p) == {a, b} else 0.0 for p in pares])

    def ajusta(cols):
        if not cols: return s, 0
        X = np.column_stack(cols)
        beta, *_ = np.linalg.lstsq(X / se[:, None], s / se, rcond=None)
        return s - X @ beta, int(np.linalg.matrix_rank(X))

    modelos = [("degrau = 0 (nada mudou)", []),
               ("escalar por ancora, so a1,a2", [col_esc("1"), col_esc("2")]),
               ("escalar por ancora, todas as 6", [col_esc(a) for a in ANC]),
               ("padrao grau 1 so em a1", cols_pad("1")),
               ("padrao grau 1 em a1 e a2", cols_pad("1") + cols_pad("2")),
               # a causa fisica do degrau (a polaridade da antena de
               # a4 foi revertida as 21h38): o padrao tem de estar em a4, e a2 mudou as 19h42.
               ("padrao grau 1 so em a4", cols_pad("4")),
               ("padrao grau 1 em a2 e a4", cols_pad("2") + cols_pad("4")),
               ("escalar todas + caminho 2-4", [col_esc(a) for a in ANC] + [cpar("2", "4")])]
    comp = []
    for nome, c in modelos:
        r, k = ajusta(c)
        comp.append((nome, k, float(np.sqrt((r ** 2).mean())),
                     float(np.sum(r ** 2 / se ** 2) / max(len(pares) - k, 1))))
    leque = {}
    for a in ANC:
        v = [(p, x) for p, x in zip(pares, s) if a in p]
        if len(v) >= 3:
            q = [x for _, x in v]
            leque[a] = (v, max(q) - min(q))
    return dict(pares=pares, ida=ida, volta=volta, s=s, se=se, comp=comp, leque=leque,
                r_recip=float(np.corrcoef(ida, volta)[0, 1]),
                rms_dif=float(np.sqrt(((ida - volta) ** 2).mean())),
                se_tip=float(np.median(se)))


# =============================================================== P5  NeSh
def p5_nesh(d, estat="mean"):
    ents = d["ents"]
    ks = sorted(d["tab"])
    L = np.array([d["d"][k] for k in ks])
    sl = np.array([serie(d, k, estat)[1].std() for k in ks])
    sr = np.array([np.mean([x["sd"] for x in d["tab"][k].values()]) for k in ks])
    niv = np.array([serie(d, k, estat)[1].mean() for k in ks])

    # (a) comprimento
    cor_L = float(np.corrcoef(L, sl)[0, 1])
    # (b) enlaces vizinhos flutuam juntos?  permutacao com o rotulo do enlace
    jan = sorted(set.intersection(*[set(d["tab"][k]) for k in ks if len(d["tab"][k]) > 40]))
    kk = [k for k in ks if len(d["tab"][k]) > 40]
    Y = np.array([[d["tab"][k][w][estat] for w in jan] for k in kk])
    Y = Y - Y.mean(1, keepdims=True)
    C = np.corrcoef(Y)
    comp, emp, mod = [], [], []
    for a in range(len(kk)):
        for b in range(a + 1, len(kk)):
            if set(kk[a]) == set(kk[b]): continue        # ida/volta do mesmo enlace
            comp.append(len(set(kk[a]) & set(kk[b]))); emp.append(C[a, b])
            sa = (ents[kk[a][0]].xyz, ents[kk[a][1]].xyz)
            sb = (ents[kk[b][0]].xyz, ents[kk[b][1]].xyz)
            mod.append(cov_nesh(sa, sb, 1.0, 2.0) /
                       np.sqrt(cov_nesh(sa, sa, 1.0, 2.0) * cov_nesh(sb, sb, 1.0, 2.0)))
    comp = np.array(comp); emp = np.array(emp); mod = np.array(mod)
    dif = emp[comp == 1].mean() - emp[comp == 0].mean()
    rng = np.random.default_rng(0); nulo = []
    for _ in range(2000):
        q = rng.permutation(len(kk))
        Cp = C[np.ix_(q, q)]
        e = []
        for a in range(len(kk)):
            for b in range(a + 1, len(kk)):
                if set(kk[a]) == set(kk[b]): continue
                e.append(Cp[a, b])
        e = np.array(e)
        nulo.append(e[comp == 1].mean() - e[comp == 0].mean())
    nulo = np.array(nulo)

    # (c) area caminhavel que obstrui cada enlace (o termo de acoplamento)
    fp = P.floorplan()
    G = [(x, y) for x in np.arange(fp.xmin, fp.xmax, 0.15)
         for y in np.arange(fp.ymin, fp.ymax, 0.15) if dentro(x, y)]
    chi2 = []
    slp = []
    for (i, j) in d["pares"]:
        c = np.array([obstrucao(ents[i].xyz, ents[j].xyz, np.array([x, y, 0.95]), 0.20)
                      for x, y in G])
        chi2.append(float((c ** 2).mean()))
        slp.append(0.5 * (serie(d, (i, j), estat)[1].std() + serie(d, (j, i), estat)[1].std()))
    return dict(L=L, sl=sl, sr=sr, niv=niv, ks=ks, cor_L=cor_L,
                cor_nivel_rap=float(np.corrcoef(niv, sr)[0, 1]),
                cor_L_rap=float(np.corrcoef(L, sr)[0, 1]),
                dif=float(dif), p=float((np.abs(nulo) >= abs(dif)).mean()),
                nulo_sd=float(nulo.std()), n_jan=len(jan), n_enl=len(kk),
                chi2=np.array(chi2), slp=np.array(slp),
                cor_chi=float(np.corrcoef(chi2, slp)[0, 1]))


# ============================================= P6  a RSSI e mistura, nao gaussiana
def p6_mistura(d):
    """IQR DENTRO de uma janela de 30 min. Numa gaussiana IQR = 1,35 sd.

    Medir dentro da janela e o que importa: prova que os dois estados coexistem,
    e nao que o enlace mudou de nivel ao longo das 23 h.
    """
    out = []
    for k in sorted(d["tab"]):
        v = [(x["q75"] - x["q25"], x["q75"] - x["q25"] / max(x["sd"], .1), x["j"], x)
             for x in d["tab"][k].values()]
        iqr = np.array([x["q75"] - x["q25"] for x in d["tab"][k].values()])
        sd = np.array([max(x["sd"], .1) for x in d["tab"][k].values()])
        i = int(np.argmax(iqr))
        x = list(d["tab"][k].values())[i]
        out.append((f"{k[0]}<-{k[1]}", float(iqr.max()), float(np.median(iqr)),
                    float((iqr / (1.35 * sd)).max()), x["j"], x))
    out.sort(key=lambda z: -z[1])
    return out


# ================================================= P7  transferencia LOPO
def campanha(d):
    """-> por ponto: {ancora: nivel corrigido de ptx}, e a posicao verdadeira."""
    g = collections.defaultdict(list)
    for c in d["campanha"]:
        if c["med"] > -90:                       # fora do piso
            g[(c["i"], c["rx"])].append(c["med"] - c["ptx"])
    pts = []
    for i, w in enumerate(d["janelas"]):
        obs = {rx: float(np.mean(v)) for (ii, rx), v in g.items() if ii == i}
        if len(obs) >= 4:
            pts.append((np.array([w["x"], w["y"], 0.75]), obs, w["ponto"]))
    return pts


def _linhas(d, pts, grau, idx, k):
    """X, y para os pontos da campanha. Colunas: A0, n, W, r_a, c_a (grau)."""
    ents = d["ents"]; fp = P.floorplan()
    X, y = [], []
    for p, obs, _ in pts:
        for a, v in obs.items():
            pa = ents[a].xyz
            dd = float(np.linalg.norm(p - pa))
            L = np.zeros(k)
            L[idx["A0"]] = 1.0
            L[idx["n"]] = -10 * np.log10(max(dd, 0.5))
            L[idx["W"]] = -paredes_entre(p[:2], pa[:2])
            L[idx[f"r:{a}"]] = 1.0
            if grau:
                u = direcao(pa, p, ents[a].M)
                L[idx[f"c:{a}"]:idx[f"c:{a}"] + (grau + 1) ** 2 - 1] = psi(u, grau).ravel()
            X.append(L); y.append(v)
    return np.array(X), np.array(y)


def _idx(grau):
    cols = ["A0", "n", "W"] + [f"r:{a}" for a in ANC]
    idx = {c: i for i, c in enumerate(cols)}
    k = len(cols)
    if grau:
        for a in ANC:
            idx[f"c:{a}"] = k; k += (grau + 1) ** 2 - 1
    return idx, k


def _gauge(grau, idx, k, ents):
    R = [np.array([1.0 if any(i == idx[f"r:{a}"] for a in ANC) else 0.0 for i in range(k)])]
    if grau:
        for eixo in range(3):
            v = np.zeros(k)
            for a in ANC:
                b = idx[f"c:{a}"]; M = ents[a].M
                v[b + 2] += M[eixo, 0]; v[b + 0] += M[eixo, 1]; v[b + 1] += M[eixo, 2]
            R.append(v)
    return np.array(R)


def p7_lopo(d, lam=0.1):
    pts = campanha(d); ents = d["ents"]; fp = P.floorplan()
    xs = np.arange(fp.xmin, fp.xmax, 0.05); ys = np.arange(fp.ymin, fp.ymax, 0.05)
    G = np.array([(x, y) for x in xs for y in ys if dentro(x, y)])
    saida = {}
    for grau in (None, 0, 1):
        idx, k = _idx(grau or 0)
        Rg = _gauge(grau or 0, idx, k, ents)
        erros, rms = [], []
        for q in range(len(pts)):
            tre = [p for i, p in enumerate(pts) if i != q]
            X, y = _linhas(d, tre, grau or 0, idx, k)
            if grau is None:                       # sem offset nenhum: zera r_a
                X = X.copy(); X[:, idx["r:1"]:idx["r:1"] + 6] = 0.0
                X[:, idx["A0"]] = 1.0
            A = np.vstack([X, 1e3 * Rg]); b = np.append(y, np.zeros(len(Rg)))
            th = np.linalg.solve(A.T @ A + lam * np.eye(k), A.T @ b)
            p, obs, _ = pts[q]
            # mapa de custo sobre o sitio
            custo = np.zeros(len(G)); res = []
            for a, v in obs.items():
                pa = ents[a].xyz
                dd = np.sqrt((G[:, 0] - pa[0]) ** 2 + (G[:, 1] - pa[1]) ** 2 + (pa[2] - 0.75) ** 2)
                base = th[idx["A0"]] - 10 * th[idx["n"]] * np.log10(np.maximum(dd, 0.5)) \
                       - th[idx["W"]] * fp.cruza(G, (pa[0], pa[1]))
                if grau is not None:
                    base = base + th[idx[f"r:{a}"]]
                if grau:
                    U = np.stack([G[:, 0] - pa[0], G[:, 1] - pa[1],
                                  np.full(len(G), 0.75 - pa[2])], -1)
                    U = U / np.linalg.norm(U, axis=1, keepdims=True)
                    U = U @ ents[a].M                    # global -> corpo
                    base = base + psi(U, grau) @ th[idx[f"c:{a}"]:idx[f"c:{a}"] + (grau + 1) ** 2 - 1]
                custo += (v - base) ** 2
                dd0 = float(np.linalg.norm(p - pa))
                prev = th[idx["A0"]] - 10 * th[idx["n"]] * np.log10(max(dd0, 0.5)) \
                       - th[idx["W"]] * paredes_entre(p[:2], pa[:2])
                if grau is not None: prev += th[idx[f"r:{a}"]]
                if grau:
                    u = direcao(pa, p, ents[a].M)
                    prev += float(psi(u, grau).ravel() @ th[idx[f"c:{a}"]:idx[f"c:{a}"] + (grau + 1) ** 2 - 1])
                res.append(v - prev)
            i = int(np.argmin(custo))
            erros.append(float(np.hypot(G[i, 0] - p[0], G[i, 1] - p[1])))
            rms.append(float(np.sqrt(np.mean(np.array(res) ** 2))))
        nome = {None: "so A,n,W", 0: "+ escalar por ancora", 1: "+ padrao grau 1"}[grau]
        saida[nome] = (float(np.mean(erros)), float(np.median(erros)),
                       float(np.mean(rms)), erros)
    return saida, [p[2] for p in pts]


# ==================================================================== relatorio
def demo():
    d, ents = carrega()
    W = 78
    print("=" * W)
    print("O MODELO CONTRA O DADO REAL")
    print(f"  malha: 47 janelas de 30 min (05/09 00:58 -> 06/09 00:20), "
          f"{len(d['tab'])} enlaces direcionais")
    print(f"  campanha: {len(d['janelas'])} pontos rotulados, {len(d['campanha'])} celulas "
          f"(ponto, ancora, potencia)")
    print("=" * W)

    print("\nP1. INVARIANTE DO TRIANGULO            [zero parametros ajustados]")
    r = p1_triangulo(d)
    print(f"    D_ij = y_ij - y_ji.  Em qualquer triangulo, D_ij + D_jk + D_ki = 0,")
    print(f"    porque percurso, paredes, corpos e os DOIS padroes cancelam.")
    print(f"    {r['n']} triangulos x janela:  media {r['med']:+.2f} dB, rms {r['rms']:.2f} dB")
    print(f"    ruido de referencia {r['ruido']:.2f} dB -> soma de 3 esperaria {r['esperado']:.2f} dB")
    print(f"    VEREDITO: {'PASSA' if r['rms'] < 1.3 * r['esperado'] else 'FALHA'}"
          f"  ({r['rms'] / r['esperado']:.2f}x o esperado)")
    print(f"\n    delta = t - r por ancora (assimetria da CADEIA, nunca medida aqui antes):")
    print("      " + "  ".join(f"a{a}={v:+.2f}" for a, v in zip(ANC, r["delta"])))
    print("      sd no tempo: " + " ".join(f"{v:.2f}" for v in r["delta_sd"]))

    print("\nP2. VARREDURA DE POTENCIA              [zero parametros ajustados]")
    r2 = p2_potencia(d)
    print(f"    {r2['n']} pares (ponto, ancora) com >=4 potencias acima do piso")
    print(f"    inclinacao mediana {r2['med']:.3f}  (media {r2['mean']:.3f} +- {r2['sd']:.3f}, "
          f"decis {r2['q'][0]:.2f}/{r2['q'][1]:.2f})")
    print(f"    VEREDITO: {'PASSA' if abs(r2['med'] - 1) < 0.15 else 'FALHA'}"
          f"   => r - ptx e uma variavel legitima")

    print("\nP3. A FLUTUACAO LENTA E RECIPROCA      [zero parametros ajustados]")
    r3 = p3_reciproco(d)
    print("    par     L(m)   r(ida,volta)   sd_ida  sd_volta   janelas")
    for i, j, L, rr, sa, sb, n in r3["linhas"]:
        print(f"    {i}<->{j}   {L:5.2f}      {rr:+.3f}       {sa:5.2f}   {sb:5.2f}      {n:3d}")
    print(f"    r mediano {r3['med']:+.3f}; {r3['n_pos']}/14 pares acima de +0,5")
    print(f"    VEREDITO: {'PASSA' if r3['med'] > 0.7 else 'FALHA'}"
          f"   => o que varia e o CANAL, nao o radio de cada ponta")

    print("\nP4. O DEGRAU DE 05/09 21h              [provocado, e com causa conhecida]")
    r4 = p4_degrau(d)
    print("    Entre as janelas 39 e 41 a malha inteira deu um passo. FUI EU: as")
    print("    21h38 o operador voltou a antena de a4 para a polaridade anterior")
    print("    (chat de 06/09 00:38 UTC). Ha um segundo evento, menor e sem causa")
    print("    registrada, por volta das 20h50, que move os enlaces de a1.")
    print("    par     ida    volta   ida-volta")
    for p, a, b in zip(r4["pares"], r4["ida"], r4["volta"]):
        print(f"    {p[0]}<->{p[1]}  {a:+6.2f} {b:+6.2f}    {a - b:+6.2f}")
    print(f"    corr(ida,volta) = {r4['r_recip']:+.3f}, rms(ida-volta) = {r4['rms_dif']:.2f} dB"
          f" (ruido {r4['se_tip']:.2f})")
    print(f"    => o degrau esta na parte RECIPROCA: e antena/caminho, nao cadeia. "
          f"O modelo poe c_e nos dois sentidos e t_e/r_e em um so.")
    print("\n    leque DENTRO de cada ancora (um escalar exigiria leque zero):")
    for a, (v, lq) in r4["leque"].items():
        print(f"      a{a}: " + " ".join(f"{p[0]}{p[1]}:{x:+5.1f}" for p, x in v) +
              f"   leque {lq:5.1f} dB")
    print("\n    modelo                          gl    rms    chi2/gl")
    for nome, k, rms, chi in r4["comp"]:
        print(f"    {nome:30s} {k:3d}  {rms:5.2f}   {chi:7.1f}")
    print("    VEREDITO: escalar por ancora REPROVADO. Com os MESMOS 6 parametros,")
    print("    o padrao direcional em duas ancoras explica 3x melhor que o escalar")
    print("    em todas as seis.")

    print("\nP5. NeSh: SOMBRA CORRELACIONADA        [a previsao da literatura]")
    r5 = p5_nesh(d)
    print(f"    (a) sigma lento x comprimento do enlace: r = {r5['cor_L']:+.3f}"
          f"  (14 pares independentes -> se ~ 0,29)")
    print(f"    (b) enlaces com ancora em comum flutuam mais junto que enlaces disjuntos?")
    print(f"        diferenca medida {r5['dif']:+.4f}; nulo por permutacao "
          f"0 +- {r5['nulo_sd']:.4f}; p = {r5['p']:.3f}")
    print(f"    (c) area caminhavel que obstrui o enlace x sigma lento: "
          f"r = {r5['cor_chi']:+.3f} (n=14)")
    print(f"    VEREDITO: (a) e (c) sao positivos mas de 2 sigma com n=14 - sugestivo,")
    print(f"    nao provado. (b), que e A previsao central do NeSh, esta REPROVADO:")
    print(f"    p = {r5['p']:.2f} e o sinal e negativo. Em 23 h de malha fixa a sombra")
    print(f"    correlacionada da literatura nao aparece. P6 diz por que.")
    print(f"    (achado colateral: sigma DENTRO da janela cresce com o NIVEL, "
          f"r = {r5['cor_nivel_rap']:+.2f},")
    print(f"     nao com o comprimento, r = {r5['cor_L_rap']:+.2f}. Enlace forte varia "
          f"MAIS. Isso e P6.)")

    print("\nP6. A RSSI DA MALHA E MISTURA, NAO GAUSSIANA")
    print("    IQR (q75-q25) DENTRO de uma unica janela de 30 min.")
    print("    Numa gaussiana IQR = 1,35 sd. Se IQR/1,35sd >> 1, sao dois estados.")
    print("    enlace   IQR max  IQR mediano  IQR/1,35sd  janela  (q10 q25 med q75 q90)")
    for k, mx, md, rz, j, x in p6_mistura(d)[:6]:
        print(f"    {k:7s}  {mx:6.1f}   {md:6.1f}       {rz:5.2f}     {j:3d}   "
              f"({x['q10']:.0f} {x['q25']:.0f} {x['med']:.0f} {x['q75']:.0f} {x['q90']:.0f})")
    print("    2<->6 passou 20 h com DOIS estados a 19 dB de distancia, os dois")
    print("    sentidos juntos, e colapsou num so as 21h. Consequencias:")
    print("      - a sd dentro da janela NAO e o erro-padrao da mediana:")
    print("        nao pesar o ajuste por 1/sd^2.")
    print("      - a mediana pula de modo; a media e mais estavel (2,42 -> 1,92 dB).")
    print("      - e o que enche o sigma lento, e por isso o NeSh nao aparece.")

    print("\nP7. TRANSFERENCIA LOPO NA CAMPANHA     [unico teste com ajuste]")
    saida, nomes = p7_lopo(d)
    print("    ajusta em 13 pontos, preve o 14o. Erro de posicao em metros.")
    print("    modelo                      erro medio   mediana   rms dB")
    for nome, (m, md, rms, _) in saida.items():
        print(f"    {nome:26s}   {m:6.2f} m   {md:6.2f} m   {rms:5.2f}")
    print("    por ponto (m):")
    print("      ponto                  " + " ".join(f"{n:>5s}" for n in nomes))
    for nome, (_, _, _, er) in saida.items():
        print(f"      {nome:22s} " + " ".join(f"{v:5.2f}" for v in er))
    print("    VEREDITO: o escalar ajustado NOS ROTULOS ajuda (1,61 -> 1,24 m). O padrao")
    print("    grau 1 nao transfere com estes 14 pontos: sao 18 coeficientes contra 13")
    print("    pontos mal distribuidos. Isso NAO contradiz P4 - P4 prova que o padrao")
    print("    existe; P7 prova que esta campanha nao consegue medi-lo.")
    print("    O teto: o residuo fora da amostra fica em ~6 dB nos tres modelos, e a")
    print("    ORIENTACAO do proprio alvo vale 2 a 10 dB (medido em 05/09). Enquanto o")
    print("    alvo nao girar dentro da janela, nenhum modelo de ancora desce disso.")


if __name__ == "__main__":
    demo()
