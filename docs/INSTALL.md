# INSTALL — do zero ao primeiro ponto na tela

> Guia de instalação e configuração. Objetivo O4 do [PRD](PRD.md): **≤ 4 h**.
> A arquitetura está em [SAD.md](SAD.md); o que comprar, em
> [../hardware/BOM.md](../hardware/BOM.md).

Este documento se lê sozinho, do começo ao fim, sem abrir outro. Onde houver
escolha, o default está escrito e funciona.

**Antes de gastar dinheiro, rode a §1.** Ela leva 10 minutos, não precisa de
nenhuma placa, e prova que o sistema inteiro funciona na sua máquina.

---

## Índice

1. [Sem hardware nenhum (10 min)](#1-sem-hardware-nenhum-10-min)
2. [Descrever o seu sítio (30–60 min)](#2-descrever-o-seu-sítio-3060-min)
3. [Onde pôr as âncoras](#3-onde-pôr-as-âncoras)
4. [Gravar as âncoras (30 min)](#4-gravar-as-âncoras-30-min)
5. [Rede: Wi-Fi, canal e UDP](#5-rede-wi-fi-canal-e-udp)
6. [Subir o host](#6-subir-o-host)
7. [O alvo/campanha na CYD (opcional)](#7-o-alvocampanha-na-cyd-opcional)
8. [Primeira campanha de rótulos](#8-primeira-campanha-de-rótulos)
9. [Personalizar](#9-personalizar)
10. [Quando der errado](#10-quando-der-errado)

---

## 1. Sem hardware nenhum (10 min)

```bash
git clone <este-repo> RTLSEsp32 && cd RTLSEsp32
python3 -m venv .venv && . .venv/bin/activate
pip install numpy
PYTHONPATH=. python3 -m testes.roda_tudo
```

Esperado: **23 ok, 0 falha(s)**, em torno de 50 s. Python 3.10 ou mais novo;
`numpy` é a única dependência obrigatória.

Se isso passou, o sistema funciona — filtro, ajuste, campanha D-ótima, LOO,
gerador de firmware e simulador, todos no sítio de exemplo versionado.

Duas linhas que valem o tempo:

```bash
PYTHONPATH=. python3 -m rtls.sitio            # resumo e validação do sítio
PYTHONPATH=. python3 ferramentas/simula.py    # dado sintético no formato das âncoras
```

## 2. Descrever o seu sítio (30–60 min)

Esta é a única etapa que ninguém pode fazer por você, e é a que mais decide o
resultado. Copie o exemplo e edite:

```bash
cp sitios/exemplo.json sitios/meu.json
export RTLS_SITIO=$PWD/sitios/meu.json
```

`sitios/*.json` é gitignorado (menos o exemplo): a planta de um imóvel habitado é
dado pessoal — ver [PRIVACIDADE.md](PRIVACIDADE.md).

### 2.1 A convenção, antes de qualquer número

Metros. Origem no canto **superior esquerdo**. `x` para a direita.
**`y` para BAIXO.** `z` do chão para o teto.

Se você exportou de CAD, o `y` de lá quase certamente aponta para **cima**:
**espelhe antes de gravar**. Errar o sinal de `y` não levanta exceção — só
desloca tudo, e é o bug mais caro deste projeto.

### 2.2 Medir

Trena a laser, 30 minutos, um cômodo de cada vez. Anote cada cômodo como um
**polígono retilíneo** (só arestas horizontais e verticais) em sentido único:

```json
"comodos": {
  "sala":    [[0,0],[4.5,0],[4.5,3.5],[0,3.5]],
  "cozinha": [[4.5,0],[8,0],[8,3.5],[4.5,3.5]]
}
```

Cômodo em L: descreva os 6 vértices, não dois retângulos. Cômodo com parede
diagonal: aproxime em degraus — `paredes()` só trata retilíneo, e `valida()`
reprova a aresta oblíqua com a mensagem exata.

Precisão que basta: **± 5 cm**. O σ de sombreamento é de 3–4 dB, que a 2 m já
vale ~60 cm de incerteza de distância. Perseguir o centímetro é perseguir ruído.

### 2.3 Portas e janelas

Uma porta é um **vão** aberto numa parede, `[eixo, posição, de, até]`:

```json
"portas": { "sala_cozinha": ["x", 4.5, 1.2, 2.0] }
```

Lê-se: na parede `x = 4,5`, o trecho de `y = 1,2` a `y = 2,0` está aberto. É o
que faz o filtro deixar a partícula atravessar ali e só ali.

Janela é `[[x0,y0],[x1,y1]]` e **precisa ser parede externa** — `valida()`
reprova janela com cômodo dos dois lados, porque isso quase sempre é erro de
digitação.

### 2.4 Rádio

```json
"radio": {
  "f_Hz": 2.44e9,
  "ptx_niveis_dBm": [-21,-15,-12,-9,-6,-3,0,3],
  "piso_dBm": -95,
  "limiar_deteccao_dBm": -90.75,
  "sigma_deteccao_dB": 7.75,
  "piso_radio_dBm": -101
}
```

Os defaults do exemplo servem para ESP32-C3 com antena de PCB. `piso_dBm` é onde
o seu rádio para de entregar pacote — se você mudar de placa ou pôr antena
externa, meça de novo ([02](matematica/02-censura.md) tem o procedimento).

### 2.5 Validar

```bash
PYTHONPATH=. python3 -m rtls.sitio sitios/meu.json
```

Imprime o resumo e **sai com código 1** se houver inconsistência — dá para pôr na
CI de quem usa. Depois rode a suíte inteira no seu sítio:

```bash
RTLS_SITIO=$PWD/sitios/meu.json PYTHONPATH=. python3 -m testes.roda_tudo
```

Tem de dar **23 ok** também aqui. Se algum alvo falhar no seu sítio e passar no
exemplo, é bug do repositório — abra uma issue com o `resumo()` do seu sítio.

## 3. Onde pôr as âncoras

Quantas: **4 é o mínimo útil**, 6 é confortável para um apartamento de 50 m².
Regra grosseira: uma âncora a cada 15–20 m² **e** pelo menos uma por cômodo que
você quer distinguir de verdade.

Cinco regras que valem mais que a quantidade:

1. **Não colineares e não simétricas.** Três âncoras em linha deixam a posição
   ambígua no eixo perpendicular. Um retângulo perfeito de 4 âncoras num cômodo
   simétrico empata. Quebre a simetria de propósito.
2. **Altura única, entre 0,3 e 1,2 m.** O efeito de altura mede 21,5 dB e **não**
   transferiu no LOPO — ou seja: sabemos que importa e **não** sabemos modelar.
   A defesa é não variar. Escolha uma altura e repita nas N.
3. **Fora do chão e longe de metal.** 30 cm de qualquer superfície metálica
   grande (geladeira, quadro de disjuntores, estrutura de estante).
4. **Espalhadas nos dois eixos**, não todas numa parede.
5. **Tomada perto.** Âncora a bateria não cabe no ciclo de trabalho da varredura
   promíscua.

Ponha as candidatas no JSON com `"radio": null` — elas ficam registradas como
plano de expansão sem entrar em conta nenhuma. Só ganham `"radio": <n>` quando
forem instaladas de verdade.

```json
"ancoras": {
  "A1": {"pos": [0.05, 1.80, 0.30], "mac": "AA:BB:CC:00:00:01", "radio": 1, "comodo": "sala"},
  "A7": {"pos": [7.00, 5.00, 0.30], "mac": null, "radio": null, "nota": "expansao"}
}
```

O `recuo` (default 0,05 m) afasta a âncora da parede para ela cair **dentro** de
um cômodo. Se `valida()` reclamar que a âncora não está em cômodo nenhum,
aumente o recuo — não mexa no polígono.

## 4. Gravar as âncoras (30 min)

### 4.1 ESP-IDF

```bash
# uma vez, na sua máquina
git clone -b v5.1.2 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf
~/esp/esp-idf/install.sh esp32c3
export IDF_PATH=$HOME/esp/esp-idf
```

**Por que ESP-IDF e não Arduino:** as libs pré-compiladas do core Arduino para C3
vêm com `CONFIG_BT_NIMBLE_EXT_ADV` e `EXT_SCAN` **desligados**. Sem *extended
scan* (BLE 5.0), a C3 não vê nada que uma placa BLE 4.2 já não veja — e aí ela
não tem por que existir no projeto.

**O alvo já vem fixado** em `sdkconfig.defaults` (`CONFIG_IDF_TARGET="esp32c3"`).
Não tire essa linha. O default do IDF é `esp32` — a ESP32 clássica, que **não tem
BLE 5.0**; com ela `SOC_BLE_50_SUPPORTED=n`, o menu inteiro do BLE 5 desaparece do
Kconfig e as três linhas de `EXT_ADV` do `sdkconfig.defaults` são descartadas **em
silêncio**. O build então vai até 97% e morre em `malha.c` com `implicit
declaration of function 'ble_gap_ext_adv_start'` — um erro que fala de função
faltando, nunca de alvo errado. Medido: era exatamente isso que acontecia num
clone novo antes de a linha existir.

### 4.2 Credenciais

```bash
cp firmware/ancora-c3/main/credenciais.h.exemplo firmware/ancora-c3/main/credenciais.h
$EDITOR firmware/ancora-c3/main/credenciais.h     # SSID e senha
```

`credenciais.h` é gitignorado. **Não** ponha a senha em arquivo versionado, em
issue, em log nem em mensagem de commit.

### 4.3 Compilar

```bash
firmware/ancora-c3/build.sh build
```

Se o `export.sh` do IDF falhar procurando um venv `idf5.x_pyX.Y_env` que não
existe, aponte o Python certo:

```bash
export RTLS_PY=/opt/homebrew/opt/python@3.13/libexec/bin   # exemplo macOS/Homebrew
```

### 4.4 Gravar as N placas

Ligue as placas no USB (uma de cada vez ou todas juntas) e:

```bash
ferramentas/flash_ancoras.sh
```

O script é **idempotente**: roda de novo à vontade, só toca em placa que ainda
não está em `ancoras.txt`. Ele identifica cada placa pelo **MAC**, não pela porta
(a porta re-enumera a cada reset), faz backup da flash virgem antes de gravar, e
só registra a placa depois de ver mais de 20 pacotes em 6 s saindo dela.

Duas variáveis:

| variável | para quê |
|---|---|
| `RTLS_NAO_GRAVAR="AA:BB:.. CC:DD:.."` | MACs a nunca tocar. Outras placas Espressif (S3, S2) têm o **mesmo** VID:PID `303a:1001` das C3 e apareceriam aqui |
| `RTLS_BUILD=/caminho/build` | se o build está fora do default |

Duas armadilhas já pagas, que o script evita e que valem para qualquer script seu:

- **Nunca `esptool ... | grep -q`**: o `grep -q` fecha o pipe no primeiro casamento
  e o esptool morre de SIGPIPE depois de gravar **só o bootloader**. A placa fica
  muda. Capture a saída inteira e conte os três `Hash of data verified`.
- **`stty` bloqueante**: o `open()` do `stty` pode esperar *carrier* para sempre.
  Use `timeout`.

Ao final, `ancoras.txt` tem `<n> <mac> <data>` por linha. **Esse arquivo é o
mapa MAC→número.** Copie cada MAC para o campo `mac` da âncora correspondente no
seu JSON — é assim que o host sabe qual placa é qual, e é por isso que as N
placas rodam um binário idêntico, sem número gravado em lugar nenhum.

## 5. Rede: Wi-Fi, canal e UDP

- **2,4 GHz, mesma sub-rede do host.** As âncoras mandam UDP **broadcast**; o
  broadcast não atravessa roteador. Rede de convidados costuma ter isolamento de
  cliente ligado — não use.
- **Canal fixo.** Deixe o AP num canal fixo (1, 6 ou 11). Wi-Fi e BLE dividem os
  2,4 GHz: se o AP fica pulando de canal, o RSSI muda de regime sem avisar e o
  modelo ajustado ontem descreve outro rádio.
- **Custo:** ~1,7 kB/s por âncora numa LAN doméstica.
- Libere as portas no host: **5007** (avistamentos), **5008** (farol), **5009**
  (rótulos), **5010** (mapa), **8099** (painel).

## 6. Subir o host

```bash
export RTLS_DADOS=$HOME/rtls-dados && mkdir -p "$RTLS_DADOS"
PYTHONPATH=. python3 -m rtls.receptor --outdir "$RTLS_DADOS" --mapa ancoras.txt
```

Deve aparecer uma linha por âncora, com contagem subindo. Se não aparecer nada,
pule para a §10.

Depois, o painel:

```bash
ferramentas/roda_painel.sh "$RTLS_DADOS" 8099
# http://<ip-do-host>:8099/
```

Ele sobe o daemon `rtls.vivo` (um filtro contínuo a 2 Hz), regenera os SVGs a
cada 30 s e serve tudo. `Ctrl-C` derruba os dois.

**Deixe rodar algumas horas antes de julgar qualquer número.** O ajuste A/n/W vem
da malha entre âncoras, e a malha precisa de tempo para cobrir os enlaces.

## 7. O alvo/campanha na CYD (opcional)

A CYD (ESP32-2432S028R, ~US$ 12) faz três papéis: sniffer, painel 3×N e a
**campanha de rótulos** — a planta na tela, o toque marca onde você está.

```bash
pip install platformio
cp firmware/ancora-c3/main/credenciais.h firmware/alvo-cyd/src/credenciais.h
PYTHONPATH=. python3 ferramentas/gera_firmware_alvo.py --escreve   # a SUA planta
export RTLS_PORTA_CYD=/dev/cu.usbserial-XXXX     # ou /dev/ttyUSB0
pio run -d firmware/alvo-cyd -e campanha -t upload
```

O `--escreve` é obrigatório e é o passo que as pessoas esquecem: ele escreve
`firmware/alvo-cyd/src/sitio_gerado.h` com a **sua** planta, as **suas** âncoras
e os pontos da campanha. Sem ele você grava a planta do exemplo.

**Outra revisão de placa** (ST7789 em vez de ILI9341, toque em outros GPIOs)
troca só o bloco `build_flags` de `firmware/alvo-cyd/platformio.ini`, e nada
mais. Se o toque sair deslocado, os quatro limites de calibração estão no topo de
`campanha.cpp`, marcados como "DA SUA PLACA".

## 8. Primeira campanha de rótulos

O modelo precisa de pontos com verdade conhecida. O desenho D-ótimo escolhe
onde:

```bash
PYTHONPATH=. python3 -m rtls.campanha          # onde medir e por quê
PYTHONPATH=. python3 -m rtls.rotulos "$RTLS_DADOS"   # recebe os rótulos do CYD
```

No campo, para cada ponto: **congele o rádio antes de andar** (não mexa em AP,
não ligue micro-ondas, não mude nada), vá até o ponto, toque nele na tela,
`INICIAR`, fique parado 3 min (o bipe avisa), `FINALIZAR`.

Três minutos por ponto é o mínimo: o transmissor de referência cicla 8 níveis de
Ptx em 48 s, e o ponto só é separável com dois a quatro ciclos inteiros
([02](matematica/02-censura.md)).

Depois da campanha:

```bash
PYTHONPATH=. python3 -m rtls.loo "$RTLS_DADOS"        # erro sem trena
PYTHONPATH=. python3 -m rtls.revisao "$RTLS_DADOS"    # modelo novo × produção, com juiz
PYTHONPATH=. python3 -m rtls.modelo.invariantes       # os sete invariantes
```

**Rótulo errado não se apaga.** `rotulos.jsonl` é append-only; a correção vai em
`correcoes.jsonl`, chaveada por `(boot, seq)`, e é aplicada na leitura.

**Nunca promova um modelo por ele ajustar melhor.** A régua é o LOPO com o
modelo em produção como controle: `média(ganho por ponto) − EP > 0,5 dB`, unidade
= ponto. Quatro blocos já reprovaram aí ([06](matematica/06-transferencia.md)).

## 9. Personalizar

| quero | onde | cuidado |
|---|---|---|
| mais âncoras | `ancoras` no JSON + `flash_ancoras.sh` | o firmware é o mesmo binário; só o JSON muda |
| outra altura de âncora | `pos[2]` no JSON | **use a mesma para todas** (§3, regra 2) |
| parede de material diferente | `classes_parede` + `classe_padrao` | [01 §1.5](matematica/01-propagacao.md) |
| outra placa de tela | `build_flags` do `platformio.ini` | só esse bloco |
| outro número de pontos por aba | `POR_CM` no gerador | regenere o `.h` |
| trocar de porta UDP | topo de `receptor.py`/`rotulos.py`/`mapa_alvo.py` + `#define PORTA_*` no `campanha.cpp` | os dois lados, sempre |
| outro estimador | `rtls/tracker.py` | mantenha `update()`, `spread()` e `P(cômodo)` |
| sítio a partir de nuvem 3D | `RTLS_NUVEM=/caminho/nuvem.ply` | [09](matematica/09-geometria-3d.md); a trena continua valendo |

Depois de **qualquer** mudança no sítio: `--escreve` no gerador e a suíte de
novo. A CI reprova o `.h` desatualizado comparando byte a byte.

O que cada mudança **obriga** a refazer — regerar o `.h`, regravar o alvo,
regravar as âncoras, e se os rótulos antigos continuam valendo — está na matriz
de acoplamento em [CI-CD §5.3](CI-CD.md). A fixação física e as regras que o
modelo enxerga (altura única, orientação, 30 cm de metal) estão em
[hardware/montagem.md](../hardware/montagem.md).

## 10. Quando der errado

| sintoma | causa provável | o que fazer |
|---|---|---|
| `ModuleNotFoundError: No module named 'rtls'` | rodou o script direto | `PYTHONPATH=.` na frente, ou `python3 -m` |
| suíte passa no exemplo e falha no seu sítio | suposição escondida no repositório | é bug nosso — mande o `resumo()` do seu sítio |
| receptor não recebe nada | broadcast bloqueado, sub-rede diferente, isolamento de cliente | `tcpdump -i any udp port 5007`; teste com `ferramentas/simula.py` |
| âncora grava mas fica muda | `esptool` morto por SIGPIPE gravou só o bootloader | regrave; conte os três `Hash of data verified` |
| âncora não aparece no `ancoras.txt` | não emitiu 20 pacotes em 6 s | olhe o LED: verde pulsando = varrendo |
| placa errada gravada | outra Espressif com o mesmo VID:PID | `RTLS_NAO_GRAVAR` com o MAC dela |
| tudo deslocado, mesma forma | sinal de `y` invertido | §2.1; espelhe o JSON |
| previsão ~20 dB abaixo do medido | parede contada duas vezes | não deve mais acontecer; se acontecer, mande o sítio |
| alvo parado "passeia" no mapa | filtro recriado a cada render | use `rtls.vivo` (um filtro contínuo), não um por quadro |
| posição pula entre cômodos | poucas âncoras ouvindo | olhe o `spread()`: > 5 m significa "não sei", e é a resposta certa |
| `pio` não acha a CYD | mais de uma placa no USB | `export RTLS_PORTA_CYD=...` |
| toque deslocado | calibração é da placa | quatro limites no topo de `campanha.cpp` |
| painel no ar mas vazio | `http.server` subiu e o `vivo` não | `cat ferramentas/painel/vivo.log` |

**Uma armadilha de shell que já matou sessões inteiras:** `pgrep -f` / `pkill -f`
com o padrão escrito na própria linha de comando casa com o **próprio** processo
(e, por ssh, mata o shell). Escreva a primeira letra entre colchetes:
`pgrep -af "[r]tls.vivo"`.
