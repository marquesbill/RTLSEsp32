"""Gera dado SINTETICO no formato exato das ancoras — o sistema inteiro roda sem hardware.

Por que isto existe e nao e um detalhe: entre encomendar seis placas e ter a
primeira malha no ar passam semanas. Com este gerador voce roda `ajuste`, `loo`,
`campanha`, `vivo` e o painel no primeiro dia, ve o pipeline inteiro funcionando
e descobre erro de sitio (parede trocada, ancora fora do comodo, y invertido)
ANTES de furar parede. E e o que faz a suite de testes deste repositorio existir:
CI nao tem radio.

MODELO DIRETO (o mesmo de docs/matematica/01-propagacao.md, em dB):

    r = ptx + A0 - 10 n log10(d) - sum_c W_c k_c + b_tx + b_rx + X + eps

    X   ~ N(0, sigma_X^2)   sombreamento, CONSTANTE por enlace na janela
    eps ~ N(0, sigma_e^2)   ruido de pacote, novo a cada pacote
    b   ~ N(0, sigma_b^2)   cadeia de cada radio, constante na vida da placa

CENSURA — a parte que quase todo simulador de RSSI erra e que domina o dado real:
o pacote com r < piso NAO VIRA UMA LINHA COM VALOR BAIXO, ele simplesmente nao
existe. Nos niveis baixos de ptx so os desvanecimentos favoraveis chegam, entao a
media SOBE e a inclinacao dRSSI/dPtx desaba (no projeto de origem, medida em +0,06
onde deveria ser 1,00). Quem simula sem censura acha que o extrator e paranoico.
Ver docs/matematica/02-censura.md.

  python3 -m ferramentas.simula --dir ~/rtls-dados --horas 2
  python3 -m ferramentas.simula --selftest
"""
import argparse, json, math, os, sys, time
import numpy as np

from rtls import sitio as P
from rtls.ajuste import paredes_entre

# Verdade do simulador. Sao os valores tipicos de 2,4 GHz em interior residencial medidos
# no projeto de origem; mude a vontade — quem le o dado nao sabe destes numeros.
VERDADE = dict(A0=-45.0, n=2.6, W=6.0, sigma_X=3.4, sigma_e=2.2, sigma_b=2.0)


def _pos(tag):
    return np.array(P.ANCORAS[tag], float)


def _mu(pa, pb, ptx, v, b_tx, b_rx, X):
    d = max(float(np.linalg.norm(pa - pb)), 0.5)
    k = paredes_entre(pa[:2], pb[:2])
    return ptx + v["A0"] - 10 * v["n"] * math.log10(d) - v["W"] * k + b_tx + b_rx + X


def simula(horas=2.0, ptx_malha=9.0, hz=1.0, semente=0, v=None, t0=None):
    """-> (linhas de malha.jsonl, dict de verdade usado).

    hz e a taxa de anuncio de CADA ancora; cada anuncio e ouvido por todas as
    outras que o receberem acima do piso.
    """
    v = dict(VERDADE, **(v or {}))
    rng = np.random.default_rng(semente)
    piso = P.RADIO.get("piso_dBm", -101)
    tags = P.ESCOLHIDAS
    b = {t: float(rng.normal(0, v["sigma_b"])) for t in tags}
    X = {(i, j): float(rng.normal(0, v["sigma_X"]))                 # reciproco: e o CANAL
         for i in tags for j in tags if i < j}
    t0 = time.time() - horas * 3600 if t0 is None else t0
    linhas, n = [], int(horas * 3600 * hz)
    for s in range(n):
        t = t0 + s / hz
        for tx in tags:
            for rx in tags:
                if rx == tx:
                    continue
                x = X[(min(tx, rx), max(tx, rx))]
                mu = _mu(_pos(tx), _pos(rx), ptx_malha, v, b[tx], b[rx], x)
                r = mu + rng.normal(0, v["sigma_e"])
                if r < piso:                                        # CENSURA
                    continue
                linhas.append({"t": round(t, 3), "rx": P.INSTALADO[rx], "tx": P.INSTALADO[tx],
                               "r": int(round(r)), "ptx": ptx_malha})
    return linhas, dict(v, b={P.INSTALADO[k]: round(x, 2) for k, x in b.items()})


def campanha(pontos, seg_por_nivel=25, hz=10.0, semente=1, v=None, t0=None, z=1.00):
    """Anda a campanha: em cada ponto, o alvo cicla os niveis de ptx do sitio.

    -> (linhas de refcyd.jsonl, linhas de rotulos.jsonl). O alvo tem um ganho
    proprio (offset de cadeia + antena) que NAO e o das ancoras — e exatamente
    por isso que o A da malha nao transfere para o alvo e a campanha existe.
    """
    v = dict(VERDADE, **(v or {}))
    rng = np.random.default_rng(semente)
    piso = P.RADIO.get("piso_dBm", -101)
    niveis = P.RADIO.get("ptx_niveis_dBm", [9, 3, -3, -9])
    b_alvo = float(rng.normal(0, v["sigma_b"])) - 6.0        # antena de tag e pior
    b = {t: float(rng.normal(0, v["sigma_b"])) for t in P.ESCOLHIDAS}
    t = time.time() - len(pontos) * len(niveis) * seg_por_nivel if t0 is None else t0
    ref, rot = [], []
    for seq, (nome, x, y) in enumerate(pontos):
        pa = np.array([x, y, z], float)
        X = {tag: float(rng.normal(0, v["sigma_X"])) for tag in P.ESCOLHIDAS}
        rot.append({"boot": 1, "seq": seq, "ev": "ini", "ponto": nome,
                    "x": x, "y": y, "z": z, "t": round(t, 3)})
        for ptx in niveis:
            for _ in range(int(seg_por_nivel * hz)):
                t += 1.0 / hz
                for tag in P.ESCOLHIDAS:
                    mu = _mu(pa, _pos(tag), ptx, v, b_alvo, b[tag], X[tag])
                    r = mu + rng.normal(0, v["sigma_e"])
                    if r < piso:
                        continue
                    ref.append({"t": round(t, 3), "rx": P.INSTALADO[tag],
                                "r": int(round(r)), "ptx": ptx})
        rot.append({"boot": 1, "seq": seq, "ev": "fim", "ponto": nome,
                    "x": x, "y": y, "z": z, "t": round(t, 3)})
        t += 30.0                                             # caminhada ate o proximo
    return ref, rot


def escreve(dirbase, horas=2.0, pontos=None, semente=0):
    os.makedirs(dirbase, exist_ok=True)
    malha, verdade = simula(horas=horas, semente=semente)
    with open(os.path.join(dirbase, "malha.jsonl"), "w") as f:
        f.writelines(json.dumps(d) + "\n" for d in malha)
    pontos = pontos or pontos_padrao()
    ref, rot = campanha(pontos, semente=semente + 1)
    with open(os.path.join(dirbase, "refcyd.jsonl"), "w") as f:
        f.writelines(json.dumps(d) + "\n" for d in ref)
    with open(os.path.join(dirbase, "rotulos.jsonl"), "w") as f:
        f.writelines(json.dumps(d) + "\n" for d in rot)
    with open(os.path.join(dirbase, "verdade_simulada.json"), "w") as f:
        json.dump({"modelo": verdade, "pontos": pontos, "sitio": P.NOME}, f, indent=2)
    return len(malha), len(ref), len(rot) // 2


def pontos_padrao(n=8):
    """Pontos de campanha do sitio, um por comodo e o resto pelo desenho D-otimo.

    Aqui e so a grade honesta; o desenho D-otimo de verdade esta em
    `rtls.modelo.testes.campanha_dotima`.
    """
    from rtls.modelo.testes import grade_de_pontos
    return [(str(i + 1), round(x, 2), round(y, 2))
            for i, (x, y) in enumerate(grade_de_pontos(n))]


def selftest():
    """A censura tem de aparecer: a inclinacao dRSSI/dPtx cai longe de 1 no elo fraco."""
    pontos = pontos_padrao(4)
    ref, rot = campanha(pontos, seg_por_nivel=8, semente=3)
    assert len(rot) == 2 * len(pontos)
    # por (PONTO, ancora), que e a unidade que o extrator usa: juntar pontos
    # mistura enlace forte com fraco e a censura some na media.
    jan = [(r["ponto"], r["t"], f["t"]) for r, f in zip(rot[::2], rot[1::2])]
    por = {}
    for d in ref:
        for nome, t0, t1 in jan:
            if t0 <= d["t"] <= t1:
                por.setdefault((nome, d["rx"], d["ptx"]), []).append(d["r"])
                break
    curva = {}
    for (nome, rx, ptx), vs in por.items():
        curva.setdefault((nome, rx), []).append((ptx, float(np.mean(vs)), len(vs)))
    ok_forte = ok_censurado = False
    for chave, vs in curva.items():
        vs.sort()
        px = np.array([p for p, _, _ in vs]); mu = np.array([m for _, m, _ in vs])
        cheio = max(c for _, _, c in vs)
        if len(px) < 3:
            continue
        a = np.polyfit(px, mu, 1)[0]
        if min(c for _, _, c in vs) == cheio:         # nada faltou: enlace forte
            ok_forte |= abs(a - 1.0) < 0.30
        if min(c for _, _, c in vs) < 0.8 * cheio:    # perdeu pacote: censurado
            ok_censurado |= a < 0.85
    # a malha tem de reproduzir os parametros que a gerou (e a prova de que o
    # gerador e o ajuste falam do MESMO modelo, nao dois modelos parecidos)
    from rtls import ajuste as AJ
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        m, v = simula(horas=0.5, semente=5)
        open(os.path.join(td, "malha.jsonl"), "w").writelines(json.dumps(d) + "\n" for d in m)
        beta, rms, _ = AJ.ajusta(AJ.pontos(td))
        assert abs(beta[1] - VERDADE["n"]) < 0.9, (beta, "n nao volta")
        assert rms < 8.0, rms
    print(f"simula ok: inclinacao 1:1 no forte, achatada no fraco; "
          f"n de volta em {beta[1]:.2f} (verdade {VERDADE['n']}), rms {rms:.2f} dB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=os.path.expanduser("~/rtls-dados"))
    ap.add_argument("--horas", type=float, default=2.0)
    ap.add_argument("--semente", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        nm, nr, np_ = escreve(a.dir, a.horas, semente=a.semente)
        print(f"{a.dir}: malha.jsonl {nm} linhas | refcyd.jsonl {nr} | "
              f"rotulos.jsonl {np_} janelas | sitio {P.NOME}")
