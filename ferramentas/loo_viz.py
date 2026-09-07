"""Painel de LOCALIZACAO: desenha o leave-one-out sobre a planta.

Cada ancora e localizada pelas outras cinco, com o modelo reajustado sem ela.
E a unica medida de RTLS com gabarito que roda sozinha: as 6 posicoes sao
conhecidas com fita metrica.

Este arquivo desenha SO O MAPA. Numero nenhum vira texto aqui dentro: as
estatisticas saem em data-hud (JSON no <svg>) e quem escreve e o painel, em
HTML. Legenda de "como ler" nao existe mais — quem le ja sabe.

  python3 loo_viz.py <dir do receptor> <saida.svg> [janela_s]
"""
import json, os, sys, statistics as st
from rtls import sitio as P
from rtls import loo as L
from rtls import rotulos as R

# Duas janelas, porque sao duas perguntas. O LOO mede ancoras PARADAS com enlaces
# de malha fracos (o pior par troca ~1 pacote/s), entao 600 s e amostra, nao atraso.
# O alvo vivo ANDA e e ouvido ~10x/s: ali 600 s borraria a pessoa por um corredor
# inteiro, e 30 s ja da >=12 amostras na ancora mais surda.
JANELA = 600

# Viridis, puxado para o brilho porque o fundo e quase preto. Nao inventar cor
# fora da rampa — a unica excecao e o ALARME, magenta, escolhido justamente por
# NAO existir no viridis: valor ruim nao pode parecer valor da escala.
V = {"bg": "#04070c", "parede": "#3b528b", "rotulo": "#24404e",
     "comodos": {"wc": "#0a1119", "circul.": "#070c13", "quarto": "#0b1420",
                 "sala": "#091018", "cozinha": "#0a1220"},
     "anc": "#a0da39", "est": "#2ee6c8", "real": "#fde725",
     "ok": "#5ff2c4", "meio": "#fde725", "alarme": "#ff4fd8"}

def cor_erro(e):
    """1 m e o alvo, 2 m ja e outro movel. Acima disso sai da rampa de proposito."""
    return V["ok"] if e < 1.0 else (V["meio"] if e < 2.0 else V["alarme"])

def svg(linhas, caminho, janela, vivo=None, real=None, esc=105, mx=95, my=95):
    my += max(0.0, -P.Y_MIN) * esc + 30
    X = lambda v: mx + v * esc
    Y = lambda v: my + v * esc
    W, H = X(P.X_MAX) + 60, Y(P.Y_MAX) + 60
    hud = {"janela": janela, "real": real}
    # data-esc/mx/my: X(v) = mx + v*esc, Y(v) = my + v*esc. O painel le isto e
    # desenha nuvem, anel e disco do alvo a 2 Hz direto do vivo.json, sem esperar
    # os 30 s do laco nem reimplementar a planta em JavaScript.
    C = [None,      # o cabecalho entra no fim: data-hud so fecha depois das contas
         f'<rect width="100%" height="100%" fill="{V["bg"]}"/>']
    errs = [l[3] for l in linhas if l[3] is not None]
    acertos = sum(1 for l in linhas if l[5] and l[5][0] == L.comodo_de(P.ANCORAS[l[0]][:2]))
    for nome, poly in P.COMODOS.items():
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in poly)
        cx = sum(q[0] for q in poly)/len(poly); cy = sum(q[1] for q in poly)/len(poly)
        C.append(f'<polygon points="{pts}" fill="{V["comodos"].get(nome, V["comodos"]["sala"])}"/>'
                 f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" font-size="11" fill="{V["rotulo"]}" '
                 f'text-anchor="middle" letter-spacing="1.5">{nome.upper()}</text>')
    for w in P.paredes():
        C.append(f'<line x1="{X(w[0][0]):.1f}" y1="{Y(w[0][1]):.1f}" x2="{X(w[1][0]):.1f}" '
                 f'y2="{Y(w[1][1]):.1f}" stroke="{V["parede"]}" stroke-width="4"/>')
    # class li/an/di/anc: sao as caixas de selecao do painel. Ligar e desligar por
    # CSS numa classe alcanca de uma vez os 6 alvos do LOO e o alvo vivo; um grupo
    # por camada obrigaria a mover elemento de lugar a cada troca.
    for alvo, na, est, err, sp, top, A, n in linhas:
        x, y, _ = P.ANCORAS[alvo]
        num = P.INSTALADO[alvo]
        if est is not None:
            c = cor_erro(err)
            C.append(f'<line class="li" x1="{X(x):.1f}" y1="{Y(y):.1f}" x2="{X(est[0]):.1f}" '
                     f'y2="{Y(est[1]):.1f}" stroke="{c}" stroke-width="2" '
                     f'stroke-dasharray="5 4" opacity="0.9"/>'
                     f'<circle class="an" cx="{X(est[0]):.1f}" cy="{Y(est[1]):.1f}" '
                     f'r="{max(sp*esc,5):.1f}" fill="{c}" fill-opacity="0.10" stroke="{c}" '
                     f'stroke-width="1.6"/>'
                     f'<circle class="di" cx="{X(est[0]):.1f}" cy="{Y(est[1]):.1f}" r="3" fill="{c}"/>'
                     f'<text class="di" x="{X(est[0]):.1f}" y="{Y(est[1])-max(sp*esc,5)-6:.1f}" '
                     f'font-size="11.5" font-weight="bold" fill="{c}" text-anchor="middle">'
                     f'{err:.2f}</text>')
        C.append(f'<g class="anc"><circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="12" fill="{V["anc"]}"/>'
                 f'<text x="{X(x):.1f}" y="{Y(y)+4:.1f}" font-size="12" fill="{V["bg"]}" '
                 f'text-anchor="middle" font-weight="bold">{num}</text></g>')
    if vivo:
        est, sp, top, na, b, idade, verd, err, *saude = vivo
        if real:                      # o rotulo da campanha manda no alvo_verdade.json
            verd = (real["x"], real["y"])
            err = ((est[0]-verd[0])**2 + (est[1]-verd[1])**2) ** 0.5
        hud["vivo"] = {"x": est[0], "y": est[1], "sp": sp, "na": na, "b": b,
                       "idade": idade, "erro": err,
                       "comodo": top[0] if top else None,
                       "p_comodo": top[1] if top else None,
                       "p_parado": saude[0] if len(saude) > 0 else None,
                       "ess": saude[1] if len(saude) > 1 else None,
                       "cego": bool(saude[3]) if len(saude) > 3 else False}
        cv, cr = V["est"], V["real"]
        if verd is not None:
            C.append(f'<g id="real">'
                     f'<line class="li" x1="{X(verd[0]):.1f}" y1="{Y(verd[1]):.1f}" '
                     f'x2="{X(est[0]):.1f}" y2="{Y(est[1]):.1f}" stroke="{cr}" '
                     f'stroke-width="2" stroke-dasharray="5 4" opacity="0.9"/>'
                     f'<circle class="di" cx="{X(verd[0]):.1f}" cy="{Y(verd[1]):.1f}" r="7" '
                     f'fill="{cr}" stroke="{V["bg"]}" stroke-width="2"/></g>')
        # Estes tres grupos existem para o loo.svg avulso valer sozinho. No painel
        # eles ficam escondidos: la a camada viva vai para um <canvas>, onde a
        # nuvem pode acumular com composicao de verdade em vez de 300 <circle>.
        nuv = saude[2] if len(saude) > 2 else None
        pts = "".join(f'<circle cx="{X(q[0]):.1f}" cy="{Y(q[1]):.1f}" r="1.7"/>'
                      for q in (nuv or []))
        C.append(f'<g id="nuvem" class="nv" fill="{cv}" fill-opacity="0.35">{pts}</g>')
        C.append(f'<g id="alvo">'
                 f'<circle class="an" cx="{X(est[0]):.1f}" cy="{Y(est[1]):.1f}" '
                 f'r="{max(sp*esc,6):.1f}" fill="{cv}" fill-opacity="0.14" stroke="{cv}" '
                 f'stroke-width="2"/>'
                 f'<circle class="di" cx="{X(est[0]):.1f}" cy="{Y(est[1]):.1f}" r="5" fill="none" '
                 f'stroke="{cv}" stroke-width="2.5"/></g>')
    if errs:
        hud["loo"] = {"mediana": st.median(errs), "media": st.mean(errs),
                      "pior": max(errs), "n": len(errs), "de": len(linhas),
                      "acertos": acertos,
                      "ouvintes": " ".join(f"{P.INSTALADO[l[0]]}:{l[1]}" for l in linhas)}
    A = next((l[6] for l in linhas if l[6]), None)
    if A is not None:
        hud["modelo"] = {"A": A, "n": next(l[7] for l in linhas if l[6])}
    C[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" '
            f'width="{W:.0f}" height="{H:.0f}" '
            f'data-esc="{esc}" data-mx="{mx}" data-my="{my:.1f}" '
            f"data-hud='{json.dumps(hud)}' "
            f'font-family="Helvetica, Arial, sans-serif">')
    C.append("</svg>")
    tmp = caminho + ".tmp"
    open(tmp, "w").write("\n".join(C))
    os.replace(tmp, caminho)
    return len(errs)

def demo():
    """Auto-teste: SVG bem formado, um erro por alvo, e data-hud navegavel."""
    # ponytail: sem parser XML de proposito — o pyexpat do python@3.14 desta caixa
    # esta quebrado e o auto-teste tem de rodar tambem no servidor.
    import re, tempfile
    ls = [(a, 5, (1.0, 2.0), 0.9, 0.3, ("sala", 0.9), -72.0, 2.3) for a in P.ESCOLHIDAS]
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        p = f.name
    vv = ((1.5, 2.5), 0.4, ("sala", 0.8), 6, 2.3, 3.0, (2.0, 2.0, 0.75), 0.71)
    na = len(ls)                       # = quantas ancoras o sitio tem
    assert svg(ls, p, 600, vv) == na
    t = open(p).read()
    assert t.startswith("<svg") and t.rstrip().endswith("</svg>")
    assert t.count(">0.90<") == na
    assert t.count('stroke-dasharray="5 4"') == na + 1   # um por alvo + o alvo vivo
    assert "Como ler" not in t and "Ablacao" not in t     # legenda saiu para o HUD
    h = json.loads(re.search(r"data-hud='(.*?)' ", t).group(1))
    assert abs(h["loo"]["mediana"] - 0.9) < 1e-9 and h["modelo"]["A"] == -72.0
    assert abs(h["vivo"]["erro"] - 0.71) < 1e-9 and h["vivo"]["cego"] is False
    # rotulo da campanha vence o alvo_verdade.json: o gabarito passa a ser o ponto
    # que eu toquei no CYD, e o erro e recalculado contra ELE.
    assert svg(ls, p, 600, vv, real={"ponto": "7", "x": 1.5, "y": 3.5}) == na
    h = json.loads(re.search(r"data-hud='(.*?)' ", open(p).read()).group(1))
    assert abs(h["vivo"]["erro"] - 1.0) < 1e-9 and h["real"]["ponto"] == "7"
    # caminho cego (p_parado, ess, nuvem, cego) tem de chegar ao HUD
    assert svg(ls, p, 600, vv + (0.9, 0.5, [], True)) == na
    t = open(p).read()
    h = json.loads(re.search(r"data-hud='(.*?)' ", t).group(1))
    assert h["vivo"]["cego"] is True and h["vivo"]["ess"] == 0.5
    # o painel desenha em cima deste SVG: sem a transformada e sem as classes das
    # caixas de selecao ele nao tem onde nem como pintar, e a falha seria silenciosa.
    assert 'data-esc="105"' in t and "data-mx=" in t and "data-my=" in t
    assert t.count('id="nuvem"') == 1 and t.count('id="alvo"') == 1 and t.count('id="real"') == 1
    assert all(f'class="{c}"' in t for c in ("li", "an", "di", "anc", "nv"))
    os.unlink(p)
    print("loo_viz ok (svg valido, 6 alvos, hud json, rotulo vence gabarito)")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    saida = sys.argv[2] if len(sys.argv) > 2 else "loo.svg"
    jan = int(sys.argv[3]) if len(sys.argv) > 3 else JANELA
    print(svg(L.loo(base, jan), saida, jan, L.alvo_vivo(base), R.aberto(base)),
          "alvos ->", saida)
