# PRD — RTLSEsp32

> Documento de produto. O *quê* e o *porquê*.
> O *como* está em [SAD.md](SAD.md); a matemática, em [matematica/](matematica/README.md).

| campo | valor |
|---|---|
| Produto | RTLSEsp32 — localização em tempo real em ambiente fechado, por rádio, com ESP32 |
| Versão do documento | 1.0 |
| Estado | as decisões marcadas **MEDIDO** vêm de uma implantação real de 6 âncoras; as marcadas **ABERTO** ainda não têm evidência |

---

## 1. Problema

Saber **em que cômodo** está uma pessoa ou um objeto, dentro de um prédio, sem
câmera, sem app no aparelho rastreado e sem infraestrutura cara.

GPS não entra em ambiente fechado. As alternativas comerciais pedem UWB
(âncoras de US$ 100+ cada, sincronizadas), Bluetooth AoA (arranjos de antena) ou
Wi-Fi RTT (poucos aparelhos suportam). Todas exigem que o alvo coopere.

Sobra o **RSSI** — a potência recebida de um pacote de anúncio BLE que qualquer
aparelho já emite. É o sinal mais barato que existe e o mais malcomportado: em
2,4 GHz, dentro de casa, o desvio-padrão do RSSI num enlace fixo é de 2 a 4 dB e
uma parede tira 6 dB. Converter isso em metros ingenuamente dá erro de 5 a 10 m,
que é maior que o cômodo.

**A tese deste projeto:** o RSSI é suficiente **se** cada etapa for modelada e
cada modelo for testado contra um invariante que ele não ajustou. O erro que
sobra não é do rádio, é de quem tratou o rádio como se fosse uma trena.

## 2. Para quem

| Persona | O que quer | O que já sabe | O que NÃO quer |
|---|---|---|---|
| **Maker** | montar num fim de semana e ver o ponto se mexer | solda, `pip install`, gravar ESP32 | ler 10 documentos antes do primeiro pacote |
| **Pesquisador** | comparar o próprio estimador com uma linha de base honesta | estatística, propagação | um sistema onde não dá para saber por que o número deu aquilo |
| **Integrador** | ocupação por cômodo num prédio real, com LGPD resolvida | redes, operação | hardware proprietário; dado pessoal na nuvem de terceiro |
| **IA** (agente que vai reproduzir isto) | um repositório onde cada afirmação é verificável sem hardware | ler código | conhecimento tácito que só existe na cabeça de quem construiu |

A quarta persona é explícita: **todo teste roda sem hardware, em segundos, com
um sítio de exemplo versionado.** `python3 -m testes.roda_tudo` é a porta de
entrada de qualquer agente.

## 3. O que o produto faz

Uma frase: **N âncoras ESP32-C3 ouvem os anúncios BLE que já existem no
ambiente; um host converte RSSI em uma distribuição de probabilidade sobre os
cômodos.**

### 3.1 Saída primária: o cômodo, não o metro

A saída oficial é `P(cômodo)` — um vetor que soma 1. O metro (x, y) sai junto,
sempre acompanhado do espalhamento da nuvem de partículas.

**Por quê.** O erro mediano MEDIDO em regime é de 1,2 a 1,7 m. Num cômodo de
3×4 m isso acerta o cômodo quase sempre e erra o canto com frequência. Publicar
"(2,27; 1,50)" convida a decisões que o dado não sustenta; publicar "quarto1:
0,88 / sala: 0,11" é honesto sobre o mesmo dado. Ver
[04 §4.6](matematica/04-filtro-particulas.md).

### 3.2 O que NÃO é

- **Não é detector de presença.** A malha detecta **movimento**. A assinatura de
  nível do cômodo vazio não transfere entre janelas (r = +0,10); a de *jitter*
  transfere. Alguém sentado imóvel é indistinguível de ninguém.
  Ver [08 §8.3](matematica/08-sombreamento.md).
- **Não é rastreador submétrico.** Sem UWB não há 30 cm. O teto medido do modelo
  de propagação é ~6 dB de resíduo, que vira ~1,2 m. Ver [07 §7.8](matematica/07-invariantes.md).
- **Não identifica pessoas.** Identifica *endereços de rádio*. O aparelho que
  gira o MAC vira um alvo novo a cada rotação — e isso é um achado, não um bug:
  ver [PRIVACIDADE.md](PRIVACIDADE.md).

## 4. Objetivos e métricas

| # | Objetivo | Métrica | Meta | Como se mede |
|---|---|---|---|---|
| O1 | Acertar o cômodo | acerto do argmax de `P(cômodo)` | ≥ 85 % dos pontos rotulados | campanha rotulada (`rtls/rotulos.py`) |
| O2 | Erro em metros sob controle | mediana do erro no LOO de âncora | ≤ 2,0 m | `rtls/loo.py` — verdade de graça, sem trena |
| O3 | Não mentir | espalhamento publicado junto de toda posição | 100 % das saídas | `Tracker.spread()` |
| O4 | Montável | do desempacotar ao primeiro ponto na tela | ≤ 4 h para o maker | [INSTALL.md](INSTALL.md) |
| O5 | Reprodutível sem hardware | suíte verde numa máquina limpa | 100 % dos alvos | `python3 -m testes.roda_tudo` |
| O6 | Auditável | toda equação citada tem referência existente | 0 citação órfã | `ferramentas/confere_citacoes.py` |
| O7 | Custo | por âncora, sem caixa | ≤ US$ 5 | [hardware/BOM.md](../hardware/BOM.md) |

**Linha de base MEDIDA** (implantação de 6 âncoras, 48 m², 23 h de malha, 14
pontos rotulados): LOO de âncora com mediana 1,64 m e pior caso 3,61 m, 6/6
cômodos certos. Multilateração + Kalman no mesmo dado: 3,4× pior na mediana.

## 5. Princípios de projeto

Estes cinco não são estilo; cada um saiu de um erro que custou dias.

1. **O sítio é dado, não código.** Um JSON descreve geometria, âncoras e rádio.
   Trocar de prédio é trocar de arquivo. Nasceu de um repositório onde a planta
   era código e por isso não saía do lugar. → `rtls/sitio.py`, [SAD §3](SAD.md)
2. **Uma métrica não pode validar o próprio ajuste.** IoU do ajuste que a gerou
   não prova nada. Cada modelo precisa de um invariante que a resposta errada
   viole. → [07](matematica/07-invariantes.md)
3. **A unidade da validação é o ponto, não a observação.** As 3–5 âncoras de um
   mesmo ponto erram juntas. Validação cruzada por observação vaza e aprova
   qualquer coisa. → [06](matematica/06-transferencia.md)
4. **Censura é dado, não ausência.** Pacote abaixo do piso de captura não produz
   linha nenhuma. Tratar a mediana dos que passaram como se fosse a mediana real
   introduz viés de até 8 dB. → [02](matematica/02-censura.md)
5. **O gancho existe e fica desligado.** Ganho direcional, mapa de material e
   offset por âncora estão implementados e **reprovados na transferência**. O
   código fica, o interruptor fica em `None`, e o motivo fica escrito ao lado.
   → [06 §6.1](matematica/06-transferencia.md)

## 6. Escopo

### 6.1 Na versão 1.0

- Firmware de âncora (ESP32-C3) — varredura BLE promíscua, envio por UDP, malha
  ESP-NOW entre âncoras para o ajuste de propagação.
- Firmware do alvo/campanha (CYD ESP32-2432S028R) — planta na tela, toque
  rotula o ponto, envia por UDP; emissor de Ptx comandável em 8 níveis.
- Host Python — recepção, ajuste A/n/W, filtro de partículas, campanha D-ótima,
  LOO, painel SVG, simulador completo (o sistema roda sem uma placa sequer).
- Sítio como JSON + validador + gerador do `.h` do firmware do alvo.
- 10 documentos de matemática com 39 referências conferidas em CI.
- Reconstrução 3D → sítio (opcional; a trena continua valendo).

### 6.2 Fora da versão 1.0

| Fora | Por quê | Quando entra |
|---|---|---|
| UWB / AoA | outro hardware, outro projeto | nunca neste repo |
| Nuvem / conta / app | o dado é do dono do prédio | integração é do integrador |
| Identificação de pessoa | LGPD; e a trilha derrota o pseudônimo | ver [PRIVACIDADE.md](PRIVACIDADE.md) |
| Tomografia como saída oficial | implementada (`ferramentas/tomografia.py`), **não** validada em sítio real | quando houver campanha com corpo rotulado |
| Ganho direcional ligado | reprovado no LOPO: piora 1,24 → 1,61 m | quando um LOPO aprovar |

## 7. Restrições

- **Custo:** âncora ≤ US$ 5. Isso exclui antena externa e exclui UWB.
- **Alimentação:** tomada. Âncora a bateria não cabe no ciclo de trabalho da
  varredura promíscua.
- **Rede:** as âncoras precisam de Wi-Fi 2,4 GHz na mesma sub-rede do host (UDP
  broadcast). Canal fixo — ver [INSTALL §5](INSTALL.md).
- **Alvo não coopera:** só emite anúncio BLE. Nada é instalado nele.
- **Legal:** a planta de uma residência habitada é dado pessoal (LGPD art. 5º, I).
  Por isso `sitios/*.json` é gitignorado, com exceção do exemplo sintético.

## 8. Riscos

| Risco | Efeito | Mitigação | Estado |
|---|---|---|---|
| Rádio muda e ninguém percebe | modelo antigo, erro cresce calado | revisão com juiz (`rtls/revisao.py`); reajuste cego é proibido | resolvido |
| Poucas âncoras ouvem o alvo | posição vira palpite | `spread()` publicado; 1 âncora → spread > 5 m explícito | resolvido |
| Sítio simétrico | encaixe 3D empata em 180° | desempate por cor ou trajetória de câmera | documentado ([09 §9.2](matematica/09-geometria-3d.md)) |
| Alvo parado "passeia" | 50 m em 20 min sem sair da mesa | cadeia de Markov de 2 estados; MEDIDO 41,9 → 3,8 m/min | resolvido |
| Parede contada duas vezes | previsão 21 dB baixa | união de intervalos por (eixo, posição) menos vãos de porta | resolvido |
| MAC rotativo | alvo "some" | trilha reidentifica; **é um risco de privacidade, não de produto** | ver PRIVACIDADE.md |

## 9. Critérios de lançamento

A versão 1.0 sai quando, numa máquina limpa e sem hardware:

1. `python3 -m testes.roda_tudo` fecha com **0 falhas**;
2. `ferramentas/confere_citacoes.py` acusa **0 órfãs e 0 faltando**;
3. `INSTALL.md` leva do zero ao primeiro ponto sem consultar outro documento;
4. `sitios/exemplo.json` é o único sítio versionado;
5. toda user story de prioridade P0 tem critério de aceite verde
   ([user-stories.md](user-stories.md)).

## 10. Perguntas abertas

- **`b_alfa`** (viés de Ptx do alvo): três valores em três chamadores (0, 0,05 e
  0,2) e nenhuma medição que reconcilie. Só campanha rotulada resolve.
- **Altura das âncoras:** o efeito de altura mede 21,5 dB e **não** transferiu no
  LOPO. O que fica é a recomendação de altura única, não um termo no modelo.
- **Escala:** o `_seed()` uniforme na caixa envolvente basta até ~2000 m². Acima
  disso, semear na região das âncoras que ouviram — região, não ponto.
- **Tomografia:** funciona no banco sintético — mediana 0,39 m e p90 0,71 m com 6
  âncoras num hexágono de 4 m e ruído de 1 dB por enlace
  (`python3 ferramentas/tomografia.py`). Nunca foi validada com corpo rotulado em
  sítio real, e por isso não é saída oficial.
