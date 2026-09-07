# 00 — Notação, unidades e convenções

Este arquivo fixa os símbolos usados em todos os outros. Se um documento
introduz um símbolo novo, ele o define no lugar; se usa um daqui, usa com
este significado.

## 0.1 Sistema de coordenadas

O sítio vive em métrica, três eixos, origem no canto mínimo do retângulo
envolvente da planta:

| eixo | sentido | unidade |
|------|---------|---------|
| `x`  | cresce para a direita na planta | m |
| `y`  | cresce **para baixo** na planta | m |
| `z`  | cresce para cima (0 = piso)     | m |

O `y` para baixo não é capricho: é a convenção de imagem (linha 0 no topo), e
é a mesma da tela do alvo e dos gráficos gerados. Trocar o sinal de `y` em um
lugar só é o erro mais barato de cometer e o mais caro de achar — a estimativa
espelha e continua "plausível". O teste `rtls/sitio.py:valida()` recusa um
sítio com aresta não ortogonal, e `rtls/modelo/testes.py:recuperacao()` recusa
um modelo cujo parâmetro recuperado saia da faixa; nenhum dos dois pega um
espelhamento global, e por isso a convenção está escrita aqui e é única.

Ângulos de instalação (`yaw` da âncora) em graus, sentido anti-horário na
planta, 0 = a face da placa aponta para `+x`.

## 0.2 Índices

| símbolo | significa |
|---------|-----------|
| `i`, `j` | entidades de rádio (âncoras, alvo, emissores fixos) |
| `i → j` | enlace **dirigido**: `i` transmite, `j` recebe |
| `c` | classe de parede (alvenaria, drywall, vidro, …) |
| `e` | entidade que serve de **obstáculo** (um corpo entre `i` e `j`) |
| `m` | índice de coeficiente do padrão de antena |
| `k` | ponto da campanha de rótulos |
| `t` | instante (s desde o *boot* do receptor, ou epoch do host) |

Uma malha de `N` âncoras tem `N(N−1)` enlaces dirigidos e `N(N−1)/2` pares.
Para `N = 6`: 30 enlaces dirigidos, 15 pares.

## 0.3 Grandezas

| símbolo | nome | unidade | onde nasce |
|---------|------|---------|-----------|
| `y_ij` | RSSI medido no enlace `i→j` | dBm | rádio |
| `p_i` | potência de transmissão de `i` | dBm | firmware (`ptx_niveis_dBm`) |
| `d_ij` | distância euclidiana 3D entre `i` e `j` | m | sítio |
| `A₀` | intercepto a 1 m, isotrópico | dB | ajuste |
| `n` | expoente de perda de percurso | — | ajuste |
| `W_c` | atenuação de uma parede da classe `c` | dB | ajuste (ou tabela) |
| `k_c(i,j)` | quantas paredes da classe `c` o segmento `i→j` cruza | inteiro ≥ 0 | geometria |
| `B_e` | atenuação de corpo cheio da entidade `e` | dB | ajuste |
| `χ_e(i,j)` | fração da 1ª zona de Fresnel que `e` tapa | [0, 1] | geometria |
| `t_i` | ganho/offset da cadeia de **transmissão** de `i` | dB | ajuste |
| `r_j` | ganho/offset da cadeia de **recepção** de `j` | dB | ajuste |
| `c_i` | coeficientes do padrão de antena de `i` | dB (rms) | ajuste |
| `ψ(u)` | base de harmônicos esféricos reais avaliada em `u` | — | fechado |
| `X_ij` | sombreamento de larga escala, **constante por enlace** | dB | aleatório |
| `ε_ij` | ruído por pacote | dB | aleatório |
| `σ_X`, `σ_ε`, `σ_b` | desvios de `X`, `ε` e do offset por rádio | dB | ajuste |
| `λ` | comprimento de onda (2,44 GHz → 0,1229 m) | m | constante |

**Convenção de sinal.** Todas as perdas entram **subtraindo**. Uma parede de
6 dB reduz o RSSI em 6 dB. `A₀` é negativo (≈ −45 dBm a 1 m com `p = 0` dBm).

**dB e dBm.** `y` e `p` são níveis absolutos (dBm); `A₀`, `W`, `B`, `t`, `r`,
`c`, `X`, `ε` são razões (dB). Somar dBm com dB é legítimo; somar dBm com dBm
não é, e é o erro que produz um modelo que "ajusta bem" e não transfere.

## 0.4 Aleatoriedade: três níveis distintos

Confundir os três é a causa mais comum de intervalo de confiança errado.

1. **`X_ij` — sombreamento.** Sorteado uma vez por enlace (por par
   antena-antena-canal) e **constante** enquanto nada se move. É recíproco:
   `X_ij = X_ji`. Média de 10 000 pacotes não o reduz.
2. **`ε_ij[t]` — ruído por pacote.** Independente entre pacotes. Média de `M`
   pacotes o reduz por `√M`.
3. **`b_i` — offset por rádio.** Sorteado uma vez por placa, na fábrica.
   Constante para sempre. É o que `t_i`/`r_i` estimam.

Consequência operacional: `M` pacotes num enlace parado dão erro padrão da
média igual a `σ_ε/√M`, **não** `√(σ_X² + σ_ε²)/√M`. Quem usa a fórmula errada
declara uma precisão que não tem, e depois se surpreende com a transferência.
Ver [06-transferencia.md](06-transferencia.md).

## 0.5 Notação matricial do ajuste

Empilhando todos os enlaces observados:

```
  z = X θ + η ,        z_l = y_l − p_l  (resíduo já descontada a Ptx)
```

- `z ∈ ℝ^L` — as `L` observações agregadas (uma por enlace-condição);
- `X ∈ ℝ^{L×P}` — matriz de projeto, colunas nomeadas
  (`A0`, `n`, `W:alvenaria`, `B:pessoa`, `t:3`, `r:5`, `c:2:1`, …);
- `θ ∈ ℝ^P` — parâmetros;
- `η` — erro, `Cov(η) = Σ`.

`X` é construída por `rtls/modelo/nucleo.py:Desenho.linha()`. **Toda a
identificabilidade do sistema é o posto de `X`** (mais as restrições de calibre
da §03), e é por isso que o modelo é deliberadamente linear em `θ` — ver
[03-estimacao.md](03-estimacao.md).

## 0.6 Onde cada símbolo vira código

| símbolo | arquivo |
|---------|---------|
| `d`, `k_c` | `rtls/sitio.py:paredes()`, `rtls/tracker.py` |
| `χ_e` | `rtls/modelo/nucleo.py:obstrucao()` |
| `ψ` | `rtls/modelo/nucleo.py:psi()` |
| `X`, `θ` | `rtls/modelo/nucleo.py:Desenho` |
| `A₀, n, W` | `rtls/ajuste.py` |
| `σ_X, σ_ε` | `ferramentas/simula.py:VERDADE`, `rtls/revisao.py` |
| limiar de detecção | `sitios/*.json` → `radio.limiar_deteccao_dBm` |

## Referências

Ver [referencias.bib](referencias.bib). As entradas citadas neste arquivo:
`rappaport2024`, `itu-p1238`.
