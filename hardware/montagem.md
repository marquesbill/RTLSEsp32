# Montagem física

O que fazer com as placas depois que elas chegam. A escolha de *onde* pôr âncora
está em [INSTALL §3](../docs/INSTALL.md); esta página é o *como* — e as decisões
físicas que o modelo enxerga.

Regra que organiza tudo abaixo:

> **O que você não conseguir repetir igual em todas as âncoras, não faça em
> nenhuma.**

O modelo aprende uma constante por âncora ($t_i$, $r_j$). Uma diferença física
que se repete é absorvida por essas constantes e some. Uma diferença que varia
de âncora para âncora, sem estar no `.json`, vira resíduo que ninguém explica.

---

## 1. Antes de fixar qualquer coisa: 10 minutos que economizam horas

Grave todas as placas, ligue todas na tomada **em cima da mesa** e confira a
malha completa antes de colar nada na parede.

```bash
firmware/ancora-c3/build.sh build
ferramentas/flash_ancoras.sh            # idempotente: roda de novo à vontade
```

O script só registra a placa em `ancoras.txt` depois que ela **provou que está
varrendo** (>20 pacotes em 6 s). Placa que gravou e não fala não entra no mapa —
e é muito mais fácil descobrir isso com ela na mão.

Com o CYD gravado em `env:painel` você vê **N/N âncoras vivas** em ESP-NOW, BT e
Wi-Fi. Só então suba na escada.

---

## 2. Altura: escolha uma e repita

> **Esta é a regra mais importante desta página.**

O efeito de altura foi medido em **21,5 dB** e **não transferiu** no LOPO — sabe-se
que importa e **não** se sabe modelar ([06](../docs/matematica/06-transferencia.md)).

A defesa é não variar: **uma altura, entre 0,3 e 1,2 m, repetida nas N âncoras**,
com tolerância de ±5 cm.

| | |
|---|---|
| ✅ Todas a 0,80 m | O modelo nunca vê o efeito, porque ele é constante |
| ❌ Cinco a 0,80 m e uma a 1,90 m | 21,5 dB entram como se fossem distância; a estimativa erra metros |

Se o ambiente **obriga** uma âncora a outra altura (uma viga, um vão), registre a
altura verdadeira no `.json` e trate essa âncora como suspeita no LOPO. Não
"arredonde" no papel — o `.json` é a fonte da verdade.

Meça a altura com trena a partir do **piso**, não do rodapé nem da mesa.

---

## 3. Orientação: gire todas para o mesmo lado

Girar a placa gira o padrão de antena. Medido neste projeto: **10,2 dB** numa
única âncora, só girando.

A convenção do sítio ([00 §0.1](../docs/matematica/00-notacao.md)):
`yaw` em graus, **anti-horário na planta**, com **0 = a face da placa aponta para
+x**.

Na prática, duas opções, nessa ordem:

1. **Melhor:** todas com a face para o mesmo lado (`yaw` igual em todas). O giro
   vira constante e some nos $t_i$/$r_j$.
2. **Aceitável:** `yaw` diferente por âncora, **anotado no `.json`**. Se você não
   souber, ponha o da parede em que ela está fixada, com a antena voltada para
   dentro do cômodo, e escreva `"nota": "yaw estimado"`.

⚠️ A antena da SuperMini é a **cerâmica na ponta da placa**, sobre o plano de
terra. Ela irradia mal para dentro do próprio plano de terra: deixe a ponta da
placa **livre**, apontando para o cômodo, nunca enfiada atrás do móvel nem
encostada na parede.

> O bloco de ganho direcional existe no código e está **desligado** — ele foi
> reprovado três vezes na transferência. Ou seja: o modelo **não** vai corrigir
> um giro que você não anotou. É por isso que a disciplina física importa mais
> aqui que em sistemas que compensam no software.

---

## 4. Etiquete a placa. Sempre.

Escreva o número da âncora **na placa**, com etiqueta ou fita crepe, antes de
fixar.

A identidade da âncora é o **MAC**: as N placas rodam o **mesmo binário**, e o
mapa MAC→número mora no host (`ancoras.txt`). Do lado do software está tudo
resolvido. Do lado da escada, não: seis placas idênticas em seis cômodos, e a
pergunta "esta aqui é a 3 ou a 5?" custa meia hora de `esptool read_mac` com o
notebook na mão.

Escreva os **três últimos octetos** do MAC junto do número. É o que aparece nos
logs e no painel.

```
   A3
   e4:12:9a
```

---

## 5. Fixação

**Dupla-face de espuma** é a resposta certa, e não é preguiça:

- não fura parede (importante em aluguel, e a instalação é experimental);
- os 2–3 mm de espuma **afastam a placa da superfície** — se for parede metálica,
  caixa de disjuntor ou perfil de gesso acartonado, é a diferença entre a antena
  irradiar e não irradiar;
- sai sem marca quando você mover a âncora, e você **vai** mover.

Distâncias mínimas:

| De | Mínimo | Por quê |
|---|---|---|
| Superfície metálica grande (geladeira, quadro, estante de aço) | **30 cm** | O metal vira refletor e o padrão de radiação muda de forma imprevisível |
| Roteador Wi-Fi | **1 m** | Saturação do receptor; o AP também entra no modelo, como emissor fixo |
| Outra âncora | **1,5 m** | Enlace curto demais domina o ajuste e não informa nada sobre o resto |
| Aquário, boiler, vaso grande | **50 cm** | Água absorve 2,4 GHz com entusiasmo |

Não parafuse a placa direto na parede pelo furo de montagem: a pressão do
parafuso na PCB é o começo de uma trinca, e você vai remover essa âncora.

---

## 6. Cabeamento e alimentação

- **Uma tomada por âncora.** Bateria não cabe no ciclo de trabalho da varredura.
- **O cabo decide a posição.** 1 m limita muito; 2 m resolve quase tudo. Meça
  antes de comprar.
- Fonte de **5 V, ≥500 mA**. Carregador de celular velho de 300 mA faz a placa
  reiniciar quando o Wi-Fi transmite — e isso aparece como `boot` subindo na
  telemetria, não como "placa ruim".
- Prenda a sobra de cabo **longe da ponta da placa** (§3).

**Como diagnosticar alimentação ruim:** o campo `boot` do pacote de telemetria
sobe a cada reinício. Se uma âncora tem `boot` crescendo, é fonte ou cabo, não é
rádio. `heap_livre` caindo continuamente é outra coisa — é software.

---

## 7. O CYD durante a campanha

O fundo metálico da tela faz padrão: **10,2 dB** entre orientações.

- **Mantenha a mesma orientação** em todos os pontos da campanha. Se você segura
  o aparelho de frente para você, segure de frente em todos.
- **Mesma altura de mão** — os pontos já variam altura de propósito (o `.h`
  gerado tem uma altura por aba); a variação tem de vir do ponto, não do seu
  braço.
- **Não cubra a placa com a mão.** Uma mão sobre o rádio é 5–15 dB.
- **Fique parado 3 min por ponto** e não ande antes de o rótulo entrar.

E a regra que vale mais que as três: **congele o rádio antes de andar.** Não
regrave âncora, não mude potência, não mexa em canal no meio de uma campanha —
um degrau no meio do conjunto de treino é absorvido pelo ajuste como se fosse
física ([CI-CD §5.1](../docs/CI-CD.md)).

---

## 8. Caixa (opcional)

Não conta no O7 (que é "sem caixa"), e o sistema funciona sem. Se for fazer:

| Faça | Não faça |
|---|---|
| Plástico (PLA, PETG, ABS) | Qualquer metal, inclusive tinta metálica |
| Deixar a ponta da antena com ≥5 mm de folga até a parede da caixa | Encostar a cerâmica no plástico |
| Furo de ventilação | Vedar — o C3 esquenta em varredura contínua |
| A **mesma** caixa nas N âncoras | Caixas diferentes: cada uma é um offset diferente |
| Etiqueta do lado de fora (§4) | Etiqueta só por dentro |

Não há STL no repositório de propósito: a montagem depende da revisão exata da
placa que você comprou, e um STL errado dá mais trabalho que nenhum.

---

## 9. Checklist antes da primeira campanha

- [ ] N âncoras gravadas e registradas em `ancoras.txt`.
- [ ] Painel mostrando **N/N** vivas por pelo menos 10 min sem oscilar.
- [ ] Nenhuma com `boot` subindo (§6).
- [ ] Todas na **mesma altura**, ±5 cm, medida do piso (§2).
- [ ] Todas com o mesmo `yaw`, ou com o `yaw` real anotado no `.json` (§3).
- [ ] Todas etiquetadas com número + 3 últimos octetos (§4).
- [ ] ≥30 cm de metal grande, ≥1 m do roteador (§5).
- [ ] `.json` do sítio com posição **medida**, não estimada, e
      `PYTHONPATH=. python3 -m rtls.sitio meu_sitio.json` sem erro.
- [ ] `python3 ferramentas/gera_firmware_alvo.py --escreve` rodado **depois** da
      última mudança no sítio, e o CYD regravado com o `.h` novo.
- [ ] Rádio congelado: nada de regravar nada até a campanha terminar.

---

## 10. Manutenção

| Sintoma | Onde olhar | Quase sempre é |
|---|---|---|
| Uma âncora some do painel | `boot` e `heap_livre` na telemetria | fonte/cabo (§6) |
| Todas somem juntas | roteador, canal, sub-rede | o AP mudou de canal sozinho |
| Erro cresceu sem ninguém mexer em nada | `rtls/revisao.py` com o juiz | o **ambiente** mudou: móvel novo, porta que passou a ficar fechada |
| Uma âncora sempre pior no LOPO | posição no `.json` vs. realidade | ela foi movida e ninguém atualizou o sítio |

A quarta linha é a mais comum de todas, e é por isso que o `.json` é a fonte da
verdade: mover uma âncora **é uma edição de arquivo**, não só um gesto de mão.
Depois de mover, os rótulos antigos **não valem mais** para aquele enlace — veja
a matriz de acoplamento em [CI-CD §5.3](../docs/CI-CD.md).

E nunca reajuste o modelo às cegas: reajuste periódico sem juiz foi exatamente o
que produziu a deriva documentada em
[06](../docs/matematica/06-transferencia.md). Toda promoção deixa registro do
antes, do depois e do número que decidiu.
