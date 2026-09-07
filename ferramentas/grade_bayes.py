"""Grade de Bayes sobre os 15 enlaces — substitui reconstrucao regularizada + centroide.
A saida NAO e imagem nem ponto: e uma distribuicao de probabilidade sobre celulas.
Rodar: python3 grade_bayes.py"""
import numpy as np
from ferramentas import tomografia as TG

R, PASSO, SIGMA, ATEN = 3.0, 0.25, 1.0, 6.0
ANC = TG.hexagono(R)
P, _ = TG.malha(R, PASSO)                    # celulas dentro do hexagono
W, LINKS = TG.pesos(ANC, P)                  # (15, n_celulas)

# ---- modelo direto: o que cada enlace mediria se o corpo estivesse em cada celula ----
F = np.array([W @ TG.corpo(P, c) * ATEN for c in P])       # (n_celulas, 15)
print(f"grade: {len(P)} celulas de {PASSO} m | {len(LINKS)} enlaces | tabela direta {F.shape} "
      f"= {F.nbytes/1024:.0f} KB\n")

def posterior(y, prior=None, sigma=SIGMA, ll_extra=None):
    ll = -0.5*(((y - F)/sigma)**2).sum(1)                  # verossimilhanca por celula
    if ll_extra is not None: ll = ll + ll_extra            # <- BLE entra como SOMA
    if prior is not None: ll = ll + np.log(prior + 1e-300)
    ll -= ll.max(); p = np.exp(ll); return p/p.sum()

def mostra(p, verdade=None, cols=41):
    """Renderiza a distribuicao em ASCII com a rampa do viridis (escuro->claro)."""
    ramp = " .:-=+*#%@"
    g = np.linspace(-R, R, cols); rows = int(cols*0.5)
    gy = np.linspace(R, -R, rows)
    out = []
    for y in gy:
        line = ""
        for x in g:
            d = np.linalg.norm(P - [x, y], axis=1)
            j = int(np.argmin(d))
            line += " " if d[j] > PASSO*1.2 else ramp[min(int(p[j]/p.max()*9.99), 9)]
        out.append(line)
    if verdade is not None:
        ix = int(np.argmin(abs(g-verdade[0]))); iy = int(np.argmin(abs(gy-verdade[1])))
        out[iy] = out[iy][:ix] + "X" + out[iy][ix+1:]
    print("\n".join(out))

def resumo(p, nome):
    mu = P.T @ p
    var = ((P-mu)**2).sum(1) @ p
    ent = -(p[p>0]*np.log2(p[p>0])).sum()
    # argsort e nao argmax: no empate isto pega o ULTIMO indice, argmax pega o
    # primeiro. Numa grade regular sao celulas vizinhas — igualmente validas,
    # mas o numero impresso muda. Nao "simplificar" sem querer mudar a saida.
    top = np.argsort(p)[::-1][:1][0]
    print(f"{nome}: media ({mu[0]:+.2f}, {mu[1]:+.2f})  MAP ({P[top,0]:+.2f}, {P[top,1]:+.2f})  "
          f"espalhamento {np.sqrt(var):.2f} m  entropia {ent:.2f} bits  "
          f"massa nas 5% melhores celulas {np.sort(p)[::-1][:max(1,len(p)//20)].sum()*100:.0f}%")
    return mu

if __name__ == "__main__":
    rng = np.random.default_rng(4)
    alvo = np.array([1.1, -0.8])
    y = W @ (TG.corpo(P, alvo)*ATEN) + rng.normal(0, SIGMA, len(LINKS))

    print("=== 1. O QUE O tomografia.py FAZ HOJE: imagem reconstruida ===")
    img = TG.reconstruir(W, y, 1e-2*np.trace(W@W.T)/len(LINKS))
    print(f"    imagem: {len(img)} valores de atenuacao em dB, faixa [{img.min():+.2f}, {img.max():+.2f}]")
    print(f"    (mal-posta: 15 equacoes para {len(P)} incognitas — e borrada e tem artefato negativo)")
    e = TG.estimar(W, P, y, 1e-2*np.trace(W@W.T)/len(LINKS))
    print(f"    depois vira UM PONTO por centroide heuristico: ({e[0]:+.2f}, {e[1]:+.2f})"
          f"  erro {np.linalg.norm(e-alvo):.2f} m\n")

    print("=== 2. GRADE DE BAYES: distribuicao de probabilidade sobre celulas ===")
    p = posterior(y)
    mu = resumo(p, "    ")
    print(f"    erro da media: {np.linalg.norm(mu-alvo):.2f} m       (X = posicao real)\n")
    mostra(p, alvo)

    print("\n=== 3. CASO AMBIGUO: so 4 dos 15 enlaces reportando ===")
    m = np.zeros(len(LINKS), bool); m[[0,4,9,13]] = True
    ll = -0.5*(((y[m] - F[:,m])/SIGMA)**2).sum(1)
    ll -= ll.max(); p2 = np.exp(ll); p2 /= p2.sum()
    resumo(p2, "    ")
    print("    a distribuicao fica MULTIMODAL — e isso e informacao, nao defeito:\n")
    mostra(p2, alvo)

    print("\n=== 4. O TERMO BLE ENTRA COMO SOMA (a razao de usar grade) ===")
    ble_xy = alvo + rng.normal(0, 2.0, 2)          # estimativa BLE grosseira, sigma ~2.9 m
    ll_ble = -0.5*((np.linalg.norm(P-ble_xy, axis=1)/2.9)**2)
    p3 = posterior(y, ll_extra=ll_ble)
    mu3 = resumo(p3, "    ")
    print(f"    BLE sozinho diria ({ble_xy[0]:+.2f}, {ble_xy[1]:+.2f}), erro {np.linalg.norm(ble_xy-alvo):.2f} m")
    print(f"    tomografia sozinha: erro {np.linalg.norm(mu-alvo):.2f} m")
    print(f"    somadas:            erro {np.linalg.norm(mu3-alvo):.2f} m")
