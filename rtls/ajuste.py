"""Ajusta A, n e a perda por parede a partir da MALHA que ja esta no ar.

A sacada: n (expoente) e W (parede) sao propriedades do AMBIENTE, nao do radio.
Elas transferem do enlace C3->C3 para o enlace alvo->C3. So o A (intercepto) e
que nao transfere, porque embute o par de antenas — e as duas pontas da malha
tem a antena ceramica ruim da SuperMini.

Entao metade do V1 sai de graca, sem campanha nenhuma: 28 pares direcionais com
distancia e contagem de paredes conhecidas, medidos continuamente.

  python3 ajuste.py <dir do receptor> [janela_s]
"""
import json, os, sys, collections, statistics as st
import numpy as np
from rtls import sitio as P
from rtls.tracker import _ccw

def paredes_entre(a, b):
    """Quantos segmentos de parede o segmento reto a->b cruza (portas ja abertas).

    a e b sao ndarray (x, y) — _ccw indexa com [..., 1], entao tupla estoura com
    TypeError. Nenhum chamador passa tupla; nao vale um asarray por chamada.
    """
    fp = P.floorplan()
    return sum(1 for w in fp.walls
               if (_ccw(a, w[0], w[1]) != _ccw(b, w[0], w[1])) and
                  (_ccw(a, b, w[0]) != _ccw(a, b, w[1])))

def pontos(dirbase, janela=None):
    """-> lista de (d3d, n_paredes, rssi_mediano, sigma, n_amostras, rotulo)"""
    caminho = os.path.join(dirbase, "malha.jsonl")
    br = collections.defaultdict(list)
    t_max = 0.0
    for l in open(caminho):
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if "rx" not in d:
            continue
        t_max = max(t_max, d.get("t", 0))
        br[(str(d["rx"]), str(d["tx"]))].append((d.get("t", 0), d["r"]))
    out = []
    for (rx, tx), vs in br.items():
        # TOMADA tem chaves int; rx/tx chegam como str (e podem ser MAC nao mapeado)
        if not (rx.isdigit() and tx.isdigit()) or int(rx) not in P.TOMADA or int(tx) not in P.TOMADA:
            continue
        if janela:
            # tupla = janela absoluta (t0, t1); numero = janela final de N s
            ini, fim = janela if isinstance(janela, tuple) else (t_max - janela, t_max)
            vs = [(t, r) for t, r in vs if ini <= t <= fim]
        if len(vs) < 8:
            continue
        pa = np.array(P.ANCORAS[P.TOMADA[int(rx)]])
        pb = np.array(P.ANCORAS[P.TOMADA[int(tx)]])
        r = [v for _, v in vs]
        out.append((float(np.linalg.norm(pa - pb)), paredes_entre(pa[:2], pb[:2]),
                    st.median(r), st.pstdev(r), len(r), f"{rx}<-{tx}"))
    return out

def ajusta(pts):
    """Minimos quadrados em dB: rssi = A - 10 n log10(d) - W k."""
    d = np.array([p[0] for p in pts]); k = np.array([p[1] for p in pts], float)
    y = np.array([p[2] for p in pts], float)
    X = np.column_stack([np.ones(len(d)), -10 * np.log10(np.maximum(d, 0.5)), -k])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    return beta, float(np.sqrt(np.mean(res ** 2))), res

def ajusta_offset(pts, w_soma=100.0):
    """Como ajusta(), mais um offset por ancora:

        rssi = A - 10 n log10(d) - W k + b_rx + b_tx

    NAO USAR NO VIVO SEM RELER ISTO. Medido 2026-09-05 e REPROVADO na unica
    metrica que vale: o offset ajustado so na malha PIORA a posicao do alvo em
    5 cm na media (4 dos 5 blocos do giro pioram). O rms da malha cai de 4,77
    para 4,17 dB, mas cai por construcao — sao 6 parametros a mais; o rms do
    proprio ajuste nao valida o ajuste. E W vai a -0,7 dB: perda de parede
    negativa, impossivel. Sinal de que o b esta absorvendo caminho, nao antena.

    O teste externo que reprova: o b da malha nao bate com o vies por ancora
    medido pelo ALVO nos 4 giros (r = 0,27, n = 6). a1 e a mais fria do alvo
    (-8,7 dB) e neutra na malha (-0,0); a5 inverte o sinal. Se o vies fosse a
    antena da ancora — passiva e reciproca — teria de aparecer nos dois.

    O que ele e, entao: caminho. A malha entrega a prova sozinha — 2<->4 a
    6,13 m com 1 parede le -77 dB, mais quente que 3<->4 a 2,75 m. Nenhum
    offset de antena produz isso; um mapa de paredes errado produz. Enquanto
    o mapa nao for consertado, os 16,5 dB nao sao ajustaveis por ancora.

    Um b por ancora, nao um par TX/RX: a antena e reciproca e e ela que domina.
    Ele entra DUAS vezes num enlace da malha (as duas pontas sao ancoras) e UMA
    no enlace alvo->ancora, que e onde isto vai ser gasto.

    sum(b) = 0 e obrigatorio: sem a restricao b desliza contra A (somar c a todo
    b e tirar 2c de A da exatamente o mesmo ajuste, entao a matriz e singular).
    Entra como linha extra com peso w_soma.

    -> (A, n, W), {ancora: b}, rms, residuos
    """
    ids = sorted({q for p in pts for q in p[5].split("<-")})
    col = {a: i for i, a in enumerate(ids)}
    d = np.array([p[0] for p in pts]); k = np.array([p[1] for p in pts], float)
    y = np.array([p[2] for p in pts], float)
    B = np.zeros((len(pts), len(ids)))
    for i, p in enumerate(pts):
        rx, tx = p[5].split("<-")
        B[i, col[rx]] += 1.0
        B[i, col[tx]] += 1.0
    X = np.column_stack([np.ones(len(d)), -10 * np.log10(np.maximum(d, 0.5)), -k, B])
    lin = np.zeros(X.shape[1]); lin[3:] = w_soma          # sum(b) = 0
    beta, *_ = np.linalg.lstsq(np.vstack([X, lin]), np.append(y, 0.0), rcond=None)
    res = y - X @ beta
    return (tuple(beta[:3]), dict(zip(ids, beta[3:])),
            float(np.sqrt(np.mean(res ** 2))), res)

def demo():
    """Auto-teste: dado sintetico com A/n/W conhecidos tem de voltar."""
    A0, n0, W0 = -40.0, 2.5, 6.0
    rng = np.random.default_rng(0)
    d = rng.uniform(1.5, 8.0, 60); k = rng.integers(0, 3, 60)
    y = A0 - 10 * n0 * np.log10(d) - W0 * k + rng.normal(0, 1.0, 60)
    pts = [(d[i], int(k[i]), y[i], 1.0, 50, "") for i in range(60)]
    (A, n, W), rms, _ = ajusta(pts)
    assert abs(A - A0) < 2 and abs(n - n0) < 0.3 and abs(W - W0) < 1.5, (A, n, W)
    assert rms < 1.6, rms
    print(f"ajuste ok (recuperou A={A:.1f} n={n:.2f} W={W:.1f} de A={A0} n={n0} W={W0})")

    # malha sintetica com offset conhecido: 6 ancoras, 30 enlaces direcionais
    b0 = {"1": -8.0, "2": -2.0, "3": +1.0, "4": +7.0, "5": +3.0, "6": -1.0}
    ids = sorted(b0)
    pares = [(a, c) for a in ids for c in ids if a != c]
    d = rng.uniform(1.5, 8.0, len(pares)); k = rng.integers(0, 3, len(pares))
    pts = []
    for i, (rx, tx) in enumerate(pares):
        y = (A0 - 10 * n0 * np.log10(d[i]) - W0 * k[i] + b0[rx] + b0[tx]
             + rng.normal(0, 1.0))
        pts.append((d[i], int(k[i]), y, 1.0, 50, f"{rx}<-{tx}"))
    (A, n, W), b, rms, _ = ajusta_offset(pts)
    assert abs(sum(b.values())) < 0.1, b                       # restricao pegou
    for a in ids:
        assert abs(b[a] - b0[a]) < 1.0, (a, b[a], b0[a])
    assert abs(A - A0) < 2 and abs(n - n0) < 0.3 and abs(W - W0) < 1.5, (A, n, W)
    print("offset ok (recuperou " +
          " ".join(f"a{a}={b[a]:+.1f}/{b0[a]:+.1f}" for a in ids) + ")")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    jan = int(sys.argv[2]) if len(sys.argv) > 2 else None
    pts = pontos(base, jan)
    (A, n, W), rms, res = ajusta(pts)
    print(f"{len(pts)} enlaces direcionais\n")
    print(" enlace   d(m) par   rssi   sigma   n   residuo")
    for p, r in sorted(zip(pts, res), key=lambda x: x[0][0]):
        print(f"  {p[5]:6s} {p[0]:5.2f} {p[1]:3d} {p[2]:6.1f}  {p[3]:5.1f} {p[4]:4d}  {r:+6.1f}")
    print(f"\nA = {A:+.1f} dBm   n = {n:.2f}   parede = {W:.1f} dB/parede   RMS = {rms:.1f} dB")
    print(f"sigma tipico por enlace (mediana dos desvios): {st.median([p[3] for p in pts]):.1f} dB")
