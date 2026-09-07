# 03 — Estimação, identificabilidade e calibre

> Código: `rtls/modelo/nucleo.py:Desenho`, `rtls/ajuste.py`,
> `rtls/modelo/testes.py:identificabilidade()`

## 3.1 O estimador

O modelo da [§01](01-propagacao.md) é linear em `θ`. Empilhando `L`
observações agregadas:

```
  z = X θ + η ,    η ~ N(0, Σ)
```

O estimador de mínimos quadrados generalizados é

```
  θ̂ = (Xᵀ Σ⁻¹ X)⁻¹ Xᵀ Σ⁻¹ z
  Cov(θ̂) = (Xᵀ Σ⁻¹ X)⁻¹
```

e, sob normalidade, é o estimador de máxima verossimilhança e atinge o limite
de Cramér–Rao. Na prática `Σ` é tomada diagonal com `σ²_l = σ_X² + σ_ε²/M_l`
(`M_l` = pacotes agregados na observação `l`), o que já captura o essencial: um
enlace com 10 000 pacotes **não** vale 500 vezes um com 20, porque `σ_X` não
some com a média (§0.4).

Isso é a razão de o modelo ser deliberadamente linear. Sem otimizador, sem
mínimo local, sem semente: `θ̂` é uma solução de sistema linear, e a
identificabilidade é uma pergunta sobre **posto**.

## 3.2 O que é observável: calibre (*gauge*)

Nem todo `θ` é recuperável, e as direções não recuperáveis são conhecidas em
forma fechada. Se `X v = 0` para algum `v ≠ 0`, então `θ` e `θ + αv` produzem
exatamente os mesmos dados. Isso é um **calibre**, e o remédio é fixá-lo por
restrição, não torcer para o ruído desempatar.

`Desenho.restricoes()` emite **cinco** linhas de calibre — duas óbvias e três
que só apareceram rodando o posto:

**(a) `Σ_i t_i = 0` e `Σ_j r_j = 0`.** Somar `α` a todo `t` e subtrair `α` de
`A₀` dá o mesmo `z`. Duas direções.

**(b) inclinação comum de dipolo = 0 — três linhas.** Esta é a interessante.
Some o **mesmo** vetor global `w ∈ ℝ³` ao termo de grau 1 do padrão de **todas**
as entidades. Num enlace `i→j` os dois lados olham em direções opostas
(`u_ij = −u_ji`), então

```
  ψ₁(u_ij)·w + ψ₁(u_ji)·w = √3 (u_ij + u_ji)·w = 0
```

As duas contribuições se cancelam identicamente. Ou seja: **só diferença de
padrão entre entidades é observável.** "A antena de todo mundo aponta um pouco
para o norte" é indistinguível de "ninguém aponta". Sem essas três linhas o
desenho é singular em três direções — **com ou sem campanha**. Nenhuma
quantidade de dados fecha um calibre.

Total: 2 + 3 = 5 dimensões de calibre para grau ≥ 1, e 2 para grau 0.

Isso dá o critério que `identificabilidade()` usa:

```
  cegueira = P − posto(X) − calibre
```

`cegueira = 0` → o experimento vê tudo o que é observável.
`cegueira > 0` → há parâmetros que **este arranjo de medidas** não separa, e a
única saída é mudar o experimento (mais âncoras, campanha, outra geometria).

## 3.3 Contagem: por que 30 enlaces não são 30 números

Uma malha de `N` âncoras dá `N(N−1)` enlaces dirigidos. Para `N = 6`: 30. Mas
o conteúdo informativo é menor, e a conta é exata.

Decomponha cada par em parte simétrica e antissimétrica:

```
  s_ij = (y_ij + y_ji)/2      # simétrica: geometria + antena + X
  a_ij = (y_ij − y_ji)/2      # antissimétrica: só as cadeias
```

- **simétrica**: `N(N−1)/2` = 15 números independentes para `N=6`;
- **antissimétrica**: `a_ij = (t_i − r_i − t_j + r_j)/2`, que depende só de
  `δ_i = t_i − r_i`. São `N` incógnitas com um calibre (soma zero) → `N−1` = 5
  números.

Total: **20 números independentes em 30 enlaces**. Os 10 restantes são
redundância — e essa redundância é o que dá o teste de invariante da
[§07](07-invariantes.md), não informação nova.

## 3.4 Resultado central: a malha é cega para metade das direções

`rtls/modelo/testes.py:identificabilidade()` roda o posto em cinco
experimentos. O resultado que governa o desenho do sistema:

| experimento | `P` | posto | calibre | **cegueira** |
|-------------|-----|-------|---------|--------------|
| malha, offset escalar (grau 0) | — | — | 2 | 0 |
| malha, padrão grau 1 | — | — | 5 | **9** |
| malha, padrão grau 2 | — | — | 5 | **>0** |
| malha + 14 pontos, grau 1 | — | — | 5 | **0** |
| malha + 14 pontos, grau 2 | — | — | 5 | >0 |

(Os números exatos saem da execução; rode `python3 -m rtls.modelo.testes`.)

Leitura, e é o argumento inteiro para existir uma campanha de rótulos:

- **grau 0 (um offset escalar por âncora): a malha basta.** 30 enlaces, 2
  calibres, nada cego. Não precisa andar pela casa.
- **grau 1 (padrão dipolar): a malha é cega em 9 das 18 direções.** As âncoras
  são fixas; cada par só olha uma direção, e 6 posições fixas não amostram a
  esfera. Aumentar o tempo de medida não muda nada — é posto, não ruído.
- **grau 1 + 14 pontos móveis: fecha.** Um alvo que anda gera direções novas
  em cada âncora, e é isso que a campanha compra.
- **grau 2 não fecha nem com 14 pontos**: precisa de uma campanha desenhada
  para isso ([§05](05-campanha-dotima.md)).

Este quadro é a justificativa formal de todo o hardware móvel do projeto. Sem
ele, a campanha seria só "medir mais", que é a resposta errada.

## 3.5 Obstáculos: coluna nula ≠ mal determinado

Regra descoberta corrigindo um teste que explodia:

> Um corpo cuja coluna `χ` é zero em **todos** os enlaces não está mal
> determinado — ele **não existe** no experimento. Tem de ser excluído do
> desenho, não regularizado.

A diferença importa. Um parâmetro mal determinado tem coluna pequena: a
estimativa é ruidosa mas o `|z|` é finito e a regularização ajuda. Um parâmetro
com coluna **identicamente nula** faz `|z| → ∞` e contamina o diagnóstico
inteiro: o teste de recuperação passa a reprovar por causa de uma entidade que
nenhuma medida toca.

`rtls/modelo/testes.py:obstrutores(ents, minimo=2)` filtra: só entra no ajuste
o corpo que obstrui pelo menos `minimo` enlaces da malha. **Isso é uma
propriedade do SÍTIO, não do modelo** — mudou a mobília, mudou quem é
estimável. É por isso que a função vive no lado do sítio e não no núcleo.

## 3.6 O bloco de altura

As âncoras deste projeto ficam em duas ou três alturas (0,30 / 1,10 m). O eixo
`z` é, portanto, o menos amostrado, e um efeito de altura se disfarça de efeito
de distância.

Medição que forçou o bloco: dois pontos no **mesmo** `(x,y)`, a 0,05 m e
1,65 m, deram **21,5 dB** de diferença; e uma âncora **mais distante** porém
mais alta chegou 9,9 dB mais forte. Nenhuma função de `d` produz isso.

O modelo de altura acrescenta termos `z` e `z²` ao ajuste:

```
  y = … + a₁ z + a₂ z²
```

`z²` porque a dependência não é monótona: perto do piso há o lóbulo de
reflexão de terra (interferência entre raio direto e refletido — modelo de
**dois raios**, `rappaport2024` §4.6), e perto do teto há o efeito da laje.

O desenho da campanha de altura em `ferramentas/gera_firmware_alvo.py` explora
isso da forma mais barata possível: **uma aba por altura, e o primeiro ponto de
cada aba é sempre o mesmo `(x,y)`**. Os três avistamentos desse ponto medem a
curva de altura **sem passar pelo modelo** — a diferença entre eles não depende
de `A₀`, de `n` nem de `W`, porque a geometria horizontal é idêntica. Se a
campanha tiver de parar no meio, são esses três pontos que valem.

## 3.7 Diagnóstico: como saber que o ajuste está certo

`recuperacao()` gera dados com `θ` conhecido e exige que o ajuste devolva `θ`:

```
  z_p = (θ̂_p − θ_p) / se(θ̂_p)       # escore padronizado
```

Critério: `|z| ≤ ~3` para todo `p` **fora do espaço de calibre** (o `assert` no
código corta em 4, que é o limite honesto para o *máximo* sobre ~50 colunas: se
os `z` fossem normais padrão independentes, `P(max > 4) ≈ 50 × 6,3×10⁻⁵ ≈
0,3 %`). Resultados de referência no sítio de exemplo:

```
  grau 1: 40 parâmetros, posto 35, |z|max = 2,04
  grau 2: 75 parâmetros, posto 70, |z|max = 2,29
```

`40 − 35 = 5` e `75 − 70 = 5`: exatamente o calibre. Cegueira zero.

### O "fora do espaço de calibre" é a parte difícil

Escrever `z = e/se` esconde uma decisão: *quais* direções estão fora. Seja

```
  A = [ X ; λ·R_g ]  = U Σ Vᵀ         (λ = 10³, o peso do calibre)
```

com posto numérico `k` ao corte `τ`. As duas quantidades do `z` saem daí:

```
  e   = ê − θ  projetado em span(V₁..V_k)      # o erro cobrado
  Cov = V_{1:k} Σ_{1:k}⁻² V_{1:k}ᵀ             # a variância que o divide
```

Ambas dependem do **mesmo** `k`. Se a projeção usar `k` e a covariância usar
`k′ ≠ k`, uma direção pode ter variância zerada (`se → 0`) e erro cobrado
(`e ≠ 0`) ao mesmo tempo, e `z` estoura sem que nada esteja errado com o
estimador. É por isso que `gls()` devolve a base do nulo junto com a `cov`: são
a mesma decomposição, não duas.

Resta escolher `τ`. Aqui o espectro de `A` tem um vão largo — os `p − k` valores
criados pelo calibre são nulos exatos, e aparecem em `σ/σ₀ ~ 10⁻¹⁷` (ruído de
arredondamento), enquanto o menor σ genuíno está em `~10⁻⁷`. Nove ordens de
grandeza. `τ = max(A.shape)·ε` cai no meio desse vão, e é a mesma tolerância que
o LAPACK usa por padrão. **A folga é o invariante**, e o teste a cobra
explicitamente: se `τ` cair dentro de um contínuo de σ, o `z` deixa de ser
reprodutível entre implementações de BLAS e o teste perde sentido — situação
medida e documentada em [CI-CD.md §3.1](../CI-CD.md).

Uma direção *quase* nula (σ pequeno mas real) não é descartada: fica na `cov`
com `se` enorme, que é a mesma afirmação — "o dado não mede isto" — sem o
penhasco de uma classificação binária.

Este é um teste de **recuperação**, não de ajuste: ele falha se um sinal estiver
trocado, se uma coluna estiver na posição errada, ou se o calibre for
incompleto. Ele não diz nada sobre se o modelo descreve o mundo — para isso é
preciso [06-transferencia.md](06-transferencia.md).

## 3.8 Verificação executável

```bash
PYTHONPATH=. python3 -m rtls.modelo.testes    # recuperacao, identificabilidade, NeSh, campanha
PYTHONPATH=. python3 -m rtls.ajuste           # ajuste A/n/W sobre dados reais ou simulados
```

## Referências

`rao1973` (posto, estimabilidade, funções estimáveis), `seber2003` (§3,
mínimos quadrados e restrições lineares), `rappaport2024` (§4.6, dois raios) —
ver [referencias.bib](referencias.bib).
