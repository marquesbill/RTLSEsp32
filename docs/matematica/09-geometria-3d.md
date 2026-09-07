# 09 — Geometria: da nuvem de pontos ao sítio

> Código: `rtls/modelo/nuvem.py`, `rtls/sitio.py`
> Entrada: `RTLS_NUVEM=/caminho/para/nuvem.ply` (o caminho **não** vive no código —
> é do usuário e muda de sítio para sítio)

A posição das âncoras entra em todas as equações de §01 a §05. Um erro de 10 cm
numa âncora é ~0,5 dB de erro sistemático de modelo em todos os enlaces dela. A
trena resolve isso mal em ambiente real (não há linha de visada até o canto,
paredes não são perpendiculares, o zero é arbitrário). Este documento é o
caminho medido: **LiDAR → nuvem → sítio**, com orçamento de erro.

Este passo é **opcional**. `sitios/exemplo.json` pode ser escrito à mão com uma
trena e o sistema funciona. A nuvem existe para quem quer o último centímetro e
uma planta que não depende de ninguém ter medido direito.

## 9.1 Orçamento de erro do LiDAR de consumo

Medido, não estimado, numa captura com iPhone + Record3D:

| fonte | valor | como escala |
|-------|-------|-------------|
| ruído do sensor | **8 mm**, constante de 0,5 a 4 m | plano ajustado **dentro de um quadro** (pose fora) |
| erro angular de registro | **0,72°** | **12,5 mm por metro** de distância sensor–superfície |
| fechamento de laço | 0,11 m em 38 m; 0,23 m em 56 m | ~0,3–0,4 % do percurso |
| costura entre gravações | mediana **40 mm** | por par de gravações |
| espessura resultante das superfícies | **~2,5 cm** | domina tudo acima |

A consequência prática para a captura é uma única regra:

> **Filme a 1–1,5 m das superfícies.** O erro dominante é angular, então 3 m
> custam 3,8 cm e 1,2 m custam 1,5 cm. **Termine onde começou** (fecha o laço).
> Ponha uma barra de comprimento conhecido em cena — é a única verificação de
> escala independente do próprio sistema.

Verificação de que a espessura é registro e não sensor: a planaridade local
**piora** quando o retalho cresce (0,175 cm a 1,3 cm → 0,260 cm a 3,7 cm), contra
um controle de ruído isotrópico puro. Se fosse ruído do sensor, a planaridade
seria independente do tamanho do retalho.

## 9.2 Nivelar, alinhar, encaixar

O problema é achar a rígida `SE(3)` que leva a nuvem ao frame do sítio. Em vez
de um ICP global (que desliza), reduz-se por etapas, cada uma com um invariante
próprio:

**(a) Gravidade → 3 DOF.** O eixo vertical vem do acelerômetro. Sobram giro em
torno de z e duas translações.

**(b) Ângulo de Manhattan → 4 candidatos.** Ambientes construídos têm paredes em
dois azimutes ortogonais. O histograma de normais (ou de projeções) tem picos
a cada 90°; achado o ângulo, o giro fica reduzido a **4 candidatos discretos**.

> **Armadilha de sinal, e o teste que a denuncia.** Guardar o ângulo numa
> convenção de giro e aplicá-lo na convenção oposta faz todo o encaixe rodar
> fora do referencial de Manhattan, e a premissa dos 4 candidatos nunca vale.
> Sintoma: ICP deslizando monotonicamente sem convergir. **O teste é a nitidez
> do histograma em `+ang` contra `−ang`** — mediu 3,80 contra 1,78. Uma métrica
> não valida o próprio ajuste; a nitidez do histograma é externa a ele.

**(c) Translação por correlação, não por picos a dedo.** `nuvem.py:encaixa()`
faz a pegada vista de cima virar máscara binária de ocupação e correlaciona
contra a máscara dos cômodos do sítio:

```
  c = FFT⁻¹{ Ĥ · conj(M̂) }        (fftconvolve com M invertido)
  (ix, sx, cx, iy, sy, cy) = argmax sobre 8 combinações de eixo/sinal
```

Usa **milhões de pontos** em vez de três picos escolhidos à mão, e o máximo é
único quando a planta quebra a simetria. Detalhes que mudam o resultado:

- **Ocupação, não densidade** (`H > 3`): senão a região onde o operador andou
  devagar domina a correlação.
- **Cortar piso e teto** (`0,15 < altura < 2,30`): um plano horizontal casa com
  **qualquer** translação e empata tudo.
- **A simetria de 180° empata sempre** em ambiente retangular. Quem desempata é
  a **cor** (erro 37,2 contra acaso 71,2 no correto; 56,9 contra 65,7 no
  errado) ou uma planta em L. O auto-teste sintético de `nuvem.py:demo()`
  documenta exatamente esse empate.
- **ICP final aparado em 40%**, não 60%: um cômodo presente numa gravação e não
  na outra entra como falsa correspondência e gira o ajuste sozinho.

**(d) Datum do piso pelo pico do histograma**, nunca por percentil. Um percentil
baixo pega ponto visto por baixo de porta e afunda o zero em ~4,4 cm.

## 9.3 Espelhos: o LiDAR mede caminho óptico

Um espelho crava o ponto em *(distância ao vidro) + (distância ao objeto)*,
**atrás** da parede: uma cópia especular do ambiente fora do envelope. Se não
for tratada, essa cópia entra na máscara de ocupação e desloca o encaixe.

Trate **dobrando**, não apagando: o vidro **é** superfície, e a parede tem de
ficar fechada.

```
  p' = p − 2 (n·p − d) n        reflexão no plano (n, d)
```

O plano candidato é encontrado refletindo o fantasma e contando quanto ele cai
a 3 cm de geometria real, com **varredura do plano como controle** (0,0 % a
−10 cm → 28,0 % no plano → 5,4 % a +10 cm).

> **Mas essa varredura não prova que existe espelho ali** — só que aquele plano
> é melhor que os vizinhos. Um plano de **simetria** (bancadas iguais dos dois
> lados de uma cozinha) produz um pico igualmente convincente, e a cor também
> não separa. **O controle que separa é a trajetória da câmera: o sensor não
> atravessa vidro.** Num plano falso o telefone esteve 21 cm além do plano em
> dezenas de poses; num espelho real, em nenhuma. É `confere_cameras()`, e é
> obrigatório antes de qualquer plano entrar na tabela.

Este é o exemplo mais limpo do princípio de §07 em geometria: a métrica original
(taxa de casamento) validava o próprio ajuste; o invariante que a resposta errada
viola é físico e vem de outro sensor.

## 9.4 Do encaixe para o `sitio.json`

Com a nuvem no frame do sítio:

- **paredes** — picos do histograma de ocupação nos eixos de Manhattan dão as
  posições; a largura do pico dá a espessura;
- **portas** — vãos na coluna de ocupação entre 0,2 e 2,0 m de altura;
- **âncoras** — clicadas na ortofoto (`nuvem.py:orto()` gera PNG + JSON com o
  retângulo de mundo que ele cobre, para que quem desenha não precise re-derivar
  a escala).

O `sitio.json` continua sendo a **única** fonte de verdade: nem o Python nem o
firmware guardam geometria (§05.9, `ferramentas/gera_firmware_alvo.py`).

## 9.5 Armadilhas numéricas que custam horas

- **`np.linalg.svd(A − centro)` monta `U` de `N×N`** — 80 GB com 100 k pontos, a
  máquina pagina até morrer. Use `np.linalg.eigh(Cᵀ C)` na `3×3`: 14 min → 4 s.
- Erro pequeno de **escala** se disfarça perto do centro da nuvem. Não compare
  distância crua entre duas reconstruções; **varra escala e deslocamento e veja
  onde a mediana tem mínimo.** Se a resposta é escala 1,000 e deslocamento 0,
  nenhuma correção melhora — aí sim as duas concordam.

## 9.6 Verificação executável

```bash
PYTHONPATH=. python3 -m rtls.modelo.nuvem       # auto-teste sintetico do encaixe (sem .ply)
RTLS_NUVEM=/caminho/nuvem.ply PYTHONPATH=. python3 -m rtls.modelo.nuvem
```

O auto-teste sintético gera uma nuvem embaralhada num frame conhecido e exige
que `encaixa()` recupere eixo, sinal e translação com erro **< 5 cm** — roda em
CI sem nenhum arquivo grande.

## Referências

`besl1992` (ICP), `rusinkiewicz2001` (variantes de ICP e o aparo), `coughlan1999`
(mundo de Manhattan), `fischler1981` (RANSAC), `curless1996` — ver
[referencias.bib](referencias.bib).
