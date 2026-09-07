"""Agrega, no servidor, o que o modelo precisa. So leitura.  v2: quantis.

Porque quantis: a RSSI da malha nao e gaussiana em volta de uma media. Nos
enlaces curtos e uma MISTURA de estados discretos (2<->6 tem dois modos a 20 dB
de distancia, e os dois sentidos mudam juntos). A mediana pula de modo; a sd
dentro da janela nao e o erro-padrao da mediana. Entao guarde os quantis e
deixe o teste escolher a estatistica.
"""
import json, os, statistics as st, collections, sys
import numpy as np
W = os.path.expanduser("~/rtls-dados")
JAN = 1800.0

def resumo(v):
    a = np.sort(np.asarray(v, float))
    q = np.quantile(a, [.10, .25, .50, .75, .90])
    return {"med": float(q[2]), "q10": float(q[0]), "q25": float(q[1]),
            "q75": float(q[3]), "q90": float(q[4]), "n": len(a),
            "sd": round(float(a.std()), 2), "mean": round(float(a.mean()), 2)}

br = collections.defaultdict(list)
t0 = t1 = None
for l in open(os.path.join(W, "malha.jsonl")):
    try: d = json.loads(l)
    except ValueError: continue
    if "rx" not in d: continue
    t = d.get("t", 0.0)
    if t0 is None: t0 = t
    t1 = t
    br[(d["rx"], d["tx"], int((t - t0) // JAN))].append(d["r"])
malha = []
for (rx, tx, j), v in br.items():
    if len(v) < 20: continue
    malha.append(dict(rx=rx, tx=tx, j=j, **resumo(v)))
print(f"# malha: {len(malha)} (link,janela)  t0={t0:.0f} t1={t1:.0f} janelas={int((t1-t0)//JAN)+1}", file=sys.stderr)

# histograma bruto por enlace (para achar os modos) — inteiro, entao e barato
hist = collections.defaultdict(collections.Counter)
for (rx, tx, j), v in br.items():
    for r in v: hist[f"{rx}<-{tx}"][int(r)] += 1
hist = {k: dict(sorted(c.items())) for k, c in hist.items()}

rot = [json.loads(l) for l in open(os.path.join(W, "rotulos.jsonl")) if l.strip()]
corr = {}
for l in open(os.path.join(W, "correcoes.jsonl")):
    if l.startswith("#") or not l.strip(): continue
    d = json.loads(l); corr[(d["boot"], d["seq"])] = d
jan, ini = [], {}
for d in rot:
    k = (d["boot"], d["seq"])
    if d["ev"] == "ini": ini[k] = d
    elif k in ini:
        a = ini.pop(k); c = corr.get(k, {})
        if c.get("descarta"): continue
        jan.append({"ponto": c.get("ponto", a["ponto"]), "x": c.get("x", a["x"]),
                    "y": c.get("y", a["y"]), "z": a["z"], "t0": a["t"], "t1": d["t"],
                    "boot": a["boot"], "seq": a["seq"], "corr": bool(c)})
acc = collections.defaultdict(list)
for l in open(os.path.join(W, "refcyd.jsonl")):
    try: d = json.loads(l)
    except ValueError: continue
    t = d.get("t", 0.0)
    for i, w in enumerate(jan):
        if w["t0"] + 40 <= t <= w["t1"]:
            acc[(i, d["rx"], d.get("ptx", 0))].append(d["r"]); break
camp = [dict(i=i, rx=rx, ptx=ptx, **resumo(v)) for (i, rx, ptx), v in acc.items() if len(v) >= 10]
print(f"# campanha: {len(jan)} janelas, {len(camp)} (janela,ancora,ptx)", file=sys.stderr)
json.dump({"malha": malha, "janelas": jan, "campanha": camp, "hist": hist,
           "t0": t0, "t1": t1, "jan_s": JAN}, sys.stdout)
