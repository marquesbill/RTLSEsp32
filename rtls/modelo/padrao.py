"""Ajuste do GANHO DIRECIONAL das ancoras: malha + campanha D-otima, juntas.

O que este arquivo decide: se `vivo.py` deve trocar

    mu = A - 10 n log10(d) - W k                       (hoje)
por
    mu = A - 10 n log10(d) - W k + r_a + psi(u).c_a    (com padrao)

A regra da casa e que metrica nao valida o proprio ajuste, entao o criterio NAO
e o residuo: e TRANSFERENCIA. Leave-one-point-out sobre os pontos da campanha,
prevendo RSSI de um ponto que o ajuste nunca viu. Se o padrao nao ganhar do
modelo isotropico nessa prova, ele nao entra no deploy — ver `promove()`.

Dado: `campanha_dot.json`, gerado por `extrai()` no servidor.
  - malha: 28 enlaces dirigidos ancora->ancora, ptx +9 dBm fixo, 14:10-14:35 de 06/09
  - campanha: 10 observacoes ancora<-CYD em 3 pontos, ja limpas de CENSURA

CENSURA e o que mata esta campanha: o transmissor cicla 8 niveis de Ptx e nos
niveis baixos o pacote simplesmente nao chega. So chegam os desvanecimentos
favoraveis, entao a media sobe e a inclinacao dRSSI/dPtx desaba (medido: +0,06
na ancora 3 vista de D3). `extrai` so aceita nivel com >= 20 pacotes e media
>= -90 dBm, e so aceita o enlace se a inclinacao ficar em 1,00 +- 0,35.
"""
import os, sys, json, math, collections
import numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI); sys.path.insert(0, os.path.dirname(AQUI))
from rtls import sitio as P
from rtls.modelo import entidades as E
from rtls.ajuste import paredes_entre
from rtls.modelo.nucleo import direcao, psi

DADOS = os.environ.get("RTLS_CAMPANHA_JSON", os.path.join(AQUI, "campanha.json"))
SAIDA = os.path.join(AQUI, "padrao.json")
ANC = [str(n) for n in sorted(P.INSTALADO.values())]   # do sitio: 6 hoje, N amanha
NC = 3                                   # grau 1: 3 coeficientes por ancora


# ------------------------------------------------------------------- extracao
def extrai(dir_wireless, janelas, pontos, t_malha, n_min=20, piso=-90.0, tol_incl=0.35):
    """Roda NO SERVIDOR. -> o dict que vira campanha_dot.json.

    janelas: {ponto: (t0, t1)} das advertencias de referencia do CYD (refcyd.jsonl)
    t_malha: (t0, t1) da malha a usar — tem de ser o MESMO periodo, senao o
             padrao ajustado e de um estado de radio e a campanha de outro.
    """
    def le(caminho, t0, t1, chave):
        g = collections.defaultdict(list)
        for l in open(caminho):
            d = json.loads(l)
            if t0 <= d["t"] <= t1: g[chave(d)].append(d["r"])
        return g

    obs = {}
    for p, (t0, t1) in janelas.items():
        g = le(os.path.join(dir_wireless, "refcyd.jsonl"), t0, t1,
               lambda d: (d["rx"], d["ptx"]))
        o = {}
        for rx in ANC:
            lv = {ptx: np.array(v) for (r, ptx), v in g.items() if r == rx}
            ok = [x for x in sorted(lv) if len(lv[x]) >= n_min and lv[x].mean() >= piso]
            if len(ok) < 2:
                continue
            inc = float(np.polyfit(ok, [lv[x].mean() for x in ok], 1)[0])
            if abs(inc - 1.0) >= tol_incl:      # censurado: descarta o enlace inteiro
                continue
            w = [len(lv[x]) for x in ok]
            o[rx] = dict(A=float(np.average([lv[x].mean() - x for x in ok], weights=w)),
                         n=int(sum(w)), niveis=ok, incl=round(inc, 3))
        obs[p] = o
    t0, t1 = t_malha
    gm = le(os.path.join(dir_wireless, "malha.jsonl"), t0, t1,
            lambda d: d["rx"] + "|" + d["tx"])
    malha = {k: dict(media=float(np.mean(v)), n=len(v), sd=float(np.std(v)))
             for k, v in gm.items() if k.split("|")[0] != k.split("|")[1]}
    return dict(ptx_malha=9.0, pontos=pontos, campanha=obs, malha=malha)


# -------------------------------------------------------------------- desenho
def _cols(grau):
    c = ["A0", "n", "W", "t:cyd"] + [f"t:{a}" for a in ANC] + [f"r:{a}" for a in ANC]
    if grau:
        for a in ANC:
            c += [f"c:{a}:{m}" for m in range(NC)]
    return {n: i for i, n in enumerate(c)}, len(c)


def _linha(idx, k, grau, ents, pa, pb, tx, rx):
    """pa transmite (entidade `tx`), pb recebe (entidade `rx`). Padrao SO das
    ancoras: com 3 pontos e orientacao fixa, os 3 coeficientes do CYD nao sao
    separaveis dos das ancoras — deixa-los livres e convidar o ajuste a mentir."""
    L = np.zeros(k)
    d = float(np.linalg.norm(np.asarray(pb) - np.asarray(pa)))
    L[idx["A0"]] = 1.0
    L[idx["n"]] = -10 * np.log10(max(d, 0.5))
    L[idx["W"]] = -paredes_entre(np.asarray(pa)[:2], np.asarray(pb)[:2])
    L[idx[f"t:{tx}"]] += 1.0
    L[idx[f"r:{rx}"]] += 1.0
    if grau:
        for e, (q0, q1) in ((tx, (pa, pb)), (rx, (pb, pa))):
            if e not in ANC:
                continue
            b = idx[f"c:{e}:0"]
            L[b:b + NC] += psi(direcao(q0, q1, ents[e].M), 1).ravel()
    return L


def monta(d, grau, pontos_usados=None):
    """grau None = o modelo QUE ESTA NO AR: A/n/W puro, sem offset por ancora.
    E o braco de controle — sem ele a comparacao so escolhe entre dois modelos
    novos e nao responde a unica pergunta que importa: mexer no vivo.py melhora?"""
    ents = E.cena()
    idx, k = _cols(grau or 0)
    X, y, tag = [], [], []
    for kk, v in d["malha"].items():
        rx, tx = kk.split("|")
        X.append(_linha(idx, k, grau or 0, ents, ents[tx].xyz, ents[rx].xyz, tx, rx))
        y.append(v["media"] - d["ptx_malha"]); tag.append(("malha", kk))
    for p, o in d["campanha"].items():
        if pontos_usados is not None and p not in pontos_usados:
            continue
        xp = np.array(d["pontos"][p], float)
        for a, v in o.items():
            X.append(_linha(idx, k, grau or 0, ents, xp, ents[a].xyz, "cyd", a))
            y.append(v["A"]); tag.append((p, a))
    X = np.array(X)
    if grau is None:                       # zera os offsets por ancora: sobra A/n/W
        for a in ANC:
            X[:, idx[f"t:{a}"]] = 0.0; X[:, idx[f"r:{a}"]] = 0.0
    return X, np.array(y), idx, k, tag, ents


def gauge(idx, k, grau, ents):
    """soma(t)=0, soma(r)=0 e, no grau 1, as 3 direcoes de inclinacao comum
    (somar o mesmo vetor ao dipolo de TODAS as ancoras nao muda enlace nenhum)."""
    R = []
    for pre in ("t", "r"):
        v = np.zeros(k)
        for a in ANC:
            v[idx[f"{pre}:{a}"]] = 1.0
        R.append(v)
    if grau:
        for eixo in range(3):
            v = np.zeros(k)
            for a in ANC:
                b = idx[f"c:{a}:0"]; M = ents[a].M
                v[b + 2] += M[eixo, 0]; v[b + 0] += M[eixo, 1]; v[b + 1] += M[eixo, 2]
            R.append(v)
    return np.array(R)


def ajusta(d, grau, pontos_usados=None, lam=0.5, peso_gauge=1e3):
    """O ridge NAO toca A0, n e W. Com A0 ~ -77 dB o termo lam*A0^2 vale 3000 e a
    soma dos residuos vale 370: o ridge no intercepto vira o ajuste inteiro (medido:
    n saltava de 2,18 para 4,80). Ele existe so para segurar os offsets e os
    coeficientes de padrao, que sao muitos e quase colineares."""
    X, y, idx, k, tag, ents = monta(d, grau, pontos_usados)
    Rg = gauge(idx, k, grau or 0, ents)
    A = np.vstack([X, peso_gauge * Rg]); b = np.append(y, np.zeros(len(Rg)))
    D = np.ones(k); D[[idx["A0"], idx["n"], idx["W"]]] = 0.0
    th = np.linalg.solve(A.T @ A + lam * np.diag(D), A.T @ b)
    return th, idx, k, ents, X, y, tag


def preve(th, idx, k, grau, ents, xp, a):
    L = _linha(idx, k, grau or 0, ents, np.asarray(xp, float), ents[a].xyz, "cyd", a)
    if grau is None:
        L[idx[f"t:{a}"]] = 0.0; L[idx[f"r:{a}"]] = 0.0
    return float(L @ th)


# --------------------------------------------------------------- transferencia
def _rms(par):
    return float(np.sqrt(np.mean([e ** 2 for _, e in par])))


def lopo(d, lam=0.5):
    """Deixa um PONTO de fora, ajusta, preve as ancoras daquele ponto.

    O ponto de fora sai tambem do ajuste inteiro (nao so da predicao), entao o
    padrao das ancoras que ele veria vem so da malha e dos outros pontos."""
    pts = sorted(d["campanha"])
    saida = {}
    for grau in (None, 0, 1):
        res = collections.defaultdict(list)
        for q in pts:
            th, idx, k, ents, *_ = ajusta(d, grau, [p for p in pts if p != q], lam)
            for a, v in d["campanha"][q].items():
                res[q].append((a, v["A"] - preve(th, idx, k, grau, ents, d["pontos"][q], a)))
        saida[grau] = dict(res)
    return saida, pts


def promove(d, lam=0.5, margem=0.5):
    """Escreve padrao.json SO se o arranjo novo vencer o QUE ESTA NO AR na
    transferencia por mais que `margem` dB de ganho liquido por ponto.
    Devolve (venceu, rms0, rms1, json)."""
    res, pts = lopo(d, lam)
    rms = {g: float(np.sqrt(np.mean([e ** 2 for v in res[g].values() for _, e in v])))
           for g in res}
    rb, r0, r1 = rms[None], rms[0], rms[1]

    # A UNIDADE DO LOPO E O PONTO, nao a observacao: as 3-5 ancoras de um mesmo
    # ponto erram juntas (mesma postura, mesmo corpo, mesma parede). Com 3 pontos
    # o rms global tem incerteza da ordem do proprio ganho, entao exigir so
    # `rms_novo < rms_deploy - margem` promove ruido. O criterio e o ganho POR
    # PONTO sobreviver a um erro padrao — se um ponto piora, nao promove.
    def ganho(g):
        d_p = np.array([_rms(res[None][q]) - _rms(res[g][q]) for q in pts])
        se = d_p.std(ddof=1) / np.sqrt(len(d_p)) if len(d_p) > 1 else np.inf
        return float(d_p.mean() - se), d_p
    g1, dp1 = ganho(1)
    g0, dp0 = ganho(0)
    venceu = bool(g1 > margem and r1 < r0)
    grau = 1 if venceu else (0 if g0 > margem else None)
    th, idx, k, ents, X, y, tag = ajusta(d, grau, None, lam)
    j = dict(grau=grau if grau is not None else -1,      # -1 = nao mexer no vivo.py
             lopo_rms_deploy=rb, lopo_rms_isotropico=r0,
             lopo_rms_padrao=r1, venceu=venceu,
             ganho_liq_isotropico=g0, ganho_liq_padrao=g1,
             ganho_por_ponto={q: [float(dp0[i]), float(dp1[i])] for i, q in enumerate(pts)},
             fonte=d.get("fonte", ""), lam=lam,
             A0=th[idx["A0"]], n=th[idx["n"]], W=th[idx["W"]],
             r={a: (th[idx[f"r:{a}"]] if grau is not None else 0.0) for a in ANC},
             t={a: th[idx[f"t:{a}"]] for a in ANC},
             c={a: (list(th[idx[f"c:{a}:0"]:idx[f"c:{a}:0"] + NC]) if grau else [0.0] * NC)
                for a in ANC},
             usar=grau is not None,
             rms_ajuste=float(np.sqrt(np.mean((y - X @ th) ** 2))))
    json.dump(j, open(SAIDA, "w"), indent=1)
    return venceu, r0, r1, j


def ganho_para(ids, caminho=SAIDA):
    """-> callable(P, ai, z_alvo) -> (N, len(ai)) dB para somar ao mu do Tracker,
    ou None se o ajuste NAO passou na transferencia.

    Devolver None e o caso normal e nao e falha: significa que a campanha ainda
    nao provou que o termo por ancora melhora a posicao de um ponto nunca visto.
    Ligar mesmo assim seria trocar o deploy por um ajuste que so ganha no proprio
    residuo — exatamente o que `ajuste.ajusta_offset` ja reprovou em 05/09.
    """
    if not os.path.exists(caminho):
        return None
    j = json.load(open(caminho))
    if not j.get("usar"):
        return None
    ents = E.cena()
    # o ao vivo chama a ancora por tag ("T4"); o modelo por numero ("4").
    ids = [str(P.INSTALADO.get(a, a)) for a in ids]
    r = np.array([j["r"].get(a, 0.0) for a in ids])
    c = np.array([j["c"].get(a, [0.0] * NC) for a in ids])
    M = np.array([ents[a].M for a in ids])
    Q = np.array([ents[a].xyz for a in ids])

    def ganho(P, ai, z_alvo):
        ai = np.asarray(ai, int)
        V = np.stack([P[:, None, 0] - Q[None, ai, 0],
                      P[:, None, 1] - Q[None, ai, 1],
                      np.broadcast_to(z_alvo - Q[ai, 2], (len(P), len(ai)))], -1)
        V = V / np.maximum(np.linalg.norm(V, axis=-1, keepdims=True), 1e-9)
        U = np.einsum("nka,kab->nkb", V, M[ai])            # planta -> corpo
        B = psi(U.reshape(-1, 3), 1).reshape(U.shape[:2] + (NC,))
        return r[ai] + np.einsum("nkm,km->nk", B, c[ai])
    return ganho


def demo():
    d = json.load(open(DADOS))
    n_camp = sum(len(o) for o in d["campanha"].values())
    print(f"dado: {len(d['malha'])} enlaces de malha + {n_camp} observacoes de campanha "
          f"em {len(d['campanha'])} pontos")
    for p, o in sorted(d["campanha"].items()):
        print(f"   {p:9s} {len(o)} ancoras: " + " ".join(f"{a}={o[a]['A']:.1f}" for a in sorted(o)))

    # posto: o desenho do grau 1 mede tudo o que promete?
    X, y, idx, k, tag, ents = monta(d, 1)
    s = np.linalg.svd(X, compute_uv=False)
    posto = int((s > max(X.shape) * np.finfo(float).eps * s[0]).sum())
    print(f"desenho grau 1: {X.shape[0]} linhas x {k} colunas, posto {posto}, "
          f"nulo {k - posto} (gauge preve {len(gauge(idx, k, 1, ents))})")

    res, pts = lopo(d)
    print("\nTRANSFERENCIA (leave-one-point-out, o ponto nunca visto):")
    for g, nome in ((None, "A/n/W (esta no ar)"), (0, "+ escalar por ancora"), (1, "+ padrao grau 1")):
        e = np.array([v for vs in res[g].values() for _, v in vs])
        por = "  ".join(f"{q}:{np.sqrt(np.mean([x**2 for _, x in res[g][q]])):.1f}" for q in pts)
        print(f"   {nome:22s} rms {np.sqrt(np.mean(e**2)):5.2f} dB   "
              f"pior {np.max(np.abs(e)):5.2f}   por ponto: {por}")

    venceu, r0, r1, j = promove(d)
    print(f"   (deploy atual {j['lopo_rms_deploy']:.2f} dB)")
    print("   ganho liquido (media por ponto - 1 erro padrao, tem de passar de +0.5):"
          f"  escalar {j['ganho_liq_isotropico']:+.2f}   padrao {j['ganho_liq_padrao']:+.2f}")
    for q, (a, b) in sorted(j["ganho_por_ponto"].items()):
        print(f"      {q:9s} escalar {a:+.1f} dB   padrao {b:+.1f} dB")
    print(f"\npromove: usar={j['usar']} grau={j['grau']}  "
          f"({'ENTRA no vivo.py' if j['usar'] else 'NAO entra: nenhum arranjo ganhou do deploy pela margem'})")
    print(f"   A0 {j['A0']:.1f} dB   n {j['n']:.2f}   W {j['W']:.1f} dB/parede   "
          f"rms do proprio ajuste {j['rms_ajuste']:.2f} dB")
    print("   r_a: " + "  ".join(f"{a}={j['r'][a]:+.1f}" for a in ANC))
    assert abs(sum(j["r"].values())) < 0.5, "gauge de r nao fechou"
    assert 1.0 < j["n"] < 6.0, f"expoente fora da fisica: {j['n']}"

    # o gancho do ao vivo, nos dois estados. Reprovado tem de devolver None (o
    # vivo.py segue isotropico); forcando usar=true com c=0, o ganho tem de ser
    # exatamente r_a em qualquer ponto — se nao for, o teste de transferencia
    # mediu um modelo e o deploy usaria outro.
    assert (ganho_para(P.ESCOLHIDAS) is None) == (not j["usar"])
    fake = os.path.join(AQUI, ".padrao_teste.json")
    json.dump(dict(j, usar=True, r={a: 1.5 for a in ANC}, c={a: [0.0] * NC for a in ANC}),
              open(fake, "w"))
    v = ganho_para(P.ESCOLHIDAS, fake)(np.array([[2.0, 3.0], [1.0, 1.0]]),
                                       np.arange(len(P.ESCOLHIDAS)), 0.75)
    os.remove(fake)
    assert v.shape == (2, len(P.ESCOLHIDAS)) and np.allclose(v, 1.5), v
    print(f"gancho do vivo.py: usar={j['usar']} -> "
          f"{'ativo' if j['usar'] else 'None (segue A/n/W isotropico)'}")
    print(f"-> {SAIDA}")


def mostra_desenho(k=10):
    d = json.load(open(DADOS))
    c, fv, fm = _testa_piso(d)
    print(f"piso: o corte separa {c}/18 enlaces do que ja foi andado "
          f"({fv} falso vivo, {fm} falso morto)\n")
    esc, hist, sig, n = desenho(d, k=k)
    print(f"{n} candidatos (grade de 35 cm x {len(ZS)} alturas, so os que passam "
          f"de {MIN_ANC:.0f} ancoras esperadas)")
    print(f"base = malha + os {len(d['campanha'])} pontos ja medidos: "
          f"log det do bloco de padrao {hist[0]:.2f}\n")
    X0 = monta(d, 1)[0]
    sv = np.linalg.svd(X0, compute_uv=False)
    print(f"so a malha + os 3 pontos: {sig[0]:.0f} dB de incerteza por coeficiente."
          f"\n  (X sozinho tem posto {int((sv > 1e-9).sum())} de {X0.shape[1]}; o gauge"
          f" fecha os 5 que faltam, mas o menor valor singular\n   sobrevivente e"
          f" {sv[int((sv > 1e-9).sum()) - 1]:.3f} — ha uma direcao do padrao que"
          f" ninguem mediu ainda.)\n")
    print("  #   x     y     z    anc  quais                              "
          "log det   sigma_c")
    for i, (xp, p) in enumerate(esc, 1):
        quem = " ".join(f"a{a}{'' if v > .9 else f'({v:.2f})'}"
                        for a, v in zip(ANC, p) if v > .1)
        print(f" {i:2d} {xp[0]:5.2f} {xp[1]:5.2f} {xp[2]:5.2f}  {p.sum():4.1f}  "
              f"{quem:36s} {hist[i] - hist[0]:+6.2f}   {sig[i]:5.2f} dB")
    obs = sum(p.sum() for _, p in esc) + sum(len(o) for o in d["campanha"].values())
    livre = len([c for c in _cols(1)[0] if c.startswith("c:")]) - 3
    print(f"\nobservacoes esperadas no total: {obs:.0f} para {livre} dimensoes livres "
          f"de padrao (+{len(ANC)*2+1} offsets) — {obs/livre:.1f} por dimensao")
    print("os 3 pontos ja andados renderam 10; o desenho velho prometia 18.")




# ------------------------------- desenho da PROXIMA campanha (D-otimo com piso)
# A campanha de 06/09 falhou por otimismo: o desenho D-otimo somava a informacao
# de 6 ancoras por ponto, e D2 entregou 2 e D3 entregou 3. O que faltava nao era
# geometria, era o PISO. `extrai()` so aceita um nivel de Ptx com media >= -90
# dBm; abaixo disso o que chega e desvanecimento favoravel, nao sinal (ver o
# item 1 do cabecalho). E um enlace so serve com >= 2 niveis, para medir a
# inclinacao — logo o enlace vive se o SEGUNDO maior nivel (+6 dBm) passa do piso.
PISO_NIVEL = -90.0                       # o mesmo corte de extrai()
PTX2 = 6.0                               # 2o maior nivel da varredura -12..+9
SIGMA_TRANSF = 4.1                       # rms do isotropico com o ponto DE FORA
ZS = (0.05, 0.45, 0.85, 1.25, 1.65)      # a altura e o eixo que a malha nao ve:
                                         # as 6 ancoras estao em z=0,30 ou 1,10
MIN_ANC = 4.0                            # ponto com menos que isso nao paga a caminhada


def p_util(A, sigma=SIGMA_TRANSF):
    """Prob. de o enlace render >= 2 niveis acima do piso, dado o A previsto.

    Nao e um corte duro: o previsto tem 4,1 dB de erro de transferencia, entao
    um ponto na fronteira vale meia observacao, e o D-otimo tem de saber disso.
    """
    return 0.5 * (1 + math.erf((A + PTX2 - PISO_NIVEL) / (sigma * math.sqrt(2.0))))


def _prev_iso(d):
    """-> f(xp, a) = A previsto (Ptx 0) pelo isotropico ajustado em TUDO."""
    th, idx, k, ents, *_ = ajusta(d, None)
    return lambda xp, a: preve(th, idx, k, None, ents, xp, a), ents


def alcance(d, xp, prev=None):
    """-> {ancora: p_util} no ponto xp. E a resposta a 'vale a pena ir ate la'."""
    prev = prev or _prev_iso(d)[0]
    return {a: p_util(prev(xp, a)) for a in ANC}


def desenho(d, k=8, grau=1, passo=0.35, zs=ZS, minsep=0.6, peso_gauge=1e3):
    """Escolhe os k proximos pontos da campanha, ja descontando o piso.

    Criterio: log det da informacao de Fisher NO BLOCO do padrao, com cada linha
    pesada pela probabilidade de aquele enlace existir. Guloso, incremental: a
    base e a malha MAIS os pontos ja andados — a campanha nova soma, nao repete.
    """
    prev, ents = _prev_iso(d)
    idx, kg = _cols(grau)
    Rg = gauge(idx, kg, grau, ents)
    ipad = [idx[c] for c in idx if c.startswith("c:")]
    G = peso_gauge ** 2 * (Rg.T @ Rg) + 1e-6 * np.eye(kg)
    Xb = monta(d, grau)[0]                       # malha + os 3 pontos ja medidos
    F0 = Xb.T @ Xb + G

    def crit(F):
        return -np.linalg.slogdet(np.linalg.inv(F)[np.ix_(ipad, ipad)])[1]

    def sigma_c(F):
        """O log det nao decide nada sozinho. Isto e o mesmo em dB: o desvio
        tipico que sobra em cada coeficiente de padrao. O efeito que se persegue
        vale 5-10 dB, entao a campanha so paga se este numero cair bem abaixo."""
        return SIGMA_TRANSF * float(np.sqrt(np.mean(
            np.diag(np.linalg.inv(F))[ipad])))

    from rtls.modelo.testes import dentro                    # ray casting sobre P.COMODOS
    fp = P.floorplan()
    cand = []
    for x in np.arange(fp.xmin + 0.3, fp.xmax - 0.2, passo):
        for y in np.arange(fp.ymin + 0.3, fp.ymax - 0.2, passo):
            if not dentro(x, y):
                continue
            for z in zs:
                xp = np.array([x, y, z])
                p = np.array([p_util(prev(xp, a)) for a in ANC])
                if p.sum() < MIN_ANC:
                    continue
                L = np.array([_linha(idx, kg, grau, ents, xp, ents[a].xyz, "cyd", a)
                              for a in ANC])
                cand.append((xp, p, (L * p[:, None]).T @ L))   # informacao esperada
    esc, F, hist, sig = [], F0.copy(), [crit(F0)], [sigma_c(F0)]
    for _ in range(k):
        melhor = None
        for xp, p, I in cand:
            if any(np.linalg.norm(xp - q) < minsep for q, _ in esc):
                continue
            v = crit(F + I)
            if melhor is None or v > melhor[0]:
                melhor = (v, xp, p, I)
        if melhor is None:
            break
        v, xp, p, I = melhor
        esc.append((xp, p)); F = F + I; hist.append(v); sig.append(sigma_c(F))
    return esc, hist, sig, len(cand)


def _testa_piso(d):
    """O piso e circular? So se o modelo nao souber prever quem NAO foi visto.

    Prevendo com o ponto de fora do ajuste, o corte tem de separar os 10 enlaces
    que existiram dos 8 que nao existiram — e, sobretudo, nunca matar um que
    existiu: um falso morto e o desenho jogando fora informacao real.
    """
    assert p_util(-70) > 0.99 and p_util(-110) < 0.01      # 50% em A = piso - Ptx2
    assert p_util(-99) < 0.5 < p_util(-93) and abs(p_util(-96) - 0.5) < 1e-9
    pts = sorted(d["campanha"])
    certo = falso_vivo = falso_morto = 0
    for p in pts:
        th, idx, k, ents, *_ = ajusta(d, None, pontos_usados=[q for q in pts if q != p])
        for a in ANC:
            vivo = p_util(preve(th, idx, k, None, ents, d["pontos"][p], a)) > 0.5
            real = a in d["campanha"][p]
            certo += vivo == real
            falso_vivo += vivo and not real
            falso_morto += real and not vivo
    assert falso_morto == 0 and certo >= 16, (certo, falso_vivo, falso_morto)
    return certo, falso_vivo, falso_morto


if __name__ == "__main__":
    if "desenho" in sys.argv:
        mostra_desenho(int(sys.argv[sys.argv.index("desenho") + 1])
                       if len(sys.argv) > sys.argv.index("desenho") + 1 else 10)
    else:
        demo()
