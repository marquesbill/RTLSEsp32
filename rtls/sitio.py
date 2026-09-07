"""O SITIO: geometria, ancoras e radio, vindos de um JSON — fonte unica de verdade.

Todo o resto do repositorio (ajuste, filtro, campanha, figuras, firmware do alvo)
le o sitio daqui e so daqui. Trocar de ambiente e trocar um arquivo JSON; nenhuma
linha de Python muda. Era exatamente o contrario no projeto de origem, onde a
planta era codigo, e por isso o codigo nao saia de um lugar so.

  export RTLS_SITIO=sitios/meu_lugar.json     # default: sitios/exemplo.json
  python3 -m rtls.sitio                       # auto-teste + resumo do sitio

CONVENCAO (a mesma do JSON, repetida aqui porque erro de sinal em y e o bug mais
caro deste projeto): metros, origem no canto superior esquerdo do desenho, x para
a direita, y para BAIXO, z do chao para o teto. Quem desenha planta em CAD costuma
usar y para cima; se voce importar dai, espelhe ANTES de gravar o JSON.

MODELO DE PAREDE: um comodo e um poligono e cada aresta e um segmento de parede.
Uma parede INTERNA e aresta de DOIS comodos, entao emitir por poligono a conta
duas vezes e o ajuste devolve um W pela metade para compensar. Onde a contagem
dobrada e uniforme isso se cancela; onde nao e, nao — no projeto de origem um
enlace que rasava dois batentes contava 6 paredes em vez de 2 e o previsto errava
21 dB para MENOS. Por isso `paredes()` faz UNIAO dos intervalos colineares antes
de emitir, e so depois subtrai o vao das portas.

Espessura de parede ignorada de proposito: ~10 cm contra um sigma de sombreamento
de 3-4 dB (que a 2 m ja vale ~60 cm de incerteza de distancia) e ruido. Se o seu
sitio tiver parede grossa ou classes diferentes, use `classes_parede` — ver
docs/matematica/01-propagacao.md.
"""
import json, sys, os
import numpy as np

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PADRAO = os.path.join(AQUI, "sitios", "exemplo.json")


def carrega(caminho=None):
    """Le o JSON e publica os nomes de modulo. Chamado no import; chame de novo
    para trocar de sitio dentro do mesmo processo (os testes fazem isso)."""
    global D, NOME, COMODOS, PORTAS, JANELAS, ANCORAS, ESCOLHIDAS, INSTALADO, TOMADA, POSTOS
    global X_MIN, X_MAX, Y_MIN, Y_MAX, Z_MAX, RECUO, EMISSORES, RADIO, CLASSES, CLASSE_PADRAO
    global CAMINHO
    caminho = caminho or os.environ.get("RTLS_SITIO") or PADRAO
    D = json.load(open(caminho))
    CAMINHO = caminho
    NOME = D["nome"]
    COMODOS = {k: [tuple(p) for p in v] for k, v in D["comodos"].items()}
    PORTAS = {k: (v[0], float(v[1]), float(v[2]), float(v[3])) for k, v in D.get("portas", {}).items()}
    JANELAS = {k: (tuple(v[0]), tuple(v[1])) for k, v in D.get("janelas", {}).items()}
    ANCORAS = {k: tuple(v["pos"]) for k, v in D["ancoras"].items()}
    # ESCOLHIDAS = as que tem radio instalado, na ordem do numero de radio. As
    # outras ficam no JSON como posicao candidata (util para planejar expansao).
    com_radio = {k: v["radio"] for k, v in D["ancoras"].items() if v.get("radio") is not None}
    ESCOLHIDAS = sorted(com_radio, key=lambda k: com_radio[k])
    INSTALADO = dict(com_radio)          # tag -> numero do radio (o que vai no JSONL)
    TOMADA = {v: k for k, v in INSTALADO.items()}
    (X_MIN, X_MAX) = D["limites"]["x"]
    (Y_MIN, Y_MAX) = D["limites"]["y"]
    Z_MAX = D["limites"].get("z", [0, 2.6])[1]
    RECUO = D.get("recuo", 0.05)
    EMISSORES = {k: tuple(v["pos"]) for k, v in D.get("emissores_fixos", {}).items()}
    # POSTOS: posicao conhecida por OPORTUNIDADE (alvo no cabo USB). Chaves com
    # "_" sao nota do JSON, nao posto. Sitio sem a secao devolve {} e todo o
    # caminho de oportunidade fica inerte — nao e obrigatorio para nada.
    POSTOS = {k: {"pos": tuple(v["pos"]), "raio": float(v.get("raio", 0.8)),
                  "hosts": tuple(v.get("hosts", ()))}
              for k, v in D.get("postos", {}).items() if not k.startswith("_")}
    RADIO = D.get("radio", {})
    CLASSES = D.get("classes_parede", {})
    CLASSE_PADRAO = D.get("classe_padrao", "alvenaria")
    return D


def paredes():
    """-> segmentos (M,2,2) com os vaos de porta ja abertos. Ver o cabecalho."""
    cortes, linhas = {}, {}
    for eixo, pos, a, b in PORTAS.values():
        cortes.setdefault((eixo, round(pos, 3)), []).append((a, b))
    for poly in COMODOS.values():
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
            eixo = "x" if x0 == x1 else "y"
            pos = x0 if eixo == "x" else y0
            t0, t1 = (min(y0, y1), max(y0, y1)) if eixo == "x" else (min(x0, x1), max(x0, x1))
            linhas.setdefault((eixo, round(pos, 3)), []).append((t0, t1))
    segs = []
    for (eixo, pos), iv in linhas.items():
        pedacos = []
        for c, d in sorted(iv):                     # uniao: colineares viram um
            if pedacos and c <= pedacos[-1][1] + 1e-9:
                pedacos[-1] = (pedacos[-1][0], max(pedacos[-1][1], d))
            else:
                pedacos.append((c, d))
        for a, b in cortes.get((eixo, pos), []):    # subtrai o vao de porta
            novos = []
            for c, d in pedacos:
                if b <= c or a >= d:
                    novos.append((c, d))
                else:
                    if c < a: novos.append((c, a))
                    if b < d: novos.append((b, d))
            pedacos = novos
        for c, d in pedacos:
            if d - c < 0.02:                        # sobra de subtracao, nao e parede
                continue
            segs.append([[pos, c], [pos, d]] if eixo == "x" else [[c, pos], [d, pos]])
    return np.array(segs, float)


def floorplan():
    from rtls.tracker import Floorplan
    return Floorplan(paredes(), (X_MIN, Y_MIN, X_MAX, Y_MAX), rooms=COMODOS)


def ancoras(quais=None):
    return {k: ANCORAS[k] for k in (quais or ESCOLHIDAS)}


def comodo_de(p):
    """-> nome do comodo que contem (x,y), ou None."""
    for nome, poly in COMODOS.items():
        if dentro_poly(p[:2], poly):
            return nome
    return None


def dentro_poly(p, poly):
    """Ponto em poligono por lancamento de raio (escalar; o vetorizado esta no tracker)."""
    x, y = p[0], p[1]; d = False; j = len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-30) + xi:
            d = not d
        j = i
    return d


def area(poly):
    x = np.array([q[0] for q in poly]); y = np.array([q[1] for q in poly])
    return abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2


def valida():
    """Checagens que pegam o erro de digitacao antes de ele virar 20 dB de residuo.

    Nao valida se o sitio bate com o mundo — isso so a medida faz. Valida se o
    JSON e consistente consigo mesmo e com a fisica minima.
    """
    erros = []
    for k, poly in COMODOS.items():
        if len(poly) < 4:
            erros.append(f"comodo {k}: {len(poly)} vertices")
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
            if x0 != x1 and y0 != y1:
                erros.append(f"comodo {k}: aresta ({x0},{y0})-({x1},{y1}) nao e ortogonal — "
                             "paredes() so trata poligono retilineo")
        if area(poly) < 0.5:
            erros.append(f"comodo {k}: area {area(poly):.2f} m2")
    for k, (x, y, z) in ANCORAS.items():
        if not (X_MIN - 0.2 <= x <= X_MAX + 0.2 and Y_MIN - 0.2 <= y <= Y_MAX + 0.2):
            erros.append(f"ancora {k} fora dos limites: ({x},{y})")
        if not 0 <= z <= Z_MAX:
            erros.append(f"ancora {k}: z={z} fora de [0,{Z_MAX}]")
        if k in ESCOLHIDAS and comodo_de((x, y)) is None:
            erros.append(f"ancora {k} nao esta dentro de nenhum comodo — "
                         f"aumente o recuo (hoje {RECUO} m) para tirar ela de cima da parede")
    if len(set(INSTALADO.values())) != len(INSTALADO):
        erros.append(f"numero de radio repetido: {INSTALADO}")
    for nome, ((x0, y0), (x1, y1)) in JANELAS.items():   # janela e parede EXTERNA
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        for d in (0.25, -0.25):
            fora = (mx + d, my) if x0 == x1 else (mx, my + d)
            if comodo_de(fora) is None:
                break
        else:
            erros.append(f"janela {nome} tem comodo dos dois lados — nao e parede externa")
    for eixo, pos, a, b in PORTAS.values():
        if b <= a:
            erros.append(f"porta com vao invertido: {eixo}={pos} [{a},{b}]")
    return erros


def resumo():
    a = {k: area(v) for k, v in COMODOS.items()}
    fp = floorplan()
    d = [float(np.linalg.norm(np.array(ANCORAS[u]) - np.array(ANCORAS[v])))
         for i, u in enumerate(ESCOLHIDAS) for v in ESCOLHIDAS[i + 1:]]
    return (f"{NOME}: {sum(a.values()):.1f} m2 em {len(a)} comodos | "
            f"{len(fp.walls)} segmentos de parede, {len(PORTAS)} vaos | "
            f"{len(ESCOLHIDAS)} ancoras, {len(d)} pares de {min(d):.2f} a {max(d):.2f} m "
            f"(mediana {np.median(d):.2f})")


def demo():
    """Auto-teste do formato, SEMPRE no sitio de exemplo — as coordenadas de porta
    e de parede abaixo sao dele. Restaura o sitio de quem chamou no fim: sem isso,
    rodar este demo dentro da suite trocaria o sitio dos modulos seguintes."""
    de_volta = CAMINHO
    carrega(PADRAO)
    assert not valida(), valida()
    fp = floorplan()
    assert len(fp.walls) > 4 and fp.rooms
    # a porta tem de deixar passar e a parede tem de barrar — os dois sentidos do
    # mesmo teste, porque so o primeiro passa com paredes() devolvendo lista vazia
    assert not fp.blocked(np.array([[4.3, 1.6]]), np.array([[4.7, 1.6]]))[0], "porta fechada"
    assert fp.blocked(np.array([[4.3, 0.4]]), np.array([[4.7, 0.4]]))[0], "parede vazando"
    # numero de radio <-> tag tem de ser bijecao: e a chave do JSONL das ancoras
    assert TOMADA[INSTALADO[ESCOLHIDAS[0]]] == ESCOLHIDAS[0]
    # um sitio quebrado tem de ser REPROVADO, senao valida() nao esta olhando
    salvo = dict(ANCORAS); ANCORAS["A1"] = (99.0, 99.0, 1.0)
    assert valida(), "valida() aceitou ancora fora dos limites"
    ANCORAS.clear(); ANCORAS.update(salvo)
    print(resumo())
    carrega(de_volta)
    print("sitio ok")


carrega()

if __name__ == "__main__":
    # `python3 -m rtls.sitio [caminho.json]` -> auto-teste do formato + validacao do
    # SEU sitio. Sai 1 se o JSON for inconsistente: da para por na CI de quem usa.
    demo()
    if len(sys.argv) > 1:
        carrega(sys.argv[1])
    print()
    print(resumo())
    erros = valida()
    for e in erros:
        print("  ERRO:", e)
    sys.exit(1 if erros else 0)
