# 08 — Sombreamento por corpo, tomografia e ocupação

> Código: `ferramentas/tomografia.py`, `rtls/modelo/nucleo.py:obstrucao()`,
> `rtls/estaticos.py`

Até aqui o alvo **carrega um rádio**. Este documento trata do caso em que o alvo
**não carrega nada**: o corpo é detectado porque atenua os enlaces entre âncoras.
É a mesma malha, o mesmo hardware, o mesmo dado — outra pergunta.

## 8.1 O corpo como obstrução: o termo χ

Um corpo em `q` entre o transmissor `p_i` e o receptor `p_j` remove uma fração da
primeira zona de Fresnel. O modelo de peso usado (§01, `nucleo.py:obstrucao()`) é

```
  χ(q) = exp( −(ρ / L)² ) ,    ρ = distância de q à reta i–j
                               L = hypot(κ F₁, raio do corpo)
                               F₁ = √(λ d₁ d₂ / d)      (1ª zona de Fresnel)
```

`F₁` é o raio da zona no ponto onde o corpo está — máximo no meio do enlace,
estreito perto das pontas. O `hypot` com o raio do corpo é o que impede que um
corpo de 0,25 m "desapareça" perto de uma âncora, onde `F₁ → 0`: a largura
efetiva nunca cai abaixo da largura física do obstáculo.

Exemplo numérico a 2,44 GHz (`λ = 12,3 cm`), enlace de 5 m, corpo no meio:
`F₁ = √(0,123 · 2,5 · 2,5 / 5) = 0,392 m`. Um corpo de 0,25 m de raio dá
`L = hypot(0,392·κ, 0,25)`, isto é, um cone de sensibilidade de **dezenas de
centímetros** — não um raio de espessura zero. Nenhum modelo de "linha reta
cortada" reproduz isso.

## 8.2 Tomografia por rádio (RTI)

A formulação canônica é a de Wilson & Patwari (`wilson2010`). O campo de
atenuação `x` é discretizado em pixels e cada enlace mede uma integral de linha
ponderada:

```
  y = W x + n ,    W_{k,l} = 1/√(d_k)  se  d₁+d₂ − d_k < λ_e ,  senão 0
```

O `1/√d` faz o enlace longo pesar menos (a mesma atenuação está diluída em mais
caminho). Isso é **subdeterminado por construção**: `N` âncoras dão
`N(N−1)/2` enlaces contra centenas de pixels — 15 equações para ~400 incógnitas
com 6 âncoras. A solução é regularização com prior espacial exponencial:

```
  C_x[k,l] = σ_x² exp(−d_kl / δ_c)                    (δ_c ≈ 4 m, σ_x² ≈ 0,4)
  x̂_MAP = (WᵀW + C_x⁻¹ σ_n²)⁻¹ Wᵀ y                   (σ_n² ≈ 10 dB²)
```

Dois detalhes de implementação que importam:

- **Forma dual.** Com poucos enlaces e muitos pixels, resolva no espaço dos
  enlaces: `x̂ = Wᵀ (WWᵀ + αI)⁻¹ y`, invertendo uma matriz `15×15` em vez de
  `400×400`. Idêntico algebricamente, ordens de grandeza mais barato.
- **O projetor é constante.** `Π = (WᵀW + C_x⁻¹σ_n²)⁻¹Wᵀ` depende só da
  geometria. Calcule uma vez na instalação; em tempo real a imagem é um
  produto matriz-vetor.

Da imagem para a posição: centroide dos pixels fortes, com peso `x³` e corte em
metade do máximo — a potência cúbica suprime a cauda difusa da regularização,
que de outro modo puxa o centroide para o centro do cômodo.

## 8.3 Movimento, não presença — o resultado que mais restringe o produto

Este é o achado que define o que a malha pode e não pode prometer. Duas
ausências reais no mesmo dia (uma rotulada, uma cega), 29 enlaces
âncora↔âncora.

**O que funciona: jitter, sem linha de base.** Média de RSSI por enlace por
minuto; estatística = **mediana sobre os enlaces de `|Δ| entre minutos
consecutivos|`**:

```
  J(t) = mediana_e | ȳ_e(t) − ȳ_e(t−1) |          [dB]
```

Sem referência, sem calibração, sem deriva. Medido: casa vazia ≈ **0,30 dB**;
casa em uso ≈ **0,60–0,90 dB**. Um limiar tirado só da janela rotulada
(0,489 dB) encontrou a ausência **cega** e nada mais no período. Em janelas de
30 s a borda de **volta** sai exata (0,95 → **1,76 dB** no minuto do retorno); a
borda de **saída** é mais mole — a casa esvazia gradualmente.

**O que NÃO funciona: assinatura de nível.** Projetar o desvio de cada minuto no
template de nível da janela rotulada **não generaliza**:

| | escala mediana |
|---|---|
| na própria janela (por construção) | +0,95 |
| numa ausência real 1 h depois | **+0,14** |
| casa ocupada | +0,05 a +0,07 |

Correlação entre os dois padrões de "vazio": **r = +0,10**. Um par recíproco
chegou a **inverter o sinal** (+1,8 → −3,4 dB nos dois sentidos). Ser recíproco
prova que é **física, não ruído** — ~5 dB de excursão num caminho inteiramente
dentro do mesmo cômodo.

**Consequência para o modelo e para o produto:**

> "Vazio" não é um estado de RF. É um estado de RF **daquela configuração de
> móveis, portas e objetos**. Fingerprint de *nível* para ocupação tem validade
> de menos de uma hora. Fingerprint de *variação* atravessa.

E a limitação não removível: **pessoa parada lê como casa vazia.** Uma varredura
cega marcou 84 min como "vazio" enquanto havia alguém sentado ao computador. A
malha detecta **movimento**. Qualquer requisito de produto escrito como
"detecta presença" está errado por construção; ver os critérios de aceite em
`docs/user-stories.md`.

## 8.4 O banco de teste sem trena: emissores estáticos

Há um teste de resiliência que não custa nenhum rótulo humano. As âncoras já
registram **todo** anunciante BLE do ambiente, e vários deles (servidor,
computador, TV, teclado) estão **parados** o dia inteiro.

Não se sabe onde cada um está. Não é preciso: sabe-se que **nenhum se mexe**,
logo todo passeio na estimativa é erro do filtro — medido em vários rádios
independentes, nenhum deles usado para calibrar nada.

Métrica: passeio em m/min da estimativa. Medido em 2 h, antes → depois do modo
parado/andando + tempering (§04):

```
  47,6 → 7,1     53,8 → 6,3     18,4 → 4,8     32,5 → 15,3
  20,1 → 2,2      7,3 → 1,4      7,0 → 1,4
```

Achado colateral com consequência de privacidade: dois endereços pousaram no
**mesmo ponto** (dentro de 8 cm) — são dois MACs do mesmo aparelho. **A rotação
de endereço BLE não sobrevive ao perfil de RSSI.** A trilha é a identidade. Isso
é um fato do sistema, não uma escolha de projeto, e é o que obriga o tratamento
de dados descrito em `docs/PRIVACIDADE.md`.

## 8.5 Verificação executável

```bash
PYTHONPATH=. python3 -m ferramentas.tomografia   # ensaio RTI sintetico, 1 e 2 alvos
PYTHONPATH=. python3 -m rtls.estaticos           # auto-teste: emissor parado -> passeio ~0
```

## Referências

`wilson2010` (RTI), `wilson2011` (variance-based RTI — a base teórica do jitter),
`patwari2008`, `kaltiokallio2014` (detecção por variância), `ghaddar2007` (corpo
humano a 2,4 GHz), `obayashi1998` — ver [referencias.bib](referencias.bib).
