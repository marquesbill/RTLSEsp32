#!/usr/bin/env python3
"""Manda a posicao estimada para o CYD por UDP, 2 Hz.

O vivo.py --daemon ja publica wireless/vivo.json a 2 Hz; aqui so se le o arquivo
e se joga em broadcast. Nao toca em nenhum processo em execucao e nao entra no
ajuste: e display. Broadcast porque o CYD pega IP por DHCP.

A confianca e o MINIMO de tres evidencias, nao a media: hoje o ponto 13 saiu com
spread 0,14 m e 2,62 m de erro porque so duas ancoras ouviam o alvo. Media
esconderia isso (spread otimo puxa para cima); minimo nao — a estimativa vale o
que vale a evidencia mais fraca. Sai quantizada em decimos: e o passo pedido para a
bolinha do painel.
"""
import json, os, socket, sys, time

PORTA = 5010
PASSO = 0.5
FRIO_S = 5.0                      # json parado ha mais que isto: nao manda nada

def broadcast():
    """Broadcast da LAN, nao 255.255.255.255.

    MEDIDO: com 255.255.255.255 nada saiu para a rede — o servidor tem oito
    pontes docker alem das duas placas na 192.168.1.0/24, e o limitado vai pela
    rota padrao, que nao e necessariamente a placa onde mora o CYD. O truque do
    connect() nao abre conexao nenhuma em UDP, so faz o kernel escolher a origem.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 53))
    ip = s.getsockname()[0]
    s.close()
    return ip.rsplit(".", 1)[0] + ".255"

def confianca(j):
    sp = j.get("spread", 9.9)
    n  = j.get("n_ancoras", 0)
    es = j.get("ess", 0.0)
    c_sp = (1.5 - sp) / 1.2       # 0,30 m -> 1,0 ; 1,50 m -> 0
    c_an = (n - 2) / 4.0          # 2 ancoras -> 0 ; 6 -> 1
    c = min(max(c_sp, 0.0), max(c_an, 0.0), max(es, 0.0), 1.0)
    return int(round(min(c, 1.0) * 10))

def roda(caminho):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    alvo = broadcast()
    print("broadcast em %s:%d" % (alvo, PORTA), flush=True)
    while True:
        try:
            with open(caminho) as f:
                j = json.load(f)
            fresco = time.time() - j["t"] < FRIO_S and not j.get("ausente")
        except (OSError, ValueError, KeyError):
            fresco, j = False, None
        if fresco:
            b = "M %.2f %.2f %d %d" % (j["x"], j["y"], confianca(j), j.get("n_ancoras", 0))
            s.sendto(b.encode(), (alvo, PORTA))
        time.sleep(PASSO)

def demo():
    # a confianca tem de ser refem da evidencia mais fraca, nao da melhor
    assert confianca({"spread": 0.14, "n_ancoras": 2, "ess": 0.9}) == 0
    assert confianca({"spread": 0.25, "n_ancoras": 6, "ess": 0.95}) == 10
    assert confianca({"spread": 0.90, "n_ancoras": 6, "ess": 0.95}) == 5
    print("mapa_alvo ok (minimo manda: 2 ancoras zeram spread bom)")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        base = sys.argv[1] if len(sys.argv) > 1 else "wireless"
        roda(os.path.join(base, "vivo.json"))
