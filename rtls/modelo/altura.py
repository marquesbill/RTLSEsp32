"""Desenho da 2a campanha: a ALTURA, que a 1a revelou e nao consegue fixar.

VEREDITO 07/09 — a campanha andou (7 dos 8 pontos, 34 enlaces) e a resposta e
NAO. Com as 16 medidas juntas, z sobre o offset da +0,20 +- 0,48 dB/ponto
(m-1EP -0,27) e o sinal TROCA: +1,09 nos 9 pontos de duas alturas, -0,94 nos 7
que tem a altura do meio. Com so 0,05 e 1,65, z nao media altura, separava dois
LOTES de pontos. A pilha vertical em (2,05 . 2,39), que nao passa por ajuste
nenhum, confirma: 0,85 m e 6-7 dB PIOR que 0,05 e que 1,65 para a3 e a5 — nao
existe funcao monotona de z que faca isso. `demo()` prende o veredito. O
desenho abaixo fica porque foi ele que produziu a medida que o derrubou.

A campanha D-otima de 06/09 (boot 46716, 9 pontos) reprovou o padrao direcional
pela terceira vez e achou outra coisa. Os pontos 4 e 6 dividem o mesmo (x,y) em
z=0,05 e z=1,65: 21,5 dB de diferenca. A T5 fica MAIS LONGE no alto (3,12 contra
2,82 m) e chega 9,9 dB mais forte — nenhuma funcao monotona da distancia faz
isso, entao nao e geometria e o A/n/W nao alcanca.

O que muda aqui em relacao a `padrao.desenho()`:

1. O BLOCO otimizado. La era `c:` (padrao direcional), reprovado. Aqui e
   offset-por-ancora + altura, o unico arranjo que passou na transferencia
   (+1,92 +- 1,24 dB/ponto, m-1EP = +0,68 > 0,50).

2. A altura entra com z E z^2. Com so duas alturas medidas, "linear" e "degrau"
   sao indistinguiveis; o termo quadratico obriga o D-otimo a pedir alturas
   intermediarias, que e como a proxima campanha responde essa pergunta.

3. A DETECTABILIDADE foi recalibrada contra dado real. A 1a campanha entregou 54
   desfechos (9 pontos x 6 ancoras, 33 vivos / 21 mortos) e o modelo antigo
   (limiar -96, sigma 4,1) errava por VIES: previa 43,2 enlaces, vieram 33, com
   13 falso-vivos contra 1 falso-morto. Maxima verossimilhanca nos 54 da
   limiar -90,75 e sigma 7,75 — espera 33,0. O limiar sobe porque `extrai()` nao
   pede so nivel acima do piso, pede inclinacao em 1,00 +- 0,35 sobre >= 2
   niveis, e enlace marginal e reprovado ali mesmo passando do piso.
"""
import os, sys, json, math
import numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI); sys.path.insert(0, os.path.dirname(AQUI))
from rtls.modelo import padrao as PD
from rtls import sitio as P

LIMIAR = -90.75          # A previsto acima do qual o enlace sobrevive ao extrai()
SIGMA_P = 7.75           # espalhamento da transferencia, medido nos 54 desfechos
ZS = (0.05, 0.45, 0.85, 1.25, 1.65)
MIN_ANC = 3.0            # com o p calibrado; a 1a campanha rendeu 3,7 em media


def p_viva(A):
    """Prob. de o enlace render um A utilizavel, dado o A previsto."""
    return 0.5 * (1 + math.erf((A - LIMIAR) / (SIGMA_P * math.sqrt(2.0))))


def _alt(z):
    return [z, z * z]


def monta_h(d, usados=None, grau=0):
    """padrao.monta() + as duas colunas de altura (0 nas linhas de malha)."""
    X, y, idx, k, tag, ents = PD.monta(d, grau, usados)
    H = np.array([_alt(d["pontos"][t[0]][2]) if t[0] != "malha" else [0.0, 0.0]
                  for t in tag])
    return np.hstack([X, H]), y, idx, k, tag, ents


def _gauge_h(idx, k, grau, ents):
    Rg = PD.gauge(idx, k, grau, ents)
    return np.hstack([Rg, np.zeros((len(Rg), 2))])


def ajusta_h(d, usados=None, grau=0, lam=0.5, pg=1e3):
    X, y, idx, k, tag, ents = monta_h(d, usados, grau)
    Rg = _gauge_h(idx, k, grau, ents)
    A = np.vstack([X, pg * Rg]); b = np.append(y, np.zeros(len(Rg)))
    D = np.ones(X.shape[1]); D[[idx["A0"], idx["n"], idx["W"]]] = 0.0
    th = np.linalg.solve(A.T @ A + lam * np.diag(D), A.T @ b)
    return th, idx, k, ents


def linha_h(idx, k, ents, xp, a, grau=0):
    xp = np.asarray(xp, float)
    return np.append(PD._linha(idx, k, grau, ents, xp, ents[a].xyz, "cyd", a), _alt(xp[2]))


def preve_h(th, idx, k, ents, xp, a, grau=0):
    return float(linha_h(idx, k, ents, xp, a, grau) @ th)


def calibra(d, grau=0):
    """-> (limiar, sigma, logvero, obs) por maxima verossimilhanca.

    Cada desfecho e previsto com o PROPRIO PONTO FORA do ajuste: o modelo nao
    pode usar o enlace para prever se aquele enlace existe.
    """
    pts = sorted(d["campanha"])
    obs = []
    for q in pts:
        th, idx, k, ents = ajusta_h(d, [p for p in pts if p != q], grau)
        for a in PD.ANC:
            obs.append((preve_h(th, idx, k, ents, d["pontos"][q], a, grau),
                        a in d["campanha"][q]))
    def lv(lim, s):
        f = lambda A: 0.5 * (1 + math.erf((A - lim) / (s * math.sqrt(2.0))))
        return sum(math.log(max(1e-12, f(A) if v else 1 - f(A))) for A, v in obs)
    b, lim, s = max((lv(l, s), l, s) for l in np.arange(-100, -74, 0.25)
                    for s in np.arange(1, 16, 0.25))
    return float(lim), float(s), float(b), obs


def desenho(d, k=8, grau=0, passo=0.35, zs=ZS, minsep=0.6, lam=0.5, pg=1e3, fixos=()):
    """Escolhe os k proximos pontos. Base = malha + TUDO que ja foi andado.

    `fixos` entra na campanha antes do guloso: e como se pede uma PILHA vertical
    no mesmo (x,y). O guloso sozinho nao pede — a pilha nao e a mais informativa
    para o ajuste — mas a diferenca entre duas alturas no mesmo lugar mede a
    altura sem passar pelo modelo, e foi assim (pontos 4 e 6) que o efeito
    apareceu. Um numero que so o proprio ajuste confirma nao confirma nada.
    """
    th, idx, kg, ents = ajusta_h(d, None, grau)
    Rg = _gauge_h(idx, kg, grau, ents)
    kk = kg + 2
    # so o que a campanha CONSEGUE mover: a linha dela e cyd->ancora, entao toca
    # t:cyd, r:a e a altura. Os t:a sao da malha e nao adianta persegui-los aqui.
    # t:cyd entra porque com duas alturas so ele, z e z^2 sao a MESMA direcao —
    # e essa confusao que a campanha tem de desfazer.
    ialvo = [idx["t:cyd"]] + [idx[f"r:{a}"] for a in PD.ANC] + [kg, kg + 1]
    D = np.ones(kk); D[[idx["A0"], idx["n"], idx["W"]]] = 0.0
    G = pg ** 2 * (Rg.T @ Rg) + lam * np.diag(D)     # a mesma cresta do ajusta_h
    Xb = monta_h(d, None, grau)[0]
    F0 = Xb.T @ Xb + G

    crit = lambda F: -np.linalg.slogdet(np.linalg.inv(F)[np.ix_(ialvo, ialvo)])[1]
    sig = lambda F: SIGMA_P * float(np.sqrt(np.mean(np.diag(np.linalg.inv(F))[ialvo])))

    from rtls.modelo.testes import dentro
    fp = P.floorplan()
    cand = []
    for x in np.arange(fp.xmin + 0.3, fp.xmax - 0.2, passo):
        for y in np.arange(fp.ymin + 0.3, fp.ymax - 0.2, passo):
            if not dentro(x, y):
                continue
            for z in zs:
                xp = np.array([x, y, z])
                p = np.array([p_viva(preve_h(th, idx, kg, ents, xp, a, grau))
                              for a in PD.ANC])
                if p.sum() < MIN_ANC:
                    continue
                L = np.array([linha_h(idx, kg, ents, xp, a, grau) for a in PD.ANC])
                cand.append((xp, p, (L * p[:, None]).T @ L))
    esc, F, hist = [], F0.copy(), [sig(F0)]
    for q in fixos:
        xp = np.array(q, float)
        p = np.array([p_viva(preve_h(th, idx, kg, ents, xp, a, grau)) for a in PD.ANC])
        L = np.array([linha_h(idx, kg, ents, xp, a, grau) for a in PD.ANC])
        esc.append((xp, p)); F = F + (L * p[:, None]).T @ L; hist.append(sig(F))
    for _ in range(k - len(esc)):
        melhor = None
        for xp, p, I in cand:
            if any(np.linalg.norm(xp - q) < minsep for q, _ in esc):
                continue
            v = crit(F + I)
            if melhor is None or v > melhor[0]:
                melhor = (v, xp, p, I)
        if melhor is None:
            break
        _, xp, p, I = melhor
        esc.append((xp, p)); F = F + I; hist.append(sig(F))
    return dict(escolhidos=[(list(map(float, q)), dict(zip(PD.ANC, map(float, p))))
                            for q, p in esc],
                sigma_dB=hist, limiar=LIMIAR, sigma_p=SIGMA_P,
                pontos_base=sorted(d["campanha"]))


def junta(*nomes):
    """Uma campanha so a partir de varios json. Prefixo no id para nao colidir.

    So vale juntar se a MALHA for a mesma: os A de campanha sao offsets contra o
    padrao ajustado, e padrao de outro estado de radio e outro numero. As duas de
    06-07/09 batem em -0,03 dB de mediana (dp 0,98), entao valem.
    """
    ds = [json.load(open(os.path.join(AQUI, n))) for n in nomes]
    m = dict(ptx_malha=ds[-1]["ptx_malha"], malha=ds[-1]["malha"], pontos={}, campanha={})
    for i, d in enumerate(ds):
        pre = chr(ord("a") + i)
        m["pontos"].update({pre + k: v for k, v in d["pontos"].items()})
        m["campanha"].update({pre + k: v for k, v in d["campanha"].items()})
    return m


def transfere(d, lam=0.5):
    """-> {braco: [rms por ponto]}, pts.  O ponto de fora sai do ajuste tambem.

    Tres bracos com o MESMO deixa-um-fora: `no ar` e o que esta no daemon
    (A/n/W), `offset` acrescenta t/r por ancora, `offset+z` acrescenta z e z^2.
    A diferenca entre os dois ultimos e o que a ALTURA vale — e so isso decide,
    porque dentro da amostra qualquer coluna a mais baixa o residuo.
    """
    pts = sorted(d["campanha"])
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v))
    R = {"no ar": [], "offset": [], "offset+z": []}
    for q in pts:
        fora = [p for p in pts if p != q]
        for nome, grau in (("no ar", None), ("offset", 0)):
            th, i, k, e, *_ = PD.ajusta(d, grau, fora, lam)
            R[nome].append(rms([v["A"] - PD.preve(th, i, k, grau, e, d["pontos"][q], a)
                                for a, v in d["campanha"][q].items()]))
        th, i, k, e = ajusta_h(d, fora, 0, lam)
        R["offset+z"].append(rms([v["A"] - preve_h(th, i, k, e, d["pontos"][q], a, 0)
                                  for a, v in d["campanha"][q].items()]))
    return R, pts


def demo():
    d = json.load(open(os.path.join(AQUI, "campanha_46716.json")))
    lim, s, b, obs = calibra(d)
    p = lambda A: 0.5 * (1 + math.erf((A - lim) / (s * math.sqrt(2.0))))
    esp, real = sum(p(A) for A, _ in obs), sum(v for _, v in obs)
    assert abs(esp - real) < 1.0, (esp, real)          # calibrado: espera o que veio
    velho = sum(PD.p_util(A) for A, _ in obs)
    assert velho - real > 8, (velho, real)             # o antigo era otimista mesmo
    # a altura tem de melhorar o ajuste dentro da amostra (transferencia e outro teste)
    th, idx, k, ents = ajusta_h(d)
    assert abs(th[k]) > 1.0, th[k]
    des = desenho(d, k=3)
    assert len(des["escolhidos"]) == 3
    assert des["sigma_dB"][-1] < des["sigma_dB"][0], des["sigma_dB"]
    assert all(sum(pp.values()) >= MIN_ANC for _, pp in des["escolhidos"])

    # VEREDITO 07/09: a 2a campanha andou e a altura NAO transfere. Com as duas
    # juntas o ganho de z sobre o offset e +0,20 +- 0,48 (m-1EP -0,27), e o sinal
    # TROCA entre os 9 velhos (+1,09, so 0,05 e 1,65) e os 7 novos (-0,94, com
    # 0,85). Com duas alturas so, z separava dois LOTES de pontos.
    j = junta("campanha_46716.json", "campanha_alt_medida.json")
    R, pts = transfere(j)
    gz = np.array(R["offset"]) - np.array(R["offset+z"])
    ep = gz.std(ddof=1) / math.sqrt(len(gz))
    assert gz.mean() - ep < 0.5, (gz.mean(), ep)       # reprova a transferencia
    velhos = gz[[i for i, q in enumerate(pts) if q.startswith("a")]].mean()
    novos = gz[[i for i, q in enumerate(pts) if q.startswith("b")]].mean()
    assert velhos > 0 > novos, (velhos, novos)         # e troca de sinal, nao ruido
    print(f"transferencia: z sobre offset {gz.mean():+.2f} +- {ep:.2f} dB/ponto "
          f"(velhos {velhos:+.2f}, novos {novos:+.2f}) -> REPROVA")
    print(f"altura ok (limiar {lim:.2f} sigma {s:.2f}; espera {esp:.1f} de {real} reais, "
          f"o modelo antigo esperava {velho:.1f}; sigma_c {des['sigma_dB'][0]:.2f}"
          f"->{des['sigma_dB'][-1]:.2f} dB em 3 pontos)")


if __name__ == "__main__":
    demo()
