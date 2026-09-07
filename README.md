# RTLSEsp32

**Localização em tempo real dentro de um prédio, com ESP32 de US$ 2, sem câmera,
sem UWB e sem instalar nada no aparelho rastreado.**

O alvo não coopera: ele só emite os anúncios BLE que qualquer celular, relógio ou
fone já emite o dia inteiro. As âncoras escutam, o host modela a propagação e um
filtro de partículas responde **em que cômodo** o alvo está.

| Medido numa implantação real | 6 âncoras, 48 m², 23 h de malha, 14 pontos rotulados |
|---|---|
| Erro de posição (LOO por âncora) | mediana **1,64 m**, pior caso 3,61 m |
| Cômodo correto | **6/6** |
| Multilateração + Kalman no mesmo dado | 3,4× pior na mediana |
| Custo por âncora | **US$ 4,62** |

> **A tese:** o RSSI basta **se** cada etapa for modelada e cada modelo for
> testado contra um invariante que ele não ajustou. O erro que sobra não é do
> rádio — é de quem tratou o rádio como se fosse uma trena.

---

## Comece aqui: 10 minutos, sem comprar nada

```bash
git clone <este-repo> && cd RTLSEsp32
pip install numpy
PYTHONPATH=. python3 -m testes.roda_tudo
```

Esperado: **`0 falha(s)`**. Com só o `numpy` saem `24 ok, 2 pulado(s)` — os dois
pulados são o caminho da nuvem de pontos, que é opcional e pede `scipy`; instale-o
se quiser os 26. O que conta é a contagem de falhas, e ela tem de ser zero. Isso roda o sistema inteiro — modelo,
estimação, filtro, campanha, geração de firmware — em dado sintético, sem placa,
sem rede e sem nuvem. Se fechar verde, o resto é hardware.

Depois: [docs/INSTALL.md](docs/INSTALL.md) leva do zero ao primeiro ponto na tela
em ≤ 4 h.

---

## Os documentos

Fluxo tradicional de produto, do *porquê* ao *como*:

| Documento | Responde |
|---|---|
| [**PRD**](docs/PRD.md) | O quê e por quê: problema, personas, objetivos com métrica, não-objetivos, riscos, critérios de lançamento |
| [**User stories**](docs/user-stories.md) | Para quem, com **critério de aceite que é um comando que roda** — nada de "funciona bem" |
| [**SAD**](docs/SAD.md) | Arquitetura: nove decisões estruturais, cada uma com a alternativa rejeitada e o custo dela |
| [**INSTALL**](docs/INSTALL.md) | Instalação e configuração, do desempacotar à primeira campanha |
| [**CI-CD**](docs/CI-CD.md) | O que a máquina confere antes de um merge, e como o repositório chega ao hardware sem derrubar uma medição |
| [**PRIVACIDADE**](docs/PRIVACIDADE.md) | Por que pseudonimizar o MAC **não** protege ninguém aqui — com a conta |
| [**Matemática**](docs/matematica/README.md) | Dez documentos, uma etapa cada, 39 referências, todas citadas |
| [**BOM**](hardware/BOM.md) · [**Montagem**](hardware/montagem.md) | O que comprar e como montar |

### A modelagem, etapa por etapa

Cada documento traz as equações, as referências e **termina com um comando que
verifica o que ele afirma**.

| # | | Fecha |
|---|---|---|
| 00 | [notação](docs/matematica/00-notacao.md) | eixos, índices, unidades, os três níveis de aleatoriedade |
| 01 | [propagação](docs/matematica/01-propagacao.md) | o modelo direto em dB, do Friis ao padrão de antena |
| 02 | [censura](docs/matematica/02-censura.md) | por que o pacote que **não** chega é informação |
| 03 | [estimação](docs/matematica/03-estimacao.md) | GLS/ML, calibre, identificabilidade — o que a malha não pode medir |
| 04 | [filtro de partículas](docs/matematica/04-filtro-particulas.md) | por que não multilateração; movimento, saída por cômodo |
| 05 | [campanha D-ótima](docs/matematica/05-campanha-dotima.md) | onde medir, quantos pontos, quando parar |
| 06 | [transferência](docs/matematica/06-transferencia.md) | a regra que decide se um bloco entra em produção |
| 07 | [invariantes](docs/matematica/07-invariantes.md) | sete testes; cinco não ajustam nada |
| 08 | [sombreamento](docs/matematica/08-sombreamento.md) | corpo sem rádio; e movimento ≠ presença |
| 09 | [geometria 3D](docs/matematica/09-geometria-3d.md) | nuvem de pontos → sítio, com orçamento de erro |
| 10 | [temporal](docs/matematica/10-temporal.md) | o relógio como coordenada; o cabo USB como restrição de posição |

---

## Como o repositório está organizado

```
sitios/exemplo.json      O SÍTIO É DADO. Geometria, âncoras, rádio — tudo aqui.
rtls/                    Host: ingestão, modelo, ajuste, filtro, saída
  sitio.py               ... carrega o sítio; é o único que lê o JSON
  receptor.py            ... UDP das âncoras -> JSONL append-only
  oportunidade.py        ... alvo no cabo USB = posição conhecida, de graça
  modelo/                ... propagação, censura, estimação, invariantes, tempo
  tracker.py  vivo.py    ... filtro de partículas; posterior por cômodo
ferramentas/             Campanha, painel, simulador, geradores, checadores
firmware/ancora-c3/      C (ESP-IDF): as N âncoras, MESMO binário nas N
firmware/alvo-cyd/       C++ (PlatformIO): sniffer, painel, campanha
testes/roda_tudo.py      Enfileira os 26 auto-testes. Sem framework.
docs/  hardware/         Ver a tabela acima
```

### A decisão que organiza todo o resto

**O sítio é dado, não código.** Um arquivo JSON descreve a geometria, as âncoras
e o rádio; `rtls/sitio.py` é o único módulo que o lê, e todo o resto — inclusive
o desenho da planta na tela do alvo, gerado em C — deriva dele.

O que sustenta essa afirmação não é a intenção: é a
[CI](.github/workflows/ci.yml) rodando a suíte inteira em **dois sítios
diferentes**, com número de âncoras, formato e cômodos diferentes. Um sítio só
provaria que o código roda; dois provam que ele não decorou o primeiro.

---

## Decisões que valem a pena conhecer antes de discordar

| Decisão | Porque não o óbvio |
|---|---|
| Filtro de partículas, não multilateração | Multilateração + Kalman mediu **3,4× pior** no mesmo dado. A verossimilhança do RSSI é assimétrica e censurada; um gaussiano em cima disso é um erro de modelo, não de sintonia |
| O pacote que não chega **entra** no ajuste | Abaixo do piso de captura não há linha nenhuma. Ignorar isso enviesa todo enlace longo. Trata-se como censura (Tobit), não como ausência |
| Todas as N placas rodam o **mesmo binário** | A identidade é o MAC; o mapa MAC→número mora no host. Gravar N firmwares diferentes é N vezes a chance de errar |
| Nada é promovido por caber melhor no ajuste | LOPO por ponto contra o modelo **em produção**; entra só se `média(ganho) − EP > 0,5 dB`. Quatro blocos foram reprovados assim — e continuam desligados no código |
| Ganho direcional e mapa de material: **desligados** | A matemática está certa; o instrumento não tem resolução para ela. O gancho fica, documentado, sem rodar |
| O alvo no cabo USB vira **âncora de oportunidade** | Horas de posição conhecida, de graça. Não serve como ponto de campanha (um ponto só dá desenho de posto 1); serve como **relógio**: com a posição travada, o resíduo só pode ser tempo |
| Sem nuvem, sem conta, sem serviço externo | O dado é do dono do imóvel. Ver [PRIVACIDADE](docs/PRIVACIDADE.md) |

> **A regra que atravessa o projeto inteiro:**
> **uma métrica não pode validar o próprio ajuste.**
> É preciso achar um invariante que a resposta errada viole —
> a soma em triângulo, a inclinação `dRSSI/dPtx = 1`, o LOPO, o emissor parado
> que não pode passear. Estão em [07-invariantes](docs/matematica/07-invariantes.md),
> e rodam dentro da suíte.

---

## Privacidade — leia antes de instalar perto de outras pessoas

O sistema não guarda nome nenhum. Mesmo assim, **dois endereços BLE do mesmo
aparelho pousaram no mesmo ponto, a 8 cm**, atravessando uma rotação de MAC.

A rotação de endereço não sobrevive ao perfil de RSSI: **a trilha é a
identidade**, e por isso trocar o MAC por um hash salgado não protege ninguém —
a chave de junção não é o endereço, é a trajetória.

A conta está em [docs/PRIVACIDADE.md §2](docs/PRIVACIDADE.md), junto com o
enquadramento LGPD/GDPR e a hierarquia de saídas que permite guardar o **menos
informativo** que resolve o seu caso.

---

## Estado

**MEDIDO** — o que tem número de uma implantação real: modelo de propagação,
censura, ajuste com calibre, filtro de partículas com movimento, campanha
D-ótima, LOPO, reidentificação por trilha.

**ABERTO** — implementado e **não** validado em sítio real, por isso não é saída
oficial: tomografia por sombreamento, mapa de material da nuvem de pontos, ganho
direcional. Ver [PRD §10](docs/PRD.md).

Se você for usar isto para decidir alguma coisa, rode
[07-invariantes](docs/matematica/07-invariantes.md) **antes** de acreditar em
qualquer número deste repositório — inclusive nos daqui de cima.

---

## Para agentes de IA

Este repositório foi escrito para ser continuado por outra pessoa **ou por outro
agente**. Quatro coisas ajudam:

1. **Comece por [docs/SAD.md](docs/SAD.md) §2**, não pelo código: nove decisões
   estruturais com a alternativa rejeitada e o custo dela. É o contexto que não
   se recupera lendo `.py`.
2. **Nunca chumbe um número do sítio.** Derive de `rtls.sitio` (`P.ESCOLHIDAS`,
   `P.COMODOS`, `P.RADIO`). A CI roda em dois sítios e reprova o que decorou o
   primeiro.
3. **Todo módulo com lógica não trivial tem um `demo()` com `assert`s**, e uma
   linha em `testes/roda_tudo.py`. Módulo novo segue a mesma regra.
4. **Não promova modelo por ele caber melhor no ajuste.** O critério é
   [06-transferencia](docs/matematica/06-transferencia.md) e não é negociável:
   quatro blocos já foram reprovados por ele.

Comentário no código explica *por que*, não *o que* — quase todo comentário longo
neste repositório é uma armadilha que custou horas. Vale ler antes de "limpar".

---

## Licença

MIT — código e documentação. Ver [LICENSE](LICENSE).

Referências científicas em [docs/matematica/referencias.bib](docs/matematica/referencias.bib);
os direitos dos trabalhos citados são de seus autores.
