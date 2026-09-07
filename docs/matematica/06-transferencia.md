# 06 — Transferência: o que decide se um modelo entra em produção

> Código: `rtls/modelo/padrao.py:lopo()`, `padrao.py:promove()`, `rtls/loo.py`,
> `rtls/revisao.py`

Este documento é uma regra de decisão, não um método de estimação. É o que
separa um bloco de modelo que **funciona** de um que só **ajusta**.

## 6.1 O problema

Adicionar parâmetros sempre reduz o resíduo do ajuste. Sempre. Para `P₂ > P₁`
parâmetros aninhados,

```
  RSS(P₂) ≤ RSS(P₁)      identicamente, por álgebra linear
```

Então "o resíduo caiu de 4,2 para 2,6 dB" não é evidência de nada. Neste
projeto, **quatro** blocos de modelo reduziram o resíduo e **reprovaram** na
transferência:

| bloco | o que prometia | desfecho |
|-------|----------------|----------|
| mapa de material da nuvem 3D | absorção por superfície real | reprovado |
| offset escalar por âncora | calibração de placa | reprovado |
| ganho direcional (padrão) | 5–10 dB de anisotropia | reprovado 3× |
| bloco de altura | curva `z`, `z²` | reprovado como estava |

Nenhum deles é errado como física. Todos falharam pelo mesmo motivo: o efeito
existe, mas o instrumento não o resolve num ponto **novo**.

## 6.2 O critério: LOPO com o modelo em produção como controle

**Leave-One-Point-Out** (LOPO), não leave-one-observation-out:

```
  para cada ponto q da campanha:
      ajustar θ̂_{−q}  usando TODOS os pontos exceto q
      prever as âncoras de q com θ̂_{−q}
      erro_q = resíduos daquele ponto
```

Duas exigências que a maioria das validações cruzadas de RSSI erra:

**(a) A unidade é o PONTO, não a observação.** As 3–5 âncoras de um mesmo ponto
erram **juntas**: mesma postura, mesmo corpo, mesma parede, mesmo `X_ij`. São
uma observação correlacionada, não 5 independentes. Tratá-las como 5 divide o
erro padrão por `√5` e promove ruído sistematicamente.

**(b) O ponto sai do ajuste inteiro, não só da predição.** Se `q` participa do
ajuste do padrão das âncoras que ele mesmo vai testar, o teste está contaminado.

**(c) O controle é o modelo IMPLANTADO, não o modelo nulo.** O `lopo()` roda
três arranjos: `grau=None` (o modelo em produção, só `A/n/W`), `grau=0` (offset
escalar) e `grau=1` (padrão dipolar). A pergunta não é "o modelo novo é melhor
que nada" — é "**o modelo novo é melhor que o que já está no ar**". Um bloco que
perde para `A/n/W` sozinho não entra, por mais elegante que seja.

## 6.3 A regra de promoção

```
  Δ_q = rms( erro_q | modelo em produção ) − rms( erro_q | modelo novo )     [dB]

  ganho_líquido = média(Δ) − se(Δ)  ,     se(Δ) = desvio(Δ) / √(#pontos)

  promove  ⟺  ganho_líquido > margem       (margem = 0,5 dB)
```

Ou seja: **o ganho médio por ponto tem de sobreviver a um erro padrão.**

A razão é o tamanho da amostra. Com 3 a 8 pontos, o rms global tem incerteza da
ordem do próprio ganho perseguido. Exigir apenas `rms_novo < rms_produção −
margem` promoveria ruído com alta frequência. Subtrair um erro padrão é uma
regra conservadora deliberada: aproximadamente um teste `t` unicaudal a ~16%,
mas aplicada como **limiar de decisão**, não como teste de hipótese — o custo
de promover um modelo ruim (deriva silenciosa em produção) é muito maior que o
de adiar um bom.

Complemento: **se um único ponto piora, não promove.** Um ganho médio positivo
com um ponto muito pior significa que o bloco novo está ajustando estrutura
local, não física transferível.

## 6.4 Por que resíduo não decide — o princípio geral

> **Uma métrica não pode validar o próprio ajuste. É preciso encontrar um
> invariante que a resposta errada viole.**

Esta é a regra mais reutilizável do projeto e se aplica muito além de RTLS.
Exemplos concretos aqui:

| pergunta | métrica que NÃO vale | invariante que vale |
|----------|----------------------|---------------------|
| a reconstrução 3D está alinhada? | IoU do próprio ajuste | picos de histograma nos eixos de Manhattan |
| o modelo de propagação presta? | rms do ajuste | LOPO contra o modelo implantado |
| o dado está censurado? | resíduo (fica **menor**) | inclinação RSSI×Ptx = 1 |
| as cadeias TX/RX estão certas? | ajuste | soma antissimétrica em triângulo = 0 |
| a posição está certa? | espalhamento da nuvem | LOO de âncora (gabarito de graça) |

Ver [07-invariantes.md](07-invariantes.md) para os invariantes em detalhe.

## 6.5 O gabarito de graça: LOO de âncora

`rtls/loo.py` esconde uma âncora, localiza-a com as outras `N−1` e compara com a
posição do sítio. Isso é validação com **verdade conhecida e nenhum rótulo
humano**: a posição da âncora é medida uma vez, na instalação, e vale para
sempre.

É o teste mais barato do projeto e o que se roda primeiro em qualquer sítio
novo. Referência no sítio de exemplo com dados simulados: mediana 1,64 m, pior
3,61 m, cômodo correto em 6/6.

Limitação honesta: a âncora está numa parede, a 0,30 ou 1,10 m, e uma pessoa
está no meio do cômodo a 1,1 m. O LOO valida a geometria e o modelo de
propagação; **não** valida a resposta do sistema a um corpo humano. Para isso é
preciso a campanha rotulada.

## 6.6 O caso da altura: quando reprovar é o resultado certo

A campanha de altura mediu 21,5 dB entre 0,05 e 1,65 m no mesmo `(x,y)`, e uma
âncora mais distante chegar 9,9 dB mais forte por estar mais alta. O efeito é
enorme e real.

Ainda assim, o bloco `z`/`z²` não foi promovido como estava. Motivo: com os
pontos disponíveis o LOPO não mostrou ganho líquido acima da margem — o efeito
é grande, mas **específico do ponto** (multipercurso vertical local), não uma
curva suave que se transfira. A resposta correta não é forçar a promoção; é
desenhar uma campanha que separe curva de multipercurso local, que é o que a
§05 faz com os verticais repetidos.

Registrar uma reprovação com o número é mais útil que um bloco ligado por fé.

## 6.7 O anti-padrão: reajuste cego automático

Modo de falha observado e corrigido: um serviço que reajusta o modelo
periodicamente e promove sozinho o resultado. Sem controle de transferência,
cada reajuste incorpora o resíduo estrutural do momento, e o sistema **deriva**
— cada passo parece melhor pelo resíduo e o conjunto piora.

`rtls/revisao.py` implementa a revisão com **juiz**: o modelo candidato só
substitui o vigente se vencer na transferência. Um `cron` que reescreve o
modelo sem esse juiz é a forma mais rápida de degradar um RTLS em produção.

## 6.8 Verificação executável

```bash
PYTHONPATH=. python3 -m rtls.loo                 # LOO de ancora: gabarito de graca
PYTHONPATH=. python3 -m rtls.modelo.padrao       # LOPO + regra de promocao
PYTHONPATH=. python3 -m rtls.revisao             # revisao com juiz
```

## Referências

`stone1974` (validação cruzada), `arlot2010` (revisão de seleção por CV),
`roberts2017` (CV com dados estruturados/correlacionados — o argumento do
bloco), `hastie2009` (§7) — ver [referencias.bib](referencias.bib).
