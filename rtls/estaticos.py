"""Banco de teste que nao precisa de trena: os emissores BLE parados da casa.

O CYD e o unico alvo com gabarito, e ele esta PARADO na mesa — um alvo so, num
lugar so. Mas as ancoras ja registram TODO anunciante BLE em
wireless/<n>/<data>_ble.jsonl, e varios deles (servidor, mac, TV, teclado) sao
estaticos e sao ouvidos por todas as ancoras o dia inteiro.

Nao sei ONDE cada um esta. Nao preciso: sei que nenhum se mexe, logo todo passeio
na estimativa e erro do filtro — medido em varios radios independentes, nenhum
deles usado para calibrar nada. E o teste de resiliencia que faltava.

MEDIDO em 2 h (passeio m/min, antes -> depois do modo parado/andando + tempering):
  47,6 -> 7,1   53,8 -> 6,3   18,4 -> 4,8   32,5 -> 15,3
  20,1 -> 2,2    7,3 -> 1,4    7,0 -> 1,4   24,9 -> ...
Dois deles pousam no mesmo ponto — (4,50;0,90) e (4,56;0,97): sao dois MACs do
MESMO aparelho. A rotacao de endereco nao sobrevive ao perfil de RSSI.

  python3 estaticos.py <dir> [horas]
"""
import sys, json, glob, os, collections
import numpy as np
from rtls import sitio as P
from rtls import vivo

def candidatos(dirbase, min_anc=4, min_pkt=300, min_min=40):
    """-> {endereco: [(t, ancora, rssi)]} dos anunciantes longos e bem ouvidos.
    Sem ptx: a Ptx destes aparelhos e desconhecida, entao o b do filtro absorve."""
    por = collections.defaultdict(list)
    for f in glob.glob(os.path.join(dirbase, "*", "*_ble.jsonl")):
        anc = P.TOMADA.get(int(os.path.basename(os.path.dirname(f))))
        if anc is None:
            continue
        for l in open(f):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d.get("b") and d.get("t"):
                por[d["b"]].append((d["t"], anc, d["r"]))
    out = {}
    for b, v in por.items():
        ancs = {a for _, a, _ in v}
        dur = (max(t for t, _, _ in v) - min(t for t, _, _ in v)) / 60
        if len(ancs) >= min_anc and len(v) >= min_pkt and dur >= min_min:
            out[b] = sorted(v)
    return out

def mede(dirbase, horas=2.0, mod=None, cands=None, **kw):
    """-> lista (endereco, metricas, p_parado_medio, posicao_media).

    mod=(A,n,W,rms) julga um modelo candidato em vez do vigente; cands reaproveita
    a varredura dos jsonl (revisao.py julga varios modelos no MESMO conjunto)."""
    A, n, W, _ = mod if mod else vivo.modelo_vigente(dirbase)
    linhas = []
    for b, v in (cands if cands is not None else candidatos(dirbase)).items():
        s = [x for x in v if x[0] >= v[-1][0] - horas*3600]
        tk = vivo.novo_tracker(A, n, W, **kw)
        ts, E, pp = [], [], []
        for t, obs in vivo.fatias(s, vivo.PASSO):
            e = tk.update(b, obs, t)
            if e is not None:
                ts.append(t); E.append(e.copy()); pp.append(tk.p_parado(b))
        if len(E) < 2:
            continue
        E = np.array(E)
        linhas.append((b, vivo.metricas(ts, E), float(np.mean(pp)), E.mean(0)))
    return linhas

def demo():
    """Auto-teste: um emissor sintetico PARADO tem de dar passeio ~0 e P(parado) alto."""
    A, n, W = -71.6, 2.31, 1.6
    # O alvo sai do sitio carregado (centro do maior comodo), nunca de uma
    # coordenada fixa: o valor absoluto do passeio escala com o tamanho do sitio.
    maior = max(P.COMODOS.values(), key=P.area)
    alvo = np.asarray(maior, float).mean(0)
    rng = np.random.default_rng(0)

    def ensaio(**kw):
        tk = vivo.novo_tracker(A, n, W, **kw)
        ts, E, pp = [], [], []
        for i in range(400):
            obs = {}
            for a in P.ESCOLHIDAS:
                d = max(np.linalg.norm(np.array(P.ANCORAS[a][:2]) - alvo), 0.5)
                obs[a] = A - 10*n*np.log10(d) + rng.normal(0, 3.8)
            e = tk.update("t", obs, i*vivo.PASSO)
            if e is not None:
                ts.append(i*vivo.PASSO); E.append(e.copy()); pp.append(tk.p_parado("t"))
        return vivo.metricas(ts[50:], np.array(E[50:])), float(np.mean(pp[50:]))

    # O teste e RELATIVO, nao um limiar em m/min: o mesmo alvo parado, medido com e
    # sem o modo parado da cadeia de Markov (t_parado ~ 0 = a particula nunca fica).
    # Um limiar absoluto so vale para a geometria em que foi calibrado; a razao vale
    # em qualquer sitio, e e ela que 03 secao 3.5 preve.
    m, pp = ensaio()
    m0, pp0 = ensaio(t_parado=1e-6)
    assert m["passeio_m_por_min"] < 0.35*m0["passeio_m_por_min"], (m, m0)
    assert pp > 0.6 > pp0, (pp, pp0)
    print(f"estaticos ok (alvo parado: passeio {m['passeio_m_por_min']:.2f} m/min contra "
          f"{m0['passeio_m_por_min']:.2f} sem modo parado; P(parado) {pp:.0%} contra {pp0:.0%})")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo(); sys.exit(0)
    base = sys.argv[1]
    h = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    print(f"{'endereco':<14} {'passeio':>8} {'salto':>6} {'desvio':>7} {'Ppar':>5}   posicao media")
    for b, m, pp, c in sorted(mede(base, h), key=lambda z: -z[1]["passeio_m_por_min"]):
        print(f"{b:<14} {m['passeio_m_por_min']:8.2f} {m['salto_medio']:6.2f} "
              f"{m['desvio_xy']:7.2f} {pp:5.2f}   ({c[0]:.2f},{c[1]:.2f})")
    print("\nNenhum destes se mexe: o passeio acima e erro do filtro, nao do mundo.")
