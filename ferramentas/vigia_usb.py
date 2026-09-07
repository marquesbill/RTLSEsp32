"""Vigia do cabo: anota quando o alvo esta plugado, e so isso.

Roda no host (Mac ou Linux) e escreve `presenca.jsonl`. Cada linha e um evento:

    {"host": "linux", "ev": "ini", "t": 1757200000.0}
    {"host": "linux", "ev": "fim", "t": 1757228800.0}

`rtls/oportunidade.py` cruza esses intervalos com o `refcyd.jsonl` do receptor e
transforma horas de cabo em dado rotulado, sem ninguem digitar nada.

  python3 ferramentas/vigia_usb.py --host linux --dir ~/rtls-dados
  python3 ferramentas/vigia_usb.py --host mac --porta '/dev/cu.usbserial-*'

## Nao abre a porta

So testa se o arquivo de dispositivo EXISTE. Abrir a serial reseta o ESP32 pelo
DTR/RTS — o vigia derrubaria de hora em hora justamente o dispositivo que ele
esta observando, e ainda brigaria com o monitor serial de quem estiver mexendo.
`glob` custa microssegundos e nao toca no barramento.

## ARMADILHA: nao case com /dev/ttyACM*

No servidor Linux, `ttyACM0` e o T-Embed S3 do RuView — outro projeto, que nao
pode ser tocado. O CYD usa ponte CH340/CP2102 e aparece como `ttyUSB*` (Linux) ou
`cu.usbserial-*` (macOS). Casar ACM registraria "o alvo esta na mesa" toda vez
que o T-Embed estivesse ligado, e todo bloco colhido nesses periodos seria um
rotulo FALSO com peso de verdade no ajuste. Se o seu alvo for um ESP32-S3 nativo
(que e CDC-ACM de verdade), passe `--porta` apontando para o link do udev pelo
serial do chip, nunca para `/dev/ttyACM*` cru.
"""
import argparse, glob, json, os, platform, sys, time

PADRAO = {"Darwin": "/dev/cu.usbserial-*", "Linux": "/dev/ttyUSB*"}


def plugado(padrao):
    return bool(glob.glob(padrao))


def vigia(host, caminho, padrao, intervalo=10.0, passos=None, relogio=time.time,
          sonda=None, saida=None):
    """Laco do vigia. `passos`/`sonda`/`saida` existem para o demo() testar.

    Grava so a TRANSICAO, nunca o estado: um arquivo com uma linha a cada 10 s
    seria 8 mil linhas por noite dizendo a mesma coisa. O par ini/fim ja e o
    intervalo, e `intervalos()` do outro lado so precisa dele.
    """
    sonda = sonda or (lambda: plugado(padrao))
    escreve = saida if saida is not None else (
        lambda ev, t: open(caminho, "a").write(
            json.dumps({"host": host, "ev": ev, "t": t}) + "\n"))
    antes, n = sonda(), 0
    if antes:
        escreve("ini", relogio())     # ja estava plugado quando o vigia subiu
    while passos is None or n < passos:
        n += 1
        if passos is None:
            time.sleep(intervalo)
        agora = sonda()
        if agora != antes:
            escreve("ini" if agora else "fim", relogio())
            antes = agora
    if antes:
        # sessao aberta no fim: fecha. `intervalos()` DESCARTA 'ini' sem 'fim',
        # entao sem isto um Ctrl-C perderia a noite inteira de dado.
        escreve("fim", relogio())
    return n


def demo():
    print("=" * 78)
    seq = [0, 1, 1, 1, 0, 0, 1, 1]          # plugou, ficou, tirou, plugou
    linhas, t = [], [0.0]
    it = iter(seq)
    vigia("teste", None, None, passos=len(seq) - 1,   # a 1a sondagem e o estado inicial
          relogio=lambda: t.__setitem__(0, t[0] + 10.0) or t[0],
          sonda=lambda: bool(next(it)),
          saida=lambda ev, tt: linhas.append((ev, tt)))
    print("VIGIA USB —", " ".join(f"{e}@{tt:.0f}" for e, tt in linhas))
    assert [e for e, _ in linhas] == ["ini", "fim", "ini", "fim"], linhas
    # transicao so: 8 sondagens, 4 linhas. E o par fecha no fim.
    assert len(linhas) == 4, linhas

    import rtls.oportunidade as O
    d = os.path.join(os.path.dirname(__file__), "..", "testes", "_vigia_tmp")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, O.PRESENCA), "w") as f:
        for e, tt in linhas:
            f.write(json.dumps({"host": "teste", "ev": e, "t": tt}) + "\n")
        f.write("{lixo\n")                  # linha truncada por crash
        f.write(json.dumps({"host": "teste", "ev": "ini", "t": 999.0}) + "\n")
    ints = O.intervalos(d)
    print(f"   -> intervalos(): {[(int(a), int(b)) for a, b, _ in ints]}"
          f"  (linha corrompida e 'ini' sem 'fim' descartados)")
    assert len(ints) == 2, ints
    assert sum(b - a for a, b, _ in ints) == 20.0, ints
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    os.rmdir(d)

    p = PADRAO.get(platform.system(), "/dev/ttyUSB*")
    assert "ACM" not in p, p                # ver a armadilha no topo do arquivo
    print(f"   nesta maquina ({platform.system()}): padrao {p} ->"
          f" {'PLUGADO' if plugado(p) else 'ausente'}")


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--host", help="nome do host no sitio (postos.hosts)")
    a.add_argument("--dir", default=".", help="onde escrever presenca.jsonl")
    a.add_argument("--porta", default=PADRAO.get(platform.system(), "/dev/ttyUSB*"))
    a.add_argument("--intervalo", type=float, default=10.0)
    a.add_argument("--demo", action="store_true")
    o = a.parse_args()
    if o.demo:
        demo(); sys.exit(0)
    if not o.host:
        a.error("--host e obrigatorio (ou use --demo)")
    import rtls.oportunidade as O
    if "ACM" in o.porta:
        print(f"AVISO: {o.porta} casa /dev/ttyACM* — leia a armadilha no topo "
              f"de {__file__}", file=sys.stderr)
    alvo = os.path.join(os.path.expanduser(o.dir), O.PRESENCA)
    print(f"vigiando {o.porta} -> {alvo} (host={o.host}, a cada {o.intervalo:.0f}s)")
    try:
        vigia(o.host, alvo, o.porta, o.intervalo)
    except KeyboardInterrupt:
        pass
