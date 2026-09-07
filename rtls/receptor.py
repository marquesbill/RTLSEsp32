#!/usr/bin/env python3
"""Recebe os avistamentos que as ancoras mandam por UDP broadcast e grava um
JSONL por ancora. O formato e o de um sniffer USB de advertising: uma linha por
avistamento, com t, endereco, rssi e payload cru — assim o mesmo dado serve para
o filtro, para o ajuste e para qualquer ferramenta de BLE que leia JSONL.

Quem carimba o tempo e este processo, na chegada. Nao se tenta sincronizar
relogio entre ancoras: foi isso que quebrou no ruview (offsets de ate 825 s).
O contador de ms da placa vem no pacote so para medir jitter de transporte.

Pacote: magica(4) mac(6) seq(4) n_regs(2) perdidos(4) heap_livre(4) e depois
        len(1) addr(6) rssi(1) props(1) tipo_addr(1) payload(len)

Rodar: python3 -m rtls.receptor --outdir $RTLS_DADOS --mapa ancoras.txt
       python3 -m rtls.receptor --selftest
"""
import argparse, json, os, socket, struct, sys, tempfile, time
from collections import defaultdict

PORTA = 5007
PORTA_FAROL = 5008        # onde o host se anuncia para as ancoras
MAGICA = 0x52544c53
# E1: cabecalho 24 -> 30. O byte de versao existe porque trocar o cabecalho sem
# trocar o receptor ja aconteceu, e o sintoma era o receptor contar TUDO como
# "ruins" sem dizer por que. Agora ele diz.
CAB = 30
VERSAO = 1


def nosso_ad(pay_hex, marca, minimo):
    """Corpo do nosso AD de fabricante, ou None.

    Anda pelas estruturas AD em vez de assumir offset: se um dia entrar um AD de
    flags antes do nosso, isto continua achando. `marca` e o par de bytes depois
    do CID: "RA" = malha das ancoras, "RC" = transmissor de referencia do CYD.
    """
    b = bytes.fromhex(pay_hex)
    i = 0
    while i + 1 < len(b):
        ln = b[i]
        if ln == 0 or i + 1 + ln > len(b):
            return None
        if b[i + 1] == 0xFF and ln >= minimo and b[i + 2:i + 6] == b"\xff\xff" + marca:
            return b[i + 6:i + 1 + ln]
        i += 1 + ln
    return None


def malha_de(pay_hex):
    """-> (mac3_hex, boot, modo) ou None."""
    c = nosso_ad(pay_hex, b"RA", 11)
    return (c[0:3].hex(), c[3] | (c[4] << 8), c[5]) if c and len(c) >= 6 else None


def ref_de(pay_hex):
    """Transmissor de referencia do CYD -> (ptx_dBm, seq) ou None.

    O payload carrega a POTENCIA com que aquele pacote saiu: quem escuta nunca
    precisa adivinhar, e a inclinacao RSSI x Ptx num ponto fixo tem de dar 1:1.
    E o unico jeito de separar o A do emissor da direcionalidade da antena, que
    com um emissor de Ptx desconhecida ficam confundidos (o teclado deu 18,7 dB
    de espalhamento no A implicito entre as seis ancoras).
    """
    c = nosso_ad(pay_hex, b"RC", 8)
    if not c or len(c) < 3:
        return None
    return struct.unpack_from("<b", c, 0)[0], c[1] | (c[2] << 8)


def desempacota(pkt):
    """-> (mac_str, seq, [(addr_hex, rssi, props, tipo, payload_hex), ...], tel)
    Levanta ValueError em pacote que nao seja nosso ou esteja truncado."""
    if len(pkt) < CAB:
        raise ValueError("curto demais")
    magica, = struct.unpack_from("<I", pkt, 0)
    if magica != MAGICA:
        raise ValueError("magica errada")
    mac = ":".join("%02X" % b for b in pkt[4:10])
    seq, = struct.unpack_from("<I", pkt, 10)
    n, = struct.unpack_from("<H", pkt, 14)
    interno, = struct.unpack_from("<I", pkt, 16)   # descartes DENTRO da ancora
    heap, = struct.unpack_from("<I", pkt, 20)      # bytes livres; queda = vazamento
    if pkt[29] != VERSAO:
        raise ValueError("versao de cabecalho %d, esperada %d" % (pkt[29], VERSAO))
    tel = {"interno": interno, "heap": heap,
           "rssi_ap": struct.unpack_from("<b", pkt, 24)[0],   # 1 byte gratis do STA
           "canal": pkt[25],                                  # ch1 cobre BLE 37, ch6 o 38
           "boot": struct.unpack_from("<H", pkt, 26)[0],       # sobe = reboot loop
           "modo": pkt[28]}                                    # 0 sem rede 1 bcast 2 unicast
    regs, off = [], CAB
    for _ in range(n):
        if off + 10 > len(pkt):
            raise ValueError("registro truncado")
        ln = pkt[off]
        addr = pkt[off + 1:off + 7]
        rssi = struct.unpack_from("<b", pkt, off + 7)[0]
        props, tipo = pkt[off + 8], pkt[off + 9]
        p = pkt[off + 10:off + 10 + ln]
        if len(p) != ln:
            raise ValueError("payload truncado")
        # o firmware manda o endereco em little-endian (ordem do NimBLE); aqui
        # invertemos para a MESMA convencao do sniffer USB, senao os dois
        # caminhos discordariam sobre o mesmo aparelho
        regs.append((addr[::-1].hex(), rssi, props, tipo, p.hex()))
        off += 10 + ln
    return mac, seq, regs, tel


class Saida:
    """Um arquivo por ancora, aberto sob demanda, linha a linha (crash-safe)."""

    def __init__(self, outdir, mapa):
        self.outdir, self.mapa = outdir, mapa
        # indice pelos 3 ultimos bytes: e so isso que cabe no anuncio da malha
        self.por3 = {k.replace(":", "").lower()[-6:]: v for k, v in mapa.items()}
        self.fmalha = self.fref = None
        self.malha_n = self.ref_n = 0
        self.f, self.perdidos, self.ultima_seq = {}, defaultdict(int), {}
        self.contagem = defaultdict(int)
        self.interno, self.heap = defaultdict(int), defaultdict(int)
        self.tel = {}

    def nome(self, mac):
        return self.mapa.get(mac.upper(), mac.replace(":", "").lower())

    def arquivo(self, mac):
        n = self.nome(mac)
        if n not in self.f:
            d = os.path.join(self.outdir, str(n))
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, time.strftime("%Y-%m-%d") + "_ble.jsonl")
            self.f[n] = open(p, "a", buffering=1)
            self.f[n].write(json.dumps({"type": "meta", "start": round(time.time(), 3),
                                        "src": "c3-udp", "ancora": n, "mac": mac}) + "\n")
        return self.f[n]

    def _abre(self, attr, nome):
        if getattr(self, attr) is None:
            os.makedirs(self.outdir, exist_ok=True)
            setattr(self, attr, open(os.path.join(self.outdir, nome), "a", buffering=1))
        return getattr(self, attr)

    def arquivo_malha(self):
        return self._abre("fmalha", "malha.jsonl")

    def arquivo_ref(self):
        return self._abre("fref", "refcyd.jsonl")

    def grava(self, mac, seq, regs, t, tel):
        n = self.nome(mac)
        ant = self.ultima_seq.get(n)
        if ant is not None and seq > ant + 1:
            self.perdidos[n] += seq - ant - 1      # buraco = pacote que nao chegou
        self.ultima_seq[n] = seq
        f = self.arquivo(mac)
        vistos = 0
        for addr, rssi, props, tipo, pay in regs:
            rf = ref_de(pay)
            if rf:
                ptx, seq = rf
                self.arquivo_ref().write(json.dumps(
                    {"rx": n, "ptx": ptx, "r": rssi, "seq": seq, "t": t},
                    separators=(",", ":")) + "\n")
                self.ref_n += 1
                continue
            m = malha_de(pay)
            if m:
                # Enlace direto ancora->ancora. Sai do fluxo de aparelhos ANTES do
                # por_aparelho.py/tracker: sem isto as 6 viram "aparelhos fortes"
                # e o proprio sistema entra na propria contagem.
                mac3, boot, modo = m
                self.arquivo_malha().write(json.dumps(
                    {"rx": n, "tx": self.por3.get(mac3, mac3), "r": rssi,
                     "boot": boot, "modo": modo, "t": t},
                    separators=(",", ":")) + "\n")
                self.malha_n += 1
                continue
            f.write(json.dumps({"e": props, "a": tipo, "r": rssi, "b": addr,
                                "p": pay, "t": t}, separators=(",", ":")) + "\n")
            vistos += 1
        self.contagem[n] += vistos
        self.interno[n] = tel["interno"]
        self.heap[n] = tel["heap"]
        self.tel[n] = tel


class Farol:
    """Anuncia o host para as ancoras, para que elas passem de BROADCAST a UNICAST.
    Broadcast em WiFi nao e ACKed nem retransmitido: com 4 ancoras medimos ~7% de
    perda contra 1,2% com uma.

    O farol vai UNICAST para cada ancora que ja apareceu — o broadcast do host
    para os clientes NAO se mostrou confiavel neste AP (medido com tcpdump: o
    farol saia a cada 3 s em 255.255.255.255 e as ancoras continuavam em
    broadcast). Nao ha problema de bootstrap: a ancora comeca em broadcast, o
    host ve o IP de origem dela e responde direto. Zero configuracao, ninguem
    digita IP."""

    def __init__(self, porta, periodo=5.0, params=None):
        self.porta, self.periodo, self.visto = porta, periodo, {}
        # envio_ms(2) adv_hz(1) adv_tx_power(1) listen_interval(1) backoff_max_s(1)
        # Zero = nao mexe. E assim que uma fase de teste roda com as 6 na tomada,
        # e assim que se faz rollback de qualquer knob: mandar zero.
        self.params = params or (0, 0, 0, 0, 0)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def pacote(self):
        return b"RTLS" + struct.pack("<HBbBB", *self.params)

    def notifica(self, ip):
        agora = time.time()
        if agora - self.visto.get(ip, 0) < self.periodo:
            return
        self.visto[ip] = agora
        try:
            self.s.sendto(self.pacote(), (ip, self.porta))
        except OSError:
            pass


def carrega_mapa(path):
    if not path or not os.path.exists(path):
        return {}
    return {l.split()[1].upper(): l.split()[0] for l in open(path) if l.split()}


def main(a):
    mapa = carrega_mapa(a.mapa)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", a.porta))
    s.settimeout(1.0)
    out = Saida(a.outdir, mapa)
    fim = time.time() + a.seconds if a.seconds else None
    prox = time.time() + 30
    ruins = 0
    prox_tel = 0.0
    f = Farol(a.farol, params=(a.envio_ms, a.adv_hz, a.adv_tx_power,
                               a.listen_interval, a.backoff_max))
    print("escutando UDP :%d -> %s (farol unicast em :%d)" % (a.porta, a.outdir, a.farol))
    try:
        while fim is None or time.time() < fim:
            try:
                pkt, de = s.recvfrom(2048)
            except socket.timeout:
                continue
            try:
                mac, seq, regs, tel = desempacota(pkt)
            except ValueError:
                ruins += 1
                continue
            f.notifica(de[0])
            out.grava(mac, seq, regs, round(time.time(), 3), tel)
            # Telemetria em arquivo: e o unico caminho para o painel ver rssi_ap,
            # canal, boot e modo — nada disso entra no jsonl de avistamentos.
            if time.time() > prox_tel:
                prox_tel = time.time() + 10
                try:
                    with open(os.path.join(a.outdir, "telemetria.json"), "w") as th:
                        json.dump({"t": round(time.time(), 1), "ruins": ruins,
                                   "malha": out.malha_n, "ref": out.ref_n,
                                   "ancoras": {n: dict(out.tel.get(n, {}),
                                                       vistos=out.contagem[n],
                                                       rede=out.perdidos[n])
                                               for n in sorted(out.contagem, key=str)}}, th)
                except OSError:
                    pass
            if time.time() > prox:
                prox = time.time() + 30
                print("  " + " | ".join(
                    "%s:%d rede-%d int-%d heap%dk ap%d ch%d b%d m%d"
                    % (n, out.contagem[n], out.perdidos[n], out.interno[n],
                       out.heap[n] // 1024, out.tel.get(n, {}).get("rssi_ap", 0),
                       out.tel.get(n, {}).get("canal", 0), out.tel.get(n, {}).get("boot", 0),
                       out.tel.get(n, {}).get("modo", 0))
                    for n in sorted(out.contagem, key=str))
                    + ("  malha:%d ref:%d ruins:%d" % (out.malha_n, out.ref_n, ruins)))
    finally:
        for fh in (out.fmalha, out.fref):
            if fh:
                fh.close()
        for fh in out.f.values():
            fh.write(json.dumps({"type": "end", "stop": round(time.time(), 3)}) + "\n")
            fh.close()
    print("fim:", dict(out.contagem), "pacotes perdidos:", dict(out.perdidos),
          "malha:", out.malha_n)


def demo():
    """Auto-teste do protocolo: desempacota um pacote montado a mao, reconhece o
    anuncio da malha e o farol, conta perda por buraco de sequencia e RECUSA lixo.
    Nao depende de rede nem de sitio — e o contrato do firmware com o host."""
    tmp = tempfile.mkdtemp(prefix="rtls-selftest-")
    addr = bytes.fromhex("990000000002")   # LE, como o NimBLE
    pay = bytes.fromhex("02011a")
    reg = bytes([len(pay)]) + addr + struct.pack("<b", -61) + bytes([0x13, 1]) + pay
    cab = (struct.pack("<I", MAGICA) + bytes.fromhex("020000000001")
           + struct.pack("<I", 7) + struct.pack("<H", 1)
           + struct.pack("<I", 42) + struct.pack("<I", 123456)
           + struct.pack("<b", -58) + bytes([6]) + struct.pack("<H", 3)
           + bytes([2, VERSAO]))
    pkt = cab + reg
    mac, seq, regs, tel = desempacota(pkt)
    assert mac == "02:00:00:00:00:01", mac
    assert tel["interno"] == 42 and tel["heap"] == 123456, tel
    assert tel["rssi_ap"] == -58 and tel["canal"] == 6, tel
    assert tel["boot"] == 3 and tel["modo"] == 2, tel
    assert seq == 7 and len(regs) == 1, (seq, regs)
    # o endereco tem de sair na MESMA ordem do sniffer USB
    assert regs[0][0] == "020000000099", regs[0][0]
    assert regs[0][1] == -61 and regs[0][2] == 0x13 and regs[0][4] == "02011a", regs[0]
    # anuncio da malha: reconhecido e desviado, nao entra na contagem de aparelhos
    adv = bytes.fromhex("0bffffff5241000099070002")
    assert malha_de(adv.hex()) == ("000099", 7, 2), malha_de(adv.hex())
    assert malha_de("02011a") is None
    # o transmissor de referencia do CYD, com a Ptx dentro do proprio pacote
    ref = bytes.fromhex("08ff" + "ffff5243" + "f4" + "2a00")   # -12 dBm, seq 42
    assert ref_de(ref.hex()) == (-12, 42), ref_de(ref.hex())
    assert ref_de(adv.hex()) is None and malha_de(ref.hex()) is None
    # AD de flags ANTES do nosso: o andador tem de achar mesmo assim
    assert malha_de("02011a" + adv.hex())[0] == "000099"
    reg_m = bytes([len(adv)]) + addr + struct.pack("<b", -70) + bytes([0x10, 1]) + adv
    _, _, regs_m, _ = desempacota(cab[:14] + struct.pack("<H", 2) + cab[16:] + reg + reg_m)
    o2 = Saida(tmp, {"02:00:00:00:00:01": "1"})
    o2.grava("02:00:00:00:00:01", 1, regs_m, 0.0, tel)
    assert o2.contagem["1"] == 1 and o2.malha_n == 1, (o2.contagem, o2.malha_n)
    # versao errada tem de gritar, nao virar "ruins" calado
    try:
        desempacota(pkt[:29] + bytes([99]) + pkt[30:]); raise AssertionError("aceitou versao errada")
    except ValueError as e:
        assert "versao" in str(e), e
    # o farol de knobs tem de caber em 10 bytes e o de zeros nao mexe em nada
    assert Farol(0, params=(1000, 3, 0, 10, 60)).pacote() == b"RTLS" + struct.pack("<HBbBB", 1000, 3, 0, 10, 60)
    assert len(Farol(0).pacote()) == 10
    for ruim in (b"", b"xxxx", pkt[:-1], struct.pack("<I", 0) + pkt[4:]):
        try:
            desempacota(ruim); raise AssertionError("aceitou lixo: %r" % ruim)
        except ValueError:
            pass
    # buraco de sequencia vira contagem de perda
    o = Saida(tmp, {"02:00:00:00:00:01": "1"})
    o.ultima_seq["1"] = 5
    o.grava("02:00:00:00:00:01", 9, [], 0.0, tel)
    assert o.perdidos["1"] == 3, o.perdidos
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.expanduser("~/rtls-dados"))
    ap.add_argument("--mapa", default=os.path.expanduser("~/rtls-dados/ancoras.txt"))
    ap.add_argument("--porta", type=int, default=PORTA)
    ap.add_argument("--farol", type=int, default=PORTA_FAROL)
    ap.add_argument("--seconds", type=int, default=0)
    # knobs do farol; 0 = nao mexe na ancora (default: nao mexe em nada)
    ap.add_argument("--envio-ms", type=int, default=0)
    ap.add_argument("--adv-hz", type=int, default=0)
    ap.add_argument("--adv-tx-power", type=int, default=0)
    ap.add_argument("--listen-interval", type=int, default=0)
    ap.add_argument("--backoff-max", type=int, default=0)
    main(ap.parse_args())
