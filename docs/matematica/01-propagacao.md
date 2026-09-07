# 01 — Propagação: o modelo direto

> Código: `rtls/modelo/nucleo.py`, `rtls/ajuste.py`, `ferramentas/simula.py`

Este é o modelo que gera um RSSI a partir da geometria. Tudo o mais no projeto
— estimação, campanha, filtro, transferência — é consequência dele ou teste
contra ele.

## 1.1 Espaço livre: por que existe um `A₀`

A equação de Friis, para antenas isotrópicas casadas em polarização,
separação `d` e comprimento de onda `λ` [`friis1946`]:

```
  P_r(d) / P_t = G_t G_r ( λ / (4 π d) )²
```

Em dB, com `d` em metros:

```
  P_r[dBm] = P_t[dBm] + G_t + G_r + 20 log₁₀(λ / 4π) − 20 log₁₀(d)
```

Para 2,44 GHz, `λ = c/f = 0,12287 m`, e

```
  20 log₁₀(λ / 4π) = 20 log₁₀(9,7787e−3) = −40,19 dB
```

Ou seja: **em espaço livre, um rádio isotrópico de 0 dBm entrega −40,2 dBm a
1 m**. Esse número é a âncora física de `A₀`. Um ajuste que devolve
`A₀ = −45 dB` está dizendo "as antenas somam −4,8 dB de perda em relação ao
isotrópico ideal" — plausível para uma PCB antenna de ESP32-C3 sem plano de
terra dedicado. Um ajuste que devolve `A₀ = −20 dB` está dizendo que o
conjunto tem 20 dB de ganho, o que uma placa de 2 cm não tem: é sinal de que
algo mais (censura, escala trocada, dBm somado com dB) contaminou o ajuste.

**Use `A₀ ≈ −40 dB` como sanidade, não como verdade**: a antena real não é
isotrópica e o casamento não é perfeito. O valor esperado fica entre −40 e
−50 dB para as placas deste projeto.

## 1.2 Log-distância: o expoente `n`

Dentro de um edifício o decaimento não é o de espaço livre. O modelo
log-distância [`rappaport2024`, cap. 4; `itu-p1238`] escreve

```
  PL(d) = PL(d₀) + 10 n log₁₀(d / d₀) + X_σ ,   d₀ = 1 m
```

`n` é o **expoente de perda de percurso**. Valores de referência medidos na
literatura, 2,4 GHz:

| ambiente | `n` | fonte |
|----------|-----|-------|
| espaço livre | 2,0 | Friis |
| residencial / escritório aberto | 2,0 – 3,0 | ITU-R P.1238-11, Tab. 2 |
| escritório com divisórias | 3,0 – 3,5 | ITU-R P.1238-11 |
| corredor (efeito guia de onda) | 1,2 – 1,8 | `rappaport2024` |
| entre andares | 4,0 – 6,0 | ITU-R P.1238-11 |

`n < 2` **não é um erro**: um corredor se comporta como guia de onda e o campo
decai mais devagar que em espaço livre. O ajuste em `sitios/exemplo.json` com
dados sintéticos devolve `n ≈ 1,6–3,4` dependendo da campanha, e isso é o
esperado num apartamento pequeno com muitas reflexões.

O que **é** um erro é `n` estimado abaixo de ~1,0 em ambiente fechado: ver
[02-censura.md](02-censura.md), porque é exatamente o que a censura produz.

## 1.3 Paredes: o modelo multi-parede

Somar paredes é mais fiel que aumentar `n`, porque a atenuação de uma parede
não depende da distância — depende de haver a parede. O modelo multi-parede
(também chamado *Multi-Wall Model*, MWM) [`itu-p1238`, §2.2; `motley1988`]:

```
  PL(d) = PL(d₀) + 10 n log₁₀(d) + Σ_c  k_c · W_c   [+ k_f · W_f para pisos]
```

`k_c` = número de paredes da classe `c` cruzadas pelo segmento reto
transmissor→receptor; `W_c` = perda por travessia daquela classe.

Valores de referência a 2,4 GHz [`itu-p2040`, Tab. 3; `rappaport2024`]:

| material | espessura típica | perda (dB) |
|----------|------------------|------------|
| drywall (gesso acartonado, 2 placas + ar) | 10 cm | 2 – 4 |
| madeira / porta | 4 cm | 2 – 4 |
| vidro comum | 6 mm | 1 – 3 |
| vidro laminado / low-e | 6 mm | 8 – 25 |
| alvenaria (tijolo cerâmico + reboco) | 15 cm | 5 – 8 |
| concreto armado | 20 cm | 10 – 20 |
| laje | 15 cm | 15 – 25 |

Os defaults de `sitios/exemplo.json` (`alvenaria 6,0`, `drywall 2,5`,
`vidro 2,0`) estão no meio dessas faixas e cada um traz a citação no próprio
JSON. **Eles são um chute informado, não uma medida**: o ajuste os re-estima.

### 1.3.1 A armadilha que custa 21 dB

Um cômodo é um polígono; cada aresta é um segmento de parede. Uma parede
**interna** é aresta de **dois** cômodos. Emitir segmentos varrendo polígono a
polígono conta essa parede duas vezes, e o ajuste responde devolvendo `W`
metade do que deveria — ou, pior, um enlace que passa raspando por dois batentes
conta 6 paredes onde há 2, e a predição erra 21 dB para baixo.

`rtls/sitio.py:paredes()` resolve fazendo **união de intervalos por (eixo,
posição)** antes de emitir, e só então subtraindo os vãos de porta:

```
  para cada (eixo, posição p):
      I ← união dos intervalos das arestas colineares em p
      I ← I \ (vãos de porta em p)
      emitir um segmento por componente de I com comprimento > 2 cm
```

A espessura da parede é ignorada de propósito: uma parede é uma linha. O erro
que isso introduz na distância é ≤ 15 cm, muito abaixo de `σ_X`; e modelar
espessura exigiria decidir de que lado da linha está cada cômodo, o que é uma
fonte de bug bem maior que o ganho.

### 1.3.2 Porta aberta é buraco, não parede

Um vão de porta não atenua, e o segmento que passa por ele não deve contar
parede. Por isso `PORTAS` no JSON do sítio guarda `(eixo, posição, a, b)` e o
intervalo `[a,b]` é **subtraído** da parede. Isso não é detalhe: o par de
âncoras que se enxerga pela porta é justamente o que separa `W` de `n` no
ajuste — sem ele os dois são quase colineares na matriz de projeto.

## 1.4 Cadeias de TX e RX: `t_i` e `r_j`

Duas placas nominalmente idênticas não têm o mesmo ganho. A dispersão medida
entre placas ESP32 é da ordem de 2–4 dB (rms), e não é simétrica: a cadeia de
transmissão (PA, casamento) e a de recepção (LNA, AGC) têm variações
independentes. Daí dois parâmetros por rádio:

```
  y_ij = … + t_i + r_j + …
```

Isso quebra a reciprocidade do **enlace** enquanto preserva a da **antena**, e
essa assimetria produz um invariante testável — ver
[07-invariantes.md](07-invariantes.md).

## 1.5 Padrão de antena

A antena de uma placa não é isotrópica. O ganho na direção `u` (no referencial
**do corpo** da placa) é expandido em harmônicos esféricos reais de grau 1..L:

```
  G_i(u) = Σ_m c_{i,m} ψ_m(u)  [dB]
```

`rtls/modelo/nucleo.py:psi()` implementa a base normalizada para **média zero e
RMS 1 na esfera**, de modo que `c_m` já se lê como "dB rms daquele modo":

grau 1 (3 coeficientes):  `√3·y`, `√3·z`, `√3·x`
grau 2 (5 coeficientes):  `√15·xy`, `√15·yz`, `(√5/2)(3z²−1)`, `√15·xz`, `(√15/2)(x²−y²)`

O grau 0 (a constante) fica **de fora de propósito**: ele é exatamente `t`+`r`,
e ter os dois torna a matriz singular. Essa é a razão de a base ser normalizada
a média zero.

Girar a placa gira o padrão, porque `ψ` é avaliado no referencial do corpo:

```
  u_corpo = Rᵀ u_planta ,   R = R_z(yaw)
```

É por isso que `yaw` está no JSON do sítio: uma placa virada 90° tem o mesmo
`c`, e um `k_c` e `d` diferentes só não bastam para explicar o RSSI.

**Estado deste bloco neste projeto: reprovado na transferência.** O padrão
direcional foi ajustado três vezes com campanhas diferentes e nunca reduziu o
erro num ponto de fora do ajuste. O gancho existe em `rtls/vivo.py` e fica
**desligado**. Ver [06-transferencia.md](06-transferencia.md) — este é um caso
em que a matemática está certa e o instrumento não tem resolução para ela.

## 1.6 Corpos no caminho: obstrução por zona de Fresnel

Um corpo entre `i` e `j` não é uma parede: a atenuação depende de **quanto** da
primeira zona de Fresnel ele tapa. O raio da 1ª zona de Fresnel a uma distância
`s` do transmissor, num enlace de comprimento `d` [`rappaport2024`, §4.7]:

```
  F₁(s) = √( λ s (d − s) / d )
```

Para `λ = 0,1229 m` e `d = 5 m`, no meio do enlace: `F₁ = √(0,1229·2,5·2,5/5)
= 0,392 m`. Ou seja, um corpo humano (~0,25 m de raio) no meio de um enlace de
5 m tapa uma fração substancial da zona.

`rtls/modelo/nucleo.py:obstrucao()` modela a fração tapada como uma gaussiana
no afastamento perpendicular `ρ` do corpo em relação ao eixo do enlace:

```
  χ_e(i,j) = exp( − (ρ / L)² ) ,   L = hypot(κ F₁(s), raio_e)
```

O `hypot` com o raio do corpo é essencial e não é cosmético: `F₁ → 0` nas
pontas do enlace, então sem o termo do raio um corpo colado na antena daria
obstrução **zero**, que é o oposto do que acontece. `χ = 0` fora do segmento.

A perda é `B_e · χ_e(i,j)`, com `B_e` = perda de corpo cheio. Referência para
corpo humano a 2,4 GHz: 3–10 dB de bloqueio parcial, 10–20 dB de bloqueio total
[`ghaddar2007`, `obayashi1998`].

## 1.7 Sombreamento e ruído

```
  y_ij[t] = μ_ij + X_ij + ε_ij[t] ,   X ~ N(0, σ_X²) ,  ε ~ N(0, σ_ε²)
```

`X_ij` é o **sombreamento log-normal**: o desvio de um enlace específico em
relação ao que o modelo prevê para a sua geometria. Ele existe porque o modelo
multi-parede não sabe onde está o armário. É constante enquanto o ambiente não
muda, e é **recíproco** (`X_ij = X_ji`) porque o canal é recíproco.

Valores típicos em interiores a 2,4 GHz: `σ_X = 3–8 dB`
[`itu-p1238`, Tab. 3; `rappaport2024`]. O valor calibrado neste projeto
(`ferramentas/simula.py:VERDADE`) é `σ_X = 3,4 dB`, `σ_ε = 2,2 dB`,
`σ_b = 2,0 dB`.

A distinção entre `σ_X` e `σ_ε` é a coisa mais importante da §0.4, e é o que
[06-transferencia.md](06-transferencia.md) usa para decidir o que entra em
produção.

## 1.8 O modelo direto completo

Reunindo tudo, com tudo em dB e `d` em metros:

```
  y_ij = p_i + A₀ − 10 n log₁₀(d_ij)
              − Σ_c W_c k_c(i,j)
              − Σ_e B_e χ_e(i,j)
              + t_i + r_j
              + ψ(u_ij)·c_i + ψ(u_ji)·c_j
              + X_ij + ε_ij
```

**Toda a expressão é linear em `θ = (A₀, n, W, B, t, r, c)`.** `n` multiplica um
log conhecido; `χ` e `ψ` são funções conhecidas da geometria. Consequências
diretas, e é por isso que o modelo foi escrito assim:

1. identificabilidade = **posto de uma matriz** (não uma propriedade de um
   otimizador);
2. a matriz de informação de Fisher e a CRLB têm forma fechada — a campanha
   D-ótima da [§05](05-campanha-dotima.md) é calculável **antes** de medir;
3. o ajuste é mínimos quadrados: sem mínimo local, sem semente, sem "não
   convergiu".

## 1.9 Verificação executável

```bash
PYTHONPATH=. python3 -m ferramentas.simula --demo   # gera com este modelo e recupera n
PYTHONPATH=. python3 -m rtls.modelo.nucleo          # psi ortonormal, obstrucao nas pontas
```

`ferramentas/simula.py` gera dados **com** este modelo, incluindo censura, e o
selftest exige que `rtls/ajuste.py` recupere `n` a partir deles. É o teste que
detecta uma inversão de sinal ou um dB somado a um dBm.

## Referências

`friis1946`, `itu-p1238`, `itu-p2040`, `motley1988`, `rappaport2024`,
`ghaddar2007`, `obayashi1998` — ver [referencias.bib](referencias.bib).
