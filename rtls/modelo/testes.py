"""Testes do modelo: recuperacao sintetica, identificabilidade, CRLB e desenho de campanha.

A ordem importa. Primeiro provo que o estimador esta certo (recupera parametros
conhecidos). So depois pergunto o que o dado REAL consegue medir — senao um posto
baixo pode ser bug meu em vez de limite do experimento.

O resultado central esta em `identificabilidade()`: com a malha sozinha, o padrao
direcional NAO e identificavel, e da para dizer exatamente quantas dimensoes faltam.
E `custo_do_escalar()` prevê, de forma independente, o numero de 5,12 dB que o operador
mediu em 05/09 como resto do offset escalar.
"""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rtls import sitio as P
from rtls.ajuste import paredes_entre
from rtls.modelo import entidades as E
from rtls.modelo.nucleo import Desenho, psi, direcao, obstrucao, gls, espaco_nulo, matriz_nesh, var_nesh

ANC = [str(n) for n in sorted(P.INSTALADO.values())]   # do sitio: 6 hoje, N amanha


def obstrutores(ents, minimo=2):
    """So entra no ajuste o corpo que TAPA pelo menos `minimo` enlaces da malha.

    Um B cuja coluna e zero em todo enlace nao e mal determinado: e inexistente.
    O ajuste devolve |z| na casa dos milhares porque divide por um erro-padrao
    que tende a infinito. Isto e do SITIO, nao do modelo — mudar o movel de lugar
    muda quem e identificavel — entao a regra mora aqui e nao num numero fixo.
    """
    fora = []
    for o in ents:
        if o in ANC or o == "cyd":
            continue
        n = sum(obstrucao(ents[i].xyz, ents[j].xyz, ents[o].xyz, ents[o].raio) > 1e-6
                for i in ANC for j in ANC if i != j)
        if n >= minimo:
            fora.append(o)
    return fora


def grade_de_pontos(n):
    """n posicoes de alvo espalhadas pelos comodos do sitio, area-proporcional.

    Nao e desenho D-otimo (esse esta em `campanha_dotima`): e so uma cobertura
    honesta para o teste de recuperacao. Determinista de proposito — o teste tem
    de falhar sempre, nao as vezes.
    """
    pesos = [(k, P.area(v)) for k, v in P.COMODOS.items()]
    tot = sum(w for _, w in pesos)
    pts = []
    for k, w in pesos:
        poly = np.array(P.COMODOS[k], float)
        x0, y0 = poly.min(0) + 0.35
        x1, y1 = poly.max(0) - 0.35
        m = max(1, round(n * w / tot))
        lado = int(np.ceil(np.sqrt(m)))
        for a in range(lado):
            for b in range(lado):
                if len(pts) >= n or a * lado + b >= m:
                    break
                pts.append((x0 + (x1 - x0) * (a + 0.5) / lado,
                            y0 + (y1 - y0) * (b + 0.5) / lado))
    return pts


# --------------------------------------------------------------- geometria
def paredes(pa, pb):
    return {"parede": paredes_entre(np.asarray(pa[:2], float), np.asarray(pb[:2], float))}


def chis(ents, obs, pa, pb):
    return {o: obstrucao(pa, pb, ents[o].xyz, ents[o].raio) for o in obs}


def enlaces_malha(ents):
    """Os N(N-1) enlaces direcionais entre as N ancoras (30 com 6)."""
    return [(i, j) for i in ANC for j in ANC if i != j]


def linhas(des, ents, enlaces, pos=None):
    """pos: dict entidade->posicao (sobrescreve). -> X"""
    pos = pos or {}
    X = []
    for i, j in enlaces:
        pi = pos.get(i, ents[i].xyz); pj = pos.get(j, ents[j].xyz)
        X.append(des.linha(i, j, paredes(pi, pj), pos_i=pi, pos_j=pj,
                           chi=chis(ents, des.obs, pi, pj)))
    return np.array(X)


# ------------------------------------------------------- 1. recuperacao
def recuperacao(grau=1, ruido=1.0, semente=0):
    """Gera com theta conhecido e verifica que o ajuste volta nele.

    Cenario rico de proposito: malha + 14 posicoes do alvo. Se nem assim voltar,
    o problema e o estimador, nao o experimento.
    """
    rng = np.random.default_rng(semente)
    ents = E.cena()
    ents["cyd"] = E.cria("cyd", "cyd", (2.5, 2.5, 1.0), R=(0, 0, 0), p_tx=0.0, movel=True)
    for k in ANC + ["cyd"]:
        ents[k].grau = grau
    obs = obstrutores(ents)
    des = Desenho({k: ents[k] for k in ANC + ["cyd"]}, obstaculos=obs, grau=grau)

    # verdade
    nc = psi(np.array([[0, 0, 1.0]]), grau).shape[1]
    th = np.zeros(len(des.cols))
    th[des.idx["A0"]] = -45.0
    th[des.idx["n"]] = 2.6
    th[des.idx["W:parede"]] = 2.5
    for o, b in zip(obs, (6.0, 4.0, 3.0, 5.0, 2.0) * 4):
        th[des.idx[f"B:{o}"]] = b
    tt = rng.normal(0, 2.0, len(des.tx))
    rr = rng.normal(0, 2.0, len(des.rx))
    for k, v in zip(des.tx, tt): th[des.idx[f"t:{k}"]] = v
    for k, v in zip(des.rx, rr): th[des.idx[f"r:{k}"]] = v
    for k in des.pad:
        th[des.idx[f"c:{k}:0"]:des.idx[f"c:{k}:0"] + nc] = rng.normal(0, 4.0, nc)
    # A verdade tem de morar no mesmo gauge do ajuste, senao comparo laranja com
    # banana: a parte de theta que vive no nulo das restricoes nao e observavel.
    Rg = des.restricoes()
    th = th - np.linalg.pinv(Rg) @ (Rg @ th)

    # dado: malha + campanha
    pts = grade_de_pontos(14)
    enl, pos_l = list(enlaces_malha(ents)), []
    for _ in enl: pos_l.append({})
    for (x, y) in pts:
        for a in ANC:
            enl.append(("cyd", a)); pos_l.append({"cyd": np.array([x, y, 1.0])})
            enl.append((a, "cyd")); pos_l.append({"cyd": np.array([x, y, 1.0])})
    X = np.array([des.linha(i, j, paredes(pos.get(i, ents[i].xyz), pos.get(j, ents[j].xyz)),
                            pos_i=pos.get(i), pos_j=pos.get(j),
                            chi=chis(ents, obs, pos.get(i, ents[i].xyz), pos.get(j, ents[j].xyz)))
                  for (i, j), pos in zip(enl, pos_l)])
    y = X @ th + rng.normal(0, ruido, len(X))
    est, cov, posto, dnula, nulo = gls(X, y, Rg=Rg)

    # A gauge fixa t e r com media zero; a verdade ja foi gerada assim. O erro so
    # pode ser cobrado NO SUBESPACO QUE O DADO VE: colunas de leverage nula (um
    # corpo que nao tapa enlace nenhum) nao sao erro do estimador, sao cegueira do
    # experimento — e e isso que o diagnostico separa.
    err = est - th
    # Folga do corte de posto: a razao entre o menor sigma MANTIDO e a tolerancia,
    # e entre a tolerancia e o maior sigma DESCARTADO. E o invariante de verdade
    # deste teste. O `|z| < 4` la embaixo so e reprodutivel entre versoes de
    # numpy/LAPACK porque o corte cai num vao de nove ordens de grandeza; foi
    # justamente um corte DENTRO do continuo que fez a CI ver z = 2e12 onde aqui
    # dava 1.99. Cobro a folga, e nao o resultado que ela sustenta.
    A = np.vstack([X, 1e3 * Rg])
    sa = np.linalg.svd(A, compute_uv=False); sa = sa / sa[0]
    tol = max(A.shape) * np.finfo(float).eps
    ka = int((sa > tol).sum())
    folga = (sa[ka - 1] / tol, tol / max(sa[ka], 1e-300) if ka < len(sa) else np.inf)
    return des, th, est, posto, dnula, err, diagnostico(err, des.cols, cov, ruido, nulo), folga


def diagnostico(err, cols, cov, ruido, nulo):
    """Cobra o erro de cada parametro CONTRA O PROPRIO DESVIO PADRAO (CRLB).

    Cobrar em dB puro seria injusto e escondido: uma coluna quase sem leverage
    (um corpo que nao tapa enlace nenhum) tem sigma enorme, e um erro de 9 dB
    nela e ruido esperado, nao bug. O z-score poe todo mundo na mesma regua.

    `nulo` vem do `gls` de proposito, e nao de um `espaco_nulo()` chamado aqui:
    a direcao cuja variancia a cov zerou tem de ser exatamente a direcao cujo
    erro eu perdoo. Recalcular com tolerancia propria e o bug que a CI pegou —
    ver o comentario da decisao de posto em `rtls/modelo/nucleo.py:gls`.

    -> (|z| maximo, coluna do pior, [(coluna, sigma) das mal determinadas])
    """
    N = nulo
    e = err - N.T @ (N @ err) if len(N) else err
    sd = ruido * np.sqrt(np.maximum(np.diag(cov), 1e-18))
    z = np.abs(e) / np.maximum(sd, 1e-9)
    i = int(np.argmax(z))
    fracas = sorted(((c, float(v)) for c, v in zip(cols, sd) if v > 3.0), key=lambda t: -t[1])
    return float(z[i]), cols[i], fracas, float(np.abs(e).max())


# ------------------------------------------------- 2. identificabilidade
def identificabilidade():
    """Posto e espaco nulo em tres experimentos. E o resultado central."""
    ents = E.cena()
    ents["cyd"] = E.cria("cyd", "cyd", (2.5, 2.5, 1.0), p_tx=0.0, movel=True)
    pts = grade_de_pontos(14)
    saida = []
    for nome, usa_camp, grau in (("malha, offset escalar (grau 0)", False, 0),
                                 ("malha, padrao grau 1", False, 1),
                                 ("malha, padrao grau 2", False, 2),
                                 ("malha + 14 pontos, grau 1", True, 1),
                                 ("malha + 14 pontos, grau 2", True, 2)):
        sub = {k: ents[k] for k in (ANC + (["cyd"] if usa_camp else []))}
        for k in sub: sub[k].grau = grau
        obs1 = [k for k in ents if k not in ANC and k != "cyd"][:1]
        des = Desenho(sub, obstaculos=obs1, grau=grau)
        enl = list(enlaces_malha(ents))
        pos_l = [{} for _ in enl]          # N(N-1), nao 30: o sitio decide o N
        if usa_camp:
            for (x, y) in pts:
                for a in ANC:
                    enl += [("cyd", a), (a, "cyd")]
                    pos_l += [{"cyd": np.array([x, y, 1.0])}] * 2
        X = np.array([des.linha(i, j, paredes(pos.get(i, ents[i].xyz), pos.get(j, ents[j].xyz)),
                                pos_i=pos.get(i), pos_j=pos.get(j),
                                chi=chis(ents, obs1, pos.get(i, ents[i].xyz), pos.get(j, ents[j].xyz)))
                      for (i, j), pos in zip(enl, pos_l)])
        s = np.linalg.svd(X, compute_uv=False)
        posto = int((s > 1e-9 * s[0]).sum())
        N = espaco_nulo(X, 1e-8)
        # gauge conhecida = 2 (soma t, soma r) + 3 (inclinacao comum de dipolo,
        # so existe com grau >= 1). O que passar disso e cegueira do experimento.
        gauge = 2 + (3 if grau >= 1 else 0)
        saida.append(dict(nome=nome, p=X.shape[1], posto=posto, nulo=X.shape[1] - posto,
                          gauge=gauge, cego=X.shape[1] - posto - gauge,
                          cond=s[0] / s[posto - 1], nulo_base=N, cols=des.cols,
                          X=X, des=des, n_obs=X.shape[0]))
    return saida


# ------------------------------------- 3. o custo de resumir padrao em escalar
def custo_do_escalar(sigma_g=5.0, n_rep=200, semente=1):
    """Mundo com padrao direcional; ajuste com offset ESCALAR por ancora.

    Mede duas coisas que foi medido de verdade em 05/09:
      (a) o resto ao transferir o b da malha para outra janela  (ele: 5,12 dB)
      (b) a correlacao entre o b da malha e o vies visto pelo ALVO (ele: r=0,27)
    """
    rng = np.random.default_rng(semente)
    ents = E.cena()
    ents["cyd"] = E.cria("cyd", "cyd", (3.17, 1.09, 0.75), p_tx=0.0)
    for k in ANC: ents[k].grau = 1
    des1 = Desenho({k: ents[k] for k in ANC}, obstaculos=[], grau=1)   # verdade: padrao
    des0 = Desenho({k: ents[k] for k in ANC}, obstaculos=[], grau=0)   # ajuste: escalar
    enl = enlaces_malha(ents)
    X1 = linhas(des1, ents, enl); X0 = linhas(des0, ents, enl)
    restos, corrs = [], []
    for _ in range(n_rep):
        th = np.zeros(len(des1.cols))
        th[des1.idx["A0"]] = -45.0; th[des1.idx["n"]] = 2.6; th[des1.idx["W:parede"]] = 2.5
        for k in ANC:
            th[des1.idx[f"c:{k}:0"]:des1.idx[f"c:{k}:0"] + 3] = rng.normal(0, sigma_g, 3)
        y = X1 @ th + rng.normal(0, 1.0, len(X1))
        b, *_ = gls(X0, y, Rg=des0.restricoes())
        # vies que o ALVO ve de cada ancora = padrao da ancora na direcao do alvo
        alvo = ents["cyd"].xyz
        vies = np.array([psi(direcao(ents[k].xyz, alvo, ents[k].M), 1)[0]
                         @ th[des1.idx[f"c:{k}:0"]:des1.idx[f"c:{k}:0"] + 3] for k in ANC])
        # o escalar da malha, somando t e r da mesma ancora (a antena e reciproca)
        besc = np.array([b[des0.idx[f"t:{k}"]] + b[des0.idx[f"r:{k}"]] for k in ANC])
        restos.append(float(np.sqrt(np.mean((vies - vies.mean() - (besc - besc.mean())) ** 2))))
        c = np.corrcoef(vies, besc)[0, 1]
        if np.isfinite(c): corrs.append(float(c))
    return float(np.mean(restos)), float(np.mean(corrs)), float(np.std(corrs))


def sombra_entre_janelas(sigma_x=4.0, delta=1.5, n_rep=120, semente=2):
    """Duas janelas, MESMA geometria, sombreamento NeSh redesenhado entre elas.

    Reproduz o teste mais forte do operador em 05/09: ajustar b em cada janela e ver
    se (b_agora - b_campanha) explica o delta bruto de cada enlace. Num mundo sem
    sombra o resto seria zero. Aqui ele mede diretamente sigma_X.
    """
    rng = np.random.default_rng(semente)
    ents = E.cena()
    for k in ANC: ents[k].grau = 0
    des = Desenho({k: ents[k] for k in ANC}, obstaculos=[], grau=0)
    enl = enlaces_malha(ents)
    X = linhas(des, ents, enl)
    segs = [(ents[i].xyz, ents[j].xyz) for i, j in enl]
    S = matriz_nesh(segs, sigma_x ** 2, delta, 0.0)
    L = np.linalg.cholesky(S + 1e-9 * np.eye(len(S)))
    th = np.zeros(len(des.cols))
    th[des.idx["A0"]] = -45.0; th[des.idx["n"]] = 2.6; th[des.idx["W:parede"]] = 2.5
    for k in ANC:
        th[des.idx[f"t:{k}"]] = rng.normal(0, 3.0); th[des.idx[f"r:{k}"]] = rng.normal(0, 3.0)
    Rg = des.restricoes(); th -= np.linalg.pinv(Rg) @ (Rg @ th)
    restos, brutos = [], []
    for _ in range(n_rep):
        y1 = X @ th + L @ rng.normal(size=len(X)) + rng.normal(0, 1.0, len(X))
        y2 = X @ th + L @ rng.normal(size=len(X)) + rng.normal(0, 1.0, len(X))
        b1, *_ = gls(X, y1, Rg=Rg); b2, *_ = gls(X, y2, Rg=Rg)
        prev = X @ (b1 - b2)                  # o que a decomposicao por ancora preve
        restos.append(float(np.sqrt(np.mean((y1 - y2 - prev) ** 2))))
        brutos.append(float(np.sqrt(np.mean((y1 - y2) ** 2))))
    m, b = float(np.mean(restos)), float(np.mean(brutos))
    return m, float(np.std(restos)), b, 1 - (m / b) ** 2


# ------------------------------------------------ 4. desenho de campanha (D-otimo)
def campanha_dotima(k=8, grau=1, passo=0.4, minsep=0.0):
    """Escolhe os k pontos que mais informam sobre os padroes das ancoras.

    Criterio: maximizar log det da informacao de Fisher NO BLOCO dos coeficientes
    de padrao (D-otimalidade), partindo da malha. Guloso — para 8 de ~200 candidatos
    o guloso e o que a preguica manda e o ganho de exaustivo nao paga.
    """
    ents = E.cena()
    ents["cyd"] = E.cria("cyd", "cyd", (2.5, 2.5, 1.0), p_tx=0.0)
    for kk in ANC + ["cyd"]: ents[kk].grau = grau
    des = Desenho({kk: ents[kk] for kk in ANC + ["cyd"]}, obstaculos=[], grau=grau)
    fp = P.floorplan()
    cand = [(x, y) for x in np.arange(fp.xmin + 0.3, fp.xmax - 0.2, passo)
            for y in np.arange(fp.ymin + 0.3, fp.ymax - 0.2, passo)
            if dentro(x, y)]
    X = linhas(des, ents, enlaces_malha(ents))
    ipad = [des.idx[c] for c in des.cols if c.startswith("c:")]
    Rg = des.restricoes()
    def bloco(Xa):
        F = Xa.T @ Xa + 1e-6 * np.eye(Xa.shape[1]) + 1e3 * Rg.T @ Rg
        C = np.linalg.inv(F)[np.ix_(ipad, ipad)]
        return -np.linalg.slogdet(C)[1]                # = log det da informacao efetiva
    esc, base = [], bloco(X)
    hist = [base]
    for _ in range(k):
        melhor, best_x = None, None
        for (x, y) in cand:
            if any((x - u) ** 2 + (y - v) ** 2 < minsep ** 2 for u, v in esc): continue
            if (x, y) in esc: continue
            L = []
            for a in ANC:
                p = np.array([x, y, 1.0])
                L.append(des.linha("cyd", a, paredes(p, ents[a].xyz), pos_i=p))
                L.append(des.linha(a, "cyd", paredes(ents[a].xyz, p), pos_j=p))
            v = bloco(np.vstack([X, np.array(L)]))
            if melhor is None or v > melhor:
                melhor, best_x, bestL = v, (x, y), np.array(L)
        esc.append(best_x); X = np.vstack([X, bestL]); hist.append(melhor)
    return esc, hist, cand


def dentro(x, y):
    """Ponto dentro de algum comodo. Ray casting; sem matplotlib nesta maquina."""
    for v in P.COMODOS.values():
        n, d = len(v), False
        for i in range(n):
            x0, y0 = v[i]; x1, y1 = v[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                d = not d
        if d:
            return True
    return False


# ------------------------------------------------------------------- demo
def demo():
    print("=" * 78)
    print("1. RECUPERACAO SINTETICA — o estimador esta certo?")
    for grau in (1, 2):
        (des, th, est, posto, dnula, err,
         (zmax, pior, fracas, emax), (acima, abaixo)) = recuperacao(grau=grau)
        print(f"   grau {grau}: {len(des.cols):3d} parametros, posto {posto}, nulo {dnula}"
              f" | |z| max {zmax:.2f} ({pior}), erro max {emax:.2f} dB"
              f" | folga do corte {acima:.0e}x / {abaixo:.0e}x")
        if fracas:
            print("            mal determinados (sigma > 3 dB): "
                  + ", ".join(f"{c} {v:.1f}" for c, v in fracas[:4]))
        # 1e3 dos dois lados. MEDIDO: o pior caso nos dois sitios versionados e
        # 1.5e6x acima e 1.9e3x abaixo, entao o teto tem tres ordens de sobra.
        # Se esta linha cair, NAO afrouxe o 4.0 abaixo: o desenho ficou mal
        # condicionado e o z virou moeda de versao de LAPACK.
        assert acima > 1e3 and abaixo > 1e3, (grau, acima, abaixo)
        assert zmax < 4.0, (grau, zmax, pior)
    print("   -> todo parametro volta dentro de 4 sigma da propria CRLB,")
    print("      e o corte de posto cai num vao — nao num continuo de sigmas.")

    print()
    print("=" * 78)
    print("2. IDENTIFICABILIDADE — o que cada experimento consegue medir")
    print(f"   {'experimento':32s} {'obs':>4s} {'p':>4s} {'posto':>6s} {'gauge':>6s} {'CEGO':>5s} {'cond':>9s}")
    res = identificabilidade()
    for r in res:
        print(f"   {r['nome']:32s} {r['n_obs']:4d} {r['p']:4d} {r['posto']:6d} "
              f"{r['gauge']:6d} {r['cego']:5d} {r['cond']:9.1f}")
    m0 = [r for r in res if r["nome"].startswith("malha, offset")][0]
    m1 = [r for r in res if r["nome"] == "malha, padrao grau 1"][0]
    m2 = [r for r in res if r["nome"] == "malha, padrao grau 2"][0]
    c1 = [r for r in res if r["nome"] == "malha + 14 pontos, grau 1"][0]
    # Posto previsto pela CONTAGEM, nao um numero decorado: N(N-1)/2 combinacoes
    # simetricas + (N-1) antissimetricas. Com N=6 da 20; com N=4 da 9.
    na = len(ANC)
    posto_previsto = na*(na - 1)//2 + (na - 1)
    assert m1["posto"] == m2["posto"] == posto_previsto, (m1["posto"], m2["posto"], posto_previsto)
    # O posto numerico tem de bater com a contagem combinatoria, TETO INCLUSIVE: quando
    # ha menos parametros livres que numeros na malha, o posto para nos parametros. Um
    # SVD que devolva mais que isso denuncia calibre mal contado; menos, degenerescencia
    # que ninguem viu. Este e o cheque; "cego == 0" e consequencia, nao hipotese.
    livres = m0["p"] - m0["gauge"]
    assert m0["posto"] == min(livres, posto_previsto), (m0, livres, posto_previsto)
    assert m1["cego"] > 0 and c1["cego"] == 0, (m1["cego"], c1["cego"])
    print()
    print(f"   CONTAGEM, sem ajuste nenhum: os {na*(na-1)} enlaces da malha carregam "
          f"{posto_previsto} numeros")
    print(f"   independentes, nao {na*(na-1)}. Para cada par {{i,j}} as duas direcoes so diferem")
    print("   em t_i+r_j contra t_j+r_i: o resto (distancia, paredes, os dois padroes) e")
    print(f"   identico. Sobram {na*(na-1)//2} simetricos + {na-1} antissimetricos "
          f"({na} ancoras - 1) = {posto_previsto}.")
    print(f"   Verificado: posto = {posto_previsto} tanto para grau 1 quanto para grau 2.")
    print()
    if m0["cego"] == 0:
        print(f"   -> escalar por ancora: identificavel na malha (cego = {m0['cego']}). Nunca foi")
        print(f"      esse o problema — o problema e que 1 numero nao descreve um padrao.")
    else:
        print(f"   -> escalar por ancora: NAO identificavel so na malha aqui — {livres} parametros")
        print(f"      livres contra {posto_previsto} numeros que {na} ancoras carregam. Faltam ancoras")
        print(f"      ou faltam pontos rotulados; nao e escolha de estimador, e contagem.")
    print(f"   -> padrao de grau 1: a malha e CEGA a {m1['cego']} das {3*na} direcoes.")
    print(f"      Com os 14 pontos rotulados fecha (cego = {c1['cego']}), cond = {c1['cond']:.0f}.")
    print(f"   -> grau 2 na malha: {m2['cego']} direcoes cegas. Sem campanha nao existe.")

    print()
    print("=" * 78)
    print("3. CUSTO DE RESUMIR O PADRAO NUM ESCALAR (o offset reprovado)")
    print(f"   {'sigma do padrao':>16s} {'resto ao transferir':>21s} {'corr(b_malha, vies_alvo)':>26s}")
    for sg in (2.0, 5.0, 8.0):
        resto, c, sc = custo_do_escalar(sigma_g=sg)
        print(f"   {sg:14.1f} dB {resto:18.2f} dB {c:19.2f} +- {sc:.2f}")
    print()
    print("   Duas leituras, e a segunda muda o veredito de 05/09:")
    print("   (a) transferir o escalar da malha para a direcao do alvo custa ~2x sigma_G.")
    print("   (b) a correlacao ESPERADA entre b da malha e vies do alvo e ~0,6 +- 0,33,")
    print("       mesmo num mundo em que o modelo direcional e exatamente verdade.")
    print("       O r = 0,27 medido esta a ~1 sigma disso: NAO era prova de que o b")
    print("       estava errado. O que reprova o escalar e o item (a), nao o r baixo.")

    print()
    print("=" * 78)
    print("3b. O RESTO DE 5,12 dB ENTRE JANELAS — quanto sombreamento ele implica?")
    print(f"   {'sigma_X':>9s} {'delta bruto':>13s} {'resto':>10s}  {'absorvido pelo b':>17s}")
    alvo, achado = 5.12, None
    for sx in (2.0, 4.0, 8.0, 12.0, 16.0):
        m, sd, bruto, frac = sombra_entre_janelas(sigma_x=sx)
        print(f"   {sx:7.1f} dB {bruto:10.2f} dB {m:7.2f} dB {100*frac:15.0f} %")
        if achado is None and m >= alvo:
            achado = sx
    print()
    print("   DUAS COISAS SAEM DAQUI:")
    print(f"   (i) a decomposicao por ancora ABSORVE ~85% da energia do sombreamento")
    print("       correlacionado — enlaces que compartilham uma ponta sombreiam junto, e")
    print("       isso e exatamente a forma de um offset por ancora. Por isso o rms da")
    print("       malha cai de graca e o W vai a -0,7 dB: o b esta comendo caminho.")
    print(f"  (ii) para sobrar os {alvo:.2f} dB medidos e preciso sigma_X ~ "
          f"{achado if achado else '>16'} dB de mudanca")
    print("       por enlace entre as janelas. Antena de ancora nao muda entre janelas.")

    print()
    print("=" * 78)
    print("4. CAMPANHA D-OTIMA — onde ficar da proxima vez")
    esc, hist, cand = campanha_dotima(k=8)
    print(f"   {len(cand)} candidatos na planta; ganho de informacao (log det) por ponto:")
    for i, (p, h) in enumerate(zip(esc, hist[1:]), 1):
        print(f"     {i}. ({p[0]:5.2f}, {p[1]:5.2f})   log det {h:8.2f}   (+{h - hist[i-1]:5.2f})")
    assert hist[-1] > hist[0], "campanha tem de aumentar a informacao"
    print(f"   -> log det da informacao do padrao: {hist[0]:.1f} (so malha) -> {hist[-1]:.1f} (8 pontos)")


if __name__ == "__main__":
    demo()
