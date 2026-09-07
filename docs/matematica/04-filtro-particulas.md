# 04 — Filtro de partículas: da medida à posição

> Código: `rtls/tracker.py`, `ferramentas/compare_filters.py`,
> `ferramentas/fingerprint.py`, `ferramentas/grade_bayes.py`

## 4.1 Por que não multilateração + Kalman

O caminho clássico é: converter cada RSSI em distância, resolver por mínimos
quadrados, suavizar com Kalman. Ele foi implementado e **medido** contra o
filtro de partículas (`ferramentas/compare_filters.py`): o filtro de partículas
é **3,4× melhor na mediana**.

A razão é matemática, não de implementação. Inverter o modelo,

```
  d̂ = 10^( (A₀ − y) / (10 n) )
```

é uma transformação **não linear e convexa** de uma variável ruidosa. Com
`y = μ + ξ`, `ξ ~ N(0, σ²)`, a distância estimada é log-normal e

```
  E[d̂] = d · exp( (σ ln10 / (10 n))² / 2 )
```

Para `σ = 3,4 dB` e `n = 2,8`: fator `exp(0,0784) = 1,082` — **+8% de viés
sistemático para fora**, antes de qualquer filtro. Com `σ = 6 dB` passa de
+13%. E o viés é **para fora em todas as âncoras ao mesmo tempo**, então não
se cancela na trilateração: ele infla o polígono inteiro.

O remédio não é corrigir o viés (o fator depende de `σ` local, que varia por
enlace): é **nunca sair do domínio em dB**, onde o ruído é de fato gaussiano.
O filtro de partículas avalia a verossimilhança em dB e nunca calcula `d̂`.

Segundo motivo: a planta baixa é uma restrição **não gaussiana** ("a partícula
não atravessa parede", "está dentro de um cômodo"). Kalman não a representa;
partículas representam de graça.

## 4.2 O filtro

Estado por partícula: `s = (x, y, vx, vy, m)` com `m ∈ {parado, andando}`.
`N = 600` partículas (default), amostragem por importância sequencial com
reamostragem (SIR) [`gordon1993`, `doucet2009`].

### Predição — modelo de movimento

Cadeia de Markov de dois estados, por partícula, com tempos médios de
permanência `T_parado = 60 s` e `T_andando = 20 s`. A probabilidade de
permanecer no modo durante `Δt` é a da exponencial:

```
  P[fica] = exp(−Δt / T_modo)
```

- **modo parado**: velocidade **exatamente zero** (não "pequena"), mais um
  jitter de 3 cm por passo. Isso importa: um modelo de velocidade contínua com
  `q` pequeno ainda produz deriva integrada, e um alvo esquecido na mesa
  "passeia" pela casa. Zero é zero.
- **modo andando**: passeio aleatório em aceleração,
  `v ← v + N(0, q Δt)`, `p ← p + v Δt + N(0, q Δt²/2)`, com `q = 0,6 m/s^1.5`
  e saturação `‖v‖ ≤ v_max = 2,5 m/s` — um pedestre não voa.
- **paredes**: se o segmento `p → p_novo` cruza uma parede, a partícula fica
  onde estava e a velocidade inverte com amortecimento (`v ← −0,3 v`).

### Correção — verossimilhança

```
  log p(y | s) = Σ_{a ∈ ouviram}  ℓ( (y_a − b − μ_a(s)) / σ )
  μ_a(s) = A₀ − 10 n log₁₀( d_a(s) ) − W · k_a(s)
```

Três escolhas com consequência:

**(a) Só as âncoras que reportaram entram na soma.** Âncora ausente é termo
ausente, **nunca** um RSSI de piso. Injetar o piso diz ao filtro "estou longe
desta âncora", e empurra a nuvem para o lado oposto — um erro que se manifesta
como a posição saltando para longe justamente quando o sinal some.

**(b) Cauda pesada.** `ℓ` é a log-densidade da Student-t com `ν` graus de
liberdade:

```
  ℓ(z) = −½ (ν+1) log(1 + z²/ν)
```

A alternativa antiga era gaussiana com piso (`max(ℓ, −8)`), que é robustez de
má qualidade: acima de ~4σ **todo** resíduo vale igual, criando um platô onde
a partícula errada por 12 dB empata com a errada por 30 dB. A `t` decai
suavemente e mantém a ordenação.

**(c) Censura é informação, não ausência.** Se `y ≤ piso`, o termo vira uma
dobradiça de um lado só:

```
  ℓ_cens = −½ ( max(μ − piso, 0) / σ )²
```

Ou seja: penaliza apenas as posições em que o modelo previa que aquela âncora
**ouviria alto**. Se o modelo já previa fraco, não penaliza nada. Isso é a
verossimilhança da cauda escrita à mão (`P[y < piso] ≈ Φ(...)`), sem
dependência de `scipy`. **Medido com gabarito: 1,70 m → 0,80 m de erro só por
tratar o piso.** Ver [02-censura.md](02-censura.md).

### Tempero (*tempering*)

```
  log w ← log w + α · Σ_a ℓ_a
```

com `α ≤ 1`. O motivo é específico deste sistema e não aparece na literatura de
SIR: o resíduo estrutural de um ambiente é **constante no tempo** (medido:
+8,7 dB num enlace, estável a 1 dB por 90 min). Multiplicar essa mesma
discrepância 120×/min como se fossem evidências novas e independentes torna a
posterior arbitrariamente confiante num lugar errado. É a causa do salto de
1,28 m com ESS colapsado que motivou o parâmetro.

Formalmente: as observações são **correlacionadas** por `X_ij`, e o filtro
assume independência. `α` é o fator de deflação da verossimilhança que
compensa aproximadamente essa correlação — o mesmo truque de *power
posteriors* [`friel2008`] usado por uma razão de modelo, não de amostragem.

### Reamostragem

Tamanho efetivo de amostra [`kong1994`]:

```
  ESS = 1 / Σ_k w_k²        (1 ≤ ESS ≤ N)
```

Reamostra quando `ESS < N/2`. `ESS` é o melhor termômetro do filtro: alvo
saudável fica em 30–60% de `N`. `ESS ≈ 1` significa que uma partícula levou
todo o peso — a nuvem não representa mais a posterior e a estimativa é uma
coincidência.

## 4.3 Saídas, e qual delas é a primária

| saída | função | o que é |
|-------|--------|---------|
| **cômodo** | `comodo(dev)` | `P[cômodo] = Σ_{k ∈ polígono} w_k` — **saída primária** |
| posição | `update()` | média ponderada `Σ w_k p_k` |
| incerteza | `spread(dev)` | desvio-padrão da nuvem, em m |
| parado? | `p_parado(dev)` | massa no modo parado |
| nuvem | `nuvem(dev, k)` | `k` partículas **amostradas pelo peso** |

**A saída por cômodo é a primária, e o metro só depois de validado.** A razão
é honestidade estatística: a posterior de cômodo é uma soma de pesos — um
número que o filtro realmente calcula. A média da nuvem é um resumo de uma
distribuição frequentemente **multimodal**, e a média de duas modas separadas
por uma parede cai *dentro da parede*, num lugar onde a probabilidade é zero.

`comodo()` devolve `{}` quando não há polígonos de cômodo, deliberadamente: não
chuta o cômodo a partir do ponto médio, porque esse é exatamente o número que
ainda não vale.

`nuvem()` amostra **pelo peso**. Desenhar as partículas cruas mentiria: depois
de uma medida forte quase todo o peso mora numa fração delas, e um sorteio
uniforme pintaria como provável exatamente o que o filtro acabou de descartar.

## 4.4 Inicialização: prior uniforme, de propósito

`_seed()` ignora a medida e semeia uniforme na caixa envolvente. Semear de uma
multilateração **piora**, e foi medido: erro em regime 3,00 → 5,12 m, p99 11,6
→ 38,0 m. Duas causas somadas: o palpite carrega o viés log-normal de §4.1, e
o espalhamento estreito trava a nuvem nessa moda errada — a reamostragem mata
as partículas que teriam corrigido.

Limite conhecido: uniforme na caixa envolvente basta até ~2000 m² com 600
partículas. Acima de ~20 000 m² a densidade inicial cai demais; a saída é subir
`n_particles` no primeiro passo e podar após a primeira medida, ou semear na
**região** das âncoras que ouviram (região, não ponto — ponto reintroduz o
viés).

## 4.5 O viés por dispositivo `b`

Um dispositivo desconhecido tem Ptx desconhecida, e Ptx entra somando: é
degenerada com `A₀`. Duas opções:

- **`fixa_vies(dev, b)`** — para uma etiqueta cuja Ptx é conhecida (o próprio
  equipamento do projeto): trava `b` e não estima nada. **É o caminho que serve.**
- **`b_alfa > 0`** — média móvel do resíduo. Precisa de ≥ 2 âncoras, senão `b`
  e posição são o mesmo parâmetro. Está **desligado por default** (`b_alfa=0`):
  medido em 10 trilhas, custa 0,05 m sem viés e não ganha nada com o alvo 8 dB
  acima, porque um offset de Ptx é **comum a todas as âncoras** e se cancela na
  comparação entre elas — que é justamente o que localiza.

Ponto em aberto, registrado: o default é 0, mas `vivo.py` passa 0,05 e
`loo.py` passa 0,2. Três valores, nenhuma medição que reconcilie os três. Só
uma campanha rotulada resolve, e até lá não se mexe — `b_alfa` altera o erro de
qualquer `A/n/W` e contaminaria qualquer A/B de modelo.

## 4.6 Variantes de modelo de medida

`loglik()` é o **único** ponto de troca. Uma subclasse substitui o modelo de
medida sem tocar em movimento, planta, reamostragem ou ciclo de vida:

- `ferramentas/fingerprint.py` — mapa de rádio medido em vez de log-distância
  [`bahl2000`];
- `ferramentas/grade_bayes.py` — posterior em grade, sem partículas, para
  comparação;
- `ferramentas/tomografia.py` — atenuação por presença (RTI), [`wilson2010`];
  ver [08-sombreamento.md](08-sombreamento.md).

## 4.7 Verificação executável

```bash
PYTHONPATH=. python3 -m rtls.tracker              # auto-teste: trilhas sinteticas
PYTHONPATH=. python3 -m ferramentas.compare_filters   # PF vs multilateracao+Kalman
PYTHONPATH=. python3 -m rtls.loo                  # cada ancora localizada pelas outras
```

`rtls/loo.py` é o teste com mais valor: esconde uma âncora, localiza-a com as
outras cinco e compara com a posição verdadeira do sítio. É um gabarito de
graça — nenhum rótulo humano envolvido. Referência no sítio de exemplo com
dados simulados: mediana 1,64 m, pior caso 3,61 m, **cômodo correto em 6/6**.

## Referências

`gordon1993`, `doucet2009`, `arulampalam2002`, `kong1994`, `friel2008`,
`bahl2000`, `wilson2010` — ver [referencias.bib](referencias.bib).
