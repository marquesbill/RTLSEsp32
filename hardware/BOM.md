# Lista de materiais (BOM)

Objetivo **O7** do [PRD](../docs/PRD.md): **≤ US$ 5 por âncora, sem caixa.** Esta
página mostra a conta, o que ela exclui e por quê.

Preços são de referência (AliExpress/Mercado Livre, setembro de 2026, sem frete e
sem imposto). Variam muito; a **ordem de grandeza** é o que importa, e é ela que
sustenta a decisão de projeto.

---

## 1. O kit mínimo

Para um ambiente de ~50 m² com 6 âncoras:

| # | Item | Qtd | Unit. | Total | Por quê |
|---|---|---|---|---|---|
| 1 | **ESP32-C3 SuperMini** | 6 | US$ 2,20 | US$ 13,20 | A âncora. BLE 5.0 com *extended advertising*, Wi-Fi 2,4 GHz, 4 MB flash — tudo que o firmware usa |
| 2 | Fonte USB 5 V ≥ 500 mA | 6 | US$ 1,20 | US$ 7,20 | Âncora a bateria não fecha o ciclo de trabalho (§5) |
| 3 | Cabo USB-C, 1–2 m | 6 | US$ 0,80 | US$ 4,80 | O comprimento é o que decide onde a âncora pode ficar |
| 4 | Fita dupla-face de espuma | 1 rolo | US$ 1,50 | US$ 1,50 | Fixação; a espuma também afasta do metal |
| 5 | Etiquetas (ou fita crepe + caneta) | 1 | US$ 1,00 | US$ 1,00 | O número da âncora escrito nela. Sério: veja [montagem §4](montagem.md) |
| | **Subtotal âncoras** | | | **US$ 27,70** | **US$ 4,62/âncora** ✅ |
| 6 | **CYD ESP32-2432S028R** | 1 | US$ 9,00 | US$ 9,00 | Alvo/rotulador: planta na tela + toque. Sem ele a campanha vira papel e cronômetro |
| 7 | Host | 1 | — | — | Qualquer máquina Linux/macOS que já exista. Um Raspberry Pi 3 dá conta |
| 8 | Roteador Wi-Fi 2,4 GHz | 1 | — | — | O que você já tem. Canal fixo ([INSTALL §5](../docs/INSTALL.md)) |
| | **Total do kit** | | | **US$ 36,70** | |

**A conta de O7:** itens 1+2+3, os únicos obrigatórios por âncora, somam
US$ 4,20. Com fita e etiqueta rateadas, US$ 4,62. A margem para os US$ 5 é
estreita de propósito — é ela que exclui antena externa, PoE e caixa, e são
essas exclusões que fazem a solução escalar para 12 ou 20 âncoras sem virar
outro projeto.

---

## 2. A âncora: por que essa placa

| Requisito | Por quê | Quem atende |
|---|---|---|
| BLE 5.0 com *extended scan* | Sem ele a placa não vê nada que uma BLE 4.2 já não veja — não teria razão de existir aqui | ESP32-C3, C6, S3 |
| Wi-Fi 2,4 GHz | O transporte dos avistamentos é UDP para o host | qualquer ESP32 |
| Rádio único, coexistência controlada | Wi-Fi e BLE no mesmo rádio exigem *modem sleep*; o promíscuo aborta o BT | C3 (single-core, comportamento previsível) |
| ≤ US$ 3 | Objetivo O7 | C3 SuperMini |

O ESP32 clássico (dual-core, 2015) **não** tem BLE 5.0 — não serve como âncora.
O C6 e o S3 servem tecnicamente e custam 2–3× mais; use-os se já tiver.

> **Compatibilidade.** O firmware é ESP-IDF com alvo `esp32c3`. Trocar de chip é
> trocar `target` e reconferir a coexistência de rádio — não é um `#define`.
> Ver [SAD §4](../docs/SAD.md).

### 2.1 A questão da antena — a decisão mais cara desta lista

A SuperMini vem com uma **antena cerâmica** colada sobre o plano de terra. Medido
neste projeto: **−16 a −24 dBi**. Uma antena de 0 dBi é a referência; isto é
20 dB abaixo, cem vezes menos potência.

| Variante | Ganho | Custo extra | Efeito |
|---|---|---|---|
| `c3_sem_antena` (padrão) | **−20 dBi** (medido) | US$ 0 | Enlaces longos batem no piso de captura — e um pacote censurado **não produz linha** ([02](../docs/matematica/02-censura.md)) |
| `c3_com_antena` (SuperMini **Plus** + u.FL) | **0 dBi** | +US$ 2,50 (placa + antena) | ~20 dB de margem em todo enlace |

Os dois tipos estão no catálogo de `rtls/modelo/entidades.py` com os ganhos
medidos, então o modelo sabe qual você usou — basta pôr `"tipo"` no `.json` da
âncora.

**Quando pagar os US$ 2,50:** se a suíte de campanha mostrar enlaces censurados
(`piso`) em pares que deveriam se ouvir, ou em ambiente maior que ~80 m². Em
apartamento com 6 âncoras, a versão sem antena mediu 1,64 m de mediana — os
20 dB não eram o gargalo.

⚠️ A variante "Plus" exige **dessoldar um jumper 0 Ω** e soldar o outro para
comutar da cerâmica para o u.FL. Se você não solda em 0402, compre a placa que já
vem comutada ou fique com a padrão.

---

## 3. O alvo (CYD)

O **ESP32-2432S028R** ("Cheap Yellow Display") é um ESP32 clássico com LCD
ILI9341 de 2,8" e toque resistivo XPT2046, tudo montado, por ~US$ 9.

Ele faz três coisas neste projeto, em três firmwares que compartilham a mesma
placa e os mesmos flags de tela:

| Ambiente | Faz | Quando você usa |
|---|---|---|
| `cyd` | Sniffer BLE → serial → Wireshark | Diagnóstico de rádio |
| `painel` | 3×N: ESP-NOW / BT / Wi-Fi por âncora | Instalação e manutenção — é o "N/N vivas" |
| `campanha` | Planta na tela + toque; rótulo por UDP | Campanha de rótulos |

**Ele não é obrigatório para o sistema funcionar** — é obrigatório para
*calibrar* sem transformar a campanha num exercício de papel, cronômetro e trena.
Alternativa: qualquer coisa que envie `(x, y, z, t)` para a porta 5009.

⚠️ Existem revisões dessa placa com **ST7789** no lugar do ILI9341 e com o toque
em outros GPIOs. Trocar de revisão troca o bloco `build_flags` do
`platformio.ini` e nada mais — os flags estão comentados um a um.

**O fundo metálico da tela faz padrão de radiação.** Medido: **10,2 dB** de
diferença só girando o aparelho. Por isso o CYD entra no catálogo como `cyd` com
`grau=2`, e por isso a campanha manda **manter a orientação** entre pontos.

---

## 4. Host

Qualquer máquina na mesma sub-rede das âncoras, com Python 3.10+ e numpy.

| Peça | Mínimo | Confortável |
|---|---|---|
| CPU | Raspberry Pi 3 | qualquer x86 dos últimos 10 anos |
| RAM | 512 MB | 2 GB |
| Disco | 1 GB + os dados | os dados crescem em GB; aponte `RTLS_DADOS` para onde couber |
| Rede | Ethernet ou Wi-Fi na **mesma sub-rede** (o transporte é broadcast UDP) | Ethernet |

Não há nuvem, não há conta e não há serviço externo. É uma decisão de projeto,
não uma limitação: o dado é do dono do imóvel ([PRIVACIDADE](../docs/PRIVACIDADE.md)).

---

## 5. O que deliberadamente **não** está na lista

| Não comprado | Custo evitado | Por quê |
|---|---|---|
| Rádio UWB (DW1000/DW3000) | US$ 15–25/âncora | Resolve melhor e é **outro projeto**. Aqui a premissa é que o alvo **não coopera**: só emite anúncio BLE, nada é instalado nele |
| Antena externa por padrão | US$ 2,50/âncora | Não foi o gargalo no sítio medido (§2.1) |
| Bateria + carregador | US$ 4/âncora | A varredura promíscua é ciclo de trabalho ~100%. Uma 18650 dura horas, não semanas, e âncora que morre sozinha é pior que âncora que não existe |
| PoE | US$ 8/âncora | Tomada já resolve, e onde não há tomada normalmente também não há cabo de rede |
| Caixa impressa em 3D | US$ 0,50 em filamento | Fica melhor com caixa. Só não conta no O7, que é "sem caixa". STL não acompanha porque a montagem depende da placa exata que você comprou |
| Sensor extra (PIR, mmWave) | US$ 3–8 | Resolveria presença melhor. Mas a malha detecta **movimento**, não presença, e misturar sensores muda a pergunta que o sistema responde |

---

## 6. Escalar para ambientes maiores

Regra de dimensionamento ([INSTALL §3](../docs/INSTALL.md)): **uma âncora a cada
15–20 m²**, e pelo menos uma por cômodo que você quer distinguir.

| Área | Âncoras | Custo (sem antena) | Pares de enlace | Números independentes na malha |
|---|---|---|---|---|
| 50 m² (apartamento) | 6 | US$ 25 | 15 | 20 |
| 100 m² (casa) | 8 | US$ 34 | 28 | 35 |
| 200 m² (escritório) | 12 | US$ 50 | 66 | 77 |
| 400 m² (galpão) | 20 | US$ 84 | 190 | 209 |

As duas últimas colunas são $\binom{N}{2}$ e $\binom{N}{2} + (N-1)$: quantos
enlaces existem e quantos números **independentes** a malha oferece ao ajuste. O
custo cresce linear em $N$; a informação cresce **quadrática**. É essa assimetria
que faz valer a pena adensar antes de melhorar o rádio.

⚠️ Um limite real aparece antes do custo: as âncoras usam broadcast UDP na mesma
sub-rede. Acima de ~20 âncoras vale medir a carga de broadcast e considerar
segmentar. Ver [SAD §6](../docs/SAD.md).

---

## 7. Ferramentas

| Ferramenta | Obrigatória? | Para quê |
|---|---|---|
| Trena (ou app de LiDAR) | **sim** | O sítio precisa de dimensões. Erro na planta vira erro na posição, sem aviso |
| Nível de bolha / app | não | Manter a mesma altura nas N âncoras ([montagem §2](montagem.md)) |
| Ferro de solda ponta fina | só para o u.FL (§2.1) | Jumper 0402 |
| Multímetro | não | Conferir 5 V numa fonte suspeita |

---

## 8. Ordem de compra recomendada

1. **1 SuperMini** (US$ 2,20). Grave, veja o LED piscar, confirme que a `build.sh`
   fecha na sua máquina. É o passo que descobre problema de toolchain por US$ 2.
2. **O resto das âncoras + fontes + cabos.** Compre **uma a mais** que o plano:
   uma placa morre, uma some, e frete de reposição custa mais que a placa.
3. **O CYD**, quando for calibrar.

Antes de qualquer compra, rode a suíte sem hardware nenhum
([INSTALL §1](../docs/INSTALL.md)): 10 minutos e você já viu o sistema inteiro
funcionando em simulação.
