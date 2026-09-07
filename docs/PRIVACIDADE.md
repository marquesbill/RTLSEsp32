# Privacidade — RTLSEsp32

Este documento existe porque o sistema tem uma propriedade **medida**, não
suposta, que inverte a intuição de quem instala: ele não guarda nome nenhum e
mesmo assim reidentifica aparelhos que trocam de endereço de propósito.

Quem for instalar isto em ambiente com outras pessoas deveria ler as §§1–3 antes
de ligar a primeira âncora.

---

## 1. O que o sistema mede, literalmente

As âncoras escutam **anúncios BLE** — pacotes que qualquer aparelho com
Bluetooth ligado emite em broadcast, sem pareamento, sem consentimento e sem que
o dono saiba. Para cada anúncio, uma âncora grava:

```
  tempo · MAC do emissor · RSSI · tipo de endereço · payload do anúncio
```

Não há microfone, não há câmera, não há nada instalado no aparelho do alvo, e o
sistema **não sabe o nome de ninguém**. Nesse sentido estrito, ele identifica
*endereços de rádio*, não pessoas.

É exatamente aí que a intuição erra.

---

## 2. O achado: a trilha é a identidade

### 2.1 O que foi medido

Durante o ensaio de emissores estáticos ([08 §8.4](matematica/08-sombreamento.md)),
**dois endereços BLE distintos pousaram no mesmo ponto, dentro de 8 cm.** São
dois MACs do mesmo aparelho, separados por uma rotação de endereço.

A rotação de MAC é a defesa de privacidade que Android e iOS ligam por padrão.
Ela não sobreviveu ao perfil de RSSI.

### 2.2 Por que isso tinha de acontecer

A posição estimada é uma função determinística do vetor de níveis recebidos

$$\mathbf{y} = (y_1, \dots, y_N) \in \mathbb{R}^N,$$

um número por âncora. Dois endereços caírem a 8 cm um do outro não significa que
as *posições* coincidiram: significa que os *vetores* coincidiram, dentro da
própria resolução do RSSI (1 dB).

Formalmente, é um teste de ligação de registros. Sejam $\mathbf{y}_A$ e
$\mathbf{y}_B$ os vetores de dois endereços observados em instantes vizinhos, e
$\boldsymbol{\Delta} = \mathbf{y}_B - \mathbf{y}_A$. Sob a hipótese
$H_1$ (**mesmo aparelho**), a diferença é só ruído de medição:
$\boldsymbol{\Delta} \sim \mathcal{N}(0,\, 2\sigma^2 I_N)$. Sob $H_0$
(**aparelhos diferentes**), some-se a dispersão que a geometria induz entre duas
posições quaisquer do sítio: $\boldsymbol{\Delta} \sim \mathcal{N}(0,\,
(2\sigma^2 + s^2) I_N)$, com $s \gg \sigma$.

A razão de verossimilhança logarítmica é

$$\Lambda = \frac{N}{2}\,\ln\!\left(1 + \frac{s^2}{2\sigma^2}\right)
  \;-\; \frac{\lVert\boldsymbol{\Delta}\rVert^2}{2}
        \left(\frac{1}{2\sigma^2} - \frac{1}{2\sigma^2+s^2}\right).$$

Com os números do sítio de referência — $N = 6$ âncoras, $\sigma \approx 4$ dB de
ruído de enlace, $s \approx 15$ dB de dispersão entre posições — o primeiro termo
vale $\tfrac{6}{2}\ln(1 + 225/32) \approx 6{,}1$ nats **por instante**, e
$\lVert\boldsymbol{\Delta}\rVert \to 0$ zera o segundo. Seis nats são um fator
$e^{6} \approx 400$ a favor de "mesmo aparelho", de **um único instante**. As
âncoras veem dezenas de anúncios por minuto: a evidência se acumula linearmente
no tempo e a dúvida evapora em segundos.

A conclusão não depende de o modelo estar bem ajustado. **Não é preciso saber
onde o aparelho está para saber que é o mesmo aparelho.** Basta que o vetor de
níveis seja estável e de dimensão alta — e é.

### 2.3 A consequência prática

> **Pseudonimizar o MAC não protege ninguém.**
> Trocar o endereço por um hash, mesmo com sal secreto, não muda nada: a chave de
> junção entre os registros **não é o endereço** — é a trajetória.

Isso derruba a arquitetura de privacidade mais comum em sistemas assim ("a gente
salga o MAC, então o dado é anônimo"). O sal protege contra quem tem só a lista
de endereços. Não protege contra quem tem os dados que o sistema **precisa**
guardar para funcionar.

Vale registrar que a rotação de MAC é a proteção, e ela é conhecidamente frágil
mesmo sem RTLS: Vanhoef et al., *Why MAC Address Randomization is not Enough*
(ASIACCS 2016) e Martin et al., *A Study of MAC Address Randomization in Mobile
Devices and When it Fails* (PoPETs 2017). O que este projeto acrescenta é que,
com uma malha de âncoras, nem os defeitos de implementação são necessários — o
canal físico basta.

O princípio geral é o mesmo de Narayanan & Shmatikov, *Robust De-anonymization of
Large Sparse Datasets* (IEEE S&P 2008) e de de Montjoye et al., *Unique in the
Crowd: The Privacy Bounds of Human Mobility* (Scientific Reports, 2013), que
mostrou que **quatro** pontos espaço-temporais bastam para singularizar 95% das
pessoas num conjunto de mobilidade. Um registro esparso e de dimensão alta é
identificador por natureza, e o vetor de RSSI é exatamente isso.

---

## 3. Enquadramento legal

### 3.1 O dado é pessoal

- **LGPD (Lei 13.709/2018), art. 5º, I** — dado pessoal é informação relacionada
  a pessoa natural *identificada ou identificável*. O padrão é "identificável",
  não "identificado". A §2 mostra que os registros são vinculáveis entre si e a
  um aparelho; um aparelho pessoal, num imóvel, é ligável a uma pessoa com
  esforço razoável.
- **LGPD art. 12, §2º** — dado que possa ser revertido, **com esforço
  razoável**, a uma pessoa **volta a ser dado pessoal**. Um MAC salgado com
  trilha preservada cai exatamente nesse dispositivo.
- **GDPR (2016/679), art. 4(1) e Considerando 26** — mesmo teste: leva-se em
  conta "todos os meios razoavelmente suscetíveis de serem utilizados".
- **Opinião 05/2014 do Grupo do Artigo 29 (WP216)** dá o critério operacional em
  três perguntas: *singularização*, *vinculabilidade* e *inferência*. Este
  sistema falha nas três — e a vinculabilidade é a que a §2 quantifica.

**A planta do imóvel também é dado pessoal.** O `sitios/*.json` de uma residência
habitada descreve cômodos, dimensões e a posição de aparelhos de uma família
específica. Por isso ele é gitignorado, com exceção do exemplo sintético.

### 3.2 Consequências para quem instala

O controlador do tratamento é **quem instala**, não este repositório. Se o
ambiente tem outras pessoas, você precisa, no mínimo:

| Obrigação | LGPD | O que significa na prática |
|---|---|---|
| Base legal | art. 7º / 11 | Legítimo interesse **não é automático**: exige teste de balanceamento documentado. Em ambiente doméstico com visitas, aviso e consentimento são mais defensáveis. |
| Finalidade e necessidade | art. 6º, I e III | Escreva a finalidade **antes** de instalar. "Porque é interessante" não é finalidade. |
| Minimização | art. 6º, III | Guarde a saída menos informativa que resolve o seu problema (§4). |
| Transparência | art. 6º, VI; art. 9º | Aviso visível na entrada do ambiente monitorado. |
| Direitos do titular | art. 18 | Alguém pode exigir eliminação. Você precisa **conseguir** apagar — o que exige saber o que guardou e onde. |
| Relatório de impacto | art. 38 (GDPR art. 35) | Monitoramento sistemático de área acessível ao público praticamente sempre exige RIPD/DPIA. |

**Uso doméstico exclusivo** tem tratamento próprio (LGPD art. 4º, I; GDPR art.
2(2)(c)) — mas a isenção cai assim que o dado alcança quem não é da casa, ou
assim que a instalação sai de casa. Um escritório, uma loja ou um galpão com
funcionários **não** estão cobertos.

Isto é um resumo técnico, não é parecer jurídico. Instalação comercial, procure
advogado.

---

## 4. Minimização: escolha a saída menos informativa que resolve

A defesa que **funciona** não é ofuscar o identificador. É não produzir o dado
que você não precisa. As saídas do sistema formam uma hierarquia estrita de
informação — cada linha pode ser derivada da de baixo, nunca o contrário:

| Nível | Saída | O que revela | Reidentificável? |
|---|---|---|---|
| 4 | **Trilha** (`vivo.json`, série de posições) | rotina, hábito, quem dorme onde, quem saiu com quem | **sim**, trivialmente (§2) |
| 3 | **Posição instantânea** | onde cada endereço está agora | **sim**, se guardada em série |
| 2 | **Cômodo por endereço** | quem está em qual cômodo | sim, se guardado em série |
| 1 | **Contagem por cômodo** | 2 aparelhos na sala | difícil; agregado |
| 0 | **Ocupação binária** | há alguém em casa | não |

Regra: **desça o máximo que a sua aplicação tolerar.** Automação de luz precisa
do nível 0 ou 1. "Quantas pessoas usam a sala à tarde" é nível 1. Ninguém precisa
de nível 4 para acender uma lâmpada, e nível 4 é o único que reidentifica sem
esforço.

O sistema publica o **posterior por cômodo** como saída primária justamente
porque o nível 2 já resolve a maioria dos casos de uso. Ver
[SAD §5](SAD.md).

Sobre a agregação do nível 1: contagem por cômodo com poucas pessoas ainda
singulariza (uma pessoa sozinha num cômodo é um agregado de tamanho 1). Se o
número vai ser publicado ou guardado, suprima células pequenas — é o argumento de
$k$-anonimato de Sweeney, *k-anonymity: a model for protecting privacy*
(IJUFKS, 2002), e o limiar é seu, não do algoritmo.

---

## 5. Retenção: é a trilha que se apaga

Como a chave de junção é a trajetória, **o que precisa expirar é a trajetória**,
não o endereço.

| Arquivo | Conteúdo | Nível | Sugestão |
|---|---|---|---|
| `avistamentos.jsonl` | tempo, MAC, RSSI por âncora | 4 (cru) | dias, não meses. É o insumo do ajuste, e o ajuste é episódico. |
| `rotulos.jsonl` | ponto rotulado à mão na campanha | 4 | é **sua** campanha, com **seu** aparelho; guarde |
| `vivo.json` | posição atual + 2 min de trilha | 4 | efêmero por construção (`TRILHA = 240` pontos em memória) |
| modelo ajustado | $A_0, n, W_c, t_i, r_j$ | 0 | guarde — não contém ninguém |
| ocupação agregada | contagem por cômodo por hora | 1 | guarde se precisar de histórico |

O ponto de arquitetura: `rtls/vivo.py` mantém a trilha **em memória**, com
tamanho fixo, e não a persiste. Histórico de longo prazo, se você precisar, deve
ser gravado já **agregado** — a pergunta de amanhã quase sempre é "quanto tempo
de sala por dia", que é nível 1, e não "por onde ele andou às 3h", que é nível 4.

Gravar cru "por precaução" é a decisão que transforma um sensor de presença num
arquivo de vigilância. Ela se toma uma vez e se paga por anos.

---

## 6. O que este repositório já faz por você

| Medida | Onde | O que impede |
|---|---|---|
| `sitios/*.json` gitignorado (exceto `exemplo.json`) | `.gitignore` | planta de imóvel habitado no git |
| `*.jsonl`, `*.ply`, `*.pcd` gitignorados | `.gitignore` | medição e nuvem de ponto no git |
| `credenciais.h` gitignorado, `.exemplo` versionado | `.gitignore` | senha de Wi-Fi no git |
| Varredura de MAC de fabricante e IP real no índice | `ferramentas/confere_repo.py` | `git add -f` passar por cima do ignore |
| Sítio de exemplo e fixture 100% sintéticos | `sitios/exemplo.json`, `testes/sitio_outro.json` | endereço real virar exemplo por conveniência |
| Trilha efêmera, em memória, tamanho fixo | `rtls/vivo.py` | histórico cru acumular sem ninguém decidir |
| Posterior por cômodo como saída primária | `rtls/vivo.py`, `rtls/tracker.py` | vazar nível 4 quando nível 2 bastava |

O critério do detector de MAC não é uma lista de exceções: é o **bit
localmente administrado** do IEEE 802 (bit 1 do primeiro octeto). `02:…` e
`AA:…` têm esse bit em 1 — a norma os reserva para uso próprio e documentação.
Um MAC com o bit em 0 saiu de um OUI atribuído, ou seja, de um aparelho que
existe no mundo.

E o que ele **não** faz: nada disso protege quem já está no ambiente. São medidas
contra vazamento pelo *repositório*. A proteção das pessoas é a §4.

---

## 7. Se um dado pessoal escapar para o histórico do git

Tirar do índice não basta — o blob continua no histórico e continua acessível
por SHA, inclusive por forks e por caches de quem já clonou.

1. Reescreva o histórico (`git filter-repo`) e force o push.
2. Se o repositório é público ou foi clonado, **trate o dado como vazado**:
   troque a credencial, não só apague o arquivo.
3. Peça a expiração dos caches ao provedor (no GitHub, via suporte — forks e
   views de commit sobrevivem ao `push --force`).

O `.gitignore` barra a **categoria inteira** e abre exceção para um arquivo só,
porque essa ordem é mais barata que confiar em disciplina. Ver
[CI-CD §6](CI-CD.md).

---

## 8. Antes de ligar num ambiente com outras pessoas

- [ ] Escrevi a finalidade em uma frase, e ela não é "porque dá".
- [ ] Escolhi o **menor nível** da tabela da §4 que atende essa finalidade.
- [ ] Defini retenção por nível, e sei o comando que apaga.
- [ ] Há aviso visível na entrada do ambiente.
- [ ] Se o ambiente não é meu, tenho autorização de quem responde por ele.
- [ ] Entendi que rotação de MAC **não** protege as pessoas aqui (§2), e não vou
      apresentar o sistema como anônimo porque não guarda nomes.
- [ ] Não estou rastreando uma pessoa específica sem que ela saiba. Isso não é
      uma questão de conformidade — é a linha que separa um sensor de ocupação de
      um instrumento de perseguição, e nenhum ajuste de configuração a apaga.

---

## 9. Usos que este projeto não apoia

Rastrear uma pessoa específica sem que ela saiba. Monitorar funcionários sem
aviso. Instalar em espaço de terceiro sem autorização de quem responde por ele.
Vender ou repassar trilhas. Correlacionar as trilhas com identidade civil.

A capacidade técnica existe e está documentada aqui inteira — inclusive a §2,
que é a parte mais útil para quem quisesse fazer isso. Está documentada assim de
propósito: quem instala precisa saber que o sistema é capaz disso, e quem é
monitorado só é protegido se a fragilidade da rotação de MAC for pública.
