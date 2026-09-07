# 07 — Invariantes: testes que não ajustam nada

> Código: `rtls/modelo/invariantes.py` (roda a escada inteira), `rtls/modelo/nucleo.py`

**Regra da casa: uma métrica não pode validar o próprio ajuste.** Um resíduo
pequeno é consequência de ter parâmetros, não evidência de que a física está
certa. O que vale é um **invariante**: uma identidade que a natureza obriga a
valer, cujo valor esperado é conhecido *antes* de olhar o dado, e que a resposta
errada viola.

Os testes abaixo estão em ordem de **força decrescente**. Os cinco primeiros
**não ajustam nenhum parâmetro** — não há como um modelo ruim "passar por
ajuste". Só o último (P7) envolve estimação, e por isso vem por último.

## 7.1 P1 — o invariante do triângulo

O modelo direto (§01) para o enlace `i → j` é

```
  y_ij = p_i + A₀ − 10n log₁₀ d_ij − ΣW k − Σχ B + t_i + r_j + c_i ψ(u_ij) + c_j ψ(u_ji) + X_ij
```

Tome a diferença entre os dois sentidos do mesmo par:

```
  D_ij ≜ y_ij − y_ji = (t_i + r_j) − (t_j + r_i) = δ_i − δ_j ,   δ_a ≜ t_a − r_a
```

Tudo que depende do **caminho** cancela: distância, paredes, corpos, sombreamento
e — crucialmente — **os dois padrões de antena**, porque `ψ(u_ij)` aparece nos
dois sentidos com o mesmo argumento. Sobra apenas a assimetria da **cadeia**
(TX menos RX) de cada rádio.

Como `D` é a diferença de uma função escalar dos nós, sua soma em qualquer ciclo
é zero. Em particular, para quaisquer três âncoras:

```
  D_ij + D_jk + D_ki = 0        (identidade, não hipótese)
```

**Como se lê o veredito.** O valor esperado não é "zero"; é o ruído propagado.
Se `D` de um par flutua com desvio `s` de janela a janela, a soma de três
diferenças independentes tem desvio `√3·s`. O teste passa se

```
  rms(soma dos triângulos)  <  1,3 · √3 · s
```

Falhar aqui significa que **a fatoração `t_i + r_j` está errada** — há algo
direcional que não é separável em nó, ou o dado está corrompido. É o teste mais
forte do sistema e o primeiro a rodar em qualquer sítio.

Subproduto: resolvendo `D_ij = δ_i − δ_j` por mínimos quadrados (com `Σδ = 0`
como calibre, §03) sai a assimetria de cadeia **de cada placa**, medida sem
nenhum equipamento de bancada.

## 7.2 P2 — a identidade da potência

Comandar `p_i` entra no modelo com coeficiente exatamente 1. Logo

```
  ∂y/∂p_i = 1,00      exatamente, por construção do modelo
```

A inclinação medida de RSSI contra Ptx comandado tem de ser 1. Não é uma
regressão a interpretar: é uma identidade a verificar. Desvio significa
(a) censura no piso — ver §02, que é o caso comum e puxa a inclinação **para
baixo**; (b) compressão/AGC no receptor; ou (c) o rádio não está obedecendo o
`ptx` comandado.

Este teste é o que faz `r − p_tx` ser uma variável legítima, e portanto é
pré-requisito de todo o resto.

## 7.3 P3 — a flutuação lenta é do canal, não do rádio

Se a variação lenta (minutos a horas) fosse deriva de oscilador, temperatura ou
ganho de cada placa, ela seria **independente** nos dois sentidos. Se for o
canal (móveis, portas, pessoas, umidade), ela é **recíproca**: a série de ida
prediz a de volta.

```
  ρ( y_ij(t) , y_ji(t) )  →  ≈ 1 se o canal domina,  ≈ 0 se o rádio domina
```

Nenhum parâmetro ajustado; só correlação. O veredito é `mediana(ρ) > 0,7`. Um
`ρ` alto autoriza tratar `X_ij` como propriedade **do enlace** (compartilhada
pelos dois sentidos), que é exatamente o que o modelo assume ao pôr `c_e` nos
dois sentidos e `t_e`/`r_e` num só.

## 7.4 P4 — o experimento natural

O invariante mais forte de todos é uma **intervenção**: mudar uma coisa
conhecida e ver a malha responder do jeito previsto. No projeto de origem, a
polaridade da antena de uma âncora foi invertida num horário registrado, e a
malha inteira deu um degrau.

Duas leituras decidem o modelo, e nenhuma delas envolve ajuste:

**(a) O degrau é recíproco.** Decompondo `Δ` em parte simétrica e
antissimétrica,

```
  s_e = ½ (Δ_ij + Δ_ji)   ← caminho/antena      a_e = ½ (Δ_ij − Δ_ji)   ← cadeia
```

O degrau apareceu em `s`, não em `a`. Antena e caminho afetam os dois sentidos;
a cadeia afeta um. Isso já elimina qualquer explicação por TX/RX.

**(b) O leque dentro da mesma âncora.** Um **offset escalar** por âncora prevê
que todos os enlaces daquela âncora se movam **igualmente** — leque zero. O
medido foi um leque de **13 dB** dentro da mesma âncora. Um escalar não pode
produzir isso; um padrão direcional pode, e produz.

A comparação de modelos com **o mesmo número de parâmetros** fecha o argumento:
padrão de grau 1 em duas âncoras (6 coeficientes) explicou ~3× melhor que offset
escalar em todas as seis (6 coeficientes). Igualdade de parâmetros é o que torna
a comparação honesta — sem ela seria de novo "mais parâmetros, menos resíduo".

## 7.5 P5 — NeSh: a previsão da literatura que o dado reprova

O modelo de sombreamento em rede (*Network Shadowing*, `agrawal2009`,
`patwari2008`) prevê que o campo de sombra é um processo espacial: enlaces que
atravessam a mesma região flutuam **juntos**. A previsão central e testável é

```
  Cov(X_e, X_f) = σ² · (área de interseção dos elipsoides) / (normalização)
```

com duas consequências verificáveis sem ajustar nada: (a) `σ` cresce com o
comprimento do enlace; (b) enlaces com âncora em comum correlacionam mais que
enlaces disjuntos.

Teste (b) com **permutação do rótulo do enlace** (nulo exato, sem suposição
distribucional): diferença medida ≈ 0, `p` alto, sinal negativo. **Reprovado.**
(a) e (c) (área caminhável que obstrui o enlace) deram positivos de ~2 σ com
n=14 — sugestivo, não provado.

Registrar a reprovação é o resultado. Uma malha fixa de 23 h num ambiente com
pouca movimentação simplesmente não excita o processo de sombra que a literatura
mede em ambientes com trânsito. O que **enche** a variância é outra coisa — P6.

## 7.6 P6 — a RSSI não é gaussiana; é mistura de estados

Achado colateral de P5, e o mais consequente para o ajuste: `σ` **dentro** de
uma janela cresce com o **nível**, não com o comprimento. Enlace forte varia
mais. Isso é impossível para ruído térmico e típico de **multipercurso com
estados discretos**.

O diagnóstico é uma comparação de escala robusta contra escala gaussiana,
**dentro** de uma única janela de 30 min (não ao longo das horas — medir dentro
prova que os dois estados **coexistem**, não que o enlace mudou de nível):

```
  numa gaussiana:   IQR = q₇₅ − q₂₅ = 1,349 · σ
  razão  IQR / (1,349 σ) ≫ 1   ⟹   mistura, não gaussiana
```

Medido: um enlace passou 20 h com **dois estados a 19 dB de distância**, nos
dois sentidos simultaneamente, colapsando num só depois de uma mudança física.
Três consequências operacionais, todas já aplicadas no código:

| observação | consequência |
|------------|--------------|
| `σ` da janela não é erro-padrão da mediana | **não** pesar o ajuste por `1/σ²` |
| a mediana pula de modo | usar a **média** da janela (2,42 → 1,92 dB) |
| a mistura enche a variância lenta | por isso o NeSh de P5 não aparece |

Isso também justifica a verossimilhança **Student-t** do filtro (§04): cauda
pesada é a aproximação certa para mistura de estados.

## 7.7 P7 — transferência (o único teste com ajuste)

Vem por último, e está documentado em [06-transferencia.md](06-transferencia.md).
Resultado de referência no projeto de origem: offset escalar ajustado **nos
rótulos** ajuda (1,61 → 1,24 m); padrão de grau 1 **não transfere** com 14
pontos — são 18 coeficientes contra 13 pontos mal distribuídos.

Isso **não** contradiz P4. P4 prova que o padrão direcional **existe**; P7 prova
que **aquela campanha não consegue medi-lo**. São perguntas diferentes, e a
resposta correta é redesenhar a campanha (§05), não forçar a promoção (§06).

## 7.8 O teto conhecido

O resíduo fora da amostra fica em ~6 dB nos três modelos, e a **orientação do
próprio alvo** vale 2 a 10 dB. Enquanto o alvo não girar dentro da janela de
medição, nenhum modelo de âncora desce disso. Saber onde está o teto é o que
impede de gastar meses perseguindo o último dB do lado errado do problema.

## 7.9 Verificação executável

```bash
PYTHONPATH=. python3 -m rtls.modelo.invariantes    # roda P1..P7 e imprime os vereditos
```

A saída é um relatório com VEREDITO por teste. Num sítio novo, P1, P2 e P3 têm
de passar **antes** de qualquer campanha; se P1 falha, o problema é de
instrumentação e nenhum modelo vai consertar.

## Referências

`patwari2008`, `agrawal2009` (NeSh), `hashemi1993` (estatística de canal
indoor), `good2005` (testes de permutação) — ver [referencias.bib](referencias.bib).
