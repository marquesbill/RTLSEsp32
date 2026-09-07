# Guia de CI/CD — RTLSEsp32

Este documento responde a duas perguntas: **o que a máquina confere antes de um
merge** e **como o que está no repositório chega ao hardware sem derrubar uma
medição em andamento**.

Arquivo da CI: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

---

## 1. O princípio: a CI só verifica o que ninguém olharia a olho nu

Uma CI que roda o que você já roda a cada save é ruído — some do radar em duas
semanas e some junto com ela a confiança de que verde significa alguma coisa.
Este projeto tem exatamente quatro coisas que passam despercebidas em revisão:

| # | O que passa despercebido | Por que só a máquina vê |
|---|---|---|
| 1 | Código chumbado no sítio do autor | Você sempre roda no *seu* sítio. Um `== 6` esquecido passa verde para sempre — até o primeiro clone com 4 âncoras. |
| 2 | `sitio_gerado.h` desatualizado | O `.h` é gerado mas **versionado**. Editar o sítio e não regerar deixa o alvo desenhando a planta antiga, sem erro nenhum. |
| 3 | Firmware que não compila | Você compila o que está mexendo. O outro firmware quebra em silêncio e só aparece com a placa na mesa, no sítio, no meio da campanha. |
| 4 | Constante duplicada que divergiu | O byte de versão do cabeçalho mora no C **e** no Python. Divergir corrompe todo pacote gravado até alguém notar. |

Tudo o mais — estilo, cobertura, lint — fica de fora de propósito.

---

## 2. Os três trabalhos

```
  push / PR
     │
     ├── suite   ×4  (2 sítios × 2 versões de Python)  ~40 s cada
     ├── ancora      (ESP-IDF v5.1.2, alvo esp32c3)    ~3 min
     └── alvo        (PlatformIO, 3 ambientes)         ~4 min (~40 s com cache)
```

Os três são independentes e rodam em paralelo. `fail-fast: false` na matriz é
deliberado: saber se caiu **em um sítio ou nos dois** é metade do diagnóstico.

### 2.1 `suite` — a matriz é o teste de arquitetura

```yaml
matrix:
  python: ["3.10", "3.13"]
  sitio:
    - { arq: sitios/exemplo.json,     nome: exemplo }
    - { arq: testes/sitio_outro.json, nome: outro }
```

Rodar em um sítio só provaria que o código roda. Rodar em dois prova que ele não
**decorou** o primeiro. [`testes/sitio_outro.json`](../testes/sitio_outro.json)
existe unicamente para isso, e varia justamente as dimensões onde o código
poderia estar chumbado:

| Dimensão | `exemplo` | `outro` | O que quebraria se estivesse chumbado |
|---|---|---|---|
| Âncoras | 6 | 4 | Contagem de pares (15 vs 6), posto da malha (20 vs 9), asserts de tamanho |
| Formato | 8×6 m (em pé) | 12×7 m (deitado) | A escolha de girar 90° a planta na tela do alvo |
| Cômodos | 5 | 3 | Índices de cômodo, cores, legendas |
| Alturas | 3 níveis | uma só (1,10 m) | Qualquer coisa que assuma variação em z |
| Emissores fixos | roteador + 2 | 1, com outro nome | Referência a emissor por nome literal |

Foram exatamente esses eixos que pegaram três bugs reais na primeira vez que a
matriz rodou: `ferramentas/malha_viz.py` referenciava globais mortas de um
módulo aposentado, `ferramentas/loo_viz.py` tinha três `== 6` literais, e
`rtls/modelo/testes.py` afirmava como universal um resultado que só vale com
6 âncoras.

> **Por que `testes/` e não `sitios/`.** O `.gitignore` só deixa passar
> `sitios/exemplo.json`, e o critério de lançamento do [PRD](PRD.md) diz que
> esse é o **único** sítio versionado. Um fixture de teste morando em `testes/`
> mantém as duas coisas verdadeiras ao mesmo tempo.

O passo `PYTHONPATH=. python3 -m rtls.sitio <arquivo>` roda antes da suite: se o
JSON é inconsistente, o erro sai com a mensagem do validador em vez de virar um
traceback de numpy trinta segundos depois.

**A suite já carrega, como alvos, os checadores de repositório** — não há
trabalho separado para eles:

| Alvo | O que garante |
|---|---|
| `ferramentas.gera_firmware_alvo:confere` | O `.h` no disco é byte a byte o que o gerador produz agora |
| `ferramentas.confere_citacoes:confere` | Nenhuma citação órfã nem faltando no `.bib` |
| `ferramentas.confere_repo:confere` | Nenhum link interno morto, nenhum sítio real versionado, versão do protocolo igual no C e no Python |

### 2.2 `ancora` — ESP-IDF

```yaml
- run: cp firmware/ancora-c3/main/credenciais.h{.exemplo,}
- uses: espressif/esp-idf-ci-action@v1
  with: { esp_idf_version: v5.1.2, target: esp32c3, path: firmware/ancora-c3 }
```

`credenciais.h` é gitignorado (é onde mora a senha do Wi-Fi). O build só precisa
que o arquivo **exista** — os valores do `.exemplo` compilam e nunca são
gravados em placa nenhuma pela CI.

A versão do IDF é fixada em `v5.1.2` de propósito. Um `latest` transforma o build
numa loteria com a agenda da Espressif; quando subir, que suba num PR que diga
que subiu.

A CI não usa [`firmware/ancora-c3/build.sh`](../firmware/ancora-c3/build.sh) — a
action já entrega o ambiente pronto. O `build.sh` existe para a *sua* máquina,
onde o `export.sh` do IDF tem duas armadilhas documentadas no próprio script.

### 2.3 `alvo` — PlatformIO

Compila os três ambientes (`cyd`, `painel`, `campanha`) num comando. `painel` e
`campanha` acham `credenciais.h` por `-I $PROJECT_DIR/../ancora-c3/main`, então
**uma cópia só** resolve os dois — não duplique o arquivo.

O cache de `~/.platformio` é chaveado pelo hash do `platformio.ini`: enquanto as
dependências não mudarem, o job cai de ~4 min para ~40 s.

Este trabalho garante que o `.h` versionado **compila**. Que ele esteja *em dia
com o gerador* é a suite que cobra — são duas falhas diferentes com dois
sintomas diferentes, e vale saber qual das duas você tem.

---

## 3. Rodar a CI inteira na sua máquina

A regra de ouro deste repositório: **a CI não roda nenhum comando que você não
possa rodar**. Não há passo mágico, nem segredo, nem serviço externo.

```bash
# 1) suite nos dois sítios (precisa só de numpy)
PYTHONPATH=. python3 -m testes.roda_tudo -v
RTLS_SITIO=testes/sitio_outro.json PYTHONPATH=. python3 -m testes.roda_tudo -v

# 2) firmware da âncora
cp firmware/ancora-c3/main/credenciais.h{.exemplo,}   # se ainda não tiver o seu
firmware/ancora-c3/build.sh build

# 3) firmware do alvo
pio run -d firmware/alvo-cyd -e cyd -e painel -e campanha
```

Esperado no passo 1, nos **dois** sítios: `26 ok, 0 falha(s)`. A CI instala
`numpy scipy` de propósito — com o `scipy` presente nada é pulado e os 26 alvos
rodam de verdade. Na sua máquina, sem `scipy`, o certo é `24 ok, 0 falha(s),
2 pulado(s)`; as duas saídas são verdes.

Se o passo 1 passa e a CI reprova, a diferença está no ambiente — quase sempre
uma versão de Python (a matriz cobre 3.10 e 3.13) ou um arquivo que existe na
sua máquina e não está versionado.

---

### 3.1 O que a sua máquina não consegue checar sozinha

Erro de **sintaxe** nova demais não aparece em teste nenhum: o módulo nem chega a
carregar, e no seu interpretador ele é sintaxe válida. `ast.parse(...,
feature_version=(3,10))` **não** resolve — medido: o tokenizador da 3.12+ aceita a
f-string com barra invertida seja qual for o `feature_version`. Só um
interpretador velho de verdade vê.

Se tiver um instalado (3.11 serve: a regra da f-string é a mesma da 3.10):

```bash
for f in $(git ls-files '*.py'); do python3.11 -m py_compile "$f" || echo "QUEBRA: $f"; done
```

Se não tiver, é para isso que a linha `python: ["3.10", "3.13"]` da matriz existe.
Ela é a única testemunha, e já pegou dois arquivos.

E há uma classe que nem uma matriz de versões pega: **o LAPACK por baixo do
numpy**. O runner do GitHub é Linux/OpenBLAS; um Mac é Accelerate. Os dois
calculam os mesmos valores singulares a menos de ~`eps·σ₀`, o que é irrelevante
— exceto quando o código decide alguma coisa por um σ que está *exatamente* na
tolerância. Aí a mesma linha de código classifica a direção de um jeito aqui e
de outro lá. Foi assim que `rtls/modelo/testes.py` fechou verde nesta caixa até
com o numpy 2.5.3 da CI e vermelho no runner, com `|z| = 2,1×10¹²`.

A defesa não é fixar versão de numpy, é **não decidir dentro do contínuo**: o
corte de posto tem de cair num vão do espectro, e o teste cobra o vão em vez de
cobrar o resultado que ele sustenta (`rtls/modelo/testes.py:demo`, assert da
folga). Se um dia essa linha cair, o desenho ficou mal condicionado — o conserto
é o desenho, nunca afrouxar o limite de `|z|`.

## 4. Ler uma falha

| Sintoma na CI | Causa quase certa | Conserto |
|---|---|---|
| `suite (outro)` vermelho, `suite (exemplo)` verde | Número chumbado do sítio de exemplo | Derive de `P.ESCOLHIDAS` / `P.COMODOS`, nunca de literal |
| `suite` vermelha nos dois, só em py3.10 | Sintaxe ou stdlib nova demais | Use o equivalente de 3.10 ou suba o piso na matriz **e** no INSTALL |
| `SyntaxError: f-string expression part cannot include a backslash` | Barra invertida **dentro** da expressão de uma f-string; a PEP 701 só liberou isso na 3.12 | Calcule o valor numa variável antes da f-string. Aconteceu de verdade em `rtls/campanha.py` e `ferramentas/malha_viz.py` |
| `gera_firmware_alvo.confere` falhou | Sítio mudou e o `.h` não foi regerado | `python3 ferramentas/gera_firmware_alvo.py --escreve` e commite o `.h` |
| `confere_repo` → `LINK MORTO` | Doc aponta para arquivo que não existe (ainda) | Crie o arquivo ou tire o link — as duas são respostas válidas |
| `confere_repo` → `VERSIONADO INDEVIDO` | `git add -f` passou por cima do `.gitignore` | `git rm --cached <arquivo>` — e veja a §6 se ele já foi *empurrado* |
| `confere_repo` → `PROTOCOLO DIVERGE` | Cabeçalho mexido em um lado só | Mexa nos dois; e leia a §5.4 antes de gravar |
| `suite` vermelha em `ModuleNotFoundError: scipy` | Alguém tornou o `scipy` obrigatório no núcleo | O núcleo roda com `numpy` e nada mais (US-01). Mova o import para o caminho da nuvem ou acrescente o módulo a `OPCIONAIS` em `testes/roda_tudo.py` |
| `ancora` → `Failed to resolve component` | Nome de componente que só existe numa faixa de versões do IDF | Peça o guarda-chuva (`driver`), não o `esp_driver_*`; a v5.4 da sua máquina aceita os dois e esconde o defeito |
| `confere_citacoes` → `ORFA` | Referência no `.bib` que nenhum `.md` cita | Cite ou remova |
| `recuperacao` → `|z|` na casa de 1e12, e só num sítio/versão | Duas tolerâncias respondendo "esta direção é observável?": a variância foi zerada por uma e o erro cobrado pela outra | Uma decomposição, um corte, e dele saem `theta`, `cov` **e** a base do nulo — `rtls/modelo/nucleo.py:gls` |
| `recuperacao` → `assert acima > 1e3 and abaixo > 1e3` | O corte de posto caiu no meio de um contínuo de σ; o `\|z\|` virou moeda de LAPACK | Conserte o **desenho** (mais âncoras, mais pontos de campanha). Afrouxar o `4.0` esconde o defeito |
| `oportunidade.demo` → `assert movt <= rej` | A checagem de assinatura parou de pegar bloco de outro lugar — em geral porque alguém passou a comparar blocos com **conjuntos de âncoras diferentes** | A média da assinatura é sobre as âncoras presentes; âncora muda muda a média. Compare só blocos com a mesma chave `tuple(b["rx"])` |
| `oportunidade.demo` → `assert r3 == r0` | A rejeição virou sensível à deriva temporal, ou seja o critério deixou de morar no espaço ortogonal a `1` | Não misture `nivel` na decisão. Se precisar, veja [10 §10.3](matematica/10-temporal.md) |
| `temporal.demo` → `assert reprovas == 6` | O portão de promoção afrouxou e passou a achar ciclo em ruído branco | Não baixe a `MARGEM` nem tire o `min_d Δ_d > 0`. Se o problema é falta de dado, o conserto é mais dias, não margem menor |
| `ancora` falhou em `malha.c` com `ble_gap_ext_adv_*` implícita | `sdkconfig` velho, configurado para outro alvo | `rm -rf firmware/ancora-c3/{sdkconfig,build}` — o `CONFIG_IDF_TARGET` do `sdkconfig.defaults` só entra quando o `sdkconfig` **não existe** |
| `ancora` falhou e `alvo` passou | Só o C3 | Reproduza com `build.sh build` |
| Os dois firmwares falharam | Quase sempre `credenciais.h` | Confira o passo `cp` |

---

## 5. CD — o que "deploy" significa aqui

Não há um deploy: há **quatro artefatos com cadências diferentes**, e o que
custa caro é a ordem entre eles.

| Artefato | Onde vive | Como vai | Frequência | Derruba a medição? |
|---|---|---|---|---|
| Firmware da âncora | N × ESP32-C3 | `ferramentas/flash_ancoras.sh` | Raro | **Sim** — a âncora reinicia |
| Firmware do alvo | 1 × CYD | `pio run -t upload` | Média | Não (o alvo é rotulador/sniffer) |
| Host (Python) | Servidor | `git pull` + reiniciar o daemon | Alta | Só o intervalo do restart |
| Sítio (`.json`) | Repositório | `git pull` + **regerar o `.h`** | Rara | **Sim** — invalida rótulos (§5.3) |

### 5.1 A regra que vale mais que todas as outras

> **Não faça deploy durante uma campanha.**

A campanha de rótulos mede rádio. Regravar uma âncora troca o `boot`, zera
contadores, e — se o firmware mudou potência, canal ou intervalo — muda o
próprio sinal que você está medindo. O resultado não é ruído: é um degrau no
meio do conjunto de treino, que o ajuste vai absorver como se fosse física.
Ver [`docs/matematica/06-transferencia.md`](matematica/06-transferencia.md).

Congele o rádio antes de andar, meça, e só então faça deploy.

### 5.2 Ordem de um deploy que não quebra nada

```
1. CI verde no commit que você vai implantar
2. host primeiro   (git pull; reiniciar receptor)    ← tolera âncora velha
3. âncoras depois  (flash_ancoras.sh)                ← uma de cada vez
4. alvo por último (pio run -t upload -e campanha)
5. 10 min de sanidade: painel com N/N âncoras vivas
```

Host antes de âncora, e não o contrário, por um motivo específico: durante uma
troca de protocolo o host novo pode ser escrito para aceitar as **duas** versões
de cabeçalho, enquanto uma âncora nova falando com host velho é rejeitada na
hora. A janela de incompatibilidade fica do lado que você controla.

### 5.3 Matriz de acoplamento: mudei X, tenho de refazer Y

| Mudei… | Regerar `sitio_gerado.h` | Regravar alvo | Regravar âncoras | Rótulos ainda valem |
|---|---|---|---|---|
| Geometria (paredes, cômodos) | **sim** | **sim** | não | sim (a posição não mudou) |
| Posição/MAC de âncora | **sim** | **sim** | não¹ | **não** — o enlace é outro |
| Pontos da campanha | **sim** | **sim** | não | sim (são pontos novos) |
| Rádio (potência, canal) | não | não | **sim** | **não** — releia a §5.1 |
| Código do host | não | não | não | sim |
| Classes de parede (`W_dB`) | não | não | não | sim (é parâmetro do modelo) |
| `postos` (mesa do cabo USB) | não | não | não | sim — não entra no `.h` nem no rádio |

¹ A âncora não sabe onde está. Todas as N placas rodam o **mesmo binário**; quem
dá identidade é o MAC, e o mapa MAC→número mora no host (`ancoras.txt`). Mover
uma âncora de lugar é uma edição no `.json`, não uma regravação.

Depois de qualquer "sim" na primeira coluna:

```bash
python3 ferramentas/gera_firmware_alvo.py --escreve   # o --escreve é o passo que todo mundo esquece
git add firmware/alvo-cyd/src/sitio_gerado.h
```

### 5.4 Trocar o protocolo do cabeçalho

O byte 29 do pacote é a versão (`VERSAO`, hoje `1`), e ele existe porque
`firmware/ancora-c3/main/wireless.c:53` e `rtls/receptor.py:27` **precisam**
concordar sem poder se incluir. Um receptor que vê versão errada levanta em vez
de decodificar lixo silenciosamente.

Para trocar: suba o número nos dois arquivos no mesmo commit (a CI reprova se só
um subir), ensine o receptor a aceitar a versão velha **também**, implante o
host, regrave as âncoras, e só então remova o suporte à velha — num commit
separado, depois que o painel mostrar N/N.

### 5.5 Gravar as âncoras

[`ferramentas/flash_ancoras.sh`](../ferramentas/flash_ancoras.sh) é idempotente:
ele só toca em placa que ainda não está em `ancoras.txt`. Três detalhes que
custaram tempo e estão codificados lá dentro:

- **Backup antes de gravar**, mesmo em placa nova.
- **`RTLS_NAO_GRAVAR="<mac> ..."`** — outras placas Espressif no mesmo USB têm o
  **mesmo VID:PID** das C3 e apareceriam na varredura. Se você tem outra placa
  ligada, ponha o MAC dela nessa variável.
- **A placa só entra no mapa depois de provar que está varrendo** (>20 pacotes
  em 6 s). Gravou mas não fala = não registrada.

### 5.6 Host

Não há build: é Python. `git pull`, reiniciar o daemon, conferir o painel.

O receptor escreve `rotulos.jsonl` em modo **append-only** — reiniciar não perde
nada, só cria uma fronteira de `boot` no arquivo, que é justamente o que você
quer para depois saber onde o deploy entrou. Correção de rótulo nunca edita o
JSONL: vai em `correcoes.jsonl`, chaveada por `(boot, seq)`.

`ferramentas/roda_painel.sh` sobe o painel e o daemon de posição juntos. Para
matar processo pelo nome, use `pgrep -af "[r]ecebe_udp"` com a classe entre
colchetes — sem isso o padrão casa com a própria linha do `ssh` e mata o seu
shell.

---

## 6. Quando um dado pessoal escapa para o histórico

`confere_repo` pega o arquivo **no índice**. Se ele já foi empurrado, tirar do
índice não basta: o blob continua no histórico e continua acessível.

O único conserto de verdade é reescrever o histórico (`git filter-repo`) e forçar
o push — e, se o repositório é público, tratar o dado como **vazado**: trocar a
credencial, não só apagá-la. Ver [`docs/PRIVACIDADE.md`](PRIVACIDADE.md).

Por isso o `.gitignore` barra a categoria inteira (`sitios/*.json`) e abre
exceção para um arquivo só. É mais barato do que confiar em disciplina.

---

## 7. Estender a CI

**Novo sítio na matriz** — se você mantém um segundo sítio *sintético* (nunca o
real):

```yaml
sitio:
  - { arq: sitios/exemplo.json,      nome: exemplo }
  - { arq: testes/sitio_outro.json,  nome: outro }
  - { arq: testes/sitio_grande.json, nome: grande }   # ex.: 12 âncoras, 2 andares
```

**Novo teste** — uma linha em `ALVOS`, em `testes/roda_tudo.py`. O contrato é
mínimo de propósito: *levantar é a única forma de falhar*; o valor de retorno não
é lido, então a mesma fila serve para `demo()` (devolve `None`) e para
`confere()` (devolve `True`).

**Novo módulo** — se ele tem lógica não trivial, ele ganha um `demo()` com
asserts no próprio arquivo e uma linha em `ALVOS`. Teste ao lado da lógica é o
que faz quem mexe no módulo ver o teste na mesma tela.

**O que deliberadamente NÃO entra:** os três alvos que dependem de campanha
gravada (`rtls.modelo.altura`, `rtls.modelo.invariantes`, `rtls.modelo.padrao`).
Eles leem o JSONL da *sua* medição; sem dado não há o que testar, e um teste que
passa por ausência de dado é pior que nenhum. Rode-os à mão depois da primeira
campanha ([INSTALL §8](INSTALL.md)).

---

## 8. O que a CI não cobre — e por quê

| Não cobre | Por quê | O que faz as vezes |
|---|---|---|
| Hardware na malha | Não há C3 no runner | O simulador (`ferramentas/simula.py`) fecha o laço em software; a malha real, o painel N/N |
| Precisão do posicionamento | Depende do sítio e da campanha | LOPO por ponto: promove só se `média(ganho) − EP > 0,5 dB` |
| Gravação de placa | Destrutivo e específico da máquina | `flash_ancoras.sh` exige 3/3 hashes verificados e >20 pacotes antes de registrar |
| Desempenho | Nada aqui é sensível a latência | — |
| Se o seu cabo USB realmente chega só à mesa | É um fato do seu apartamento, não do código | A checagem de assinatura, que rejeita o bloco cuja forma não bate com as outras do mesmo posto ([10 §10.4](matematica/10-temporal.md)) |
| Se existe ciclo diário no **seu** ambiente | Depende do prédio, dos vizinhos e da hora em que você usa o cabo | O portão de dia-inteiro-fora: se não existe, `ajusta()` devolve `None`, e isso é o resultado certo |

O ponto do último item vale para o segundo: **uma métrica não valida o próprio
ajuste**. Uma CI que aprovasse o modelo pelo erro no conjunto em que ele foi
ajustado estaria carimbando qualquer coisa. O que vale é o invariante que a
resposta errada viola — e esses moram em
[`docs/matematica/07-invariantes.md`](matematica/07-invariantes.md), rodando
dentro da suite, não numa métrica de dashboard.
