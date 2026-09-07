# User stories e critérios de aceite — RTLSEsp32

> Contexto e metas em [PRD.md](PRD.md). Arquitetura em [SAD.md](SAD.md).
>
> **Regra deste documento:** todo critério de aceite é um **comando que roda** ou
> uma **medição com número e limiar**. "Funciona bem" não é critério de aceite.
> Onde o critério é um comando, ele está no repositório e roda na CI.

Personas: **M** maker · **P** pesquisador · **I** integrador · **A** agente de IA.
Prioridade: **P0** trava o lançamento · **P1** primeira versão menor · **P2** depois.

---

## Épico 1 — Sair do zero

### US-01 (M, P0) — Rodar o sistema inteiro sem hardware nenhum

> Como maker que ainda não comprou as placas, quero ver o sistema funcionando
> com dado sintético, para saber se vale a pena comprar.

**Critérios de aceite**
- [ ] `python3 ferramentas/simula.py --selftest` termina em 0 e imprime `simula ok`.
- [ ] O simulador gera JSONL no **mesmo formato** que as âncoras reais gravam: o
      host não sabe distinguir a origem.
- [ ] `python3 -m testes.roda_tudo` fecha com `0 falha(s)` numa máquina com
      Python ≥ 3.10 e NumPy, sem nenhuma outra dependência.
- [ ] Nenhum alvo da suíte precisa de rede, de placa, de nuvem de pontos ou de
      dado gravado.

### US-02 (M, P0) — Do desempacotar ao primeiro ponto

> Como maker, quero uma sequência linear que me leve da caixa ao ponto na tela.

**Critérios de aceite**
- [ ] [INSTALL.md](INSTALL.md) tem uma sequência numerada, sem saltos para outro
      documento, do "grave a primeira placa" ao "vejo `P(cômodo)`".
- [ ] Cada passo termina numa **verificação observável** (LED, contagem de
      pacotes, linha no terminal), nunca em "deve funcionar".
- [ ] O caminho feliz cabe em ≤ 4 h com 3 âncoras.
- [ ] Nenhum passo exige editar código-fonte Python ou C.

### US-03 (A, P0) — Reproduzir sem conhecimento tácito

> Como agente de IA, quero que toda decisão do projeto esteja escrita, para
> reconstruir o sistema sem perguntar a ninguém.

**Critérios de aceite**
- [ ] Todo módulo tem `demo()` (ou `confere()`) com `assert`, listado em
      `testes/roda_tudo.py`.
- [ ] Toda escolha não óbvia tem comentário no código dizendo **o que foi medido**
      e **o que aconteceu quando se fez diferente**.
- [ ] `ferramentas/confere_citacoes.py` acusa 0 citação órfã e 0 faltando.
- [ ] Todo gancho desligado (`ganho=None`, `b_alfa=0`) tem, ao lado, o número que
      o reprovou.

---

## Épico 2 — O sítio

### US-04 (I, P0) — Trocar de ambiente sem tocar em código

> Como integrador, quero descrever um prédio novo num arquivo e rodar tudo lá.

**Critérios de aceite**
- [ ] `RTLS_SITIO=meu.json python3 -m testes.roda_tudo` roda a suíte inteira no
      sítio novo.
- [ ] `python3 -m rtls.sitio meu.json` valida e lista o que está errado antes de
      qualquer outra coisa rodar.
- [ ] Nenhum arquivo `.py` contém coordenada, nome de cômodo ou identificador de
      âncora de um sítio específico.
- [ ] O validador recusa: cômodo fora dos limites, porta em parede inexistente,
      âncora fora de todo cômodo, MAC repetido.

**Verificação (a que travou a regressão):** os testes de `campanha`, `loo`,
`estaticos` e `nuvem` já falharam por assumir a geometria de um sítio específico
— proporção da planta, marcadores `T4`/`T6`, limiar de 3,0 m/min. Os três foram
reescritos para derivar tudo do sítio carregado. **Não** adicione um `assert` com
número absoluto que só vale na sua casa.

### US-05 (I, P1) — Mais âncoras

> Como integrador de um andar comercial, quero usar 12 ou 20 âncoras.

**Critérios de aceite**
- [ ] Nada no código fixa N = 6. Confirmação: `grep -rn "\b6 ancoras\b" rtls/`
      não retorna nenhuma condição de código.
- [ ] Todas as N placas rodam o **mesmo binário**; a identidade é o MAC de
      fábrica, e o mapa MAC→número vive no host.
- [ ] O ajuste da malha escala: N âncoras dão N(N−1) enlaces dirigidos e
      N(N−1)/2 − ... parâmetros independentes segundo o calibre de
      [03 §3.4](matematica/03-estimacao.md).
- [ ] Acima de ~2000 m², a nota de escala de `Tracker._seed()` diz o que mudar.

### US-06 (P, P1) — Sítio a partir de reconstrução 3D

> Como pesquisador, quero gerar a planta de uma varredura LiDAR, sem trena.

**Critérios de aceite**
- [ ] `rtls/modelo/nuvem.py` alinha por gravidade → Manhattan → correlação FFT da
      pegada de ocupação, **sem** ponto de referência marcado à mão.
- [ ] Em planta assimétrica o encaixe recupera a posição com erro < 5 cm
      (verificado em `nuvem.demo()`).
- [ ] Em planta simétrica o empate de 180° **aparece** e o teste exige que
      apareça — a limitação é verificada, não escondida.
- [ ] O orçamento de erro de cada etapa está em [09 §9.1](matematica/09-geometria-3d.md).

---

## Épico 3 — Medir bem

### US-07 (P, P0) — Saber onde ficar de pé

> Como pesquisador, quero que o sistema me diga em quais pontos medir, em vez de
> eu escolher no olho.

**Critérios de aceite**
- [ ] `rtls.campanha.pontos(k)` devolve k pontos **D-ótimos** para o sítio
      carregado, com o motivo de cada um (cômodo, distância da âncora mais
      próxima, ganho em log-det).
- [ ] O ganho de informação de cada ponto adicional é impresso, para decidir
      quando parar.
- [ ] Os pontos escolhidos têm **contraste** de distância: `min(d) < 0,35·max(d)`
      — sem isso, A e n ficam confundidos.
- [ ] Trocar o sítio troca os pontos, sem editar código
      (`rtls.campanha.demo()` verifica).

### US-08 (P, P0) — Não ser enganado pela censura

> Como pesquisador, quero que o pacote que não chegou conte como evidência.

**Critérios de aceite**
- [ ] A varredura de Ptx mostra inclinação dRSSI/dPtx = 1,00 no enlace forte
      (identidade) e **achatada** no fraco (`ferramentas/simula.py:selftest`).
- [ ] `Tracker.loglik` trata leitura abaixo do piso como **dobradiça de um lado
      só**, não como ausência de informação.
- [ ] Âncora que não reportou no passo **não** vira RSSI de piso: termo ausente,
      não termo inventado.
- [ ] Todo limiar de detecção do sítio (`limiar_deteccao_dBm`, `sigma_deteccao_dB`)
      é do JSON, não constante no código.

### US-09 (P, P0) — Provar que um modelo melhora antes de ligá-lo

> Como pesquisador, quero um portão que impeça um modelo bonito e inútil de
> entrar em produção.

**Critérios de aceite**
- [ ] A unidade da validação cruzada é o **ponto**, não a observação.
- [ ] O ponto retirado sai do **ajuste inteiro**, não só da avaliação.
- [ ] O braço de controle é o **modelo implantado**, não um modelo nulo.
- [ ] Promove só se `média(ganho por ponto) − erro padrão > 0,5 dB`.
- [ ] Quatro blocos já reprovados (material, offset escalar, ganho direcional,
      altura) continuam no código, desligados, com o número que os reprovou ao
      lado.

### US-17 (P, P1) — Rótulo que aparece sozinho

> Como pesquisador, quero que as horas em que o alvo fica no cabo USB virem dado
> rotulado, sem que ninguém precise andar pela casa nem digitar nada.

**Critérios de aceite**
- [ ] O sítio descreve `postos` — posição, raio (= incerteza) e quais hosts.
- [ ] Um host só pode pertencer a um posto; `valida()` reprova o contrário.
- [ ] O vigia detecta o cabo **sem abrir a porta serial** (abrir reseta o ESP32)
      e sem casar `/dev/ttyACM*` (é o T-Embed de outro projeto).
- [ ] Grava só a **transição**, e fecha a sessão aberta ao sair.
- [ ] Todo bloco colhido é conferido antes de ser usado, e a conferência é
      **livre de modelo** — nunca contra o `A/n/W` que ele vai ajudar a estimar.
- [ ] A conferência é cega à variação temporal: mesmo conjunto de rejeitados com
      e sem 8 dB de deriva comum.
- [ ] Sítio sem `postos` continua funcionando — o caminho inteiro fica inerte.

---

### US-18 (P, P1) — Medida mais precisa dada a hora

> Como pesquisador, quero que o sistema saiba que às 20h o canal é pior que às
> 4h, e que ele desconfie mais do RSSI na hora ruim.

**Critérios de aceite**
- [ ] Modela `μ(t)` **e** `σ(t)`; um modelo que só corrige a média não serve.
- [ ] `μ` não tem termo constante — não pode competir com o `A` da propagação.
- [ ] A correção de viés de `log ε²` (−1,2704) está aplicada e testada.
- [ ] `K` é escolhido com **dia inteiro fora**, e a régua é NLL, não RMSE.
- [ ] Promove pela regra da US-09 traduzida: `média(Δ) − EP > 0,16 nats` e
      **nenhum dia pode piorar**.
- [ ] Em ruído branco puro, **não promove nada** — verificado em 6/6 sementes.
- [ ] Fora das horas com dado de treino, devolve `μ=0` e escala `1`: nunca
      extrapola Fourier para dentro de um buraco de 16 h.
- [ ] Com `temporal=None` o rastreador é idêntico ao de hoje.

---

## Épico 4 — Usar

### US-10 (I, P0) — Cômodo com incerteza, nunca um ponto sozinho

**Critérios de aceite**
- [ ] Toda saída de posição vem com `spread()` em metros.
- [ ] `P(cômodo)` soma 1 e o argmax bate com a verdade nos casos de teste.
- [ ] Alvo ouvido por **1 âncora** produz posição com spread > 5 m — sinaliza
      incerteza, não mente (`rtls.tracker.demo()`).
- [ ] Sem âncora nenhuma e sem histórico: devolve `None`, não inventa.

### US-11 (I, P0) — Alvo parado tem de ficar parado

**Critérios de aceite**
- [ ] Emissor sintético imóvel: passeio < 35 % do passeio do mesmo filtro sem o
      modo parado. MEDIDO no sítio de exemplo: **3,8 contra 41,9 m/min**.
- [ ] `P(parado)` > 0,6 com o modo ligado e < 0,6 sem ele.
- [ ] O teste é **relativo**, não um limiar absoluto em m/min — um limiar
      absoluto só vale na geometria em que foi calibrado.

### US-12 (I, P1) — Ver a malha sem instalar nada

**Critérios de aceite**
- [ ] `ferramentas/roda_painel.sh` sobe um painel HTTP que mostra enlaces medidos
      e o LOO sobre a planta, regenerado a cada 30 s.
- [ ] Um só filtro permanente publica o estado; os SVGs apenas **leem** — criar
      um filtro por render é o bug que fazia o alvo passear.
- [ ] Falha alto e cedo se a porta já estiver ocupada.

### US-13 (M, P1) — Rotular pontos andando pela casa

**Critérios de aceite**
- [ ] O alvo desenha a planta do **sítio carregado** na tela (gerada por
      `ferramentas/gera_firmware_alvo.py`), não uma planta compilada à mão.
- [ ] `confere()` falha se o `.h` em disco divergir do que o sítio geraria agora.
- [ ] Toque na tela envia o rótulo por UDP na hora; `rtls/rotulos.py` grava.
- [ ] `rotulos.jsonl` é **append-only**; correção vai em `correcoes.jsonl`
      indexada por `(boot, seq)`.

---

## Épico 5 — Operar

### US-14 (I, P0) — O modelo não se reajusta às cegas

> Como integrador, quero que o sistema recuse trocar o modelo sozinho quando a
> troca piora.

**Critérios de aceite**
- [ ] `rtls/revisao.py` tem um **juiz**: o candidato só entra se ganhar no
      critério de transferência.
- [ ] Reajuste periódico sem juiz é tratado como defeito conhecido, com o
      episódio documentado.
- [ ] Toda promoção deixa registro do antes, do depois e do número que decidiu.

### US-15 (I, P0) — Privacidade

**Critérios de aceite**
- [ ] `sitios/*.json` é gitignorado; só o exemplo sintético é versionado.
- [ ] Nenhum MAC, SSID, endereço, IP ou caminho de usuário real no repositório
      (varredura por expressão regular na CI).
- [ ] `credenciais.h` gitignorado, com `.exemplo` versionado ao lado.
- [ ] [PRIVACIDADE.md](PRIVACIDADE.md) diz explicitamente que a **trilha**
      reidentifica um MAC rotativo — pseudonimizar o endereço não basta.

### US-16 (M, P2) — Gravar N placas sem errar

**Critérios de aceite**
- [ ] `ferramentas/flash_ancoras.sh` é idempotente: rodar de novo não regrava
      quem já está no mapa.
- [ ] Backup da flash virgem **antes** de gravar, sempre.
- [ ] Placa só entra no mapa depois de provar que está varrendo (> 20 pacotes em
      6 s).
- [ ] `RTLS_NAO_GRAVAR` protege placas Espressif alheias no mesmo USB (mesmo
      VID:PID).
- [ ] A gravação exige as **3** verificações de hash; `| grep -q` é proibido
      (SIGPIPE mata o `esptool` depois do bootloader).

---

## Matriz de rastreabilidade

| Story | Objetivo (PRD §4) | Verificação executável |
|---|---|---|
| US-01 | O5 | `python3 -m testes.roda_tudo` |
| US-02 | O4 | revisão de [INSTALL.md](INSTALL.md) |
| US-03 | O5, O6 | `ferramentas/confere_citacoes.py` |
| US-04 | O5 | `RTLS_SITIO=… python3 -m testes.roda_tudo` |
| US-05 | — | `rtls.modelo.testes.demo()` |
| US-06 | — | `rtls.modelo.nuvem.demo()` |
| US-07 | O2 | `rtls.campanha.demo()` |
| US-08 | O3 | `ferramentas.simula.selftest()` |
| US-09 | O2 | `rtls/modelo/padrao.py:lopo()` |
| US-10 | O1, O3 | `rtls.tracker.demo()` |
| US-11 | O2 | `rtls.estaticos.demo()` |
| US-12 | — | `ferramentas/roda_painel.sh` |
| US-13 | O1 | `ferramentas.gera_firmware_alvo.confere()` |
| US-14 | O3 | `rtls/revisao.py` |
| US-15 | — | varredura da CI |
| US-16 | O4 | `bash -n` + execução com placas |
| US-17 | O2 | `rtls.oportunidade.demo()`, `ferramentas.vigia_usb.demo()` |
| US-18 | O2 | `rtls.modelo.temporal.demo()` |
