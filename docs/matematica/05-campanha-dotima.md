# 05 — Campanha D-ótima: onde ficar de pé

> Código: `rtls/modelo/testes.py:campanha_dotima()`,
> `rtls/modelo/padrao.py:desenho()`, `ferramentas/gera_firmware_alvo.py`

A [§03](03-estimacao.md) mostrou que a malha sozinha é cega para parte dos
parâmetros. A campanha compra as direções que faltam: alguém anda pela casa com
o alvo e marca onde está. É a etapa mais cara do projeto em tempo humano, então
**onde ficar de pé é uma pergunta de desenho de experimentos, não de intuição.**

## 5.1 O critério

Cada ponto candidato `p` acrescenta `2N` linhas à matriz de projeto (cada
âncora ouve o alvo e é ouvida por ele). A informação de Fisher de um modelo
linear gaussiano é

```
  F(θ) = Xᵀ Σ⁻¹ X          (não depende de θ — modelo linear)
```

e `Cov(θ̂) = F⁻¹`. Como não interessa toda a matriz — interessa o bloco dos
coeficientes que a malha não vê — o critério é a **D-otimalidade restrita ao
bloco** `I` de interesse [`fedorov1972`, `pukelsheim2006`, `atkinson2007`]:

```
  maximizar   Φ(S) = − log det [ (F₀ + Σ_{p∈S} I_p)⁻¹ ]_{I,I}
```

`F₀` é a informação já disponível (malha + pontos já andados). O sinal negativo
e a inversão fazem com que `Φ` seja "informação efetiva no bloco": subir `Φ` é
encolher o elipsoide de confiança **daqueles** parâmetros.

Por que D e não A ou E:

- **D** (determinante) é invariante a reparametrização linear do bloco — não
  depende de eu escrever o padrão em harmônicos ou em outra base equivalente;
- **A** (traço) depende da escala de cada coordenada, e as coordenadas aqui têm
  significados diferentes;
- **E** (menor autovalor) otimiza o pior caso e, na prática, gasta a campanha
  inteira na direção mais difícil.

## 5.2 O log det não decide sozinho: `σ_c`

`log det` é adimensional e cresce sem escala interpretável. Ao lado dele o
código reporta

```
  σ_c(F) = σ_transf · √( média dos elementos diagonais de F⁻¹ no bloco )
```

que é o **desvio típico que sobra em cada coeficiente de padrão, em dB**. Esse
é o número que decide se a campanha vale: o efeito perseguido vale 5–10 dB, e a
campanha só paga se `σ_c` cair bem abaixo disso. Referência da campanha real:
incerteza do bloco 4,2 → 2,6 dB em 8 pontos.

Sem `σ_c`, um `log det` de −112,9 → 61,3 parece ótimo e não informa nada sobre
se o experimento resolve a pergunta.

## 5.3 O peso que muda tudo: probabilidade de o enlace existir

Erro cometido na primeira campanha real: o desenho contava 6 âncoras por ponto
e devolveu três pontos. Na medição, o cômodo isolado entregou 2 âncoras e a
cozinha 3. O desenho esperava 43 enlaces e colheu 33; **o ajuste não fitou.**

A causa não era geometria — era o **piso** ([§02](02-censura.md)). Uma linha da
matriz de projeto só informa se aquele enlace **existir**. A busca refeita pesa
cada linha pela probabilidade de detecção:

```
  P_a(p) = Φ( (μ_a(p) − τ) / σ_det )     τ = −90,75 dBm, σ_det = 7,75 dB
  I_p = Σ_a  P_a(p) · ℓ_a ℓ_aᵀ
```

Isto é exatamente o desenho ótimo com **observações faltantes aleatórias**: a
informação esperada é a soma das informações pesadas pela probabilidade de
observar [`atkinson2007`, §17]. E há um corte duro: um candidato com
`Σ_a P_a < MIN_ANC` é descartado, porque um ponto que ouve 2 âncoras não é
"um ponto pior", é um ponto que não fecha.

O efeito prático é grande: a busca deixa de escolher o canto mais distante (que
maximiza ângulo e minimiza detecção) e passa a escolher pontos que combinam
ângulo novo **com** enlaces que chegam.

## 5.4 Algoritmo: guloso, e por quê

Escolher `k` de ~250 candidatos exaustivamente são `C(250,8) ≈ 3·10¹⁴`
avaliações. O código é guloso: escolhe um ponto por vez, o que mais sobe `Φ`.

Isso não é só preguiça — tem garantia. `log det` é **monótona e submodular** no
conjunto de linhas escolhidas, e para maximização de função submodular monótona
sob restrição de cardinalidade o guloso atinge pelo menos `(1 − 1/e) ≈ 63%` do
ótimo [`nemhauser1978`]. Na prática, com um bloco pequeno, fica muito mais
perto que isso. O ganho de exaustivo não paga.

Saída típica no sítio de exemplo (`python3 -m rtls.modelo.testes`):

```
  1. ( 5,50,  0,30)   log det  −42,95   (+69,95)
  2. ( 1,90,  5,10)   log det   15,87   (+58,81)
  3. ( 0,30,  0,30)   log det   38,13   (+22,27)
  ...
  8. ( 7,50,  0,30)   log det   61,26   (+ 2,68)
```

**A coluna de ganho é o critério de parada.** Ela cai de ~70 para ~2,7: os
primeiros três pontos valem 150 das 174 unidades de `log det`, e o oitavo vale
2,7. Uma campanha de 3 pontos captura a maior parte do valor; a partir do 6º o
tempo humano rende pouco. Quem tiver 20 minutos faz três pontos, não oito.

## 5.5 Separação mínima: geometria e tela

Dois pontos colados são quase a mesma linha de projeto (ganho quase nulo) **e**
dois círculos que se cobrem na tela do alvo, onde o dedo não consegue escolher
entre eles — o rótulo deixa de ser atribuível. Daí a restrição

```
  ‖p_i − p_j‖ ≥ minsep ,      minsep = 2 · RAIO_px / escala_px_por_m
```

`ferramentas/gera_firmware_alvo.py` calcula `minsep` **a partir da escala da
tela**, que por sua vez sai do tamanho do sítio. Num sítio grande a escala cai
e a separação exigida sobe — o que é correto tanto na tela quanto no desenho.

## 5.6 A dimensão que a malha nunca vê: altura

As âncoras ficam em duas ou três alturas. Um efeito de `z` se disfarça de
efeito de `d`, e foi medido em 21,5 dB (ver [03](03-estimacao.md) §3.6).

O desenho da campanha resolve por construção, e não por otimização:

- **uma altura por aba** da tela do alvo (`ALTURAS = 0,05 / 0,85 / 1,65 m`);
- **o primeiro ponto de cada aba é sempre o mesmo `(x,y)`**.

Os três avistamentos desse ponto formam um **contraste puro em `z`**: mesma
distância horizontal, mesmas paredes, mesmas âncoras. A diferença entre eles
estima a curva de altura sem passar pelo modelo — não depende de `A₀`, `n` nem
`W`. É a medida mais barata e mais robusta da campanha inteira, e é a que se
faz primeiro se houver risco de a campanha ser interrompida.

As alturas escolhidas não são uniformes de propósito: 0,05 m fica no lóbulo de
reflexão de terra, 1,65 m acima da cabeça, 0,85 m no meio. Um `z` e um `z²`
precisam de três alturas para serem identificáveis; três alturas *bem
separadas* dão a melhor condicionamento possível com o mínimo de trabalho.

## 5.7 Protocolo de medição no ponto

Um ponto de campanha não é um instante, é uma **janela**:

1. o alvo transmite ciclando os 8 níveis de Ptx (`−12 … +9 dBm`), `REF_MS =
   6 s` por nível → um ciclo completo leva **48 s**;
2. permanência útil por ponto: 2–3 min = 2 a 4 ciclos;
3. o toque em INICIAR e em FINALIZAR marca `(ini, fim)`, e o par vai por UDP na
   hora — três vezes, com dedup por `(seq, ev)` no servidor.

A varredura de Ptx **não é opcional**: é ela que torna a campanha separável. A
inclinação RSSI×Ptx num ponto fixo é uma identidade conhecida (§02), e é o
único teste que detecta censura. Um ponto medido em Ptx fixa produz um número
que não dá para validar.

Regra operacional: **congelar o rádio antes de andar.** Trocar Ptx, canal ou
intervalo de anúncio no meio de um ponto invalida a janela inteira, porque a
janela é a unidade estatística.

## 5.8 Por que o rótulo no aparelho e não no caderno

O sistema acumula centenas de milhares de avistamentos e pouquíssimos rótulos.
O rótulo é o insumo escasso, e anotar hora à mão é onde a campanha morre —
relógio do caderno contra relógio do servidor, erro de minutos, janelas
deslocadas.

No alvo, o início e o fim da janela **são o toque**. Sem transcrição, sem
sincronismo de relógio, sem digitação posterior.

E vai por UDP no instante, não por cartão SD no fim: o alvo já está associado
com IP; gravar tudo no cartão e mandar no final cria o modo de falha em que a
campanha inteira mora no cartão até o fim. Cada evento vai 3× (UDP cai) e o
servidor deduplica.

## 5.9 Do desenho ao firmware, sem cópia à mão

`ferramentas/gera_firmware_alvo.py` gera `firmware/alvo-cyd/src/sitio_gerado.h`
a partir do sítio + do desenho: MACs, posições de âncora, paredes com os vãos
abertos, pontos da campanha, escala e orientação da tela.

Antes, esses números eram cópia à mão dentro do `.cpp`, com um comentário
pedindo "se a planta mudar, estes números TÊM de vir junto". Promessa em
comentário não segura nada: quando a planta muda e o firmware não, o alvo
rotula a campanha nova com as coordenadas velhas, e **o rótulo continua
chegando, só que errado** — silencioso e a montante de tudo.

`--confere` regenera em memória e compara byte a byte com o arquivo em disco. É
o que a CI roda, e não precisa de placa. Ver [CI-CD.md](../CI-CD.md).

## 5.10 Verificação executável

```bash
PYTHONPATH=. python3 -m rtls.modelo.testes                      # busca D-otima + tabela de ganho
PYTHONPATH=. python3 ferramentas/gera_firmware_alvo.py --demo   # desenho + ajuste de tela
PYTHONPATH=. python3 ferramentas/gera_firmware_alvo.py --confere
```

## Referências

`fedorov1972`, `pukelsheim2006`, `atkinson2007`, `nemhauser1978`,
`chaloner1995` — ver [referencias.bib](referencias.bib).
