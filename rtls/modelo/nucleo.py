"""Nucleo do modelo: geometria, padrao de antena, obstrucao, sombreamento e ajuste.

MODELO (tudo em dB, um enlace = i transmite, j recebe):

  y_ij - ptx_i =  A0                      intercepto (1 m, isotropico)
                - 10 n log10(d_ij)        perda de percurso
                - sum_c W_c k_c(i,j)      paredes, por classe
                - sum_e B_e X_e(i,j)      CORPO das outras entidades   <-- o acoplamento
                + t_i + r_j               cadeias de TX e de RX (nao reciprocas)
                + psi(u_ij).c_i           padrao de i na direcao de j (ref. do corpo de i)
                + psi(u_ji).c_j           padrao de j na direcao de i
                + X_ij + eps_ij           sombreamento correlacionado + ruido

Duas escolhas que carregam o resto:

1. TUDO E LINEAR EM THETA. n multiplica um log conhecido; o padrao e uma combinacao
   linear de harmonicos esfericos. Entao identificabilidade = posto de uma matriz,
   e a CRLB e (X' S^-1 X)^-1 em forma fechada. Nada de otimizador opaco.

2. A ANTENA E RECIPROCA, A CADEIA NAO. c_e entra igual nos dois sentidos; t_e e r_e
   nao. Isso nao e cosmetico: produz um INVARIANTE de zero parametros (ver
   `antissimetrico` e o teste do triangulo em real.py) que o dado pode refutar.

Base do padrao: harmonicos esfericos reais de grau 1..L, escalados para media zero
e RMS 1 na esfera. Assim c_m ja e "dB rms daquele modo" e o grau 0 (a constante)
fica de fora de proposito — ele E o t/r, e ter os dois e matriz singular.
"""
import numpy as np

LAMBDA = 0.125          # 2,44 GHz


# ---------------------------------------------------------------- direcoes
def direcao(pa, pb, M=None):
    """Vetor unitario de pa para pb, opcionalmente no referencial do corpo (M' v)."""
    v = np.asarray(pb, float) - np.asarray(pa, float)
    nrm = np.linalg.norm(v, axis=-1, keepdims=True)
    u = v / np.maximum(nrm, 1e-9)
    return u if M is None else u @ M           # u @ M == (M' u')' : corpo <- planta


# ------------------------------------------------- harmonicos esfericos reais
def psi(u, grau):
    """(..., 3) -> (..., n_coef): harmonicos de grau 1..grau, media 0 e RMS 1."""
    u = np.atleast_2d(np.asarray(u, float))
    x, y, z = u[..., 0], u[..., 1], u[..., 2]
    saida = []
    if grau >= 1:
        s = np.sqrt(3.0)
        saida += [s * y, s * z, s * x]
    if grau >= 2:
        a = np.sqrt(15.0); b = np.sqrt(5.0) / 2.0; cq = np.sqrt(15.0) / 2.0
        saida += [a * x * y, a * y * z, b * (3 * z * z - 1), a * x * z, cq * (x * x - y * y)]
    if grau >= 3:
        raise NotImplementedError("grau <= 2 basta: 8 coeficientes ja excedem as 5 direcoes da malha")
    return np.stack(saida, -1) if saida else np.zeros(u.shape[:-1] + (0,))


# ---------------------------------------------------------------- obstrucao
def obstrucao(pa, pb, pe, raio, kappa=1.0):
    """Fracao [0,1] da 1a zona de Fresnel do enlace pa->pb que a entidade em pe tapa.

    Gaussiana no afastamento perpendicular, com largura = raio de Fresnel local
    combinado com o raio do proprio corpo (hypot). Sem o raio do corpo, uma
    entidade colada na antena daria zero (Fresnel -> 0 na ponta), que e o oposto
    do que acontece. Vale 0 fora do segmento.
    """
    pa = np.asarray(pa, float); pb = np.asarray(pb, float); pe = np.asarray(pe, float)
    v = pb - pa; d = np.linalg.norm(v)
    if d < 1e-6:
        return 0.0
    u = v / d
    s = float(np.dot(pe - pa, u))
    if s <= 0.0 or s >= d:
        return 0.0
    rho = float(np.linalg.norm((pe - pa) - s * u))
    F1 = np.sqrt(LAMBDA * s * (d - s) / d)
    L = np.hypot(kappa * F1, raio)
    return float(np.exp(-(rho / L) ** 2))


# ------------------------------------------------------ sombreamento (NeSh)
def _nos(p0, p1, delta, nq):
    """Gauss-Legendre COMPOSTO ao longo do segmento: paineis de ~delta/2.

    Painel unico nao serve — o nucleo e^{-|u-v|/delta} tem bico em u=v e o erro
    cresce com L/delta (medido: 2e-3 dB2 em L=3, 1,5e-2 em L=8). Com painel de
    meio delta o bico cai na fronteira e o erro vai para ~1e-6.
    """
    L = float(np.linalg.norm(p1 - p0))
    npan = int(np.clip(np.ceil(L / (delta / 2)), 4, 40))   # minimo 4: em L << delta o bico fica dentro do painel
    x, w = np.polynomial.legendre.leggauss(nq)
    bordas = np.linspace(0.0, L, npan + 1)
    t = ((bordas[:-1, None] + bordas[1:, None]) / 2 + (bordas[1:, None] - bordas[:-1, None]) / 2 * x).ravel()
    ww = np.tile(w, npan) * np.repeat((bordas[1:] - bordas[:-1]) / 2, nq)
    u = (p1 - p0) / max(L, 1e-9)
    return p0 + t[:, None] * u, ww, L


def cov_nesh(seg_a, seg_b, sigma2, delta, nq=8):
    """Cov(X_a, X_b) do modelo NeSh (Patwari & Agrawal, IPSN 2008).

    X_a = integral de linha normalizada de um campo gaussiano isotropico p(x) com
    E[p(x)p(y)] = (sigma2/delta) exp(-|x-y|/delta). Aqui por quadratura composta;
    a normalizacao e escolhida para Var(X_a) -> sigma2 num enlace longo (verificado
    contra a forma fechada em demo()).
    """
    (a0, a1), (b0, b1) = np.asarray(seg_a, float), np.asarray(seg_b, float)
    if np.linalg.norm(a1 - a0) < 1e-9 or np.linalg.norm(b1 - b0) < 1e-9:
        return 0.0
    A, wa, La = _nos(a0, a1, delta, nq)
    B, wb, Lb = _nos(b0, b1, delta, nq)
    D = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=-1)
    I = wa @ np.exp(-D / delta) @ wb
    return float(sigma2 / (2 * delta) * I / np.sqrt(La * Lb))


def var_nesh(L, sigma2, delta):
    """Forma fechada de Var(X_a) para um enlace de comprimento L. Satura em sigma2;
    vale ~0 para L << delta. E a predicao P5: sigma cresce com o comprimento."""
    L = np.maximum(np.asarray(L, float), 1e-9)
    return sigma2 * (1 - (delta / L) * (1 - np.exp(-L / delta)))


def matriz_nesh(segs, sigma2, delta, sigma2_eps, nq=8):
    """Sigma = Sigma_X (NeSh) + sigma2_eps I, para uma lista de segmentos."""
    K = len(segs)
    S = np.empty((K, K))
    for i in range(K):
        for j in range(i, K):
            S[i, j] = S[j, i] = cov_nesh(segs[i], segs[j], sigma2, delta, nq)
    return S + sigma2_eps * np.eye(K)


# ------------------------------------------------------------ matriz de desenho
class Desenho:
    """Monta X e nomeia as colunas. Um objeto por conjunto de enlaces."""

    def __init__(self, ents, classes_parede=("parede",), obstaculos=(), grau=None):
        self.e = ents
        self.cp = list(classes_parede)
        self.obs = list(obstaculos)                  # nomes de entidades que tapam
        self.grau = grau                             # None = usa o grau de cada entidade
        ids = list(ents)
        self.tx = [k for k in ids if ents[k].tx]
        self.rx = [k for k in ids if ents[k].rx]
        self.pad = [k for k in ids if self._grau(k) > 0]
        cols = ["A0", "n"] + [f"W:{c}" for c in self.cp] + [f"B:{o}" for o in self.obs]
        cols += [f"t:{k}" for k in self.tx] + [f"r:{k}" for k in self.rx]
        for k in self.pad:
            cols += [f"c:{k}:{m}" for m in range(psi(np.array([[0, 0, 1.0]]), self._grau(k)).shape[1])]
        self.cols = cols
        self.idx = {c: i for i, c in enumerate(cols)}

    def _grau(self, k):
        return self.e[k].grau if self.grau is None else self.grau

    def linha(self, i, j, k_parede, pos_i=None, pos_j=None, chi=None):
        """Uma linha de X para o enlace i->j.

        pos_i/pos_j sobrescrevem a posicao (o alvo se move); k_parede e um dict
        classe->contagem; chi e um dict entidade->fracao de obstrucao.
        """
        ei, ej = self.e[i], self.e[j]
        xi = np.asarray(pos_i, float) if pos_i is not None else ei.xyz
        xj = np.asarray(pos_j, float) if pos_j is not None else ej.xyz
        d = float(np.linalg.norm(xj - xi))
        L = np.zeros(len(self.cols))
        L[0] = 1.0
        L[1] = -10 * np.log10(max(d, 0.5))
        for c in self.cp:
            L[self.idx[f"W:{c}"]] = -float((k_parede or {}).get(c, 0.0))
        for o in self.obs:
            L[self.idx[f"B:{o}"]] = -float((chi or {}).get(o, 0.0))
        L[self.idx[f"t:{i}"]] += 1.0
        L[self.idx[f"r:{j}"]] += 1.0
        for k, (pa, pb) in ((i, (xi, xj)), (j, (xj, xi))):
            g = self._grau(k)
            if g <= 0:
                continue
            v = psi(direcao(pa, pb, self.e[k].M), g)[0]
            b = self.idx[f"c:{k}:0"]
            L[b:b + len(v)] += v
        return L

    def restricoes(self):
        """Linhas de gauge. Sao 5, nao 2, e a terceira eu so descobri rodando o posto.

        (a) soma(t) = 0 e soma(r) = 0. Deslocar todo t contra A0 da o mesmo ajuste.

        (b) INCLINACAO COMUM DE DIPOLO = 0, tres linhas. Se somar o MESMO vetor
            global w ao termo de grau 1 de TODAS as entidades, nada muda: numa
            ligacao os dois lados olham em direcoes opostas (u e -u) e as duas
            contribuicoes se cancelam. Ou seja, so DIFERENCA de padrao entre
            entidades e observavel — "a antena de todo mundo aponta um pouco para
            o norte" e indistinguivel de "ninguem aponta". Sem estas 3 linhas o
            desenho fica singular em 3 direcoes, com ou sem campanha.
        """
        Rg = []
        for pre, lst in (("t", self.tx), ("r", self.rx)):
            v = np.zeros(len(self.cols))
            for k in lst:
                v[self.idx[f"{pre}:{k}"]] = 1.0
            Rg.append(v)
        g1 = [k for k in self.pad if self._grau(k) >= 1]
        if g1:
            # psi_1 = sqrt(3)(u_y, u_z, u_x) no corpo => o vetor de dipolo em
            # coordenadas do corpo e (c2, c0, c1); no global, M_e @ isso.
            for eixo in range(3):
                v = np.zeros(len(self.cols))
                for k in g1:
                    b = self.idx[f"c:{k}:0"]
                    M = self.e[k].M
                    v[b + 2] += M[eixo, 0]
                    v[b + 0] += M[eixo, 1]
                    v[b + 1] += M[eixo, 2]
                Rg.append(v)
        return np.array(Rg)


# ------------------------------------------------------------------- ajuste
def gls(X, y, S=None, Rg=None, peso_gauge=1e3, ridge=0.0):
    """Minimos quadrados generalizados com restricoes de gauge.

    -> (theta, cov, posto, dim_nula, nomes_nulos_idx)
    """
    if S is None:
        Xw, yw = X, y
    else:
        Lc = np.linalg.cholesky(S)
        Xw = np.linalg.solve(Lc, X); yw = np.linalg.solve(Lc, y)
    A, b = Xw, yw
    if Rg is not None and len(Rg):
        A = np.vstack([A, peso_gauge * Rg]); b = np.append(b, np.zeros(len(Rg)))
    if ridge:
        A = np.vstack([A, np.sqrt(ridge) * np.eye(X.shape[1])])
        b = np.append(b, np.zeros(X.shape[1]))
    th, *_ = np.linalg.lstsq(A, b, rcond=None)
    # posto e espaco nulo do desenho SEM gauge: e isso que diz o que o dado mede
    s = np.linalg.svd(Xw, compute_uv=False)
    tol = max(Xw.shape) * np.finfo(float).eps * (s[0] if len(s) else 1.0)
    posto = int((s > max(tol, 1e-9 * (s[0] if len(s) else 1))).sum())
    F = A.T @ A
    cov = np.linalg.pinv(F)
    return th, cov, posto, X.shape[1] - posto, s


def espaco_nulo(X, tol=1e-8):
    """Base do espaco nulo de X: as combinacoes de parametros que o dado NAO ve."""
    _, s, Vt = np.linalg.svd(X)
    k = (s > tol * (s[0] if len(s) else 1)).sum()
    return Vt[k:]


def antissimetrico(y, pares):
    """D_ij = y_ij - y_ji. O modelo preve D_ij = delta_i - delta_j com delta=t-r:
    percurso, paredes, corpos e AMBOS os padroes cancelam. Zero parametros."""
    d = {}
    for (i, j), v in zip(pares, y):
        d[(i, j)] = v
    out = {}
    for (i, j), v in d.items():
        if (j, i) in d and i < j:
            out[(i, j)] = v - d[(j, i)]
    return out


def demo():
    rng = np.random.default_rng(3)
    # --- base: media zero e RMS 1 na esfera
    u = rng.normal(size=(200000, 3)); u /= np.linalg.norm(u, axis=1, keepdims=True)
    P = psi(u, 2)
    assert np.abs(P.mean(0)).max() < 0.02, P.mean(0)
    assert np.abs((P ** 2).mean(0) - 1).max() < 0.03, (P ** 2).mean(0)
    G = P.T @ P / len(P)
    assert np.abs(G - np.eye(8)).max() < 0.03, G                 # ortogonais

    # --- obstrucao: 1 no eixo, cai com o afastamento, 0 fora do segmento
    a, b = np.array([0, 0, 1.0]), np.array([4.0, 0, 1.0])
    assert obstrucao(a, b, np.array([2.0, 0, 1.0]), 0.2) > 0.99
    assert obstrucao(a, b, np.array([2.0, 0.35, 1.0]), 0.02) < 0.5
    assert obstrucao(a, b, np.array([-1.0, 0, 1.0]), 0.2) == 0.0
    assert obstrucao(a, b, np.array([2.0, 0.35, 1.0]), 0.4) > 0.5   # corpo maior tapa mais

    # --- NeSh: a quadratura tem de bater com a forma fechada da variancia,
    # Var(L) = s2 (1 - (delta/L)(1 - e^{-L/delta})). Ela SATURA em s2, nao e
    # constante: e por isso que enlace curto sombreia menos (predicao P5).
    s2, dl = 9.0, 1.5
    for L in (0.5, 3.0, 5.0, 8.0, 12.0):
        v = cov_nesh(((0, 0, 0), (L, 0, 0)), ((0, 0, 0), (L, 0, 0)), s2, dl)
        exato = s2 * (1 - (dl / L) * (1 - np.exp(-L / dl)))
        # Sobra do bico: O(h^2), ~5e-3 dB2 contra sigma2 = 9. Refinar so troca CPU
        # por digito que nao existe no dado. ponytail: para aqui.
        assert abs(v - exato) < 1e-3 * s2, (L, v, exato)
    assert abs(var_nesh(12.0, s2, dl) - s2) < 0.13 * s2
    # enlaces vizinhos correlacionam, enlaces longe nao
    perto = cov_nesh(((0, 0, 0), (5, 0, 0)), ((0, 0.3, 0), (5, 0.3, 0)), s2, dl)
    longe = cov_nesh(((0, 0, 0), (5, 0, 0)), ((0, 30.0, 0), (5, 30.0, 0)), s2, dl)
    assert perto > 0.5 * s2 > longe and longe < 1e-6, (perto, longe)
    print(f"nucleo ok (var NeSh {var_nesh(3.0, s2, dl):.1f} dB2 em L=3 m -> "
          f"{var_nesh(12.0, s2, dl):.1f} em L=12, satura em {s2:.0f}; "
          f"cov de enlaces vizinhos {perto:.1f}, distantes {longe:.1e})")


if __name__ == "__main__":
    demo()
