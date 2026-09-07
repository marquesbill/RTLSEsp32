"""Revisao periodica do modelo de propagacao, com juiz.

O daemon reajustava A/n/W pela malha a cada 15 min e adotava o resultado SEM
comparar com nada: bastava ser novo para entrar em producao. Numa noite em que o
RSSI mediano de cada ancora nao mexeu 1 dB, o erro do CYD subiu 0,98 -> 1,19 m.
Ou seja: o ajuste cru da malha nao e monotonicamente melhor, e ninguem estava
olhando.

Aqui o ajuste vira CANDIDATO. Quem decide e o banco dos emissores parados da casa
(estaticos.py): 8 radios que ninguem mexe e que nunca calibraram nada, logo todo
passeio na estimativa deles e erro do filtro. Um candidato so entra em producao se
passear MENOS que o modelo vigente, com margem. Empate perde: trocar modelo tem
custo e nenhum ganho comprovado.

Por que o juiz nao e o CYD: das 2h as 8h o CYD roda o firmware de sniffer BLE e
para de anunciar. E exatamente a janela em que esta revisao roda. Os emissores
parados sao ouvidos pelas ancoras o tempo todo, independem do CYD, e por isso sao
o unico juiz que existe as 3h da manha. Quando o CYD ESTA no ar, ele entra como
juiz secundario (veto): um candidato que ganhe nos estaticos mas piore o erro
contra a fita nao passa.

Aprendizado de maquina aqui e ajuste de parametro com validacao fora da amostra,
nao rede neural: o alvo real tem UM ponto de gabarito (alvo_verdade.json) contra
20 MB de RSSI sem rotulo. O que se aprende e A/n/W da malha — que TEM gabarito,
6 ancoras por fita — e o que valida sao radios que nao entraram no ajuste.

  python3 revisao.py <dir>              # so relata, nao promove
  python3 revisao.py <dir> --aplicar    # promove se algum candidato ganhar
  python3 revisao.py <dir> --slots      # corte do erro por faixa de hora

Agendado as 4h (dentro da janela do sniffer, com folga ate as 8h; 3h17 e 3h30 ja
tem job na caixa). flock -n para que uma revisao lenta nao empilhe com a proxima:
  0 4 * * * cd ~/rtls-dados && flock -n wireless/.revisao.lock nice -n 15 \
            python3 -u revisao.py wireless --aplicar --horas 2 >> wireless/revisao.log 2>&1

CUSTO MEDIDO: ~1090 s para 14 emissores x 1 h (5 min so para varrer 4,3 M de
registros BLE); ~35 min com --horas 2. O gargalo e a reamostragem multinomial do
filtro (rng.choice), nao o I/O — se um dia isto apertar, reamostragem sistematica
resolve, e de quebra tem variancia menor.

PRIMEIRA RODADA REAL (2026-09-05, 14 emissores, 1 h):
  modelo      A      n     W    passeio  erro CYD
  vigente   -71,1  2,54  1,4     2,63     1,35
  malha_1h  -71,8  2,37  1,6     2,51     1,41   <- passou na margem, VETADO por erro
  malha_6h  -69,6  2,75  1,8     2,94     1,32   <- melhor erro, passeia mais: fora
Nada promovido. Os dois juizes discordaram e a regra nao trocou o modelo por 4%
de passeio que custava erro. E para isso que o juiz existe.
"""
import json, os, sys, time, collections, statistics as st
import numpy as np
from rtls import ajuste, estaticos, vivo, loo

JANELAS_H = (1, 6, 24, 72)   # o ambiente muda de hora e de semana; deixa a janela competir
MARGEM = 0.97                # ganho minimo para trocar: 3% no passeio. Empate perde.
VETO_ERRO_M = 0.05           # piora tolerada no erro do CYD quando ele esta no ar
AUDIT = "revisao.jsonl"

def _passo(t0, msg):
    """Progresso em stderr. Um job noturno que fica 30 min mudo e indistinguivel
    de um job travado — e ja me custou meia hora de diagnostico."""
    print(f"[{time.time()-t0:6.1f}s] {msg}", file=sys.stderr, flush=True)

def candidatos(dirbase):
    """-> [(tag, (A, n, W, rms))]: o vigente mais um ajuste por janela."""
    out = [("vigente", vivo.modelo_vigente(dirbase))]
    for h in JANELAS_H:
        try:
            (A, n, W), rms, _ = ajuste.ajusta(ajuste.pontos(dirbase, h * 3600))
        except Exception:
            continue                      # janela sem enlaces suficientes: pula
        m = (float(A), float(n), float(W), float(rms))
        if not any(np.allclose(m[:3], o[:3], atol=0.01) for _, o in out):
            out.append((f"malha_{h}h", m))
    return out

def cyd_no_ar(dirbase, tol_s=300.0):
    """O CYD anuncia agora? Das 2h as 8h ele e sniffer e a resposta e nao."""
    caminho = os.path.join(dirbase, "refcyd.jsonl")
    try:
        with open(caminho, "rb") as f:          # so o fim: o arquivo tem 20 MB
            f.seek(max(0, os.path.getsize(caminho) - 4096))
            ult = f.read().decode("utf8", "ignore").strip().splitlines()[-1]
        return time.time() - json.loads(ult)["t"] < tol_s
    except Exception:
        return False

def julga(dirbase, mods, horas=3.0):
    """-> {tag: {"passeio": mediana, "desvio": mediana, "n_alvos": k}}.

    Mesmos emissores, mesma janela, mesma semente para todos os candidatos: a
    unica coisa que muda entre as linhas e o modelo."""
    t0 = time.time()
    cands = estaticos.candidatos(dirbase)
    _passo(t0, f"juiz montado: {len(cands)} emissores parados")
    fora = {}
    for tag, mod in mods:
        L = estaticos.mede(dirbase, horas, mod=mod, cands=cands)
        _passo(t0, f"estaticos {tag}")
        if not L:
            continue
        fora[tag] = {"passeio": st.median(m["passeio_m_por_min"] for _, m, _, _ in L),
                     "desvio": st.median(m["desvio_xy"] for _, m, _, _ in L),
                     "n_alvos": len(L)}
    return fora

def julga_cyd(dirbase, mods, horas=3.0):
    """Juiz secundario: so existe quando o CYD esta anunciando. -> {tag: erro_medio}."""
    v = loo.verdade_do_alvo()
    if v is None or not cyd_no_ar(dirbase):
        return {}
    t0 = time.time()
    sig = vivo.sightings(dirbase)      # 20 MB: le uma vez, julga todos em cima dela
    _passo(t0, f"{len(sig)} avistamentos do CYD lidos")
    fora = {}
    for tag, mod in mods:
        ts, E, _, _ = vivo.replay(dirbase, horas, mod=mod, sig=sig)
        _passo(t0, f"cyd {tag}")
        m = vivo.metricas(ts, E, v)
        if m:
            fora[tag] = m["erro_medio"]
    return fora

def escolhe(placar, erros=None):
    """Regra de promocao. Separada porque e a unica logica que decide producao.

    Ganha quem passear menos que o vigente por MARGEM. Se o CYD estiver no ar, um
    candidato que piore o erro contra a fita mais que VETO_ERRO_M nao passa, por
    melhor que seja no passeio."""
    if "vigente" not in placar:
        return None
    base = placar["vigente"]["passeio"]
    erros = erros or {}
    e0 = erros.get("vigente")
    aptos = [(v["passeio"], t) for t, v in placar.items()
             if t != "vigente" and v["passeio"] < base * MARGEM
             and (e0 is None or t not in erros or erros[t] <= e0 + VETO_ERRO_M)]
    return min(aptos)[1] if aptos else None

def promove(dirbase, tag, mod, placar, erros):
    A, n, W, rms = mod
    j = {"t": time.time(), "A": A, "n": n, "W": W, "rms": rms, "origem": tag}
    alvo = os.path.join(dirbase, vivo.MODELO_JSON)
    tmp = alvo + ".tmp"
    with open(tmp, "w") as f:
        json.dump(j, f)
    os.replace(tmp, alvo)                # o daemon le isto sem parar
    return j

def audita(dirbase, linha):
    with open(os.path.join(dirbase, AUDIT), "a") as f:
        f.write(json.dumps(linha) + "\n")

def slots(dirbase):
    """Erro do CYD por faixa de hora, do historico do daemon. Relatorio, NUNCA
    criterio de promocao: cada hora tem uma populacao BLE diferente e o corte
    confunde modelo com transito de radio."""
    v = loo.verdade_do_alvo()
    b = collections.defaultdict(list)
    caminho = os.path.join(dirbase, "vivo_hist.jsonl")
    if v is None or not os.path.exists(caminho):
        return []
    for l in open(caminho):
        try:
            d = json.loads(l)
        except ValueError:
            continue
        b[time.localtime(d["t"]).tm_hour].append(d)
    out = []
    for h in sorted(b):
        e = sorted(float(np.hypot(d["x"] - v[0], d["y"] - v[1])) for d in b[h])
        f = lambda k: st.median([d[k] for d in b[h] if d.get(k) is not None])
        out.append((h, len(e), st.median(e), e[int(0.9 * (len(e) - 1))],
                    f("p_parado"), f("ess")))
    return out

def demo():
    """Auto-teste da regra de promocao e do ida-e-volta do modelo.json."""
    p = {"vigente": {"passeio": 10.0}, "a": {"passeio": 9.9}, "b": {"passeio": 8.0}}
    assert escolhe(p) == "b", escolhe(p)                  # 1% nao paga a troca
    assert escolhe({"vigente": {"passeio": 10.0}, "a": {"passeio": 9.9}}) is None
    # veto: ganha no passeio, mas piora o erro contra a fita
    assert escolhe(p, {"vigente": 1.00, "b": 1.30}) is None
    assert escolhe(p, {"vigente": 1.00, "b": 1.02}) == "b"
    assert escolhe({}) is None                            # sem vigente nao ha o que bater
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        promove(d, "teste", (-70.0, 2.5, 3.0, 1.2), {}, {})
        assert vivo.modelo_vigente(d)[:3] == (-70.0, 2.5, 3.0)
    print("revisao ok (margem, veto do CYD e modelo.json de ida e volta)")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1]
    horas = float(sys.argv[sys.argv.index("--horas") + 1]) if "--horas" in sys.argv else 3.0

    if "--slots" in sys.argv:
        print(" h      n  erro_med   p90  P(parado)   ESS")
        for h, n, med, p90, pp, ess in slots(base):
            print(f"{h:02d}  {n:5d}  {med:8.2f} {p90:5.2f}  {pp:8.0%} {ess:5.0%}")
        sys.exit(0)

    mods = candidatos(base)
    placar = julga(base, mods, horas)
    erros = julga_cyd(base, mods, horas)
    d = dict(mods)

    print(f"juiz: {placar.get('vigente', {}).get('n_alvos', 0)} emissores parados, "
          f"{horas:g} h" + ("  |  CYD no ar (veto por erro ativo)" if erros
                            else "  |  CYD fora do ar (sniffer BLE): sem veto"))
    print(f"\n{'modelo':<12} {'A':>7} {'n':>6} {'W':>6} {'RMS':>6} "
          f"{'passeio':>9} {'desvio':>7} {'erro CYD':>9}")
    for tag, (A, n, W, rms) in mods:
        v = placar.get(tag)
        if not v:
            continue
        print(f"{tag:<12} {A:7.1f} {n:6.2f} {W:6.1f} {rms:6.2f} "
              f"{v['passeio']:9.2f} {v['desvio']:7.2f} "
              + (f"{erros[tag]:9.2f}" if tag in erros else f"{'-':>9}"))

    g = escolhe(placar, erros)
    linha = {"t": time.time(), "horas": horas, "placar": placar, "erros": erros,
             "modelos": {t: list(m) for t, m in mods}, "promovido": g,
             "cyd_no_ar": bool(erros)}
    if g and "--aplicar" in sys.argv:
        promove(base, g, d[g], placar, erros)
        print(f"\nPROMOVIDO: {g}  (passeio {placar[g]['passeio']:.2f} vs "
              f"{placar['vigente']['passeio']:.2f} do vigente)")
    elif g:
        print(f"\nvenceria: {g} — rode com --aplicar para promover")
        linha["promovido"] = None
    else:
        print("\nnada promovido: o vigente segue (empate perde)")
    audita(base, linha)
