"""Filtro AO VIVO, com estado que atravessa o tempo.

O painel ate agora criava um filtro NOVO a cada render e o alimentava 120 vezes
com a MESMA mediana de 30 s. Isso nao e filtrar: e re-estimar do zero, e o
resultado e um alvo parado que anda 50 m em 20 min no mapa (MEDIDO). Um filtro
de particulas existe justamente para carregar a crenca de um instante ao
seguinte; jogar ela fora a cada 30 s e desligar a unica parte que da resiliencia.

Aqui roda UM filtro continuo, alimentado com os avistamentos em ordem de tempo,
em fatias de PASSO segundos. Ancora que nao falou na fatia simplesmente nao entra
(termo ausente, nunca RSSI de piso).

  python3 vivo.py <dir> --daemon     # ao vivo, escreve vivo.json a 2 Hz
  python3 vivo.py <dir> --replay N   # refaz as ultimas N horas do log e mede
"""
import json, os, sys, time, collections
import numpy as np
from rtls import sitio as P
from rtls import ajuste
from rtls import loo
from rtls.tracker import Tracker

PASSO = 0.5          # s por atualizacao do filtro. 2 Hz com ~10 avistamentos/s
                     # significa ~5 medidas por passo, de 2-3 ancoras diferentes.
REAJUSTE_S = 900     # o modelo A/n/W vem da malha; nao precisa reajustar rapido
TRILHA = 240         # pontos guardados para o painel desenhar o rastro
HIST_S = 10          # s entre linhas de vivo_hist.jsonl

def sightings(dirbase, desde=0.0):
    """-> lista (t, ancora, rssi_normalizado_por_ptx) em ordem de tempo."""
    out = []
    with open(os.path.join(dirbase, "refcyd.jsonl")) as f:
        for l in f:
            try:
                d = json.loads(l)
            except ValueError:
                continue
            rx = str(d.get("rx", ""))
            if not rx.isdigit() or int(rx) not in P.TOMADA or d.get("t", 0) < desde:
                continue
            out.append((d["t"], P.TOMADA[int(rx)], d["r"] - d.get("ptx", 0)))
    out.sort(key=lambda z: z[0])
    return out

def modelo(dirbase, janela=None):
    (A, n, W), rms, _ = ajuste.ajusta(ajuste.pontos(dirbase, janela))
    return float(A), float(n), float(W), float(rms)

# alpha=0,5 (tempering) SO no deploy real, nao no default da classe. O banco
# simulado gera ruido independente por passo, entao ali qualquer alpha<1 perde por
# construcao (MEDIDO: 3,18 -> 4,26 m no alvo que anda). Nesta casa o residuo e
# MEDIDO constante — +8,7 dB no enlace 5<->3, +16 dB do CYD para a 5, estavel a
# 1 dB em 90 min — logo contar 120 leituras/min como evidencias novas e
# independentes e a mentira que deixa a posterior confiante e errada.
#
# Varredura de 2 h no CYD parado, gabarito por fita (passeio m/min | erro | p90):
#   alpha 1,0  q 0,60   23,93 | 1,08 | 2,25    <- so o modo parado/andando
#   alpha 0,5  q 0,60   11,58 | 0,96 | 1,31    <- ESCOLHIDO
#   alpha 0,5  q 0,05    9,22 | 0,94 | 1,27    <- 2 m/min a mais nao paga: q=0,05
#                                                 leva o alvo que ANDA a 11,76 m
#   Student-t (nu=4) baixa o passeio e PIORA o p90 (2,79): fora.
# Referencia antes de tudo isto: passeio 64,10 | erro 1,36 | p90 2,81.
ALPHA = 0.5

MODELO_JSON = "modelo.json"
VALIDADE_MODELO_S = 172800   # 48 h: a revisao noturna pode falhar uma noite
SEM_ALVO_S = 120.0           # sem pacote do CYD por mais que isto = alvo ausente

def modelo_vigente(dirbase):
    """O modelo que o DEPLOY usa: o promovido por revisao.py, com queda para o
    ajuste cru da malha se nao houver revisao recente.

    Antes o daemon reajustava A/n/W pela malha a cada 15 min sem juiz nenhum — um
    ajuste entrava em producao so por ser novo, e o erro do CYD subia 0,98 -> 1,19 m
    numa noite em que o RSSI mediano de cada ancora nao mexeu 1 dB (MEDIDO). Agora
    so entra o que ganhou no banco dos emissores parados.
    """
    try:
        with open(os.path.join(dirbase, MODELO_JSON)) as f:
            j = json.load(f)
        if time.time() - j["t"] < VALIDADE_MODELO_S:
            return float(j["A"]), float(j["n"]), float(j["W"]), float(j.get("rms", 0.0))
    except Exception:
        pass
    return modelo(dirbase)

def ganho_por_ancora(ids):
    """Ganho direcional/offset por ancora de modelo/padrao.py — SO se a
    transferencia leave-one-point-out tiver aprovado. Hoje devolve None (a
    campanha D-otima de 3 pontos nao ganhou do A/n/W isotropico), e None e o
    caminho normal, nao falha. Le o `usar` a seco antes de importar o modelo:
    reprovado, o daemon nem carrega numpy extra."""
    try:
        j = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelo", "padrao.json")
        if not (os.path.exists(j) and json.load(open(j)).get("usar")):
            return None
        sys.path.insert(0, os.path.dirname(j))
        import padrao
        return padrao.ganho_para(ids, j)
    except Exception as e:
        print(f"[vivo] padrao.json ignorado: {e}", file=sys.stderr)
        return None

def novo_tracker(A, n, W, **kw):
    kw.setdefault("alpha", ALPHA)
    kw.setdefault("ganho", ganho_por_ancora(list(P.ESCOLHIDAS)))
    return Tracker({a: P.ANCORAS[a] for a in P.ESCOLHIDAS}, P.floorplan(),
                   # b_alfa=0,05 aqui, 0,2 em loo.online, 0 no default do Tracker.
                   # Divergencia nao medida — ver a nota em Tracker.__init__.
                   A=A, n_exp=n, sigma=3.8, W=W, z_alvo=0.75, b_alfa=0.05,
                   seed=1, piso=loo.PISO, **kw)

def fatias(sig, passo=PASSO):
    """Agrupa avistamentos em fatias de tempo. -> (t_fim, {ancora: rssi_mediano})."""
    if not sig:
        return
    t0 = sig[0][0]
    bal = collections.defaultdict(list)
    lim = t0 + passo
    for t, a, r in sig:
        while t >= lim:
            if bal:
                yield lim, {k: float(np.median(v)) for k, v in bal.items()}
                bal = collections.defaultdict(list)
            lim += passo
        bal[a].append(r)
    if bal:
        yield lim, {k: float(np.median(v)) for k, v in bal.items()}

def replay(dirbase, horas=1.0, passo=PASSO, mod=None, sig=None, **kw):
    """Refaz o log com UM filtro continuo. -> (ts, ests, spreads, tracker).

    sig= reaproveita a leitura: refcyd.jsonl tem 20 MB e revisao.py julga varios
    modelos sobre exatamente os mesmos avistamentos."""
    sig = sightings(dirbase) if sig is None else sig
    if not sig:
        return [], np.zeros((0, 2)), [], None
    corte = sig[-1][0] - horas * 3600
    sig = [s for s in sig if s[0] >= corte]
    A, n, W, _ = mod if mod else modelo_vigente(dirbase)
    tk = novo_tracker(A, n, W, **kw)
    ts, ests, sps = [], [], []
    for t, obs in fatias(sig, passo):
        e = tk.update("cyd", obs, t)
        if e is not None:
            ts.append(t); ests.append(e.copy()); sps.append(tk.spread("cyd"))
    return ts, np.array(ests), sps, tk

def metricas(ts, E, verdade=None):
    """O que importa num alvo PARADO: nao e so o erro, e o quanto ele PASSEIA."""
    if len(E) < 2:
        return {}
    d = np.linalg.norm(np.diff(E, axis=0), axis=1)
    dur = (ts[-1] - ts[0]) / 60 or 1
    m = {"n": len(E), "min": dur,
         "passeio_m_por_min": float(d.sum() / dur),
         "salto_medio": float(d.mean()), "salto_max": float(d.max()),
         "desvio_xy": float(np.mean(np.std(E, axis=0)))}
    if verdade is not None:
        er = np.linalg.norm(E - np.asarray(verdade, float)[:2], axis=1)
        m |= {"erro_medio": float(er.mean()), "erro_p90": float(np.percentile(er, 90)),
              "erro_max": float(er.max())}
    return m

def linha(tag, m):
    return (f"{tag:34s} passeio {m['passeio_m_por_min']:6.2f} m/min  "
            f"salto {m['salto_medio']:.2f}/{m['salto_max']:.2f}  "
            f"desvio {m['desvio_xy']:.2f}  "
            + (f"erro {m['erro_medio']:.2f} (p90 {m['erro_p90']:.2f})" if "erro_medio" in m else ""))

def demo():
    """Auto-teste: as fatias preservam ordem e conteudo."""
    sig = [(0.0, "T1", -60), (0.1, "T1", -62), (0.2, "T3", -70),
           (0.7, "T1", -61), (1.4, "T4", -80)]
    fs = list(fatias(sig, 0.5))
    assert [sorted(f[1]) for f in fs] == [["T1", "T3"], ["T1"], ["T4"]], fs
    assert fs[0][1]["T1"] == -61.0, fs[0]          # mediana dentro da fatia
    assert all(fs[i][0] < fs[i+1][0] for i in range(len(fs)-1))
    # o passeio de um ponto imovel tem de dar zero, e o de um ponto que anda, nao
    parado = np.zeros((10, 2))
    assert metricas(list(range(10)), parado)["passeio_m_por_min"] == 0.0
    anda = np.column_stack([np.arange(10.0), np.zeros(10)])
    assert metricas(list(range(10)), anda)["salto_medio"] == 1.0
    print("vivo ok (fatias em ordem, mediana na fatia, passeio zero para ponto imovel)")

# ------------------------------------------------------------------ daemon
SAIDA = "vivo.json"

def _tail(caminho, desde_fim=True):
    """Gerador infinito de linhas novas. Reabre se o arquivo for trocado (inode)."""
    f = open(caminho)
    if desde_fim:
        f.seek(0, 2)
    ino = os.fstat(f.fileno()).st_ino
    while True:
        l = f.readline()
        if l:
            yield l
            continue
        try:
            if os.stat(caminho).st_ino != ino:
                f.close(); f = open(caminho); ino = os.fstat(f.fileno()).st_ino
                continue
        except OSError:
            pass
        yield None            # nada novo: quem chama decide se dorme

def _publica(j, saida):
    tmp = saida + ".tmp"          # troca atomica: o painel nunca le json pela metade
    with open(tmp, "w") as f:
        json.dump(j, f)
    os.replace(tmp, saida)

def daemon(dirbase, passo=PASSO, aquece_h=0.25):
    """UM filtro permanente. Le refcyd.jsonl ao vivo e publica vivo.json a 1/passo Hz.

    O painel antes criava um Tracker NOVO por render e o alimentava 120x com a MESMA
    mediana de 30 s. Isso e re-estimar do zero: joga fora exatamente a parte do filtro
    que da resiliencia. Aqui o estado atravessa o tempo, e o painel so LE o json.
    """
    caminho = os.path.join(dirbase, "refcyd.jsonl")
    saida = os.path.join(dirbase, SAIDA)
    A, n, W, rms = modelo_vigente(dirbase)
    tk = novo_tracker(A, n, W)
    t_mod = time.time()
    # aquece com o passado recente para nao publicar uma nuvem uniforme no primeiro seg
    sig = sightings(dirbase)
    for t, obs in fatias([s for s in sig if s[0] >= sig[-1][0] - aquece_h*3600] if sig else [], passo):
        tk.update("cyd", obs, t)
    bal, lim, trilha = collections.defaultdict(list), None, collections.deque(maxlen=TRILHA)
    t_hist, t_visto, ultimo = 0.0, time.time(), None
    verdade = loo.verdade_do_alvo()
    for l in _tail(caminho):
        if l is None:
            time.sleep(0.05)
        else:
            try:
                d = json.loads(l)
            except ValueError:
                continue
            rx = str(d.get("rx", ""))
            if not rx.isdigit() or int(rx) not in P.TOMADA:
                continue
            bal[P.TOMADA[int(rx)]].append(d["r"] - d.get("ptx", 0))
        agora = time.time()
        if lim is None:
            lim = agora + passo
        if agora < lim:
            continue
        lim = agora + passo
        obs = {k: float(np.median(v)) for k, v in bal.items()}
        bal = collections.defaultdict(list)
        if obs:
            t_visto = agora
        # Das 2h as 8h o CYD vira sniffer BLE e para de anunciar. Alimentar o filtro
        # com fatias VAZIAS por 6 h so espalha a nuvem e enche o historico de um
        # passeio que ninguem andou. Sem evidencia o filtro nao avanca: o TTL do
        # track expira sozinho e as 8h ele volta limpo.
        ausente = agora - t_visto > SEM_ALVO_S
        if ausente:
            if ultimo is None:
                continue
            j = dict(ultimo, t=agora, ausente=True,
                     idade_alvo=agora - t_visto, n_ancoras=0)
            _publica(j, saida)
            continue
        est = tk.update("cyd", obs, agora)
        if est is None:
            continue
        trilha.append([round(float(est[0]), 3), round(float(est[1]), 3)])
        com = tk.comodo("cyd")
        top = max(com, key=com.get) if com else None
        j = {"t": agora, "x": float(est[0]), "y": float(est[1]),
             "spread": tk.spread("cyd"), "p_parado": tk.p_parado("cyd"),
             "ess": tk.tracks["cyd"].ess / tk.n, "b": tk.tracks["cyd"].b,
             "n_ancoras": len(obs), "comodo": top, "p_comodo": com.get(top, 0.0),
             "modelo": {"A": A, "n": n, "W": W, "rms": rms},
             "ausente": False, "idade_alvo": agora - t_visto,
             # A nuvem inteira, nao so o desvio: o anel resume em UM numero uma
             # crenca que quase nunca e um circulo. Quando o filtro esta dividido
             # entre dois comodos, o anel mostra um disco gordo no corredor entre
             # eles — um lugar onde ele nao acha que o alvo esta.
             "nuvem": tk.nuvem("cyd"),
             "trilha": list(trilha)}
        ultimo = j
        if verdade is not None:
            j["verdade"] = list(map(float, verdade[:2]))
            j["erro"] = float(np.linalg.norm(est - np.asarray(verdade, float)[:2]))
        # historico: a trilha em memoria cobre 2 min, e a pergunta de amanha e sobre
        # a NOITE inteira. Uma linha por HIST_S segundos, so o essencial.
        if agora - t_hist >= HIST_S:
            t_hist = agora
            with open(saida.replace(".json", "_hist.jsonl"), "a") as f:
                f.write(json.dumps({k: j[k] for k in
                        ("t","x","y","spread","p_parado","ess","n_ancoras","comodo")}) + "\n")
        _publica(j, saida)
        if agora - t_mod > REAJUSTE_S:
            t_mod = agora
            try:
                A, n, W, rms = modelo_vigente(dirbase)
                tk.A, tk.n_exp, tk.W = A, n, W
            except Exception:
                pass                   # modelo velho e melhor que daemon morto


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1]
    if "--daemon" in sys.argv:
        daemon(base); sys.exit(0)
    if "--replay" in sys.argv:
        h = float(sys.argv[sys.argv.index("--replay") + 1])
        v = loo.verdade_do_alvo()
        ts, E, sps, tk = replay(base, h)
        print(linha(f"sequencial passo {PASSO}s", metricas(ts, E, v)))
