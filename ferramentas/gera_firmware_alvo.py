"""Escreve firmware/alvo-cyd/src/sitio_gerado.h a partir do sitio + do desenho da campanha.

POR QUE ISTO EXISTE. O alvo (o CYD na mao de quem anda) desenha a planta na tela
e manda o rotulo por UDP no instante do toque. Para desenhar ele precisa da
geometria, e no projeto de origem essa geometria era uma COPIA A MAO dentro do
.cpp: um `Rect COMODOS[]` e um `Ponto PONTOS[]` com um comentario pedindo "se a
planta mudar, estes numeros TEM de vir junto". Promessa em comentario nao segura
nada — quando a planta muda e o firmware nao, o CYD rotula a campanha nova com
as coordenadas velhas e o rotulo continua chegando, so que errado. E o pior tipo
de erro: silencioso e a montante de tudo.

Aqui a copia deixa de existir. O .h e derivado do sitio; `confere()` regera em
memoria e compara byte a byte com o que esta em disco, entao a CI reprova a
divergencia sem precisar de placa.

O QUE ELE DECIDE SOZINHO (e o que voce pode forcar):

1. ESCALA E ORIENTACAO. A tela util e um retangulo de (PAN_X-4-MX) x (BT_Y-MY)
   px — estreito e alto. Um sitio largo e baixo cabe melhor girado 90 graus, e
   a escala em px/m e o que decide a precisao do toque. Escolhemos

       esc = max sobre t in {0,1} de  min( L_px / lado_x(t), A_px / lado_y(t) )

   com t=1 trocando os eixos, e o giro so entra se ganhar >5% de escala (girar
   confunde quem olha; so paga se pagar bem). O giro e SO no desenho: a
   coordenada que vai no rotulo continua sendo a do sitio.

2. SEPARACAO DOS PONTOS. Dois pontos a menos de 2*RAIO px na tela se cobrem e o
   toque nao consegue escolher entre eles. Isso vira uma restricao em METROS na
   busca D-otima: minsep = 2*RAIO/esc. Nao e cosmetica — e a condicao para o
   rotulo ser atribuivel ao ponto certo.

3. ALTURA. A malha e quase cega para z (as ancoras ficam todas em duas ou tres
   alturas), entao a campanha mede a curva da altura explicitamente: cada aba e
   UMA altura, e o primeiro ponto de cada aba e SEMPRE o mesmo (x,y). A
   diferenca entre esses tres avistamentos mede a altura sem passar pelo modelo
   — se for para parar a campanha no meio, sao esses os pontos a fazer. Ver
   docs/matematica/03-estimacao.md (bloco de altura) e 05-campanha-dotima.md.

USO
    python3 ferramentas/gera_firmware_alvo.py            # gera do sitio padrao
    RTLS_SITIO=sitios/meu.json python3 ferramentas/gera_firmware_alvo.py
    python3 ferramentas/gera_firmware_alvo.py --confere  # CI: regera e compara
    python3 ferramentas/gera_firmware_alvo.py --pontos meu_desenho.json
"""
import json, math, os, sys

import numpy as np

from rtls import sitio as P
from rtls.modelo import testes as T

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(AQUI, "firmware", "alvo-cyd", "src", "sitio_gerado.h")

# Tem de bater com campanha.cpp. Nao sao gosto: MX/MY sao margem, PAN_X e onde
# comeca o painel de texto (o texto precisa de ~106 px), BT_Y e o topo do botao
# grandao do rodape, RAIO e o circulo do ponto.
MX, MY, PAN_X, BT_Y, RAIO = 4, 30, 134, 258, 10
# DESVIO: quanto o ponto e empurrado em x para separar alturas iguais (ver px()).
# Entra na reserva de borda de escala(), nao so em px(): reservar so RAIO deixava o
# ponto da borda estourar a lateral por DESVIO px. So aparece em sitio LARGO, onde a
# planta girada encosta nos dois lados — o de exemplo, quadrado, nunca chegou la.
DESVIO = 9
BORDA = RAIO + DESVIO
ALTURAS = (0.05, 0.85, 1.65)     # chao / meio / acima da cabeca
POR_CM = 3                       # pontos por aba = 1 vertical fixa + 2 novos
MAX_ABAS = 5                     # AB_W = 240/(N_CM+1); abaixo de 40 px nao da o dedo


def escala(fp, pan_x=PAN_X):
    """-> (transposto, esc_px_por_m, u0, v0, mxp, myp). u,v sao os eixos DA TELA.

    O retangulo util e encolhido de RAIO em cada borda: o ponto na parede e
    legitimo, e o circulo dele tem de caber inteiro. O que sobra depois da
    escala e dividido nas duas bordas — planta centrada, nao encostada.
    """
    livre_x, livre_y = pan_x - 4 - MX - 2 * BORDA, BT_Y - MY - 2 * BORDA
    lx, ly = fp.xmax - fp.xmin, fp.ymax - fp.ymin
    reto = min(livre_x / lx, livre_y / ly)
    virado = min(livre_x / ly, livre_y / lx)
    gira = virado > 1.05 * reto                   # so gira se ganhar de verdade
    esc = math.floor((virado if gira else reto) * 2) / 2
    du, dv = (ly, lx) if gira else (lx, ly)
    mxp = MX + BORDA + int((livre_x - du * esc) / 2)
    myp = MY + BORDA + int((livre_y - dv * esc) / 2)
    return (gira, esc, fp.ymin, fp.xmin, mxp, myp) if gira else \
           (gira, esc, fp.xmin, fp.ymin, mxp, myp)


def desenho(k_por_altura=2, alturas=ALTURAS, minsep=0.6, semente=None):
    """-> [(nome, x, y, z)] na ordem das abas: uma altura por aba.

    Os (x,y) vem da busca D-otima do sitio (rtls.modelo.testes.campanha_dotima),
    que maximiza log det da informacao no bloco dos coeficientes de padrao. O
    primeiro (x,y) e a VERTICAL: repete-se em todas as abas.
    """
    n = 1 + k_por_altura * len(alturas)
    esc, _, _ = T.campanha_dotima(k=n, minsep=minsep)
    vert, resto = esc[0], list(esc[1:])
    pts, i = [], 0
    for z in alturas:
        pts.append((vert[0], vert[1], z))
        for _ in range(k_por_altura):
            x, y = resto[i]; i += 1
            pts.append((x, y, z))
    return [(str(j + 1), x, y, z) for j, (x, y, z) in enumerate(pts)]


def _mac(s):
    b = [int(p, 16) for p in s.replace("-", ":").split(":")]
    assert len(b) == 6, f"MAC invalido: {s}"
    return "{" + ",".join("0x%02X" % v for v in b) + "}"


def gera(pontos=None, por_cm=POR_CM, pan_x=PAN_X):
    """-> texto do .h. Levanta AssertionError se o desenho nao couber na tela."""
    fp = P.floorplan()
    virado, esc, u0, v0, mxp, myp = escala(fp, pan_x)
    if pontos is None:
        pontos = desenho(minsep=2.0 * RAIO / esc)
    n_cm = math.ceil(len(pontos) / por_cm)
    assert n_cm <= MAX_ABAS, (f"{len(pontos)} pontos em abas de {por_cm} dao {n_cm} abas; "
                              f"o maximo que cabe na faixa de 240 px e {MAX_ABAS}")

    ancoras = sorted(P.D["ancoras"].items(), key=lambda kv: kv[1].get("radio") or 0)
    ancoras = [(t, m) for t, m in ancoras if m.get("radio") is not None]
    macs = [m.get("mac") for _, m in ancoras]
    assert all(macs), "toda ancora com radio precisa de 'mac' no JSON do sitio"
    assert len(set(macs)) == len(macs), "MAC repetido entre ancoras"

    # px na tela, ja com o giro e com o desvio em x que separa alturas iguais
    def px(x, y, z=None):
        u = y if virado else x
        d = 0 if z is None else (-DESVIO if z > 1.2 else 0 if z > 0.4 else DESVIO)
        return max(RAIO + 2, mxp + int((u - u0) * esc) + d)

    def py(x, y):
        return myp + int(((x if virado else y) - v0) * esc)

    for nome, x, y, z in pontos:
        # Esta DENTRO do sitio? Com --pontos vindo de um arquivo escrito a mao, um
        # ponto fora e erro de digitacao — e um rotulo em coordenada que nao existe
        # entra no ajuste como dado bom. Nao da para deixar so o cheque de tela pegar
        # isto: a tela tem margem, e um ponto pouco fora do sitio ainda desenha.
        assert P.comodo_de((x, y)) is not None, f"ponto {nome} ({x:.2f},{y:.2f}) fora do sitio"
        a, b = px(x, y, z), py(x, y)             # cabe na tela?
        assert RAIO <= a <= pan_x - 4 - RAIO, f"ponto {nome} sai pela lateral (px={a})"
        assert MY + RAIO <= b <= BT_Y - RAIO, f"ponto {nome} bate no botao (py={b})"
    for t in range(n_cm):                           # se cobrem DENTRO da aba?
        aba = pontos[t * por_cm:(t + 1) * por_cm]
        for i, u in enumerate(aba):
            for w in aba[i + 1:]:
                d = math.hypot(px(*u[1:]) - px(*w[1:]), py(u[1], u[2]) - py(w[1], w[2]))
                assert d >= 2 * RAIO - 2, f"{u[0]} e {w[0]} se cobrem na tela ({d:.0f} px)"

    segs = P.paredes()
    eixo_u, eixo_v = ("y", "x") if virado else ("x", "y")
    L = []
    w = L.append
    w("// GERADO por ferramentas/gera_firmware_alvo.py — NAO EDITE A MAO.")
    w(f"// sitio: {P.NOME} ({sum(P.area(v) for v in P.COMODOS.values()):.1f} m2, {len(P.COMODOS)} comodos)")
    w("// Regenere depois de mexer no sitio ou na campanha; a CI compara byte a byte.")
    w("#pragma once")
    w("")
    w(f'#define SITIO_NOME "{P.NOME}"')
    w(f"#define N_ANC {len(ancoras)}")
    w("// MAC de fabrica do STA (esptool read_mac). Indice = numero instalado - 1:")
    w("// as N placas rodam o MESMO binario, quem da identidade e o MAC.")
    w("static const uint8_t MACS[N_ANC][6] = {")
    for (t, m), s in zip(ancoras, macs):
        w(f"  {_mac(s)},  // {m['radio']}  {t} @ {m.get('comodo', '?')}")
    w("};")
    w("static const float ANC[N_ANC][2] = {   // metros, sistema do sitio")
    for t, m in ancoras:
        w("  {%.2ff, %.2ff},  // %s" % (m["pos"][0], m["pos"][1], m["radio"]))
    w("};")
    w("")
    w("// Paredes com os vaos de porta JA abertos (rtls.sitio.paredes(): uniao por")
    w("// (eixo, posicao) antes de emitir — parede interna divide dois comodos e")
    w("// seria contada duas vezes se saisse poligono a poligono).")
    w("struct Seg { float x0, y0, x1, y1; };")
    w("static const Seg PAREDES[] = {")
    for (a, b), (c, d) in segs:
        w("  {%.2ff, %.2ff, %.2ff, %.2ff}," % (a, b, c, d))
    w("};")
    w("#define N_PAREDES (sizeof(PAREDES) / sizeof(PAREDES[0]))")
    w("")
    w("struct Ponto { const char *nome; float x, y, z; };")
    w(f"#define POR_CM {por_cm}")
    w("static const char *CMS[] = {" + ", ".join(
        '"%s"' % (f"{t * por_cm + 1}-{min((t + 1) * por_cm, len(pontos))}")
        for t in range(n_cm)) + "};")
    w("#define N_CM (sizeof(CMS) / sizeof(CMS[0]))")
    w("// Uma ALTURA por aba, e o 1o ponto de cada aba e sempre o mesmo (x,y):")
    w("// os tres juntos medem a altura sem passar pelo modelo.")
    w("static const Ponto PONTOS[] = {")
    for nome, x, y, z in pontos:
        w('  {"%s", %.2ff, %.2ff, %.2ff},' % (nome, x, y, z))
    w("};")
    w("#define N_PONTOS (sizeof(PONTOS) / sizeof(PONTOS[0]))")
    w("")
    w(f"// Tela 240x320 retrato. {'PLANTA GIRADA 90 GRAUS' if virado else 'planta sem giro'}: "
      f"o eixo {eixo_u} do sitio corre na horizontal da tela, o {eixo_v} na vertical.")
    w(f"// esc escolhida por ferramentas/gera_firmware_alvo.py:escala() — "
      f"{esc:.1f} px/m enche o retangulo util.")
    w(f"#define MX {MX}")
    w(f"#define MY {MY}")
    w(f"#define MXP {mxp}   // origem do desenho: MX + raio do ponto + centragem")
    w(f"#define MYP {myp}")
    w(f"#define ESC {esc:.1f}f")
    w(f"#define U0P {u0:.2f}f   // origem do eixo horizontal da tela = {eixo_u} minimo")
    w(f"#define V0P {v0:.2f}f   // origem do eixo vertical da tela  = {eixo_v} minimo")
    w(f"#define PAN_X {pan_x}")
    w(f"#define BT_Y {BT_Y}")
    w(f"#define RAIO_PX {RAIO}     // circulo do ponto; o desenho no C usa estes dois")
    w(f"#define DESVIO_PX {DESVIO}   // desvio em x que separa alturas no mesmo (x,y)")
    if virado:
        w("#define PLX(x, y) (MXP + (int)(((y) - U0P) * ESC))")
        w("#define PLY(x, y) (MYP + (int)(((x) - V0P) * ESC))")
    else:
        w("#define PLX(x, y) (MXP + (int)(((x) - U0P) * ESC))")
        w("#define PLY(x, y) (MYP + (int)(((y) - V0P) * ESC))")
    return "\n".join(L) + "\n"


def escreve(caminho=SAIDA, **kw):
    txt = gera(**kw)
    open(caminho, "w").write(txt)
    return txt


def confere(caminho=SAIDA, **kw):
    """O .h em disco e o que este sitio geraria? Diferiu = alguem mexeu na planta
    e nao regerou; o CYD rotularia a campanha nova com a geometria velha."""
    if not os.path.exists(caminho):
        raise AssertionError(f"{caminho} nao existe — rode sem --confere")
    # O .h versionado e do sitio versionado. Rodando com RTLS_SITIO apontando para
    # OUTRO sitio, "difere" e a resposta certa, nao uma falha: quem troca de sitio
    # regera o .h dele. Sem esta saida a suite inteira ficaria vermelha em sitio novo.
    if P.CAMINHO != P.PADRAO and caminho == SAIDA:
        print(f"confere pulado: {os.path.basename(P.CAMINHO)} nao e o sitio do .h versionado")
        return True
    disco, agora = open(caminho).read(), gera(**kw)
    if disco != agora:
        import difflib
        d = list(difflib.unified_diff(disco.splitlines(), agora.splitlines(),
                                      "em disco", "gerado agora", lineterm="", n=1))
        raise AssertionError(f"{caminho} esta desatualizado:\n" + "\n".join(d[:40]))
    return True


def demo():
    fp = P.floorplan()
    virado, esc = escala(fp)[:2]
    assert esc > 5, f"escala absurda: {esc}"
    pts = desenho(k_por_altura=2, minsep=2.0 * RAIO / esc)
    assert len(pts) == 9 and len({p[3] for p in pts}) == 3
    v = [p for p in pts if abs(p[1] - pts[0][1]) < 1e-9 and abs(p[2] - pts[0][2]) < 1e-9]
    assert len(v) == 3, "a vertical tem de aparecer nas 3 abas"
    txt = gera(pontos=pts)
    for k in ("MACS", "PAREDES", "PONTOS", "PLX", "ESC"):
        assert k in txt, k
    # o desenho fora do sitio TEM de ser recusado, senao o cheque nao vale nada
    fora = [("1", fp.xmax + 3.0, fp.ymin, 0.05)]
    try:
        gera(pontos=fora); raise SystemExit("gera() aceitou ponto fora da tela")
    except AssertionError:
        pass
    print(f"gera_firmware_alvo ok: {'girada' if virado else 'reta'}, {esc:.1f} px/m, "
          f"{len(pts)} pontos em {len(P.paredes())} paredes")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--demo" in a:
        demo()
    elif "--confere" in a:
        confere(); print(f"ok: {SAIDA} confere com {P.NOME}")
    else:
        pts = None
        if "--pontos" in a:
            j = json.load(open(a[a.index("--pontos") + 1]))["pontos"]
            pts = [(str(p.get("i", i + 1)), p["x"], p["y"], p.get("z", 1.0))
                   for i, p in enumerate(j)]
        escreve(pontos=pts)
        print(f"escrito {SAIDA}")
