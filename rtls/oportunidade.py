"""Ancora de oportunidade: o alvo no cabo USB e uma posicao conhecida, de graca.

Quando o alvo esta plugado no USB de um host, ele esta na mesa daquele host — os
cabos sao curtos. Isso vale por horas seguidas (a noite inteira, uma tarde de
trabalho em outro projeto) e nao custa NADA: nenhuma caminhada, nenhum toque na
tela, nenhum rotulo digitado. E dado rotulado que aparece sozinho.

O ganho nao e "mais um ponto de campanha". Um ponto so, por melhor amostrado que
seja, nao mede A/n/W melhor do que 14 pontos espalhados — a informacao de Fisher
de um ponto fixo e degenerada na direcao da distancia. O ganho e OUTRO:

    com a posicao TRAVADA, tudo que sobra no residuo e tempo.

E o unico instrumento que separa deriva temporal de deriva de posicao sem
confundir as duas. Sem ele, um enlace que caiu 3 dB e ambiguo (o alvo andou? o
canal mudou?); com o alvo no cabo, so pode ser o canal. Por isso este modulo
existe antes de `rtls/modelo/temporal.py` e alimenta ele.

## A decomposicao que faz tudo funcionar

Seja `y` o vetor de RSSI que as N ancoras ouviram do farol do alvo num bloco.
Decomponho em duas partes ortogonais:

    nivel(y)      = media(y) - ptx        <- MODO COMUM: tempo, potencia, ganho
                                             do farol, ocupacao do espectro
    assinatura(y) = y - media(y)          <- FORMA: geometria. So posicao.

A separacao nao e heuristica: somar uma constante a todas as ancoras (que e
exatamente o que uma mudanca de ptx, de temperatura do oscilador ou de piso de
ruido faz) move `nivel` e deixa `assinatura` IDENTICA. Mudar o alvo de lugar
move `assinatura`. Sao os dois autoespacos do projetor `I - 11^T/N`.

Disso sai a checagem que torna o rotulo gratuito confiavel:

## "Plugado" nao PROVA "na mesa", e o codigo nao finge que prova

O alvo pode estar plugado num cabo de 2 m e ter sido levado para o sofa. Um
rotulo errado e pior que rotulo nenhum — entra no ajuste com peso de verdade.
Entao cada bloco e conferido, e a conferencia NAO usa o modelo:

    comparo a assinatura de cada bloco com a MEDIANA das assinaturas dos outros
    blocos do mesmo posto, em unidades de MAD.

E model-free de proposito. Validar o rotulo com o proprio A/n/W que o rotulo vai
ajudar a estimar e o erro classico de deixar a metrica validar o proprio ajuste
(CLAUDE.md). Aqui o unico pressuposto e "o mesmo lugar da a mesma forma", que e
verificavel contra os proprios dados e falseavel: se as assinaturas nao se
agruparem, a premissa esta errada e o modulo diz isso em vez de inventar.

E como a checagem mora na assinatura, ela e CEGA a deriva temporal — que e
justamente o sinal que queremos medir. Rejeitar um bloco por ele ter sido
gravado numa hora barulhenta seria jogar fora o dado por ter a propriedade que
buscamos. Ver a parte (3) do demo().

## Formato

`presenca.jsonl`, escrito por `ferramentas/vigia_usb.py` no host:

    {"host": "linux", "ev": "ini", "t": 1757200000.0}
    {"host": "linux", "ev": "fim", "t": 1757228800.0}

`refcyd.jsonl`, que o `rtls.receptor` ja grava hoje sem alteracao nenhuma:

    {"rx": 3, "ptx": -6, "r": -61, "seq": 918, "t": 1757200145.2}
"""
import json, os
import numpy as np
import rtls.sitio as P

PRESENCA = "presenca.jsonl"
REF = "refcyd.jsonl"
BLOCO = 300.0        # s por bloco. 5 min: longo p/ mediana, curto p/ ver a hora.
MIN_POR_ANCORA = 5   # avistamentos minimos p/ a mediana do bloco valer
CORTE_MAD = 3.5      # |desvio|/MAD acima disto = bloco de outro lugar.
# O corte e deliberadamente APERTADO porque os custos sao assimetricos. Rejeitar
# um bloco bom joga fora 5 min de dado que nao custou nada e do qual ha centenas
# de horas. Aceitar um bloco ruim injeta um rotulo FALSO no ajuste, com peso de
# verdade. Entao 3.5 MAD (~0.05% por ancora sob normal, ~0.2% por bloco com 5
# ancoras) e o preco certo: MEDIDO no demo, ~1 falso positivo em 576 blocos.


def posto_do_host(host, postos=None):
    """-> nome do posto que este host representa, ou None.

    Um posto pode listar varios hosts (uma bancada com dois computadores); um
    host so pode estar em um posto, senao "plugado" nao determina lugar. A
    validacao cobra isso.
    """
    postos = P.POSTOS if postos is None else postos
    for nome, d in postos.items():
        if host in d["hosts"]:
            return nome
    return None


def valida(postos=None):
    """-> lista de problemas. Vazia = os postos deste sitio sao usaveis."""
    postos = P.POSTOS if postos is None else postos
    ruim, visto = [], {}
    for nome, d in postos.items():
        for h in d["hosts"]:
            if h in visto:
                ruim.append(f"host '{h}' em dois postos ({visto[h]} e {nome}): "
                            f"plugado deixa de determinar lugar")
            visto[h] = nome
        if not d["hosts"]:
            ruim.append(f"posto '{nome}' sem host: nunca sera detectado")
        if d["raio"] <= 0:
            ruim.append(f"posto '{nome}' com raio {d['raio']}: o raio E a incerteza")
        p = d["pos"]
        if not (P.X_MIN <= p[0] <= P.X_MAX and P.Y_MIN <= p[1] <= P.Y_MAX):
            ruim.append(f"posto '{nome}' em {p[:2]} esta fora dos limites do sitio")
    return ruim


def intervalos(dirbase):
    """presenca.jsonl -> [(t0, t1, host)]. 'ini' sem 'fim' e ignorado (sessao aberta)."""
    caminho = os.path.join(dirbase, PRESENCA)
    if not os.path.exists(caminho):
        return []
    aberto, out = {}, []
    for linha in open(caminho):
        try:
            j = json.loads(linha)
        except json.JSONDecodeError:
            continue                       # linha truncada por crash: pula, nao morre
        h, ev, t = j.get("host"), j.get("ev"), j.get("t")
        if h is None or t is None:
            continue
        if ev == "ini":
            aberto[h] = float(t)
        elif ev == "fim" and h in aberto:
            out.append((aberto.pop(h), float(t), h))
    return sorted(out)


def blocos(regs, ints, passo=BLOCO, minimo=MIN_POR_ANCORA, postos=None):
    """Avistamentos + intervalos -> blocos rotulados.

    regs: iteravel de {"t","rx","r","ptx"} (o refcyd.jsonl do receptor).
    -> [{"t","posto","host","ptx","rx":[...],"y":[...]}], y em dBm por ancora.

    A mediana dentro do bloco, e nao a media: o desvanecimento rapido joga picos
    de 10 dB e uma media anda atras deles.
    """
    balde = {}
    for r in regs:
        t = r.get("t")
        if t is None:
            continue
        for t0, t1, host in ints:
            if t0 <= t <= t1:
                po = posto_do_host(host, postos)
                if po is None:
                    break
                k = (int((t - t0) // passo), t0, po, host, r.get("ptx"))
                balde.setdefault(k, {}).setdefault(r["rx"], []).append(float(r["r"]))
                break
    out = []
    for (i, t0, po, host, ptx), porx in sorted(balde.items()):
        bons = {rx: float(np.median(v)) for rx, v in porx.items() if len(v) >= minimo}
        if len(bons) < 2:
            continue                       # com uma ancora so nao existe "forma"
        rx = sorted(bons)
        out.append({"t": t0 + (i + 0.5) * passo, "posto": po, "host": host,
                    "ptx": ptx, "rx": rx, "y": np.array([bons[k] for k in rx])})
    return out


def assinatura(y):
    """y - media(y): a parte do vetor que so a POSICAO explica.

    Projetor `I - 11^T/N`. Imune a qualquer coisa que suba ou desca todas as
    ancoras junto — potencia do farol, ganho do oscilador, piso de ruido, hora
    do dia. Soma zero por construcao, entao vive num espaco de N-1 dimensoes.
    """
    y = np.asarray(y, float)
    return y - y.mean()


def nivel(b):
    """media(y) - ptx: a parte que a POSICAO nao explica. E o que o tempo move.

    Subtrair ptx e obrigatorio, nao higiene: o firmware da campanha varre a
    potencia do farol em 8 degraus, e sem descontar isso a varredura vira uma
    "variacao temporal" de ate 20 dB que nao existe.
    """
    return float(np.mean(b["y"])) - (0.0 if b["ptx"] is None else float(b["ptx"]))


def coerentes(bs, corte=CORTE_MAD):
    """Separa os blocos que concordam com os demais do mesmo posto.

    -> (aceitos, [(bloco, escore, motivo)])

    Robusto dos dois lados: centro pela mediana e escala pela MAD, senao um unico
    bloco de outro lugar puxa o centro e passa a rejeitar os certos. 1.4826 e o
    fator que faz a MAD estimar sigma de uma normal.
    """
    ok, fora = [], []
    for po in sorted({b["posto"] for b in bs}):
        g = [b for b in bs if b["posto"] == po]
        # so comparo blocos com o MESMO conjunto de ancoras: a media de assinatura
        # e sobre as ancoras presentes, entao vetores de conjuntos diferentes nao
        # sao comparaveis. Ancora que ficou muda muda a media e falsearia a forma.
        for chave in sorted({tuple(b["rx"]) for b in g}):
            h = [b for b in g if tuple(b["rx"]) == chave]
            if len(h) < 4:
                # sem massa para dizer quem e o desviante, aceito e registro.
                ok.extend(h)
                continue
            A = np.array([assinatura(b["y"]) for b in h])
            med = np.median(A, axis=0)
            mad = 1.4826 * np.median(np.abs(A - med), axis=0)
            mad = np.maximum(mad, 0.5)     # piso: MAD zero faria todo mundo infinito
            esc = np.max(np.abs(A - med) / mad, axis=1)
            for b, e in zip(h, esc):
                if e <= corte:
                    ok.append(b)
                else:
                    fora.append((b, float(e), f"assinatura a {e:.1f} MAD do posto"))
    return ok, fora


def serie(bs):
    """Blocos aceitos -> (t, nivel) prontos para `rtls.modelo.temporal`.

    O nivel e centrado POR POSTO antes de juntar: postos diferentes tem geometria
    diferente e portanto niveis medios diferentes, e essa diferenca e espacial,
    nao temporal. Sem centrar, dois postos usados em horarios diferentes
    inventariam um ciclo diario que e so a troca de mesa.

    A mediana usa a serie inteira, inclusive dias que a validacao vai segurar
    fora. Isso e de proposito e nao vaza: a constante e o CALIBRE (`mu` do modelo
    temporal nao tem termo constante, entao nao ha o que ela possa entregar), e
    fixar calibre por dobra so acrescentaria variancia.
    """
    t, v = [], []
    for po in sorted({b["posto"] for b in bs}):
        g = [b for b in bs if b["posto"] == po]
        n = np.array([nivel(b) for b in g])
        t.extend(b["t"] for b in g)
        v.extend(n - np.median(n))
    o = np.argsort(t)
    return np.array(t)[o], np.array(v)[o]


# ------------------------------------------------------------------ demo
def _sintetico(semente=0, dias=6, drift=None, movidos=()):
    """Gera refcyd.jsonl sintetico do alvo parado num posto, com deriva no tempo."""
    rng = np.random.default_rng(semente)
    postos = P.POSTOS
    assert postos, "sitio sem postos"
    nome = sorted(postos)[0]
    pos = np.array(postos[nome]["pos"], float)
    anc = {n: np.array(P.ANCORAS[t], float) for t, n in P.INSTALADO.items()}
    host = postos[nome]["hosts"][0]
    A, n_exp = -45.0, 2.6
    def nivel_de(p):
        d = {k: max(float(np.linalg.norm(p - v)), 0.5) for k, v in anc.items()}
        return {k: A - 10 * n_exp * np.log10(x) for k, x in d.items()}
    regs, ints, movt, t0 = [], [], set(), 1_757_000_000.0
    for dia in range(dias):
        # uma sessao por noite: 22h -> 6h. E o caso real: fica plugado dormindo.
        ini = t0 + dia * 86400 + 22 * 3600
        fim = ini + 8 * 3600
        ints.append((ini, fim, host))
        for k in range(int((fim - ini) // BLOCO)):
            tb = ini + k * BLOCO + 30
            p = pos
            if (dia, k) in movidos:
                p = pos + np.array([2.5, 1.5, 0.0])
                movt.add(ini + (k + 0.5) * BLOCO)      # centro do bloco, p/ conferir
            mu = nivel_de(p)
            d = 0.0 if drift is None else drift(tb)
            for rx, m in mu.items():
                for _ in range(MIN_POR_ANCORA + 2):
                    regs.append({"t": tb + rng.uniform(0, 60), "rx": rx, "ptx": -6,
                                 "r": m + d - 6 + rng.normal(0, 1.2)})
    return regs, ints, nome, movt


def demo():
    print("=" * 78)
    print(f"ANCORA DE OPORTUNIDADE — {P.NOME}: {len(P.POSTOS)} posto(s)")
    ruins = valida()
    for r in ruins:
        print("   PROBLEMA:", r)
    assert not ruins, ruins
    for nome, d in sorted(P.POSTOS.items()):
        print(f"   {nome:14s} {d['pos']}  raio {d['raio']:.2f} m  hosts {list(d['hosts'])}")

    # (1) colheita: o rotulo aparece sozinho
    regs, ints, nome, _ = _sintetico()
    bs = blocos(regs, ints)
    horas = sum(t1 - t0 for t0, t1, _ in ints) / 3600
    print(f"\n1. COLHEITA — {len(ints)} sessoes, {horas:.0f} h no cabo -> {len(bs)} blocos"
          f" de {BLOCO:.0f}s, todos rotulados em '{nome}', custo humano zero")
    assert len(bs) > 50, len(bs)
    assert all(b["posto"] == nome for b in bs)

    # (2) a checagem pega o alvo que saiu da mesa
    movidos = {(1, 3), (1, 4), (4, 10)}
    regs2, ints2, _, movt = _sintetico(semente=1, movidos=movidos)
    bs2 = blocos(regs2, ints2)
    ok2, fora2 = coerentes(bs2)
    rej = {b["t"] for b, _, _ in fora2}
    fp = rej - movt
    print(f"\n2. FALSIFICACAO — {len(movt)} blocos gravados a 2,9 m da mesa,"
          f" em {len(bs2)}: pegou {len(movt & rej)}/{len(movt)},"
          f" {len(fp)} falso(s) positivo(s) ({100*len(fp)/len(bs2):.1f}%)")
    for b, e, m in sorted(fora2, key=lambda x: -x[1])[:3]:
        print(f"   rejeitado t={b['t']:.0f}  {m}"
              + ("" if b["t"] in movt else "   <- falso positivo (barato)"))
    # recall tem de ser 1: rotulo errado no ajuste e o que nao se pode aceitar.
    assert movt <= rej, sorted(movt - rej)
    # e o preco disso, em falso positivo, tem de ficar na casa do 1%.
    assert len(fp) <= 0.01 * len(bs2), (len(fp), len(bs2))

    # (3) e NAO pega uma deriva temporal. Esta e a parte que importa: se a
    # checagem confundisse tempo com lugar, ela jogaria fora exatamente o sinal
    # que o modelo temporal precisa medir.
    #
    # O invariante e forte: MESMA semente com e sem deriva tem de dar o MESMO
    # conjunto de rejeitados, bloco a bloco. Nao "quase o mesmo" — igual. Ficar
    # so em "rejeitou pouco" nao provaria nada: a taxa de falso positivo ja e
    # ~0,2%, e um teste frouxo passaria mesmo se a deriva estivesse vazando.
    forte = lambda t: 12.0 * np.sin(2 * np.pi * (t % 86400) / 86400)
    bs3 = blocos(*_sintetico(semente=2, drift=forte)[:2])
    bs0 = blocos(*_sintetico(semente=2)[:2])
    ok3, fora3 = coerentes(bs3)
    _, fora0 = coerentes(bs0)
    amp = np.ptp([nivel(b) for b in bs3])
    r3 = {b["t"] for b, _, _ in fora3}
    r0 = {b["t"] for b, _, _ in fora0}
    print(f"\n3. CEGUEIRA AO TEMPO — mesma mesa, nivel comum variando {amp:.1f} dB:"
          f" rejeitados com deriva {len(r3)}, sem deriva {len(r0)}, iguais: {r3 == r0}")
    assert r3 == r0, (sorted(r3 ^ r0))
    # 8 dB de um seno de 24 h com amplitude 12: as sessoes vao 22h->6h e cobrem
    # so um pedaco do ciclo. Nao e defeito do cenario, e o caso REAL — o cabo so
    # e usado em certas horas. E a razao de o modelo temporal usar Fourier e nao
    # 24 baldes de hora: baldes de horas nunca visitadas ficam vazios, uma base
    # continua ainda interpola. Ver docs/matematica/10-temporal.md.
    assert amp > 5.0, amp
    a_com = np.median([assinatura(b["y"]) for b in bs3], axis=0)
    a_sem = np.median([assinatura(b["y"]) for b in bs0], axis=0)
    dif = float(np.abs(a_com - a_sem).max())
    # zero EXATO, nao "pequeno": a deriva entra igual em todas as ancoras do
    # bloco e o projetor I-11^T/N a anula algebricamente. O teste vale por
    # confirmar que o caminho do codigo faz o que a algebra promete.
    print(f"   assinatura mediana mudou {dif:.3e} dB com {amp:.1f} dB de deriva")
    assert dif < 1e-9, dif

    t, v = serie(ok3)
    print(f"\n4. SAIDA -> rtls.modelo.temporal: {len(t)} pontos (t, nivel),"
          f" {(t.max()-t.min())/86400:.1f} dias")
    assert len(t) == len(ok3)
    return bs


if __name__ == "__main__":
    demo()
