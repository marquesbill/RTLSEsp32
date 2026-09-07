"""Modelagem temporal: o canal muda com a hora, e com ancora fixa da p/ medir.

O espectro em volta do apartamento nao e estacionario. Vizinho liga o micro-ondas,
o roteador do 5o troca de canal, a TV entra em standby, o AP muda de potencia
sozinho. Isso aparece como um deslocamento COMUM a todas as ancoras — sobe ou
desce o nivel inteiro — e nao como mudanca de geometria.

Sozinho, esse fato e inutil: um enlace que caiu 3 dB pode ser o canal ou o alvo
tendo andado 2 m, e nada no dado separa os dois. O que torna o tempo mensuravel
e a ancora de OPORTUNIDADE (`rtls/oportunidade.py`): com o alvo travado na mesa
pelo cabo USB, a posicao e conhecida por horas seguidas e tudo que sobra no
residuo e tempo. Este modulo consome exatamente a serie que ela produz.

## A base: Fourier, sem termo constante

    mu(t)      = sum_{k=1..K}  a_k cos(2pi k tau) + b_k sen(2pi k tau)
    log s2(t)  = c_0 + sum_{k=1..K}  d_k cos(...) + e_k sen(...)
                                                   tau = (t mod 24h) / 24h

Tres escolhas, cada uma com motivo:

1. **Fourier e nao 24 baldes de hora.** O cabo nao e usado a todas as horas —
   MEDIDO no demo de oportunidade.py, sessoes 22h->6h cobrem ~1/3 do ciclo. Um
   balde de hora nunca visitada fica vazio e o modelo nao tem o que dizer sobre
   ela; uma base continua interpola. E K harmonicos custam 2K parametros contra
   24, o que importa quando ha 6 dias de dado e nao 6 meses.

2. **mu SEM termo constante.** O nivel medio ja e absorvido por A do modelo de
   propagacao (docs/matematica/01) e pelo `b` do rastreador. Se mu tivesse
   constante, os dois estimariam a MESMA coisa e a soma ficaria indeterminada —
   e o classico problema de calibre que 03-estimacao trata com R_g. Sem
   constante, mu tem media zero sobre o ciclo por construcao e o calibre e de
   graca: nao ha nada para fixar. Ja log s2 TEM constante, porque o nivel de
   ruido e uma quantidade propria e ninguem mais o estima.

3. **s2 tambem varia.** E o ganho que chega ao rastreador. Numa hora barulhenta
   nao adianta so corrigir a media: a informacao daquele RSSI vale menos, e o
   filtro tem de saber disso. E o peso `exp(-z^2/2)`, com z = (r-mu)/sigma.

## O ajuste de log s2 e enviesado, e o vies e conhecido

Ajustar a base contra `log e^2` nao da `log s2`: para e ~ N(0, s2),

    E[log e^2] = log s2 + psi(1/2) + log 2 = log s2 - 1.2703628...

E uma constante (nao depende de s2), entao entra so no termo constante c_0 e a
correcao e exata — some a constante de volta. Sem isso, todo sigma sai ~53%
pequeno demais e o filtro fica confiante demais em tudo.

## E ele tem de poder dizer NAO

Um modelo com 2K+2K+1 parametros ajustado em 6 dias acha ciclo diario em ruido
branco — sempre. Entao a promocao segue a regra de 06-transferencia: dia inteiro
fora, ganho medio menos um erro padrao, e nenhum dia pode piorar. Se nada passa,
`ajusta()` devolve None e o rastreador roda como hoje. A parte (3) do demo() e
justamente ruido branco: o resultado CERTO ali e nenhum K promovido.
"""
import numpy as np

DIA = 86400.0
# psi(1/2) + log(2). Constante de Euler-Mascheroni: psi(1/2) = -gamma - 2 log 2.
VIES_LOG = -1.2703628454614782
# Piso de sigma. RSSI chega quantizado em dBm inteiro; so a quantizacao ja da
# desvio 1/sqrt(12) = 0.289 dB. Abaixo disso o modelo estaria afirmando precisao
# que o instrumento nao tem, e um sigma->0 explode a NLL fora da amostra.
PISO_SIGMA = 0.289
# Cobertura: hora do dia so "existe" para o modelo se tiver ao menos tantos
# pontos de treino. Sem isso, o cabo usado so de madrugada faria o Fourier
# extrapolar 16 h as cegas — MEDIDO: a escala de sigma as 03h saia 2,00 quando a
# verdade era 1,42, porque o normalizador media horas inventadas.
MIN_POR_HORA = 3
# Margem de promocao, em nats/ponto. E a regra dos 0,5 dB de 06-transferencia
# convertida: um ganho puro de escala vale log(rms_velho/rms_novo) nats, e com o
# sigma nominal do rastreador (3,4 dB) melhorar 0,5 dB da log(3.4/2.9) = 0,16.
MARGEM = 0.16


def base(t, K, periodo=DIA):
    """-> matriz (N, 2K) de cos/sen ate o harmonico K. Sem coluna constante."""
    t = np.atleast_1d(np.asarray(t, float))
    tau = 2 * np.pi * (t % periodo) / periodo
    if K <= 0:
        return np.zeros((len(t), 0))
    return np.column_stack([f(k * tau) for k in range(1, K + 1)
                            for f in (np.cos, np.sin)])


def _resolve(B, y):
    """Minimos quadrados por UMA svd e UM corte. -> (coef, posto).

    Mesma disciplina do `gls` de nucleo.py, pelo mesmo motivo (defeito #5): tres
    tolerancias respondendo "esta direcao e observavel?" divergem entre LAPACKs.
    Aqui o risco e concreto — com o cabo usado so de madrugada, a cobertura de
    fase e parcial e harmonicos altos ficam quase colineares.
    """
    if B.shape[1] == 0:
        return np.zeros(0), 0
    U, s, Vt = np.linalg.svd(B, full_matrices=False)
    k = int((s > max(B.shape) * np.finfo(float).eps * s[0]).sum())
    return Vt[:k].T @ ((U[:, :k].T @ y) / s[:k]), k


class Temporal:
    """mu(t) e sigma(t) diurnos. K=0 e o modelo nulo: mu=0, sigma constante."""

    def __init__(self, K, cmu, csig, periodo=DIA, cob=None, ref=1.0):
        self.K, self.cmu, self.csig, self.periodo = K, cmu, csig, periodo
        # cob: 24 booleanos, uma por hora. ref: sigma medio nas horas cobertas.
        self.cob = np.ones(24, bool) if cob is None else np.asarray(cob, bool)
        self.ref = float(ref)

    def coberto(self, t):
        """Havia dado de treino nesta hora? Fora disso o modelo se cala."""
        h = ((np.atleast_1d(np.asarray(t, float)) % self.periodo)
             / (self.periodo / 24)).astype(int) % 24
        return self.cob[h]

    def mu(self, t):
        """Deslocamento comum a TODAS as ancoras, em dB. Media zero no ciclo.

        Zero nas horas sem treino: extrapolar Fourier para dentro de um buraco de
        16 h nao e conservador, e invencao com cara de medicao.
        """
        B = base(t, self.K, self.periodo)
        m = (B @ self.cmu) if self.K else np.zeros(len(np.atleast_1d(t)))
        return np.where(self.coberto(t), m, 0.0)

    def sigma(self, t):
        B = base(t, self.K, self.periodo)
        z = np.full(len(np.atleast_1d(t)), self.csig[0])
        if self.K:
            z = z + B @ self.csig[1:]
        return np.maximum(np.exp(0.5 * (z - VIES_LOG)), PISO_SIGMA)

    def escala(self, t):
        """sigma(t) / sigma de referencia -> multiplicador para o rastreador.

        Normalizado de proposito: o `sigma` do rastreador ja foi calibrado e e o
        calibre. Este modulo entrega so a FORMA da variacao; se devolvesse sigma
        absoluto, os dois estariam estimando o mesmo nivel e um sobrescreveria a
        calibracao do outro sem ninguem perceber.

        A referencia e a media nas horas COBERTAS, nao nas 24 h: uma media que
        inclui horas extrapoladas divide a forma verdadeira por um numero
        inventado. Hora sem treino devolve 1,0 — o rastreador segue como hoje.
        """
        e = np.asarray(self.sigma(t)) / self.ref
        return np.where(self.coberto(t), e, 1.0)

    def nll(self, t, v):
        """-log verossimilhanca gaussiana por ponto (nats). Menor e melhor."""
        s = self.sigma(t)
        e = np.asarray(v, float) - self.mu(t)
        return 0.5 * np.log(2 * np.pi) + np.log(s) + 0.5 * (e / s) ** 2


def ajusta_k(t, v, K, periodo=DIA):
    """Ajusta mu e log s2 com K harmonicos. -> Temporal, ou None se K nao cabe."""
    t, v = np.asarray(t, float), np.asarray(v, float)
    B = base(t, K, periodo)
    cmu, posto = _resolve(B, v)
    if posto < B.shape[1]:
        return None                 # harmonico nao observavel nas horas cobertas
    e = v - (B @ cmu if K else 0.0)
    # max(e^2, piso^2) e nao e^2 + piso^2: somar deslocaria TODO log s2 para
    # cima; o max so trata o caso degenerado de residuo exatamente zero, que o
    # RSSI inteiro produz de vez em quando.
    y = np.log(np.maximum(e ** 2, PISO_SIGMA ** 2))
    B1 = np.column_stack([np.ones(len(t)), B])
    csig, posto1 = _resolve(B1, y)
    if posto1 < B1.shape[1]:
        return None
    h = ((t % periodo) / (periodo / 24)).astype(int) % 24
    cob = np.bincount(h, minlength=24) >= MIN_POR_HORA
    m = Temporal(K, cmu, csig, periodo, cob, 1.0)
    m.ref = float(np.mean(m.sigma(t)))      # media nas horas que existem mesmo
    return m


def ajusta(t, v, Ks=(1, 2, 3), margem=MARGEM, periodo=DIA):
    """Escolhe K por dia-fora e promove pela regra de 06-transferencia.

    -> (modelo ou None, relatorio). None = o dado nao sustenta ciclo diario;
    quem chama roda como antes. Nunca devolve "o melhor dos ruins".
    """
    t, v = np.asarray(t, float), np.asarray(v, float)
    dias = np.floor(t / periodo).astype(int)
    unicos = np.unique(dias)
    rel = {"dias": len(unicos), "pontos": len(t), "por_k": {}, "K": 0}
    if len(unicos) < 3:
        rel["motivo"] = f"{len(unicos)} dia(s): sem dia-fora nao ha teste"
        return None, rel

    for K in Ks:
        d = []
        for dia in unicos:
            tr, te = dias != dia, dias == dia
            if te.sum() < 5 or tr.sum() < 10:
                continue
            m0 = ajusta_k(t[tr], v[tr], 0, periodo)
            mk = ajusta_k(t[tr], v[tr], K, periodo)
            if m0 is None or mk is None:
                d = []
                break
            # ganho = quanto o modelo com K harmonicos derruba a NLL do dia que
            # ele NAO viu, contra o modelo nulo treinado no mesmo conjunto.
            d.append(float(np.mean(m0.nll(t[te], v[te]) - mk.nll(t[te], v[te]))))
        if len(d) < 3:
            rel["por_k"][K] = {"promove": False, "motivo": "poucos dias uteis"}
            continue
        d = np.array(d)
        se = float(np.std(d, ddof=1) / np.sqrt(len(d)))
        liq = float(d.mean() - se)
        # as duas condicoes de 06-transferencia: o ganho medio sobrevive a um
        # erro padrao, E nenhum dia piora (um dia pior = estrutura local, nao
        # ciclo). Sem a segunda, um dia excepcional carrega a media sozinho.
        ok = liq > margem and d.min() > 0
        rel["por_k"][K] = {"ganho": float(d.mean()), "se": se, "liquido": liq,
                           "pior_dia": float(d.min()), "promove": bool(ok)}

    bons = {k: r for k, r in rel["por_k"].items() if r.get("promove")}
    if not bons:
        rel["motivo"] = "nenhum K sobrevive ao dia-fora"
        return None, rel
    K = max(bons, key=lambda k: bons[k]["liquido"])
    rel["K"] = K
    return ajusta_k(t, v, K, periodo), rel


# ------------------------------------------------------------------ demo
def _serie(semente, amp_mu, amp_sig, dias=10, sigma0=2.0):
    """Serie sintetica com ciclo diario conhecido, so nas horas do cabo."""
    rng = np.random.default_rng(semente)
    t = []
    for d in range(dias):
        # mesma janela do cabo real: 22h -> 6h. Cobertura parcial de propósito.
        t.append(d * DIA + 22 * 3600 + np.arange(0, 8 * 3600, 300.0))
    t = np.concatenate(t)
    tau = 2 * np.pi * (t % DIA) / DIA
    mu = amp_mu * np.cos(tau) + 0.4 * amp_mu * np.sin(2 * tau)
    s = sigma0 * np.exp(0.5 * amp_sig * np.cos(tau - 1.0))
    return t, mu + rng.normal(0, s), mu, s


def demo():
    print("=" * 78)
    print("MODELO TEMPORAL — ciclo diario de mu e sigma")

    # (1) recupera um ciclo que existe
    t, v, mu, s = _serie(0, amp_mu=3.0, amp_sig=0.8)
    m, rel = ajusta(t, v)
    print(f"\n1. CICLO REAL — {rel['pontos']} pontos em {rel['dias']} dias,"
          f" mu +-3 dB, sigma 1.3..3.0 dB -> K={rel['K']}")
    for K, r in sorted(rel["por_k"].items()):
        if "ganho" in r:
            print(f"   K={K}: ganho {r['ganho']:+.3f} nats/pt, se {r['se']:.3f},"
                  f" liquido {r['liquido']:+.3f}, pior dia {r['pior_dia']:+.3f}"
                  f"  {'PROMOVE' if r['promove'] else 'nao'}")
    assert m is not None, rel
    emu = float(np.abs(m.mu(t) - mu).mean())
    es = float(np.abs(m.sigma(t) / s - 1).mean())
    print(f"   erro medio de mu: {emu:.3f} dB   erro relativo de sigma: {100*es:.1f}%")
    assert emu < 0.5, emu
    assert es < 0.25, es

    # (2) o vies de log e^2 NAO e opcional
    z = np.full(len(t), m.csig[0]) + base(t, m.K) @ m.csig[1:]
    sem = np.exp(0.5 * z)                       # o que sairia sem corrigir
    r_sem = float(np.mean(sem / s))
    print(f"\n2. VIES DE log e^2 — sem a correcao sigma sai {100*(1-r_sem):.0f}%"
          f" pequeno demais (fator {np.exp(0.5*VIES_LOG):.3f}); com ela,"
          f" razao {float(np.mean(m.sigma(t)/s)):.3f}")
    assert r_sem < 0.62, r_sem
    assert abs(np.mean(m.sigma(t) / s) - 1) < 0.1

    # (3) ruido branco: o resultado CERTO e nao promover nada
    reprovas = 0
    for semente in range(6):
        tb, vb, _, _ = _serie(100 + semente, amp_mu=0.0, amp_sig=0.0)
        mb, rb = ajusta(tb, vb)
        reprovas += mb is None
    print(f"\n3. RUIDO BRANCO — sem ciclo nenhum: {reprovas}/6 sementes"
          f" corretamente NAO promoveram (ultimo motivo: {rb.get('motivo')})")
    assert reprovas == 6, reprovas

    # (4) ciclo fraco demais: reprovar tambem e o certo
    tf, vf, _, _ = _serie(7, amp_mu=0.3, amp_sig=0.05)
    mf, rf = ajusta(tf, vf)
    lf = max((r.get("liquido", -9) for r in rf["por_k"].values()), default=-9)
    print(f"\n4. CICLO FRACO (mu +-0,3 dB) — melhor liquido {lf:+.3f} nats/pt"
          f" contra margem {MARGEM:.2f}: {'promoveu' if mf else 'nao promoveu'}")
    assert mf is None, rf

    # (5) o que o rastreador consome
    hh = [3, 23, 5, 13]                      # 13h esta FORA da janela do cabo
    h = np.array([hx * 3600.0 for hx in hh])
    e, sv = m.escala(h), np.interp(h % DIA, t % DIA, s, period=DIA)
    print(f"\n5. GANCHO DO RASTREADOR — horas cobertas: {sum(m.cob)}/24")
    for hx, ex, sx in zip(hh, e, sv):
        print(f"   {hx:02d}h  escala {ex:.2f}   verdade {sx/np.mean(s):.2f}"
              + ("" if m.cob[hx] else "   <- fora da cobertura, devolve 1,00"))
    assert m.escala(np.array([13 * 3600.0]))[0] == 1.0        # nao inventa
    assert abs(e[0] - sv[0] / np.mean(s)) < 0.2, (e[0], sv[0] / np.mean(s))
    assert np.ptp(e[:3]) > 0.1, e

    # (6) ponta a ponta com a ancora de oportunidade
    from rtls.oportunidade import _sintetico, blocos, coerentes, serie
    ondas = lambda tt: 3.0 * np.cos(2 * np.pi * (tt % DIA) / DIA)
    bs, _ = coerentes(blocos(*_sintetico(semente=3, dias=10, drift=ondas)[:2]))
    to, vo = serie(bs)
    mo, ro = ajusta(to, vo)
    assert mo is not None, ro
    print(f"\n6. PONTA A PONTA — CYD no cabo, {len(to)} blocos em {ro['dias']}"
          f" dias -> K={ro['K']}, mu varia {np.ptp(mo.mu(to)):.1f} dB")
    assert np.ptp(mo.mu(to)) > 1.0
    return m


if __name__ == "__main__":
    demo()
