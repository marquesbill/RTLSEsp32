# SAD — Arquitetura do RTLSEsp32

> Documento de arquitetura. O *como*.
> O *quê* e o *porquê* estão em [PRD.md](PRD.md); a matemática, em
> [matematica/](matematica/README.md); o passo a passo de montar, em
> [INSTALL.md](INSTALL.md).

| campo | valor |
|---|---|
| Versão do documento | 1.0 |
| Estilo arquitetural | pipeline de dados, um sentido, sem banco |
| Linguagens | C (ESP-IDF), C++ (Arduino/PlatformIO), Python 3.10+ |
| Dependências do host | `numpy` — e mais nada obrigatório |

---

## 1. Visão em uma tela

```
      ~~~ ar, 2,4 GHz ~~~
                                                     .------------------.
  [alvo BLE]  anuncia -----.                         |  navegador       |
  (celular, tag, CYD)      |                         |  painel.html     |
                           v                         '--------^---------'
  [âncora 1] ---.     varredura BLE promíscua                 | HTTP :8099
  [âncora 2] ---+---> + malha ESP-NOW/BLE entre âncoras        |
      ...       |          |                          .-------+--------.
  [âncora N] ---'          | UDP :5007 broadcast      |   rtls/vivo.py  |
                           v                          |   (daemon 2 Hz) |
                    .--------------.                  '-------^--------'
                    | rtls/        |  JSONL por âncora        |
                    | receptor.py  | -----------------------> |
                    '--------------'   $RTLS_DADOS/*.jsonl    |
                           ^                                  |
                           | UDP :5008 (farol do host)         | vivo.json
                           |                                   v
  [CYD campanha] --------> | UDP :5009 rótulos           [ P(cômodo), x, y, spread ]
       ^                   v                                   |
       |            .--------------.                           |
       '------------| rtls/        | <--- UDP :5010 -----------'
        mapa na tela| mapa_alvo.py |
                    '--------------'
```

Um sentido só: o rádio produz, o host consome. Não há caminho de volta que
altere o dado bruto — o único tráfego host→campo é o farol (`:5008`, que diz às
âncoras para onde mandar) e o mapa (`:5010`, cosmético).

## 2. Decisões estruturais e o que cada uma custou

| # | Decisão | Alternativa recusada | Por quê |
|---|---|---|---|
| D1 | O sítio é um JSON | planta em código | trocar de prédio não pode exigir editar Python. §3 |
| D2 | Identidade da âncora = MAC de fábrica | número gravado na placa | as N placas rodam **o mesmo binário**; trocar uma não reflasha as outras. §4.1 |
| D3 | UDP broadcast | IP fixo, mDNS | IP fixo quebrou duas vezes com troca de DHCP; mDNS é um protocolo inteiro para o que o broadcast resolve sem descoberta |
| D4 | Carimbo de tempo no host, na chegada | sincronizar relógio das âncoras | tentativa anterior acumulou offsets de até 825 s. O contador de ms da placa viaja no pacote **só** para medir jitter de transporte |
| D5 | JSONL, sem banco | SQLite/Postgres | o dado é append-only e lido em varredura; um banco só acrescentaria migração |
| D6 | Filtro de partículas sobre RSSI cru | multilateração + Kalman | duas etapas jogam fora a censura e a planta. MEDIDO: 3,4× pior na mediana. §5.3 |
| D7 | Um filtro contínuo, não um por render | recriar o filtro a cada quadro | recriar é re-estimar do zero: alvo parado andava 50 m em 20 min |
| D8 | O `.h` do firmware do alvo é **gerado** | copiar a planta a mão no C | a cópia deixa de existir; a CI compara byte a byte. §4.3 |
| D9 | ESP-IDF na âncora, Arduino no alvo | Arduino nos dois | o core Arduino do C3 vem com *extended scan* (BLE 5.0) desligado — sem ele a C3 não vê nada que a CYD já não veja |

## 3. O sítio como dado — `rtls/sitio.py`

É o único módulo que os outros importam por completo. Ele carrega um JSON e
publica nomes de módulo; **nenhuma linha de Python muda entre um prédio e outro**.

```
sitios/meu_lugar.json ──carrega()──> P.COMODOS, P.ANCORAS, P.ESCOLHIDAS,
                                     P.PORTAS, P.JANELAS, P.EMISSORES,
                                     P.RADIO, P.X_MIN..P.Z_MAX, P.CAMINHO
```

**Contrato público** (o que uma reimplementação precisa oferecer):

| função | devolve | usada por |
|---|---|---|
| `carrega(caminho)` | dict cru; republica os globais | tudo, no import |
| `paredes()` | `(M,2,2)` de segmentos, vãos de porta já abertos | tracker, ajuste, gerador do `.h` |
| `floorplan()` | `Floorplan` com paredes + cômodos | filtro de partículas |
| `ancoras(quais=None)` | `{tag: (x,y,z)}` das instaladas | ajuste, LOO, campanha |
| `comodo_de((x,y))` | nome do cômodo, ou `None` | saída por cômodo, validação de ponto |
| `area(poly)`, `dentro_poly(p, poly)` | escalares | geometria auxiliar |
| `valida()` | lista de erros (vazia = ok) | CI de quem usa; `python3 -m rtls.sitio` |
| `resumo()` | uma linha legível | diagnóstico |

**Seleção do sítio**, em ordem de precedência: argumento explícito de
`carrega()` → variável `RTLS_SITIO` → `sitios/exemplo.json`.

### 3.1 Convenção de coordenadas

Metros; origem no canto **superior esquerdo**; `x` para a direita; **`y` para
baixo**; `z` do chão para o teto. Quem exporta planta de CAD costuma ter `y` para
cima: **espelhe antes de gravar o JSON**. Erro de sinal em `y` é o bug mais caro
deste projeto — ele não levanta exceção, só desloca tudo.

### 3.2 Modelo de parede, e a união que evita contar duas vezes

Um cômodo é um polígono retilíneo; cada aresta é um segmento de parede. Uma
parede **interna** é aresta de *dois* cômodos. Emitir polígono a polígono conta
essa parede duas vezes, e o ajuste devolve um `W` pela metade para compensar.
Onde a contagem dobrada é uniforme isso se cancela; onde não é, não: um enlace
que rasava dois batentes contou 6 paredes em vez de 2 e o previsto errou 21 dB
para menos. Por isso `paredes()` faz **união dos intervalos colineares** por
`(eixo, posição)` e só depois subtrai o vão das portas.

Espessura de parede é ignorada de propósito: ~10 cm contra σ de sombreamento de
3–4 dB é ruído. Parede grossa ou material diferente vai em `classes_parede` —
ver [01 §1.5](matematica/01-propagacao.md).

### 3.3 Esquema do JSON

| chave | tipo | obrigatória | nota |
|---|---|---|---|
| `nome`, `descricao` | string | `nome` sim | aparece no `.h` gerado e no painel |
| `convencao` | string | não | texto livre; documenta o sinal de `y` |
| `limites` | `{x:[min,max], y:[...], z:[...]}` | sim | caixa envolvente; o filtro semeia aqui |
| `recuo` | float (m) | não (0,05) | afasta a âncora da parede para ela cair dentro de um cômodo |
| `comodos` | `{nome: [[x,y], ...]}` | sim | polígono **retilíneo**, sentido livre |
| `portas` | `{nome: [eixo, pos, a, b]}` | não | vão aberto em `eixo=pos`, de `a` a `b` |
| `janelas` | `{nome: [[x0,y0],[x1,y1]]}` | não | `valida()` exige que seja parede externa |
| `classes_parede`, `classe_padrao` | dict / string | não | `k_c` por material |
| `ancoras` | `{tag: {...}}` | sim | ver abaixo |
| `emissores_fixos` | `{nome: {pos, tipo, tipo_rf}}` | não | AP, TV, balança: não são âncoras, mas ocupam espaço e emitem |
| `postos` | `{nome: {pos, raio, hosts}}` | não | onde o alvo **fica** quando está no cabo USB; posição conhecida por oportunidade |
| `radio` | dict | sim | `f_Hz`, `ptx_niveis_dBm`, `piso_dBm`, `limiar_deteccao_dBm`, `sigma_deteccao_dB`, `piso_radio_dBm` |

Dentro de `ancoras[tag]`: `pos: [x,y,z]` e `mac` são obrigatórios; `radio: <n>`
(o número instalado) é o que separa âncora **candidata** de âncora **instalada**
— sem ele a posição fica no JSON como plano de expansão e não entra em conta
nenhuma. Opcionais: `comodo`, `nota`, `tipo`, `yaw`, `p_tx_dBm`.

`postos` é a única seção cuja validade é **temporária**: vale só enquanto o host
correspondente enxerga o dispositivo. `raio` é o alcance do cabo mais a folga da
bancada — **é a incerteza da posição**, e um cabo de 2 m vale muito menos que um
de 60 cm. Um `host` só pode aparecer em um posto, senão "plugado" deixa de
determinar lugar; `rtls/oportunidade.py:valida()` cobra isso.

### 3.4 O que `valida()` pega

Aresta não ortogonal; cômodo com menos de 4 vértices ou área < 0,5 m²; âncora
fora dos limites ou com `z` fora de `[0, Z_MAX]`; âncora instalada que não caiu
dentro de nenhum cômodo (ficou em cima da parede — aumente `recuo`); número de
rádio repetido; janela com cômodo dos dois lados; porta com vão invertido.

Ele **não** valida se o sítio bate com o mundo. Isso só a medida faz.

```bash
python3 -m rtls.sitio sitios/meu_lugar.json    # imprime erros, sai 1 se houver
```

## 4. Camada de campo (firmware)

### 4.1 Âncora — `firmware/ancora-c3/` (ESP-IDF, ESP32-C3)

Quatro responsabilidades, uma por arquivo:

| arquivo | faz |
|---|---|
| `main.c` | varredura BLE **estendida** (BLE 5.0) contínua; emite `@b e a rssi bda payload` |
| `wireless.c` | Wi-Fi STA; empacota avistamentos e manda em UDP broadcast `:5007` |
| `malha.c` | 1 Hz de anúncio BLE + 1 Hz de ESP-NOW, ambos com a mesma carga útil |
| `led.c` | semáforo local: verde pulsando = varrendo e transmitindo |

**Pacote do avistamento** (`:5007`, big-endian, cabeçalho de 30 bytes):

```
magica(4)=0x52544c53  mac(6)  seq(4)  n_regs(2)  perdidos(4)  heap_livre(4) ...
depois, n_regs vezes:  len(1) addr(6) rssi(1) props(1) tipo_addr(1) payload(len)
```

O byte de versão existe porque trocar o cabeçalho sem trocar o receptor já
aconteceu; o sintoma era o receptor contar tudo como "ruins" sem dizer por quê.

**Malha entre âncoras.** Carga útil: CID `0xFFFF` (reservado pela SIG para
teste) + `"RA"` + os 3 últimos bytes do MAC STA + `boot_count` + modo. Vai por
anúncio BLE **e** por ESP-NOW, de propósito: o alvo é GFSK na cadeia do BLE, e só
o anúncio mede o que o alvo mede; o ESP-NOW custa 1 quadro/s e dá a referência de
taxa **fixa**, que o UDP não dá (o RSSI do UDP anda com o MCS que o *rate
control* escolher).

**Por que Wi-Fi e não um gateway ESP-NOW:** medido antes, só *ligar* o rádio
Wi-Fi já custa −38 % dos avistamentos BLE; transmitir em cima disso não custa
nada mensurável. O gateway economizaria pouco e custaria uma placa e um protocolo.

### 4.2 Alvo / campanha — `firmware/alvo-cyd/` (Arduino, ESP32-2432S028R)

Três *environments* na mesma placa e nos mesmos flags de tela:

| env | fonte | para quê |
|---|---|---|
| `cyd` | `main.cpp` | sniffer de advertising → serial → Wireshark (extcap) |
| `painel` | `painel.cpp` | painel 3×N: RSSI das N âncoras nas três cadeias de rádio |
| `campanha` | `campanha.cpp` | planta na tela; o toque rotula o ponto e sai por UDP `:5009` |

Cada evento de rótulo vai **3×** (UDP cai); o host deduplica por `(boot, seq)`.
Sem cartão SD e sem ACK de propósito: gravar tudo no cartão e mandar no fim cria
o modo de falha em que a campanha inteira mora no cartão até o fim.

O transmissor de referência (`"RC"`, Ptx cíclica em 8 níveis) é o mesmo do painel
e **não muda**: é a inclinação RSSI × Ptx num ponto fixo que torna a campanha
separável ([02](matematica/02-censura.md)). Um ciclo leva 48 s, então a
permanência útil num ponto é de 2–3 min.

### 4.3 A fronteira gerada — `ferramentas/gera_firmware_alvo.py`

O firmware do alvo precisa da planta, das âncoras e do desenho da campanha. Isso
já existe no JSON do sítio, e copiar a mão para o C é a definição de deriva. O
gerador escreve `firmware/alvo-cyd/src/sitio_gerado.h` e a CI o regera em memória
e **compara byte a byte**.

Atravessam a fronteira: `SITIO_NOME`, `N_ANC`, `MACS[][6]`, `ANC[][2]`,
`PAREDES[]`, `PONTOS[]`, `CMS[]`, `POR_CM`, a escala e a orientação da tela
(`MX MY MXP MYP ESC U0P V0P PAN_X BT_Y RAIO_PX DESVIO_PX`) e as macros
`PLX/PLY`. **Nenhum número de tela aparece dos dois lados** — foi assim que
`DESVIO` (o desvio lateral que separa duas alturas no mesmo `(x,y)`) passou a
entrar também na reserva de borda da escala, depois de um ponto de parede
estourar a lateral num sítio largo.

O gerador escolhe girar a planta 90° quando isso ganha mais de 5 % de px/m,
porque px/m é o que decide se o dedo acerta o ponto certo.

```bash
PYTHONPATH=. python3 ferramentas/gera_firmware_alvo.py --escreve   # regera
PYTHONPATH=. python3 ferramentas/gera_firmware_alvo.py --confere   # a CI
```

`--confere` sai **pulando** quando `RTLS_SITIO` aponta para outro sítio: o `.h`
versionado é do sítio versionado, e "difere" ali é a resposta certa.

## 5. Camada de host (`rtls/`)

### 5.1 Ingestão — `receptor.py`, `rotulos.py`

`receptor.py` escuta `:5007`, valida mágica e versão, carimba o tempo na chegada
e grava um JSONL por âncora em `$RTLS_DADOS`. Anuncia-se em `:5008` para as
âncoras. `rotulos.py` escuta `:5009` e grava `rotulos.jsonl`.

**`rotulos.jsonl` é append-only e nunca é editado.** Correção vai em
`correcoes.jsonl`, chaveada por `(boot, seq)`, e é aplicada na leitura. Um rótulo
errado apagado some sem rastro; um rótulo errado corrigido deixa as duas versões.

### 5.2 Modelo de propagação — `ajuste.py`, `modelo/`

O modelo direto, em dB, de um enlace `i→j`:

```
y_ij = p_i + A₀ − 10·n·log₁₀(d_ij) − Σ_c W_c k_c − Σ_e B_e χ_e
       + t_i + r_j + ψ(u_ij)·c_i + ψ(u_ji)·c_j + X_ij + ε_ij
```

`p_i` Ptx, `A₀` intercepto a 1 m, `n` expoente, `W_c` perda da classe de parede,
`B_e` obstrução por entidade, `t_i`/`r_j` offsets de transmissão/recepção,
`c` ganho direcional, `X` sombreamento correlacionado, `ε` ruído. Derivação e
referências em [01](matematica/01-propagacao.md).

**Calibre e posto.** Com N âncoras há `N(N−1)` enlaces dirigidos, mas só
`N(N−1)/2 + (N−1)` números independentes (20 para N=6; 9 para N=4): as somas
simétricas e as antissimétricas. O calibre tem dimensão 2 (`Σt`, `Σr`) mais 3 de
inclinação comum de dipolo quando há grau direcional. `modelo/testes.py` verifica
o posto contra `N(N−1)/2 + (N−1)` — se essa conta falhar, o ajuste está
estimando um número que o dado não contém. [03](matematica/03-estimacao.md)

**Censura.** Um pacote abaixo do piso de captura não produz linha nenhuma. Tratar
a mediana dos que passaram como mediana real introduz viés de até 8 dB. O sinal
que separa enlace forte de enlace censurado é a inclinação `dRSSI/dPtx`: vale
1,00 por identidade num enlace forte e achata num fraco.
[02](matematica/02-censura.md)

**Ganchos desligados.** Ganho direcional, mapa de material e offset escalar por
âncora estão implementados (`modelo/padrao.py`, `modelo/material.py`) e
**reprovados na transferência**. O código fica, o interruptor fica em `None`, e o
motivo fica escrito ao lado. [06 §6.1](matematica/06-transferencia.md)

### 5.3 Estimação de posição — `tracker.py`, `vivo.py`

Filtro de partículas SIR, 600 partículas, com restrição de planta baixa
(partícula não atravessa parede). Movimento: cadeia de Markov de **2 estados**
(parado / andando), com `t_parado = 60 s`, `t_andando = 20 s` e
`jitter_parado = 0,03 m`. Opções: verossimilhança Student-t (`nu`), dobradiça de
censura no piso, temperagem `alpha`. Reamostragem quando `ESS < N/2`.

O estado **atravessa o tempo**: `vivo.py` roda **um** filtro contínuo alimentado
em fatias de 0,5 s (2 Hz), não um filtro novo por render. Âncora que não falou na
fatia simplesmente não entra — termo ausente, nunca RSSI de piso.

Saída: `P(cômodo)` (primária) + `(x, y)` + `spread()`, sempre juntos.
[04](matematica/04-filtro-particulas.md)

### 5.4 Validação — `loo.py`, `estaticos.py`, `revisao.py`

| módulo | invariante que testa | por que não é auto-validação |
|---|---|---|
| `loo.py` | localiza cada âncora a partir das outras | a posição da âncora é verdade de graça, medida com trena, e não entrou no ajuste daquele enlace |
| `estaticos.py` | emissores BLE parados da casa | o alvo não se move; qualquer passeio no mapa é erro do estimador |
| `revisao.py` | modelo novo × modelo em produção, com juiz | reajuste cego era a deriva; o juiz compara contra o que já está no ar |

**A regra de promoção (LOPO).** A unidade é o **ponto**, não a observação — as
3–5 âncoras de um mesmo ponto erram juntas, e validação cruzada por observação
vaza e aprova qualquer coisa. O braço de controle é o **modelo em produção**, não
o modelo nulo. Promove-se só se `média(ganho por ponto) − EP > 0,5 dB`. Quatro
blocos já reprovaram nessa régua. [06](matematica/06-transferencia.md)

### 5.5 Desenho de campanha — `campanha.py`, `modelo/padrao.py`

Escolha D-ótima dos pontos de rótulo: maximiza `log det` da informação de Fisher
do que se quer estimar, com dois cuidados que o critério puro não tem —
separação mínima na tela (`2·RAIO_PX/esc` metros, senão o dedo não distingue os
pontos) e peso pela probabilidade de o enlace **existir** (`P[RSSI > limiar]`),
porque num cômodo isolado o desenho conta N âncoras por ponto e a realidade
entrega 2. [05](matematica/05-campanha-dotima.md)

### 5.6 Sítio a partir de nuvem de pontos — `modelo/nuvem.py`

Opcional. Lê uma reconstrução 3D e a encaixa no frame da planta (ajuste de plano
de Manhattan + ICP restrito). A trena continua valendo; o ganho é o orçamento de
erro medido, não a conveniência. Sítio simétrico empata em 180° — o desempate é
por cor ou pela trajetória da câmera. [09](matematica/09-geometria-3d.md)

### 5.7 Tempo — `oportunidade.py`, `modelo/temporal.py`

O par que acrescenta o relógio ao modelo. `oportunidade.py` cruza os intervalos
de `presenca.jsonl` (escritos por `ferramentas/vigia_usb.py` no host) com o
`refcyd.jsonl` do receptor: enquanto o alvo está no cabo USB, ele está na mesa, a
posição é conhecida e **o resíduo só pode ser tempo**. É a única configuração em
que deriva temporal e deriva de posição não estão confundidas — e custa zero
trabalho humano.

O rótulo gratuito é conferido antes de ser usado, e a conferência é **livre de
modelo**: `assinatura(y) = y − média(y)` separa o vetor de RSSI em modo comum
(tempo, potência) e forma (geometria); um bloco é rejeitado se a forma dele se
afastar da mediana das outras em mais de 3,5 MAD. Usar `A/n/W` aqui seria a
métrica validando o próprio ajuste.

`modelo/temporal.py` ajusta `μ(t)` e `log σ²(t)` numa base de Fourier diurna,
escolhe `K` com **dia inteiro fora**, e promove pela regra de
[06](matematica/06-transferencia.md) medida em NLL — não RMSE, porque o modelo
muda `σ` e o RMSE é cego a isso. Ele devolve `None` quando não há ciclo, e fora
das horas cobertas se cala. O rastreador consome como `temporal=`:
`b ← b + μ(t)` e `σ ← σ·escala(t)`. [10](matematica/10-temporal.md)

## 6. Interfaces

### 6.1 Portas UDP e HTTP

| porta | sentido | carga | quem escuta |
|---|---|---|---|
| 5007 | âncora → host (broadcast) | avistamentos BLE | `rtls/receptor.py` |
| 5008 | host → âncoras (broadcast) | farol: "o host está aqui" | firmware da âncora |
| 5009 | CYD → host | rótulos da campanha (3× cada) | `rtls/rotulos.py` |
| 5010 | host → CYD | posição estimada, 2 Hz | firmware `campanha` |
| 8099 | navegador → host | painel SVG | `ferramentas/roda_painel.sh` |

Trocar de porta: as constantes moram no topo de `rtls/receptor.py`,
`rtls/rotulos.py`, `rtls/mapa_alvo.py` e em `#define PORTA_*` de
`firmware/alvo-cyd/src/campanha.cpp`. Não há descoberta automática — de propósito.

### 6.2 Arquivos em `$RTLS_DADOS`

| arquivo | escrito por | formato | regra |
|---|---|---|---|
| `<n>.jsonl` | `receptor.py` | um avistamento por linha | append-only |
| `refcyd.jsonl` | `receptor.py` | avistamentos do transmissor de referência | append-only |
| `presenca.jsonl` | `vigia_usb.py` (no host) | `{host, ev: ini\|fim, t}` | append-only; só transições |
| `rotulos.jsonl` | `rotulos.py` | um evento de rótulo por linha | **append-only, nunca editado** |
| `correcoes.jsonl` | você, à mão | `{boot, seq, ...}` | corrige sem apagar |
| `modelo.json` | `revisao.py` | `A`, `n`, `W`, offsets | promovido só via LOPO |
| `vivo.json` | `vivo.py` | posição, `P(cômodo)`, spread | reescrito a 2 Hz |
| `vivo_hist.jsonl` | `vivo.py` | uma linha a cada 10 s | append-only |

`dados/` e `*.jsonl` são gitignorados: crescem em GB e são do **sítio**, não do
projeto.

### 6.3 Variáveis de ambiente

| variável | default | efeito |
|---|---|---|
| `RTLS_SITIO` | `sitios/exemplo.json` | qual sítio carregar |
| `RTLS_DADOS` | argumento explícito | onde os JSONL moram |
| `RTLS_NUVEM` | vazio | caminho da nuvem de pontos; sem ela, `modelo/nuvem.py` roda só os testes sintéticos |
| `RTLS_BUILD` | `../firmware/ancora-c3/build` | de onde `flash_ancoras.sh` tira os binários |
| `RTLS_NAO_GRAVAR` | vazio | MACs que o gravador nunca toca |
| `RTLS_PORTA_CYD` | detecção automática | porta serial da CYD |

## 7. Sem hardware: o simulador

`ferramentas/simula.py` gera dado sintético **no formato exato das âncoras**, o
que faz o sistema inteiro rodar sem uma placa sequer — inclusive a censura, que é
o comportamento que mais engana quem simula ingenuamente. É o que sustenta a
quarta persona do PRD (a IA que reproduz isto) e o objetivo O5.

```bash
PYTHONPATH=. python3 ferramentas/simula.py --help
```

## 8. Testes

Não há framework. Cada módulo carrega o próprio `demo()` com `assert`s, porque o
teste tem de morar ao lado da lógica que ele protege. `testes/roda_tudo.py` só os
enfileira, e o contrato é minúsculo: **levantar é a única forma de falhar**.

```bash
PYTHONPATH=. python3 -m testes.roda_tudo             # 26 alvos (24 sem scipy), ~50 s, sem hardware
PYTHONPATH=. python3 -m testes.roda_tudo sitio       # só os que casam com 'sitio'
RTLS_SITIO=testes/sitio_outro.json PYTHONPATH=. python3 -m testes.roda_tudo  # o que importa
```

A terceira linha é a que sustenta a arquitetura: se a suíte só passa no sítio de
exemplo, o sítio não é dado, é código disfarçado. O sítio alternativo é versionado
— [`testes/sitio_outro.json`](../testes/sitio_outro.json), galpão de 12×7 m com 4
âncoras — e existe **só** para isso; a [CI](CI-CD.md) roda a suíte nos dois. Foi
ele que expôs quatro suposições escondidas — posto 20, `range(30)`, nome de
emissor fixo e reserva de borda da tela — todas corrigidas na raiz.

Ele mora em `testes/` e não em `sitios/` de propósito: o critério de lançamento
do [PRD](PRD.md) diz que `sitios/exemplo.json` é o **único** sítio versionado, e
um fixture de teste em `testes/` mantém as duas coisas verdadeiras.

Ficam fora da suíte `modelo/altura.py`, `modelo/invariantes.py` e
`modelo/padrao.py`: eles leem os JSONL de uma campanha real, e um teste que passa
por ausência de dado é pior que nenhum. Rode-os à mão depois da primeira campanha.

## 9. Como estender

| quero | mexo em | não mexo em |
|---|---|---|
| outro prédio | `sitios/meu.json` | nada de Python |
| mais âncoras | `ancoras` no JSON + `flash_ancoras.sh` | o firmware é o mesmo binário |
| outra placa de tela | `build_flags` de `platformio.ini` | o resto do firmware |
| outro modelo de propagação | `rtls/modelo/nucleo.py` | só promova via LOPO ([06](matematica/06-transferencia.md)) |
| outro estimador | `rtls/tracker.py` | a interface é `update()` + `spread()` + `P(cômodo)` |
| outro transporte | `wireless.c` + `receptor.py` | o formato do JSONL é o contrato |

**A regra que atravessa todas as extensões:** um número que aparece em dois
lugares vai divergir. Se o seu ajuste precisa de uma constante que o firmware
também precisa, ela vai no gerador do `.h` — não nos dois arquivos.
