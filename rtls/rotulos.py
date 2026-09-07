"""Receptor dos rotulos da campanha: o CYD manda, isto grava.

O CYD desenha a planta na tela, eu toco o ponto onde estou e aperto
INICIAR/FINALIZAR. Cada evento sai por broadcast UDP na hora (3 copias, porque
UDP cai) e o carimbo de tempo e o da CHEGADA aqui: o CYD nao tem relogio de
parede, e o refcyd.jsonl esta no relogio deste servidor. O atraso de LAN e de
milissegundos contra janelas de minutos.

  python3 rotulos.py <dir>            # escuta e grava rotulos.jsonl
  python3 rotulos.py <dir> --spec     # pares ini/fim -> pontos.json p/ campanha.py
  python3 rotulos.py --selftest

rotulos.jsonl e o que o CYD disse e nao se edita: o processo que escuta esta com
ele aberto em append a campanha inteira. Rotulo errado se conserta em
correcoes.jsonl, uma linha por janela, casada por (boot, seq):

  {"boot":58713,"seq":2,"ponto":"5","x":2.60,"y":3.60,"nota":"por que"}
  {"boot":58713,"seq":0,"descarta":true,"nota":"por que"}
"""
import json, os, socket, sys, time
import rtls.sitio as P

PORTA = 5009          # 5007 = avistamentos, 5008 = farol, 5009 = rotulo
ARQ = "rotulos.jsonl"
COR = "correcoes.jsonl"    # rotulo consertado a mao; ver o docstring do modulo

# Dedup por (boot, seq, ev) e nao so (seq, ev): g_rot reinicia em zero quando a
# CYD reinicia, e a campanha agora sao TRES sessoes. Sem o boot, a primeira
# janela depois de um reset sumiria em silencio, tratada como copia UDP.
def escuta(dirbase, porta=PORTA):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", porta))
    caminho = os.path.join(dirbase, ARQ)
    vistos = set()
    print(f"escutando UDP :{porta} -> {caminho}", flush=True)
    with open(caminho, "a") as f:
        while True:
            pkt, de = s.recvfrom(1024)
            try:
                j = json.loads(pkt.decode("utf8"))
                chave = (j.get("boot", 0), j["seq"], j["ev"])
            except Exception:
                continue                       # nao e nosso; o ar tem de tudo
            if chave in vistos:
                continue                       # as outras 2 copias
            vistos.add(chave)
            j["t"] = round(time.time(), 3)
            j["ip"] = de[0]
            f.write(json.dumps(j) + "\n")
            f.flush()                          # campanha longa, sem buffer pendurado
            print(f"  {j['ev']:3s} {j.get('cm','?'):3s} ponto {j['ponto']:>3s}  "
                  f"{j.get('ancoras','?')}/{len(P.ESCOLHIDAS)} ancoras", flush=True)

def correcoes(dirbase):
    """{(boot, seq): {...}} de correcoes.jsonl. Arquivo ausente = nenhuma."""
    caminho = os.path.join(dirbase, COR)
    if not os.path.exists(caminho):
        return {}
    c = {}
    for l in open(caminho):
        l = l.strip()
        if l and not l.startswith("#"):
            j = json.loads(l)
            c[(j["boot"], j["seq"])] = j
    return c

def spec(dirbase):
    """-> lista de janelas no formato que campanha.janelas() consome.

    Casa 'ini' e 'fim' por (boot, seq), que o firmware garante iguais nos dois
    eventos da MESMA janela — e nao pelo nome do ponto, que se repete quando o
    mesmo ponto e medido duas vezes e ainda muda quando correcoes.jsonl renomeia
    a janela. Um 'ini' sem 'fim' (bateria, tranco) simplesmente nao vira janela.

    correcoes.jsonl entra AQUI e nao no rotulos.jsonl: o que o CYD disse fica
    como esta, o que eu sei que era vai por cima, e a nota diz por que."""
    L = [json.loads(l) for l in open(os.path.join(dirbase, ARQ))]
    cor = correcoes(dirbase)
    abertos, out = {}, []
    for j in sorted(L, key=lambda d: d["t"]):
        k = (j.get("boot", 0), j.get("seq", 0))
        if j["ev"] == "ini":
            abertos[k] = j
        elif j["ev"] == "fim" and k in abertos:
            i = abertos.pop(k)
            c = cor.get(k, {})
            if c.get("descarta"):
                continue
            # perto=False de proposito: em campanha.py "perto" marcava o CORPO
            # ao lado de um CYD parado na mesa, um absorvedor nao modelado que
            # o ajuste tinha de descartar. Aqui o corpo E o alvo — o CYD esta na
            # mao em toda janela. Marcar True descartaria a campanha inteira.
            out.append({"ponto": c.get("ponto", j["ponto"]), "cm": j.get("cm", ""),
                        "de": i["t"], "ate": j["t"],
                        "x": c.get("x", j["x"]), "y": c.get("y", j["y"]),
                        "z": c.get("z", j["z"]), "perto": False})
    return out

def aberto(dirbase):
    """A janela que esta ABERTA agora — o ponto onde eu estou. -> dict ou None.

    Em campanha o gabarito do alvo movel nao e o alvo_verdade.json parado no
    disco desde ontem: e o ponto que eu toquei no CYD antes de comecar a captura.
    Sem isto o painel escreve "CYD real" num lugar onde eu nao estou ha horas, o
    que e pior que nao escrever nada. Mesma correcao de spec(): (boot, seq)."""
    caminho = os.path.join(dirbase, ARQ)
    if not os.path.exists(caminho):
        return None
    cor, abertos = correcoes(dirbase), {}
    for l in open(caminho):
        l = l.strip()
        if not l:
            continue
        j = json.loads(l)
        k = (j.get("boot", 0), j.get("seq", 0))
        if j["ev"] == "ini":
            abertos[k] = j
        else:
            abertos.pop(k, None)
    if not abertos:
        return None
    k, j = max(abertos.items(), key=lambda kv: kv[1]["t"])
    c = cor.get(k, {})
    if c.get("descarta"):
        return None
    return {"ponto": c.get("ponto", j["ponto"]), "cm": j.get("cm", ""),
            "x": c.get("x", j["x"]), "y": c.get("y", j["y"]),
            "z": c.get("z", j["z"]), "de": j["t"]}

def demo():
    j = lambda ev, p, t, s: {"ev": ev, "ponto": p, "t": t, "x": 1.0, "y": 2.0,
                             "z": 1.0, "cm": "cm1", "boot": 7, "seq": s}
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, ARQ), "w") as f:
            for r in [j("ini", "3", 100, 0), j("fim", "3", 220, 0),
                      j("ini", "3", 300, 1), j("fim", "3", 400, 1),   # MESMO nome
                      j("ini", "9", 500, 2)]:                         # 9 fica aberto
                f.write(json.dumps(r) + "\n")
        w = spec(d)
        # duas janelas do mesmo ponto tem de sair separadas: casar por nome
        # devolveria uma so, com o 'de' da primeira e o 'ate' da segunda.
        assert [(x["ponto"], x["de"], x["ate"]) for x in w] == \
               [("3", 100, 220), ("3", 300, 400)], w
        assert all(x["cm"] == "cm1" and not x["perto"] for x in w), w

        with open(os.path.join(d, COR), "w") as f:
            f.write(json.dumps({"boot": 7, "seq": 0, "descarta": True}) + "\n")
            f.write(json.dumps({"boot": 7, "seq": 1, "ponto": "5",
                                "x": 2.6, "y": 3.6}) + "\n")
        w = spec(d)
        # o 9 ficou sem 'fim': e exatamente o ponto onde eu estou agora
        a = aberto(d)
    assert [(x["ponto"], x["x"], x["y"], x["de"]) for x in w] == \
           [("5", 2.6, 3.6, 300)], w
    assert a and (a["ponto"], a["de"]) == ("9", 500), a
    print("rotulos ok (par por boot/seq, mesmo ponto 2x, correcao renomeia, aberto)")

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        demo()
    elif "--spec" in a:
        json.dump(spec(a[0]), sys.stdout, indent=1)
    else:
        escuta(a[0])
