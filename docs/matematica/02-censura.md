# 02 — Censura: o erro que parece dado

> Código: `rtls/modelo/padrao.py:extrai()`, `ferramentas/simula.py`,
> `sitios/*.json → radio.limiar_deteccao_dBm`

Este é o documento mais importante do conjunto. A censura é a única falha
deste sistema que **não aparece como erro**: ela aparece como um ajuste
excelente com um parâmetro absurdo, e um usuário que não a conheça vai
concluir a coisa errada com muita confiança.

## 2.1 O mecanismo

Um pacote BLE cujo RSSI cai abaixo do piso de captura do rádio **não gera
linha nenhuma**. Não gera `-120 dBm`, não gera `NaN`: não existe. O receptor
não sabe que houve uma transmissão.

Isso é **censura à esquerda com limiar aleatório**, não truncamento
determinístico: o mesmo enlace, na mesma potência, às vezes chega e às vezes
não, porque `ε` varia pacote a pacote. Formalmente, o pacote `t` do enlace
`i→j` é observado com probabilidade

```
  P[observar] = P[ μ_ij + ε > τ ] = Φ( (μ_ij − τ) / σ )
```

com `τ` = limiar prático de captura e `Φ` a normal acumulada. Este é o modelo
*probit* de detecção, e é ele que a busca da campanha usa como peso
(ver [05](05-campanha-dotima.md)).

Valores calibrados neste projeto, por máxima verossimilhança sobre 54 desfechos
observados/não-observados de uma campanha real:

```
  τ = −90,75 dBm        σ = 7,75 dB
```

que entram em `sitios/exemplo.json` como `limiar_deteccao_dBm` e
`sigma_deteccao_dB`. O desenho anterior usava `τ = −96`, `σ = 4,1`: ele
esperava 43 enlaces e a campanha colheu 33. **A recalibração é a diferença
entre uma campanha que fita e uma que não.**

Note que `σ = 7,75 dB` é maior que `σ_ε = 2,2 dB` da [§01](01-propagacao.md).
Não é contradição: o `σ` da detecção absorve também a variação de `X` entre
enlaces e o erro do próprio `μ` previsto. É um `σ` de **predição**, não de
repetição.

## 2.2 Por que três pisos diferentes no JSON

`sitios/exemplo.json` traz três números que parecem redundantes e não são:

| campo | valor | o que é |
|-------|-------|---------|
| `piso_radio_dBm` | −101 | sensibilidade de folha de dados do rádio |
| `piso_dBm` | −95 | piso prático de captura de *advertising* BLE |
| `limiar_deteccao_dBm` | −90,75 | limiar **efetivo** ajustado ao dado |

O primeiro é físico. O segundo é o que se observa na prática, porque um
*advertising* precisa de preâmbulo + CRC íntegros e o scanner só olha o canal
uma fração do tempo. O terceiro é o que o modelo deve usar, e é maior que os
outros dois porque incorpora perda de janela de varredura e colisão.

Usar `piso_radio_dBm` como limiar de detecção é um erro comum e silencioso: o
desenho de campanha passa a esperar enlaces que nunca vão chegar.

## 2.3 O sintoma: a inclinação que colapsa

O teste que separa dado bom de dado censurado é a **inclinação de RSSI contra
Ptx**. Se o rádio varre `p ∈ {−12, −9, …, +9} dBm` num ponto fixo, o modelo diz

```
  ∂ E[y] / ∂ p = 1,00     exatamente, por construção
```

porque `p` entra somando. Não há física a estimar aqui: é uma identidade.

Sob censura ela desaba. Em `p` baixo, só os pacotes cujo `ε` foi
**favorável** chegam. A média condicional dos observados é a média de uma
normal truncada:

```
  E[ y | y > τ ] = μ + σ · φ(α) / (1 − Φ(α)) ,     α = (τ − μ)/σ
```

O segundo termo é a **razão inversa de Mills**, e ela é grande justamente
quando `μ` é baixo. Ou seja: baixar `p` **sobe** o viés e a média medida quase
não desce. Medido neste projeto, num enlace fraco: inclinação **+0,06** onde
deveria ser 1,00.

Consequências em cadeia, todas plausíveis à primeira vista:

- o RSSI "não responde" à potência → o ajuste conclui que a distância importa
  pouco → **`n` cai** para perto de zero;
- a média por enlace fraco é otimista → o modelo prevê alcance maior do que há;
- o resíduo fica **pequeno**, porque os pontos difíceis simplesmente não estão
  na amostra. O ajuste parece ótimo.

Este último é o ponto: **a censura melhora o resíduo do próprio ajuste.**
Nenhuma métrica interna a detecta. É a razão da regra em
[07-invariantes.md](07-invariantes.md): *uma métrica não pode validar o próprio
ajuste; é preciso um invariante que a resposta errada viole.*

## 2.4 A defesa: rejeitar, não corrigir

Existem duas saídas para censura: modelar (regressão *tobit*, verossimilhança
com o termo `Φ`) ou rejeitar a amostra contaminada. Este projeto **rejeita**.

Razão: o *tobit* recupera `μ` bem quando o limiar é conhecido e fixo. Aqui `τ`
é ele próprio estimado, com `σ = 7,75 dB` de incerteza, e a agregação já é por
janela. O ganho de modelar não paga o risco de errar `τ` — e errar `τ` produz
exatamente o mesmo viés que se quis remover, agora escondido dentro de um
estimador mais complicado.

`rtls/modelo/padrao.py:extrai()` aceita uma amostra `(ponto, rx)` só se:

```
  n_pacotes  ≥ 20                 # erro padrão da média ≤ σ_ε/√20 ≈ 0,5 dB
  média      ≥ −90 dBm            # acima do limiar, com margem
  inclinação ∈ 1,00 ± 0,35        # a identidade da §2.3
```

A tolerância de 0,35 não é arbitrária: com 8 níveis de Ptx cobrindo 21 dB e
`σ_ε = 2,2 dB` com ~20 pacotes por nível, o erro padrão da inclinação estimada
por mínimos quadrados é

```
  se(β) = σ_ε / ( √M · sd(p) )  ≈  2,2 / ( √160 · 6,7 )  ≈  0,026
```

logo 0,35 são ~13 desvios: a faixa não corta ruído, corta **censura**. Um
enlace saudável passa com folga; um enlace com 10% de perda por censura já cai
para ~0,6 e é rejeitado.

## 2.5 A unidade de agregação importa

Erro cometido e corrigido durante o desenvolvimento: agrupar por `rx` apenas.
Um ponto forte e um ponto fraco no mesmo receptor se misturam, a inclinação
média fica boa e a censura passa despercebida.

A unidade correta é **`(ponto, rx)`** — a mesma janela que `extrai()` usa — e é
por isso que a campanha grava `rotulos.jsonl` com `(ini, fim)` por ponto: a
janela de rótulo *é* a unidade estatística.

`ferramentas/simula.py:selftest()` verifica exatamente isso: gera um enlace
forte e um censurado, agrupa por `(ponto, rx)`, e exige inclinação ≈ 1 no forte
e < 0,85 no fraco. Se alguém "otimizar" a agregação de volta para `rx`, o teste
falha.

## 2.6 Por que o simulador precisa de censura

Um simulador de RSSI que não censura produz dados **fáceis demais**: qualquer
estimador acerta, e o pipeline passa nos testes enquanto quebra em campo. Por
isso `ferramentas/simula.py` implementa a censura (`piso_dBm`) e o selftest
exige ver o colapso da inclinação. É a parte que a maioria dos simuladores de
RSSI erra, e é a única com valor de teste real.

## 2.7 Como diagnosticar num dado novo

```bash
# 1. quantos enlaces sobreviveram ao filtro?
PYTHONPATH=. python3 -m rtls.campanha medir           # imprime aceitos/rejeitados

# 2. a distribuicao de RSSI encosta no piso?
#    se o histograma tem uma parede vertical perto de -90, ha censura.
PYTHONPATH=. python3 -m ferramentas.malha_viz
```

Sinais de censura num conjunto novo:

- `n` estimado < 1,0 num ambiente fechado;
- histograma de RSSI com corte abrupto (não cauda) na esquerda;
- contagem de pacotes que **cai** com a distância mais rápido que 1/d²;
- inclinação RSSI×Ptx < 0,8 em qualquer janela.

Remédio, em ordem de preferência: subir a Ptx do transmissor; aproximar as
âncoras; aumentar a janela de varredura; por último, remover o enlace do
ajuste. Nunca: baixar o limiar para "aproveitar mais dados".

## Referências

`tobin1958` (regressão censurada), `heckman1979` (viés de seleção e a razão
de Mills), `greene2018` (§19, censura e truncamento) — ver
[referencias.bib](referencias.bib).
