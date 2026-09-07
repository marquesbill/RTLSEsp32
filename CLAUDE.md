# Instruções para agentes neste repositório

Ponto de entrada: [README.md](README.md) → seção **"Para agentes de IA"**.
Este arquivo não repete o conteúdo de lá; ele só fixa o que **não** é negociável.

## Antes de escrever código

1. Leia [docs/SAD.md](docs/SAD.md) §2 — nove decisões estruturais, cada uma com a
   alternativa rejeitada e o custo dela. É o contexto que não se recupera lendo
   `.py`.
2. Rode a suíte. Tem de fechar **`0 falha(s)`** (`26 ok` com `scipy`; `24 ok,
   2 pulado(s)` só com `numpy` — as duas são verdes):
   ```bash
   PYTHONPATH=. python3 -m testes.roda_tudo
   ```

## Regras que não se negociam

- **Nunca chumbe um número do sítio.** Derive de `rtls.sitio` (`P.ESCOLHIDAS`,
  `P.COMODOS`, `P.RADIO`, `P.EMISSORES`). A CI roda em dois sítios e reprova o
  código que decorou o primeiro.
- **Módulo com lógica não trivial ganha um `demo()` com `assert`s** no próprio
  arquivo e uma linha em `testes/roda_tudo.py`. Sem framework, sem fixture.
- **Uma métrica não valida o próprio ajuste.** Nada entra em produção por caber
  melhor no dado em que foi ajustado; o critério é
  [06-transferencia](docs/matematica/06-transferencia.md), e quatro blocos já
  foram reprovados por ele.
- **Nada de dado pessoal.** Sem planta real, sem modelo 3D de imóvel habitado,
  sem MAC de fabricante, sem IP de máquina, sem senha. `ferramentas/confere_repo.py`
  cobra isso a cada merge. Ver [docs/PRIVACIDADE.md](docs/PRIVACIDADE.md).
- **Depois de mexer no sítio**, regenere o firmware do alvo e commite o `.h`:
  ```bash
  python3 ferramentas/gera_firmware_alvo.py --escreve
  ```
- **Comentário longo é armadilha documentada**, não ruído: quase todo comentário
  extenso aqui custou horas a alguém. Explique *por quê*, não *o quê*, e pense
  duas vezes antes de "limpar".

## Antes de abrir PR

```bash
PYTHONPATH=. python3 -m testes.roda_tudo                                  # sítio de exemplo
RTLS_SITIO=testes/sitio_outro.json PYTHONPATH=. python3 -m testes.roda_tudo  # o que importa
```

Os dois têm de fechar em `0 falha(s)`. O que mais a CI faz — e a matriz de
acoplamento do deploy — está em [docs/CI-CD.md](docs/CI-CD.md).
