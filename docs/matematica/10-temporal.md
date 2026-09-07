# 10 — Modelagem temporal: o relógio como coordenada

Os documentos 01 a 09 tratam o canal como uma função da **geometria**. Não é: a
mesma geometria dá RSSI diferente às 3h e às 20h, porque o espectro em volta é
ocupado por equipamentos que entram e saem. Este documento acrescenta o tempo
como coordenada, e — mais importante — mostra **o instrumento que torna isso
mensurável**, porque sem ele a variação temporal é indistinguível de movimento.

## 10.1 Por que o tempo, sozinho, não é observável

Considere um enlace âncora *i* → alvo que caiu 3 dB entre duas medidas. As duas
explicações são exatamente compatíveis com o dado:

| hipótese | efeito em `r_i` |
|----------|-----------------|
| o alvo se afastou de `d` para `d·10^{3/(10n)}` | −3 dB |
| o canal ficou 3 dB mais ruidoso/atenuado | −3 dB |

Com o alvo livre, `p(t)` e o termo temporal entram na mesma equação e a
verossimilhança é **plana ao longo da troca entre os dois**. Não é um problema de
estimador ruim; é o mesmo problema de calibre de [03](03-estimacao.md): duas
direções do espaço de parâmetros produzem a mesma predição.

A saída é fixar uma das duas. Não com um prior — com uma **restrição dura**.

## 10.2 A âncora de oportunidade: o cabo USB como restrição

Quando o alvo está enumerado na USB de um host, ele está fisicamente ao alcance
do cabo daquele host. Isso é uma restrição de posição, e é gratuita:

```
  t ∈ I_h  (intervalo em que o host h enxerga o dispositivo)
  ⟹  p(t) ∈ B(c_h, r_h)
```

`c_h` é a posição do posto e `r_h` o alcance do cabo mais a folga da bancada —
`sitios/*.json → postos`. `r_h` **é a incerteza da posição**, não um enfeite: com
cabo de 2 m e bancada larga, `r_h = 2 m` e a restrição vale muito menos.

### Quanto isso vale, e quanto não vale

Não vale como ponto de campanha. Para o modelo direto `μ = A − 10 n log₁₀ d`, um
único ponto dá linhas de desenho todas iguais a `[1, −10 log₁₀ d]`: a matriz tem
**posto 1**, e `A` e `n` não são separadamente identificáveis por mais horas que
se meça. É o teste de identificabilidade de [03](03-estimacao.md) §3.4 aplicado a
um desenho degenerado. Mil horas num ponto só não valem os 14 pontos espalhados
de [05](05-campanha-dotima.md).

Vale como **relógio**. Com `p` conhecido e fixo, o resíduo

```
  ε_i(t) = r_i(t) − μ_i(p_posto)
```

não tem para onde fugir: o que sobra é tempo, ganho do rádio e ruído. É a única
configuração experimental em que deriva temporal e deriva de posição não estão
confundidas. E ela custa zero — MEDIDO no auto-teste: 48 h de cabo em 6 noites
produzem 576 blocos de 5 min rotulados, sem ninguém andar pela casa nem digitar
um rótulo.

## 10.3 Nível e assinatura: duas projeções ortogonais

Seja `y ∈ ℝᴺ` o vetor de RSSI que as N âncoras ouviram do farol num bloco, e
`P₁ = 11ᵀ/N` o projetor no vetor constante. Então

```
  nível(y)     = 1ᵀy/N − P_tx        = a componente em span(1)
  assinatura(y) = (I − P₁) y          = a componente ortogonal a 1
```

As duas somam `y` e são ortogonais por construção. A separação é útil porque as
duas classes de perturbação caem em espaços diferentes:

- **Modo comum** (`y → y + c·1`): potência do farol, ganho do oscilador com a
  temperatura, piso de ruído, ocupação do espectro. Move `nível`; deixa
  `assinatura` **algebricamente idêntica**, não "quase".
- **Geometria** (`p → p'`): muda `μ_i = A − 10n log₁₀ d_i(p) − W·c_i(p)` de forma
  diferente para cada `i`, porque `d_i` depende de `i`. Move `assinatura`.

O invariante é exato e verificado: no auto-teste, injetar uma deriva senoidal de
**8,2 dB de pico a pico** move a assinatura mediana em **7,1×10⁻¹⁵ dB** — zero de
máquina — e o conjunto de blocos rejeitados é *idêntico* com e sem deriva.

**Limite honesto.** A assinatura é cega a um movimento que escale todas as
distâncias `d_i` pelo mesmo fator. Com N ≥ 3 âncoras não colineares nenhuma
translação física faz isso. Com **N = 2** faz: toda a hipérbole `d₁/d₂ = const` é
invisível. Por isso o código exige N ≥ 2 para formar o vetor e ≥ 4 blocos para
julgar, e por isso um sítio de duas âncoras tem essa checagem fraca.

## 10.4 A falsificação tem de ser cega ao modelo

"Plugado" não **prova** "na mesa": o cabo pode ter sido levado ao sofá. Um rótulo
errado é pior que rótulo nenhum, porque entra no ajuste com peso de verdade.

A tentação é conferir o bloco contra o modelo `A/n/W`. Isso violaria a regra de
[06](06-transferencia.md) §6.4: seria a métrica validando o próprio ajuste, já
que esses blocos vão ajudar a estimar `A/n/W`. O critério usado é **livre de
modelo**:

```
  m = mediana_b { assinatura(y_b) }          (por posto, por conjunto de âncoras)
  s = 1,4826 · mediana_b | assinatura(y_b) − m |
  rejeita b  ⟺  max_i | assinatura(y_b)_i − m_i | / s_i  >  3,5
```

Mediana e MAD dos dois lados porque um único bloco de outro lugar puxaria uma
média e passaria a reprovar os certos; `1,4826 = 1/Φ⁻¹(3/4)` faz a MAD estimar σ
de uma normal (`rousseeuw1993`). O único pressuposto é "o mesmo lugar dá a mesma
forma" — verificável nos próprios dados e falseável.

**O corte é assimétrico de propósito.** Rejeitar um bloco bom joga fora 5 min de
dado gratuito, do qual há centenas de horas; aceitar um bloco ruim injeta um
rótulo falso permanente. MEDIDO: recall 3/3 nos blocos deslocados 2,9 m, ao preço
de 1 falso positivo em 576 blocos (0,2%, coerente com 5 âncoras a 3,5 MAD).

E, crucialmente, o critério mora na assinatura — logo é **cego à deriva
temporal**, que é justamente o sinal que se quer medir. Um critério que
reprovasse blocos por terem sido gravados numa hora barulhenta destruiria o
experimento.

## 10.5 A base: regressão harmônica

Com `τ = (t mod 24 h)/24 h`:

```
  μ(t)      = Σ_{k=1..K} [ a_k cos(2πkτ) + b_k sen(2πkτ) ]
  log σ²(t) = c₀ + Σ_{k=1..K} [ d_k cos(2πkτ) + e_k sen(2πkτ) ]
```

Três decisões, cada uma com consequência mensurável.

**(a) `μ` sem termo constante.** O nível médio já é o `A` de
[01](01-propagacao.md) e o `b` do rastreador. Uma coluna constante aqui seria
colinear com aquele intercepto: `X` perderia posto e a soma ficaria
indeterminada — o problema de calibre de [03](03-estimacao.md), agora de graça
evitado. Sem constante, `∫₀^{24h} μ dt = 0` exatamente, e não há nada a fixar.
`log σ²` **tem** constante, porque o nível de ruído é uma quantidade própria e
ninguém mais o estima.

**(b) Fourier e não 24 baldes de hora.** O cabo não é usado a todas as horas —
sessões 22h→6h cobrem 8/24. Baldes são indicadores de suporte disjunto: a coluna
de uma hora nunca visitada é identicamente zero, o desenho perde posto e o
modelo não tem o que dizer. Uma base contínua interpola dentro da faixa coberta.
Custo: `4K + 1` parâmetros contra 48, o que importa com 6 dias de dado
(`bloomfield2000`).

**(c) `σ²` também varia.** É o ganho que chega ao filtro. Numa hora barulhenta
não basta corrigir a média: aquele RSSI *vale menos*, e o peso é `exp(−z²/2)`
com `z = (r − μ)/σ`. Modelo de heterocedasticidade multiplicativa clássico
(`harvey1976`, `cook1983`).

## 10.6 O viés de `log ε²` é exato e não é opcional

Ajustar a base contra `log ε²` **não** estima `log σ²`. Para `ε ~ N(0, σ²)`,
`ε²/σ² ~ χ²₁`, e

```
  E[ log χ²₁ ] = ψ(1/2) + log 2 = (−γ − 2 log 2) + log 2 = −γ − log 2
               = −1,2703628454614782…

  ⟹  E[ log ε² ] = log σ² − 1,2703628…
```

É uma **constante** — não depende de `σ²` — então entra só em `c₀` e a correção é
exata: some a constante de volta. MEDIDO: sem ela, `σ` sai 44% pequeno demais
(fator `e^{−1,27/2} = 0,53`) e o filtro fica confiante demais em tudo; com ela, a
razão `σ̂/σ` fica em 1,06.

Detalhe que custa amostra: `Var[log χ²₁] = ψ′(1/2) = π²/2`, ou seja **desvio de
2,22 nats por ponto**. A regressão de `log ε²` é intrinsecamente ruidosa; é por
isso que ela precisa das centenas de horas que o cabo dá de graça, e não das
poucas dezenas de minutos de uma campanha andada.

## 10.7 O modelo se cala fora do que viu

A janela do cabo cobre 8 das 24 horas. Extrapolar Fourier para dentro de um
buraco de 16 h não é conservador — é invenção com cara de medição. Cada hora só
"existe" para o modelo se tiver ≥ 3 pontos de treino; fora disso `μ = 0` e a
escala de `σ` é 1, e o rastreador roda exatamente como hoje.

Isso não é higiene: MEDIDO, antes da correção a escala de σ às 03h saía **2,00**
quando a verdade era **1,42**, porque o normalizador era a média sobre 24 h e
2/3 dela eram horas inventadas. Depois: 1,09 contra 1,10.

## 10.8 Promoção: dia inteiro fora, e a régua é NLL

Um modelo com `4K+1` parâmetros ajustado em 6 dias acha ciclo diário em ruído
branco — sempre. A promoção segue [06](06-transferencia.md) §6.3, com a unidade
de retenção sendo **o dia**:

```
  Δ_d = NLL_d( modelo nulo )  −  NLL_d( modelo com K )      [nats/ponto]
        (os dois treinados no mesmo conjunto, sem o dia d)

  promove  ⟺  média(Δ) − ep(Δ) > 0,16   E   min_d Δ_d > 0
```

**Por que o dia inteiro e não pontos sorteados.** Blocos vizinhos de 5 min são
fortemente correlacionados; validação cruzada por ponto vaza a resposta pela
autocorrelação e aprova qualquer coisa (`roberts2017`, `arlot2010`). O dia é a
menor unidade que contém um ciclo completo.

**Por que NLL e não RMSE.** O modelo muda `μ` **e** `σ`. RMSE é cego a `σ`: um
modelo que acerta "esta hora é barulhenta" melhora a calibração sem mexer no
RMSE, e seria reprovado por uma régua que só olha a média. A log-verossimilhança
é uma regra de pontuação estritamente própria para a distribuição preditiva
inteira (`gneiting2007`).

**A margem de 0,16 nats** é os 0,5 dB de [06](06-transferencia.md) convertidos:
um ganho puro de escala vale `log(rms_velho/rms_novo)` nats, e com o `σ` nominal
do rastreador (3,4 dB) melhorar 0,5 dB dá `log(3,4/2,9) = 0,16`.

**O modelo pode — e deve — dizer NÃO.** MEDIDO no auto-teste: em 6 sementes de
ruído branco puro, 6/6 corretamente não promoveram; um ciclo real mas fraco
(μ ±0,3 dB) dá líquido −0,011 e também não passa. Quando nada passa, `ajusta()`
devolve `None` e o rastreador segue como hoje.

## 10.9 O que chega ao rastreador

```
  b   ←  b + μ(t)                    deslocamento comum a todas as âncoras
  σ   ←  σ · escala(t)               escala(t) = σ(t) / σ̄_coberto
```

`escala` é **normalizada** de propósito: o `σ = 3,4 dB` do rastreador já foi
calibrado e é o calibre. Este modelo entrega só a *forma* da variação; se
entregasse `σ` absoluto, os dois estariam estimando o mesmo nível e um
sobrescreveria a calibração do outro em silêncio.

**Armadilha.** `μ(t)` entra na mesma fenda que `tr.b`. Com `b_alfa > 0` os dois
estimam o mesmo deslocamento e brigam — e `b_alfa` é exatamente o reajuste cego
que [06](06-transferencia.md) §6.7 reprovou. Por isso `b_alfa` nasce 0.

## 10.10 Verificação executável

```bash
PYTHONPATH=. python3 -m ferramentas.vigia_usb --demo   # o vigia e o par ini/fim
PYTHONPATH=. python3 -m rtls.oportunidade              # colheita e falsificacao
PYTHONPATH=. python3 -m rtls.modelo.temporal           # ciclo, vies, e o "nao"
RTLS_SITIO=testes/sitio_outro.json PYTHONPATH=. python3 -m rtls.oportunidade
```

Os auto-testes exigem, sem nenhum dado gravado: recuperar `μ` com erro < 0,5 dB e
`σ` com erro < 25%; rejeitar 3/3 blocos deslocados com ≤ 1% de falso positivo;
dar o **mesmo** conjunto de rejeitados com e sem 8 dB de deriva; e **não**
promover nada em 6/6 séries de ruído branco.

Em produção, no host:

```bash
python3 ferramentas/vigia_usb.py --host linux --dir ~/rtls-dados
```

## Referências

`harvey1976` (regressão de `log e²` e a constante −1,2704), `cook1983`
(diagnóstico de heterocedasticidade), `bloomfield2000` (regressão harmônica),
`gneiting2007` (regras de pontuação próprias, por que NLL e não RMSE),
`roberts2017` e `arlot2010` (validação cruzada com estrutura temporal),
`rousseeuw1993` (MAD e o fator 1,4826), `kaemarungsi2004` e `hashemi1993`
(variação temporal medida do RSS indoor) — ver [referencias.bib](referencias.bib).
