"""Campanha: um emissor de Ptx conhecida em posicoes conhecidas.

Por que um emissor com Ptx COMANDAVEL e nao um telefone: a Ptx tem de ser
conhecida E ciclica. Com um emissor de Ptx desconhecida numa unica posicao o A
implicito variou 18,7 dB entre as seis ancoras — nao da para separar "A do
emissor" de "direcionalidade da antena". Variando a potencia num ponto fixo a
inclinacao tem de ser 1,00 por identidade (docs/matematica/02-censura.md §2.3);
o que sobra depois disso e do ambiente.

Os pontos NAO sao uma lista fixa: saem da busca D-otima do sitio carregado
(docs/matematica/05-campanha-dotima.md). Trocar de ambiente = trocar
RTLS_SITIO; nenhuma coordenada mora neste arquivo.

  python3 -m rtls.campanha folha saida.svg          # folha para imprimir/olhar
  python3 -m rtls.campanha medir <dir> pontos.json  # ajusta com as janelas anotadas
  python3 -m rtls.campanha --selftest
"""
import functools, json, sys, collections, statistics as st
import numpy as np
from rtls import sitio as P
from rtls import ajuste

Z_ALVO = 1.00   # altura padrao da campanha: mao/bolso, nao chao nem mesa
N_PONTOS = 5    # default da folha; a D-otima diz quando parar (§5.4)


@functools.lru_cache(maxsize=None)
def pontos(k=N_PONTOS, z=Z_ALVO, minsep=0.6):
    """-> [(nome, x, y, motivo)] D-otimos para o sitio carregado.

    lru_cache porque a busca gulosa custa segundos e a folha, o ajuste e o
    auto-teste pedem a MESMA lista — se cada um gerasse a sua, o rotulo "P3" da
    folha impressa nao seria o "P3" do ajuste.
    """
    from rtls.modelo import testes as T           # importado aqui: puxa scipy/numpy pesado
    esc, hist, _ = T.campanha_dotima(k=k, minsep=minsep)
    fora = []
    for i, (x, y) in enumerate(esc):
        ganho = hist[i + 1] - hist[i]
        com = P.comodo_de((x, y)) or "fora dos comodos"
        d = min(float(np.linalg.norm(np.array(P.ANCORAS[t]) - np.array((x, y, z))))
                for t in P.ESCOLHIDAS)
        fora.append((f"P{i+1}", float(x), float(y),
                     f"{com} — ancora mais proxima a {d:.2f} m; ganho D +{ganho:.2f}"))
    return fora


def folha(caminho, esc=105, mx=95, my=95, PONTOS=None):
    PONTOS = pontos() if PONTOS is None else PONTOS
    my += max(0.0, -P.Y_MIN) * esc + 30
    X = lambda v: mx + v * esc
    Y = lambda v: my + v * esc
    C = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {X(P.X_MAX)+430:.0f} '
         f'{Y(P.Y_MAX)+90:.0f}" font-family="Helvetica, Arial, sans-serif">'
         f'<rect width="100%" height="100%" fill="#fff"/>']
    C.append(f'<text x="{mx}" y="36" font-size="18" font-weight="bold">Campanha — {P.NOME}</text>'
             f'<text x="{mx}" y="56" font-size="12" fill="#555">3 min por ponto · metade afastado, '
             f'metade parado ao lado · anote as horas</text>')
    for nome, poly in P.COMODOS.items():
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in poly)
        C.append(f'<polygon points="{pts}" fill="#f6f6f4" stroke="none"/>')
    for w in P.paredes():
        C.append(f'<line x1="{X(w[0][0]):.1f}" y1="{Y(w[0][1]):.1f}" x2="{X(w[1][0]):.1f}" '
                 f'y2="{Y(w[1][1]):.1f}" stroke="#111" stroke-width="4"/>')
    for t in P.ESCOLHIDAS:
        x, y, _ = P.ANCORAS[t]
        C.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="9" fill="#111"/>'
                 f'<text x="{X(x):.1f}" y="{Y(y)+3.5:.1f}" font-size="10" fill="#fff" '
                 f'text-anchor="middle" font-weight="bold">{P.INSTALADO[t]}</text>')
    for i, (nome, x, y, _) in enumerate(PONTOS):
        C.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="15" fill="none" stroke="#c0392b" '
                 f'stroke-width="2.5"/><circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="#c0392b"/>'
                 f'<text x="{X(x):.1f}" y="{Y(y)-21:.1f}" font-size="13" fill="#c0392b" '
                 f'text-anchor="middle" font-weight="bold">{nome}</text>')
    lx, ly = X(P.X_MAX) + 34, 100
    linhas = [("Os cinco pontos", 1)]
    for nome, x, y, pq in PONTOS:
        linhas += [(f"{nome}  x={x:.2f}  y={y:.2f}  z={Z_ALVO:.2f}", 1)]
        linhas += [("   " + pq[i:i+42], 0) for i in range(0, len(pq), 42)]
    linhas += [("", 0), ("Como anotar", 1),
               ("Para cada ponto, tres horas:", 0),
               ("  inicio · virada · fim", 0),
               ("A virada e quando voce sai de perto", 0),
               ("(ou volta). A diferenca entre as duas", 0),
               ("metades MEDE o efeito do corpo, que e", 0),
               ("o que o V8 precisa e nao temos.", 0)]
    for t, forte in linhas:
        # fora da f-string por causa do piso 3.10; ver ferramentas/malha_viz.py
        peso = 'font-weight="bold"' if forte else ""
        cor = "#111" if forte else "#555"
        C.append(f'<text x="{lx:.0f}" y="{ly}" font-size="{12.5 if forte else 11.5}" '
                 f'{peso} fill="{cor}">{t}</text>')
        ly += 18 if forte else 15
    C.append("</svg>")
    open(caminho, "w").write("\n".join(C))
    return caminho

def janelas(dirbase, spec):
    """spec: [{"ponto":"1","de":<epoch>,"ate":<epoch>,"x":..,"y":..,"perto":bool}, ...]

    A posicao vem da JANELA quando ela traz x/y — a campanha da CYD numera 1..15
    e nao conhece os "P1".."P5" daqui. Sem x/y cai na lista fixa deste modulo."""
    L = [json.loads(l) for l in open(f"{dirbase}/refcyd.jsonl")]
    fixo = {n: (x, y, Z_ALVO) for n, x, y, _ in pontos()}
    out = collections.defaultdict(list)
    for d in L:
        for j in spec:
            if j["de"] <= d["t"] <= j["ate"]:
                p = ((j["x"], j["y"], j.get("z", Z_ALVO)) if "x" in j
                     else fixo[j["ponto"]])
                out[(j["ponto"], p, bool(j.get("perto")), d["rx"], d["ptx"])].append(d["r"])
    return out

def ajusta_campanha(agr, piso=-93.0, dmin=1.5):
    """Um ponto por (posicao, ancora, Ptx), com DOIS filtros que a primeira rodada
    mostrou serem obrigatorios:

    - piso -93: a menos de 8 dB do piso real (-101) so os picos passam e a mediana
      MENTE para cima. O -98 que usei antes deixava passar dados censurados.
    - dmin 1,5 m: abaixo disso e campo proximo e o log-distancia nao vale. O CYD a
      0,90 m da T1 deu residuo de +20 dB e puxava a curva inteira.

    Mesmo assim o ajuste NAO e estavel: variando os filtros, n foi de 2,19 a 4,36
    e A0 de -59,8 a -70,1. Ver residuo_por_par() para o porque."""
    pts = []
    for (pt, pos, perto, rx, ptx), vs in agr.items():
        rx = str(rx)          # o receptor grava int quando conhece o MAC, str quando nao
        if perto or len(vs) < 5 or not rx.isdigit() or int(rx) not in P.TOMADA:
            continue
        m = st.median(vs)
        if m < piso:
            continue
        a = np.array(P.ANCORAS[P.TOMADA[int(rx)]]); b = np.array(pos)
        d = float(np.linalg.norm(a - b))
        if d < dmin:
            continue
        k = ajuste.paredes_entre(a[:2], b[:2])
        pts.append((d, k, m - ptx, 0, len(vs), f"{pt}/{rx}/{ptx:+d}"))  # normaliza pela Ptx
    return pts, (ajuste.ajusta(pts) if len(pts) >= 6 else (None, None, None))

def residuo_por_par(pts, res):
    """Separa o residuo em ESTRUTURA (offset do par) e RUIDO (dentro do par).

    Cada par (posicao, ancora) foi medido com 8 potencias diferentes. Se o residuo
    fosse ruido, variaria entre os niveis. MEDIDO: offset medio 4,1 dB, variacao
    dentro do par 1,7 dB — 2,4x mais estrutura que ruido. Isso e a assinatura do
    local, reprodutivel, e e exatamente o que o log-distancia joga fora e o
    fingerprint usa.
    """
    g = collections.defaultdict(list)
    for p, x in zip(pts, res):
        g[p[5]].append(x)
    sis = [(k, float(np.mean(v)), float(np.std(v))) for k, v in g.items() if len(v) >= 4]
    estrutura = float(np.mean([abs(m) for _, m, _ in sis])) if sis else 0.0
    ruido = float(np.mean([s for _, _, s in sis])) if sis else 0.0
    return sorted(sis, key=lambda t: -abs(t[1])), estrutura, ruido


def demo():
    ps = pontos()
    assert len({p[0] for p in ps}) == N_PONTOS, ps
    for nome, x, y, _ in ps:                        # todo ponto dentro de um comodo
        assert P.comodo_de((x, y)), f"{nome} caiu fora dos comodos"
    ds = [float(np.linalg.norm(np.array(P.ANCORAS[t]) - np.array((x, y, Z_ALVO))))
          for t in P.ESCOLHIDAS for _, x, y, _ in ps]
    # a D-otima tem de gerar CONTRASTE: um ponto perto (ancora o A0) e um longe
    # (ancora o n). Se todos ficarem na mesma faixa de distancia, A0 e n ficam
    # correlacionados e o ajuste anda pela crista — ver 03-estimacao.md §3.1.
    assert min(ds) < 0.35 * max(ds), (min(ds), max(ds))
    # cache: a folha impressa e o ajuste tem de ver a MESMA lista
    assert pontos() is ps
    # o separador de estrutura/ruido tem de reconhecer offset constante como estrutura
    pts = [(2.0, 0, -80.0, 0, 30, "A/1")] * 4 + [(3.0, 0, -85.0, 0, 30, "B/2")] * 4
    sis, est, rui = residuo_por_par(pts, [5.0] * 4 + [-5.0, -5.2, -4.8, -5.0])
    assert est > 4.5 and rui < 0.5, (est, rui)
    # janela com x/y proprio nao depende da lista D-otima: nome "77" nao existe la
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "refcyd.jsonl"), "w") as f:
            f.write(json.dumps({"t": 50, "rx": "4", "ptx": 0, "r": -70.0}) + "\n")
        k = list(janelas(d, [{"ponto": "77", "de": 0, "ate": 100,
                              "x": 3.6, "y": 2.6, "z": 1.0}]))
        assert k == [("77", (3.6, 2.6, 1.0), False, "4", 0)], k
    print(f"campanha ok — {len(ps)} pontos D-otimos em '{P.NOME}', "
          f"distancias {min(ds):.2f} a {max(ds):.2f} m")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    if sys.argv[1] == "folha":
        print(folha(sys.argv[2]))
    else:
        agr = janelas(sys.argv[2], json.load(open(sys.argv[3])))
        pts, (beta, rms, res) = ajusta_campanha(agr)
        print(f"{len(pts)} pontos uteis")
        if beta is None:
            print("poucos pontos"); sys.exit(1)
        for p, r in sorted(zip(pts, res), key=lambda x: x[0][0]):
            print(f"  {p[5]:14s} d={p[0]:5.2f} par={p[1]} rssi-ptx={p[2]:7.1f}  res {r:+5.1f}")
        print(f"\nA0 (Ptx 0 dBm) = {beta[0]:+.1f} dBm   n = {beta[1]:.2f}   "
              f"parede = {beta[2]:.1f} dB   RMS = {rms:.1f} dB")
        sis, est, rui = residuo_por_par(pts, res)
        print(f"residuo: estrutura {est:.1f} dB  x  ruido {rui:.1f} dB  "
              f"({est/max(rui,1e-9):.1f}x mais estrutura)")
