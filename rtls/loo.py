"""Leave-one-out: localiza cada ancora a partir das OUTRAS.

E o unico teste de RTLS de verdade que da para fazer sem ninguem em casa: as 6
posicoes sao conhecidas com fita metrica, entao cada ancora e um alvo com gabarito.
Para nao trapacear, o modelo (A, n, W) e reajustado SEM nenhum enlace que envolva
a ancora sendo localizada.

Nao e o caso do alvo real (a antena das duas pontas e a mesma ceramica ruim, e
alvo e ancora estao em alturas diferentes), mas e o piso: se nao localiza uma
ancora parada com 5 vizinhas, nao localiza uma pessoa.

  python3 loo.py <dir com malha.jsonl> [janela_s]
"""
import json, os, sys, time, collections, statistics as st
import numpy as np
from rtls import sitio as P
from rtls import ajuste
from rtls.tracker import Tracker

PASSOS, DT = 60, 2.0     # alvo parado: 2 min de medidas iguais, so pra nuvem fechar

# Piso de censura. -101 e o piso real do radio; a 8 dB dele so os picos passam e a
# mediana mente para cima (campanha.py). Tratar (nao jogar fora) e MEDIDO:
#
#             LOO 6 alvos            CYD com gabarito
#   nada      1,82 / pior 3,98       1,76 m
#   joga fora 2,79 / pior 5,72       0,88 m   <- perde um alvo inteiro no LOO
#   cauda     1,69 / pior 4,24       1,06 m   <- unica que melhora nos dois
PISO = -93.0

def por_enlace(dirbase, janela=None):
    """-> {(rx, tx): [rssi, ...]} com rx/tx ja em rotulo de ancora (T1, T3, ...)."""
    br = collections.defaultdict(list)
    t_max = 0.0
    for l in open(os.path.join(dirbase, "malha.jsonl")):
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if "rx" not in d:
            continue
        rx, tx = str(d["rx"]), str(d["tx"])
        if not (rx.isdigit() and tx.isdigit()):
            continue
        rx, tx = int(rx), int(tx)
        if rx not in P.TOMADA or tx not in P.TOMADA:
            continue
        t_max = max(t_max, d.get("t", 0))
        br[(P.TOMADA[rx], P.TOMADA[tx])].append((d.get("t", 0), d["r"]))
    return {k: [r for t, r in v if not janela or t >= t_max - janela]
            for k, v in br.items()}

def vies_por_ancora(pts, beta):
    """Residuo medio de cada ancora COMO RECEPTORA, nos enlaces de treino.

    Nao e um refinamento: e o que separa um sistema que funciona de um que nao
    funciona aqui. Uma ancora que ouve 5 dB abaixo do modelo (antena, orientacao,
    movel na frente) empurra a nuvem sistematicamente para LONGE dela, e como o
    erro e sistematico o filtro fica confiante no lugar errado. MEDIDO abaixo.
    """
    X = lambda p: np.array([1.0, -10 * np.log10(max(p[0], 0.5)), -p[1]])
    acc = collections.defaultdict(list)
    for p in pts:
        rx = P.TOMADA[int(p[5].split("<-")[0])]
        acc[rx].append(p[2] - float(X(p) @ beta))
    return {a: float(np.mean(v)) for a, v in acc.items()}

def loo(dirbase, janela=None, minimo=8, calibra=False, paredes=True, piso=PISO):
    """calibra=False e MEDIDO, nao preguica. Ablacao na malha de 26 h, 6 alvos:

        paredes  calib   mediana  media  pior
          nao     nao      2,02   3,23   9,49
          nao     sim      2,32   2,75   5,13
          SIM     nao      1,55   1,49   2,60   <- melhor
          SIM     sim      1,90   2,07   4,65

    Com o termo de parede no modelo, o residuo por ancora ja esta explicado; tirar
    ele de novo e contar duas vezes. A calibracao so ajudava para tapar a falta das
    paredes."""
    enl = por_enlace(dirbase, janela)
    pts = ajuste.pontos(dirbase, janela)
    fp = P.floorplan()
    linhas = []
    for alvo in P.ESCOLHIDAS:
        # modelo sem nenhum enlace do alvo: ajuste.pontos rotula "rx<-tx" com o
        # numero da tomada, entao remapeia para comparar com o rotulo da ancora
        fora = []
        for p in pts:
            rx, tx = p[5].split("<-")
            if P.TOMADA[int(rx)] != alvo and P.TOMADA[int(tx)] != alvo:
                fora.append(p)
        beta, rms, _ = ajuste.ajusta(fora)
        (A, n, W) = beta
        c = vies_por_ancora(fora, beta) if calibra else {}

        obs = {a: st.median(v) - c.get(a, 0.0) for (a, t), v in enl.items()
               if t == alvo and a != alvo and len(v) >= minimo}
        verdade = np.array(P.ANCORAS[alvo][:2])
        if len(obs) < 3:
            linhas.append((alvo, len(obs), None, None, None, None, A, n))
            continue
        anc = {a: P.ANCORAS[a] for a in P.ESCOLHIDAS if a != alvo}
        tk = Tracker(anc, fp, A=A, n_exp=n, sigma=3.8, W=W if paredes else 0.0,
                     z_alvo=P.ANCORAS[alvo][2], seed=1, piso=piso)
        est = None
        for i in range(PASSOS):
            est = tk.update("alvo", obs, i * DT)
        err = float(np.linalg.norm(est - verdade))
        com = tk.comodo("alvo")
        top = max(com, key=com.get) if com else None
        linhas.append((alvo, len(obs), est, err, tk.spread("alvo"),
                       (top, com.get(top, 0.0)), A, n))
    return linhas

JANELA_VIVO = 30   # s. O CYD e ouvido ~10x/s no total; 30 s ja da >=12 amostras
                   # na ancora mais surda. Janela longa aqui BORRA um alvo que anda.

def alvo_vivo(dirbase, janela=JANELA_VIVO, minimo=4, passos=120, dt=1.0,
              jan_modelo=None, z_alvo=0.75):
    """Posicao AO VIVO do CYD — o unico alvo movel que existe hoje. SEM gabarito.

    O CYD carimba a Ptx em cada anuncio, entao normaliza (r - ptx). O que sobra de
    desconhecido e so a diferenca de antena CYD x SuperMini mais a Ptx da malha:
    um offset COMUM a todas as ancoras. Offset comum quase nao move a estimativa
    (MEDIDO no proprio tracker: 8 dB de alvo custam 3,60 -> 3,59 m), porque o que
    localiza e a comparacao ENTRE ancoras. Fica no b do filtro, semeado do
    centroide para o primeiro passo nao jogar a nuvem num canto.

    -> (est, spread, comodo_top, n_ancoras, b, idade_s, verdade|None, erro|None,
        p_parado, ess_frac, nuvem, cego).  Os tres primeiros do fim sao o
    termometro do filtro; loo_viz consome como `*saude` e tolera ausencia, mas
    ambos os caminhos daqui devolvem os 12.

    cego=True marca o caminho de queda: A/n/W reajustados na hora, do ajuste CRU
    da malha, sem passar pelo juiz do revisao.py. Foi esse reajuste que fez o
    erro subir 0,98 -> 1,19 m numa noite sem 1 dB de mudanca no radio. Nada na
    tela distinguia os dois caminhos: idade_s aqui e a idade do ultimo
    AVISTAMENTO, entao o painel parecia saudavel. Agora o SVG diz.
    """
    # Se o daemon (vivo.py --daemon) esta publicando, USA o estado dele: e o mesmo
    # filtro atravessando o tempo, em vez de um filtro novo re-estimado do zero a
    # cada render. So cai no caminho antigo se o json estiver velho ou ausente.
    try:
        with open(os.path.join(dirbase, "vivo.json")) as f:
            j = json.load(f)
        if time.time() - j["t"] < 15:
            return (np.array([j["x"], j["y"]]), j["spread"],
                    (j["comodo"], j["p_comodo"]), j["n_ancoras"], j["b"],
                    # idade do ALVO, nao da publicacao: das 2h as 8h o CYD vira
                    # sniffer BLE e o daemon republica a ultima posicao conhecida.
                    # Mostrar "ha 0 s" ali seria mentira.
                    j.get("idade_alvo", time.time() - j["t"]),
                    j.get("verdade"), j.get("erro"),
                    j.get("p_parado"), j.get("ess"), j.get("nuvem"), False)
    except Exception:
        pass
    caminho = os.path.join(dirbase, "refcyd.jsonl")
    if not os.path.exists(caminho):
        return None
    obs_t = collections.defaultdict(list)
    t_max = 0.0
    for l in open(caminho):
        try:
            d = json.loads(l)
        except ValueError:
            continue
        rx = str(d.get("rx", ""))
        if not rx.isdigit() or int(rx) not in P.TOMADA:
            continue
        t_max = max(t_max, d.get("t", 0))
        obs_t[P.TOMADA[int(rx)]].append((d.get("t", 0), d["r"] - d.get("ptx", 0)))
    obs = {a: st.median([r for t, r in v if t >= t_max - janela])
           for a, v in obs_t.items()
           if sum(1 for t, _ in v if t >= t_max - janela) >= 3}
    if len(obs) < minimo:
        return None
    (A, n, W), _, _ = ajuste.ajusta(ajuste.pontos(dirbase, jan_modelo))
    anc = {a: P.ANCORAS[a] for a in P.ESCOLHIDAS}
    # b_alfa=0,2 (4x o do vivo.py, e o default do Tracker e 0). Ver Tracker.__init__:
    # a divergencia e real e so a campanha rotulada decide qual dos tres vale.
    tk = Tracker(anc, P.floorplan(), A=A, n_exp=n, sigma=3.8, W=W,
                 z_alvo=z_alvo, b_alfa=0.2, seed=1, piso=PISO)
    # b0 pelo centroide: e uma ancora de ESCALA, nao um palpite de posicao
    viv = [a for a, r in obs.items() if r > PISO] or list(obs)
    c = np.mean([P.ANCORAS[a][:2] for a in viv], axis=0)
    mu0 = [A - 10*n*np.log10(max(np.linalg.norm(np.array(P.ANCORAS[a][:2]) - c), 0.5))
           for a in viv]
    b0 = float(np.mean([obs[a] for a in viv]) - np.mean(mu0))
    est = None
    for i in range(passos):
        est = tk.update("cyd", obs, i * dt)
        if i == 0:
            tk.tracks["cyd"].b = b0
    com = tk.comodo("cyd")
    top = max(com, key=com.get) if com else None
    v = verdade_do_alvo()
    err = float(np.linalg.norm(est - np.array(v[:2]))) if v else None
    # mesma aridade do caminho do daemon; p_parado/ESS existem, mas aqui saem de um
    # filtro re-estimado do zero, entao valem menos — o daemon e quem deve responder.
    return (est, tk.spread("cyd"), (top, com.get(top, 0.0)) if top else None,
            len(obs), tk.tracks["cyd"].b, time.time() - t_max, v, err,
            tk.p_parado("cyd"), tk.tracks["cyd"].ess / tk.n, tk.nuvem("cyd"), True)

def verdade_do_alvo(caminho=None):
    """Gabarito do alvo movel, se alguem anotou onde ele esta. -> (x, y, z) ou None.

    Sem isto o painel desenha uma estimativa que ninguem pode contestar. Com isto
    ela vira medida: o primeiro gabarito do alvo REAL (nao de ancora) mostrou 1,76 m
    de erro com nuvem de 0,82 m — confiante e errado, o defeito que importa."""
    caminho = caminho or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "alvo_verdade.json")
    try:
        d = json.load(open(caminho))
        return (float(d["x"]), float(d["y"]), float(d.get("z", 0.75)))
    except (OSError, ValueError, KeyError):
        return None

def comodo_de(p):
    """As ancoras ficam EM CIMA da parede, fora de todo poligono: sem o desempate
    pelo mais proximo, metade dos gabaritos vinha '?' e a comparacao nao existia."""
    fp = P.floorplan()
    melhor, dmin = "?", 1e9
    for k, poly in (fp.rooms or {}).items():
        if _dentro1(p, poly):
            return k
        q = np.array(poly, float)
        d = float(np.min(np.linalg.norm(q - np.asarray(p, float), axis=1)))
        if d < dmin:
            melhor, dmin = k, d
    return melhor

def _dentro1(p, poly):
    from rtls.tracker import _dentro
    return bool(_dentro(np.array([p]), poly)[0])

def demo():
    """Auto-teste: com RSSI SINTETICO do proprio modelo, o erro tem de ser pequeno."""
    fp = P.floorplan()
    A, n = -72.0, 2.3
    # As ancoras vem do sitio carregado, nunca de uma lista fixa: este e o mesmo
    # ensaio da secao 06 (LOO de ancora), que so faz sentido no sitio de quem roda.
    for alvo in list(P.ESCOLHIDAS)[:2]:
        anc = {a: P.ANCORAS[a] for a in P.ESCOLHIDAS if a != alvo}
        v = np.array(P.ANCORAS[alvo])
        obs = {}
        for a, q in anc.items():
            d = np.linalg.norm(np.array(q) - v)
            obs[a] = A - 10 * n * np.log10(max(d, 0.5))
        tk = Tracker(anc, fp, A=A, n_exp=n, sigma=3.8, z_alvo=v[2], seed=1)
        for i in range(PASSOS):
            est = tk.update("x", obs, i * DT)
        e = float(np.linalg.norm(est - v[:2]))
        assert e < 0.8, (alvo, e, est)
    print("loo ok (dado sintetico do proprio modelo volta a < 0,8 m)")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    jan = next((int(x) for x in sys.argv[2:] if x.isdigit()), None)
    cal = "--calibracao" in sys.argv
    par = "--sem-paredes" not in sys.argv
    print(f"calibracao por ancora: {'LIGADA' if cal else 'desligada'}   "
          f"paredes no modelo: {'LIGADAS' if par else 'desligadas'}")
    print(f"{'alvo':5} {'n_anc':>5} {'estimado':>16} {'verdade':>16} {'erro':>6} "
          f"{'nuvem':>6}  comodo estimado / real")
    errs = []
    for alvo, na, est, err, sp, top, A, n in loo(base, jan, calibra=cal, paredes=par):
        v = P.ANCORAS[alvo]
        if est is None:
            print(f"{alvo:5} {na:5}   (menos de 3 ancoras ouviram)")
            continue
        errs.append(err)
        real = comodo_de(v[:2])
        marca = "OK " if top and top[0] == real else "ERR"
        print(f"{alvo:5} {na:5} ({est[0]:5.2f},{est[1]:5.2f}) ({v[0]:5.2f},{v[1]:5.2f}) "
              f"{err:6.2f} {sp:6.2f}  {marca} {top[0]}({top[1]:.0%}) / {real}")
    if errs:
        print(f"\nerro mediano {st.median(errs):.2f} m   medio {st.mean(errs):.2f} m   "
              f"pior {max(errs):.2f} m   ({len(errs)} alvos)")
