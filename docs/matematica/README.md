# Modelagem matemática do RTLSEsp32

Cada etapa do sistema tem um documento, cada documento tem as equações e as
referências que a sustentam, e **cada documento termina com um comando que
verifica o que ele afirma**. Se um número aparece aqui, ou é uma identidade
demonstrada, ou é uma medida com o procedimento junto.

| # | documento | o que fecha |
|---|-----------|-------------|
| 00 | [notação](00-notacao.md) | eixos, índices, unidades, os três níveis de aleatoriedade |
| 01 | [propagação](01-propagacao.md) | o modelo direto em dB, do Friis ao padrão de antena |
| 02 | [censura](02-censura.md) | por que o pacote que não chega é informação, e como não deixá-lo mentir |
| 03 | [estimação](03-estimacao.md) | GLS/ML, calibre, identificabilidade, o que a malha **não** pode medir |
| 04 | [filtro de partículas](04-filtro-particulas.md) | por que não multilateração; o SIR, o modelo de movimento, a saída por cômodo |
| 05 | [campanha D-ótima](05-campanha-dotima.md) | onde medir, quantos pontos, e quando parar |
| 06 | [transferência](06-transferencia.md) | a regra que decide se um bloco entra em produção |
| 07 | [invariantes](07-invariantes.md) | sete testes em ordem de força; cinco não ajustam nada |
| 08 | [sombreamento](08-sombreamento.md) | corpo sem rádio: tomografia, e movimento ≠ presença |
| 09 | [geometria 3D](09-geometria-3d.md) | nuvem de pontos → sítio, com orçamento de erro |
| 10 | [temporal](10-temporal.md) | o relógio como coordenada; o cabo USB como restrição de posição |
|  — | [referências](referencias.bib) | 45 entradas, todas citadas |

## A regra que organiza tudo

> **Uma métrica não pode validar o próprio ajuste.**
> É preciso encontrar um invariante que a resposta errada viole.

Ela aparece em cada documento sob uma forma diferente: a soma em triângulo (§07),
a inclinação `dRSSI/dPtx = 1` (§02), o LOPO contra o modelo em produção (§06), a
trajetória da câmera contra o plano de espelho (§09). É o que separa este
repositório de um ajuste bem-sucedido.

## Ordem de leitura

- **Vou instalar e usar** → §00, §01, depois `../INSTALL.md`. O resto é opcional.
- **Vou customizar o modelo** → §01 → §03 → §06. Não promova nada sem §06.
- **Vou desenhar a campanha do meu sítio** → §02 → §05.
- **Vou julgar se isto funciona** → §07, e rode-o antes de acreditar em qualquer
  número deste repositório.

## Verificar tudo de uma vez

```bash
PYTHONPATH=. python3 -m testes.roda_tudo      # todos os auto-testes dos documentos
python3 ferramentas/confere_citacoes.py       # nenhuma citacao orfa ou faltando
```
