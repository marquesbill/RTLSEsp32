"""Desenha a malha MEDIDA sobre a planta. E a GUI mais barata que resolve o
problema de hoje: ver de uma olhada quais enlaces existem e com que forca.

Nao mostra posicao de alvo DE PROPOSITO — sem o A/n do V1 o metro ainda nao vale,
e um painel que mostra numero que nao vale e pior que painel nenhum: cria
confianca onde nao ha. Entra quando V9 autorizar.

  python3 malha_viz.py <dir do receptor> <saida.svg> [janela_s]
"""
import json, os, sys, time, collections, statistics as st
import urllib.request
import numpy as np
from rtls import sitio as P
from rtls import ajuste

CORTE = -93.0            # piso operacional da C3 (PROPOSTA)
# MEDIDO com o CYD ciclando Ptx: perto do piso a mediana MENTE para cima, porque
# so os picos passam. Enlace a menos disto do piso esta censurado, nao atenuado.
CENSURA = 8.0
PISO_REAL = -101.0       # medido: o -93 da PROPOSTA e conservador
ESPECTRO = "http://127.0.0.1:8091/rows?since=0"   # nRF24 do T-Embed, 2400-2480 MHz
JANELA = 120             # s: so o passado recente; o jsonl cresce para sempre
CAUDA = 3 << 20          # le so os ultimos 3 MB — o arquivo vira GB num dia

T = {  # skin dark
    "bg": "#0f1216", "sala": "#181d24", "parede": "#5c6672", "txt": "#c9d1d9",
    # tons distintos por comodo: sem isso o fundo vira uma mancha so e nao da
    # para saber onde um enlace esta passando, que e metade do valor do painel
    "comodos": {"wc": "#1b232c", "circul.": "#151a20", "quarto": "#1a2027",
                "sala": "#171c23", "cozinha": "#1b2129"},
    "fraco": "#7d8590", "ap": "#f85149", "viva": "#e6edf3", "morta": "#f85149",
    "n": [(-70, "#3fb950"), (-85, "#d29922"), (CORTE, "#db6d28")], "ruim": "#f85149",
    "sem": "#30363d",
    # residuo contra o modelo ajustado: azul = melhor que o previsto, quente =
    # pior. E o que revela obstrucao — foi assim que a T4 atras do aparador
    # apareceu. O RSSI cru so repete o que a distancia ja dizia.
    "res": [(6, "#58a6ff"), (3, "#79c0ff"), (-3, "#3fb950"), (-6, "#d29922")],
    "res_ruim": "#f85149", "espectro": "#39424e", "marca": "#f0883e",
}

def le(dirbase, janela=JANELA):
    """-> pares {(rx,tx): [rssi]}, vistos, telemetria. Janela deslizante."""
    caminho = os.path.join(dirbase, "malha.jsonl")
    pares, vistos = collections.defaultdict(list), collections.Counter()
    corte_t = 0.0
    try:
        tam = os.path.getsize(caminho)
        with open(caminho, "rb") as fh:
            if tam > CAUDA:
                fh.seek(tam - CAUDA)
                fh.readline()            # descarta a linha partida
            bruto = fh.read().decode("utf8", "replace").splitlines()
    except OSError:
        bruto = []
    if bruto:
        for l in reversed(bruto):        # o t do fim manda; relogio do host
            try:
                corte_t = json.loads(l)["t"] - janela
                break
            except (ValueError, KeyError):
                continue
    for l in bruto:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if "rx" not in d or d.get("t", 0) < corte_t:
            continue
        pares[(str(d["rx"]), str(d["tx"]))].append(d["r"])
        vistos[str(d["tx"])] += 1
    try:
        tel = json.load(open(os.path.join(dirbase, "telemetria.json")))
    except (OSError, ValueError):
        tel = {}
    return pares, vistos, tel


def espectro(n=20):
    """Ocupacao de 2,4 GHz do nRF24 do T-Embed -> (f0, step, [media de hits]).

    O T-Embed ja varre 2400-2480 continuamente para o projeto de radio; aqui so
    consumimos. E o unico dado do sistema que mostra o AMBIENTE em que a malha
    vive, em vez do que a malha conseguiu apesar dele. Falha em silencio: o
    painel nao pode depender de outro projeto estar no ar.
    """
    try:
        with urllib.request.urlopen(ESPECTRO, timeout=3) as r:
            d = json.load(r)
        linhas = [x for x in d.get("rows", []) if x.get("radio") == "nrf"][-n:]
        if not linhas:
            return None
        ax = linhas[-1]["axis"]
        m = np.mean([x["data"] for x in linhas], axis=0)
        return ax["f0"], ax["step"], m, ax.get("max", 48)
    except Exception:
        return None

def cor(r):
    if r is None:
        return T["sem"]
    for lim, c in T["n"]:
        if r >= lim:
            return c
    return T["ruim"]


def cor_res(x):
    if x is None:
        return T["sem"]
    for lim, c in T["res"]:
        if x >= lim:
            return c
    return T["res_ruim"]

def modelo(pares):
    """Ajusta A/n/parede na propria janela -> (beta, {par: residuo})."""
    pts, chave = [], []
    for (rx, tx), vs in pares.items():
        if not (rx.isdigit() and tx.isdigit()):
            continue
        if int(rx) not in P.TOMADA or int(tx) not in P.TOMADA or len(vs) < 8:
            continue
        a = np.array(P.ANCORAS[P.TOMADA[int(rx)]]); b = np.array(P.ANCORAS[P.TOMADA[int(tx)]])
        pts.append((float(np.linalg.norm(a - b)), ajuste.paredes_entre(a[:2], b[:2]),
                    st.median(vs), 0, len(vs), ""))
        chave.append((rx, tx))
    if len(pts) < 5:
        return None, {}
    beta, _, res = ajuste.ajusta(pts)
    return beta, dict(zip(chave, res))


def svg(pares, vistos, tel, caminho, esc=105, mx=95, my=95, esp=None):
    my += max(0.0, -P.Y_MIN) * esc + 30
    X = lambda v: mx + v * esc
    Y = lambda v: my + v * esc
    W, H = X(P.X_MAX) + 430, Y(P.Y_MAX) + (150 if esp else 90)
    anc = {int(k): v for k, v in (tel.get("ancoras") or {}).items() if str(k).isdigit()}
    C = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" '
            f'width="{W:.0f}" height="{H:.0f}" '
         f'data-esc="{esc}" data-mx="{mx}" data-my="{my:.1f}" '
         f'font-family="Helvetica, Arial, sans-serif"><rect width="100%" height="100%" fill="{T["bg"]}"/>']
    idade = ("sem dados" if not tel else
             f'telemetria de {max(0, int(time.time() - tel.get("t", 0)))} s atras')
    C.append(f'<text x="{mx}" y="38" font-size="18" font-weight="bold" fill="{T["txt"]}">'
             f'Malha — janela de {JANELA} s</text>'
             f'<text x="{mx}" y="58" font-size="11.5" fill="{T["fraco"]}">{idade}</text>')
    for nome, poly in P.COMODOS.items():
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in poly)
        cx = sum(q[0] for q in poly) / len(poly); cy = sum(q[1] for q in poly) / len(poly)
        C.append(f'<polygon points="{pts}" fill="{T["comodos"].get(nome, T["sala"])}" stroke="none"/>'
                 f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" font-size="11" fill="#39424e" '
                 f'text-anchor="middle" letter-spacing="1.5">{nome.upper()}</text>')
    for w in P.paredes():
        C.append(f'<line x1="{X(w[0][0]):.1f}" y1="{Y(w[0][1]):.1f}" x2="{X(w[1][0]):.1f}" '
                 f'y2="{Y(w[1][1]):.1f}" stroke="{T["parede"]}" stroke-width="4"/>')
    beta, resid = modelo(pares)
    n_ok = n_cens = n_assim = 0
    for i, ta in enumerate(P.ESCOLHIDAS):
        for tb in P.ESCOLHIDAS[i + 1:]:
            a, b = str(P.INSTALADO[ta]), str(P.INSTALADO[tb])
            ida, volta = pares.get((a, b)), pares.get((b, a))
            vs = [st.median(x) for x in (ida, volta) if x]
            r = sum(vs) / len(vs) if vs else None
            n_ok += r is not None
            x1, y1, _ = P.ANCORAS[ta]; x2, y2, _ = P.ANCORAS[tb]
            dash = "" if (ida and volta) else ' stroke-dasharray="7 5"'
            # cor pelo RESIDUO; o RSSI cru vai no numero. Assimetria > 4 dB entre
            # os sentidos e obstrucao direcional, nao ruido: marca com traco duplo.
            rs = [resid.get((a, b)), resid.get((b, a))]
            rs = [q for q in rs if q is not None]
            res = sum(rs) / len(rs) if rs else None
            assim = abs(vs[0] - vs[1]) if len(vs) == 2 else 0.0
            cens = r is not None and r < PISO_REAL + CENSURA
            n_cens += cens; n_assim += assim > 4
            c = cor_res(res) if res is not None else cor(r)
            C.append(f'<line x1="{X(x1):.1f}" y1="{Y(y1):.1f}" x2="{X(x2):.1f}" y2="{Y(y2):.1f}" '
                     f'stroke="{c}" stroke-width="{3.0 if r is not None else 1.4}" '
                     f'opacity="{0.9 if r is not None else 0.45}"{dash}/>')
            if assim > 4:
                nx, ny = (y2 - y1), -(x2 - x1)
                m_ = (nx * nx + ny * ny) ** 0.5 or 1
                dx, dy = nx / m_ * 3.5, ny / m_ * 3.5
                C.append(f'<line x1="{X(x1)+dx:.1f}" y1="{Y(y1)+dy:.1f}" x2="{X(x2)+dx:.1f}" '
                         f'y2="{Y(y2)+dy:.1f}" stroke="{c}" stroke-width="1.6" opacity="0.7"/>')
            if r is not None:
                rot = f"{r:.0f}" + ("*" if cens else "")
                C.append(f'<text x="{X((x1+x2)/2):.1f}" y="{Y((y1+y2)/2)-4:.1f}" font-size="11.5" '
                         f'fill="{c}" text-anchor="middle" font-weight="bold">{rot}</text>')
    # Emissores fixos do sitio: nao sao ancoras, mas ocupam espaco e emitem — e o
    # que explica um residuo que a planta sozinha nao explica. Roteador vem redondo
    # (potencia alta, sempre no ar); o resto, quadrado.
    for nome, (ex, ey_, _) in P.EMISSORES.items():
        ap = P.D.get("emissores_fixos", {}).get(nome, {}).get("tipo") == "roteador"
        cr = T["ap"] if ap else "#a371f7"
        C.append(f'<circle cx="{X(ex):.1f}" cy="{Y(ey_):.1f}" r="7" fill="none" '
                 f'stroke="{cr}" stroke-width="2"/>' if ap else
                 f'<rect x="{X(ex)-5:.1f}" y="{Y(ey_)-5:.1f}" width="10" height="10" '
                 f'fill="none" stroke="{cr}" stroke-width="2"/>')
        C.append(f'<text x="{X(ex)+12:.1f}" y="{Y(ey_)+4:.1f}" font-size="10" '
                 f'fill="{cr}">{nome}</text>')
    for t in P.ESCOLHIDAS:
        n = P.INSTALADO[t]; x, y, z = P.ANCORAS[t]
        d = anc.get(n, {})
        viva = vistos.get(str(n), 0) > 0
        C.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="12" '
                 f'fill="{T["viva"] if viva else T["morta"]}"/>'
                 f'<text x="{X(x):.1f}" y="{Y(y)+4:.1f}" font-size="12" fill="{T["bg"]}" '
                 f'text-anchor="middle" font-weight="bold">{n}</text>'
                 f'<text x="{X(x)+17:.1f}" y="{Y(y)-11:.1f}" font-size="10.5" '
                 f'fill="{T["fraco"]}">{t} z={z:.2f}</text>')
        if d:
            rede = d.get("rede", 0)
            C.append(f'<text x="{X(x)+17:.1f}" y="{Y(y)+15:.1f}" font-size="10" fill="{T["fraco"]}">'
                     f'ap {d.get("rssi_ap", 0)}  b{d.get("boot", 0)}'
                     f'{"  rede-" + str(rede) if rede else ""}</text>')
    if esp:
        f0, step, dados, mx_hits = esp
        ey, eh, ew = Y(P.Y_MAX) + 46, 54, X(P.X_MAX) - mx
        C.append(f'<text x="{mx}" y="{ey-10:.0f}" font-size="11.5" fill="{T["txt"]}" '
                 f'font-weight="bold">Espectro 2,4 GHz (nRF24 do T-Embed) — ocupacao</text>')
        n_b = len(dados)
        for i, v in enumerate(dados):
            h = eh * min(1.0, v / max(mx_hits * 0.5, 1e-9))
            C.append(f'<rect x="{mx + i*ew/n_b:.1f}" y="{ey+eh-h:.1f}" width="{ew/n_b-0.6:.1f}" '
                     f'height="{h:.1f}" fill="{T["espectro"]}"/>')
        ap_ch = (tel.get("ancoras") or {}).get("1", {}).get("canal", 0)
        marcas = [(2402, "BLE 37"), (2426, "BLE 38"), (2480, "BLE 39")]
        if ap_ch:
            marcas.append((2407 + 5 * ap_ch, f"AP ch{ap_ch}"))
        for f, rot in marcas:
            px = mx + (f - f0) / step * ew / n_b
            C.append(f'<line x1="{px:.1f}" y1="{ey:.1f}" x2="{px:.1f}" y2="{ey+eh:.1f}" '
                     f'stroke="{T["marca"]}" stroke-width="1.2" stroke-dasharray="3 3"/>'
                     f'<text x="{px:.1f}" y="{ey+eh+13:.0f}" font-size="9.5" fill="{T["marca"]}" '
                     f'text-anchor="middle">{rot}</text>')
    lx, ly = X(P.X_MAX) + 34, 92
    n_par = len(P.ESCOLHIDAS) * (len(P.ESCOLHIDAS) - 1) // 2
    linhas = [(f"{n_ok}/{n_par} enlaces com dado", 1), ("", 0),
              ("COR = residuo contra o modelo,", 0),
              ("nao forca. Azul: melhor que o", 0),
              ("previsto. Quente: pior — e o que", 0),
              ("revela obstrucao.", 0),
              ("numero = RSSI medido", 0),
              (f"* = a menos de {CENSURA:.0f} dB do piso real", 0),
              (f"  ({PISO_REAL:.0f}): a mediana mente p/ cima", 0),
              ("traco duplo = assimetrico > 4 dB", 0),
              ("tracejado = so um sentido ouviu", 0), ("", 0)]
    if beta is not None:
        linhas += [("Modelo nesta janela", 1),
                   (f"A {beta[0]:+.1f} dBm   n {beta[1]:.2f}   parede {beta[2]:.1f} dB", 0),
                   (f"{n_cens} censurados · {n_assim} assimetricos", 0), ("", 0)]
    if tel:
        linhas += [("Receptor", 1), (f"malha {tel.get('malha', 0)} · ruins {tel.get('ruins', 0)}", 0), ("", 0)]
    linhas += [("Posicao de alvo", 1),
               ("O metro agora tem gabarito: aba", 0),
               ("Localizacao, cada ancora achada", 0),
               ("pelas outras 5. Alvo real (antena", 0),
               ("e altura diferentes) ainda nao.", 0)]
    for t_, forte in linhas:
        C.append(f'<text x="{lx:.0f}" y="{ly}" font-size="{13 if forte else 11.5}" '
                 f'{"font-weight=\"bold\"" if forte else ""} '
                 f'fill="{T["txt"] if forte else T["fraco"]}">{t_}</text>')
        ly += 19 if forte else 16
    C.append("</svg>")
    tmp = caminho + ".tmp"
    open(tmp, "w").write("\n".join(C))
    os.replace(tmp, caminho)      # atomico: o navegador nunca pega meio arquivo
    return n_ok

def demo():
    """Auto-teste sem servidor: janela recorta, cor respeita os limiares."""
    assert cor(None) == T["sem"] and cor(-60) == "#3fb950" and cor(-99) == T["ruim"]
    # residuo: azul quando melhor que o modelo, quente quando pior
    assert cor_res(8) == "#58a6ff" and cor_res(0) == "#3fb950" and cor_res(-9) == T["res_ruim"]
    assert cor_res(None) == T["sem"]
    assert cor(-93) == "#db6d28" and cor(-85) == "#d29922"
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "malha.jsonl"), "w") as fh:
        for t, r in ((1000.0, -60), (1100.0, -80), (1105.0, -90)):
            fh.write(json.dumps({"rx": "1", "tx": "3", "r": r, "t": t}) + "\n")
    pares, vistos, tel = le(d, janela=30)      # corte = 1105-30 = 1075
    assert pares[("1", "3")] == [-80, -90], pares      # o de t=1000 fica fora
    assert vistos["3"] == 2 and tel == {}
    n = svg(pares, vistos, {}, os.path.join(d, "x.svg"), esp=None)
    assert n == 1 and os.path.getsize(os.path.join(d, "x.svg")) > 1000
    t = open(os.path.join(d, "x.svg")).read()          # o painel le a transformada daqui
    assert 'data-esc="105"' in t and "data-mx=" in t and "data-my=" in t
    print("malha_viz ok")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else "malha.svg"
    if len(sys.argv) > 3:
        JANELA = int(sys.argv[3])
    p, v, tl = le(base, JANELA)   # explicito: sem isto o argv[3] mudava so o texto
    e = espectro()
    n = svg(p, v, tl, out, esp=e)
    n_par = len(P.ESCOLHIDAS) * (len(P.ESCOLHIDAS) - 1) // 2
    print(f"{out}: {n}/{n_par} enlaces, {sum(v.values())} registros na janela"
          + (f", espectro {len(e[2])} canais" if e else ", sem espectro"))
