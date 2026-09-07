"""Roda TODOS os auto-testes do repositorio: um comando, um codigo de saida.

Nao ha framework. Cada modulo carrega o proprio `demo()` (ou `confere()`) com
asserts, porque o teste tem de morar ao lado da logica que ele protege — quem
mexe no modulo ve o teste na mesma tela. Isto aqui so os enfileira.

Contrato: LEVANTAR e a unica forma de falhar. O que a funcao devolve nao e lido
— assim o mesmo enfileirador serve para `demo()` (devolve None) e para
`confere()` (devolve True), sem cada modulo ter de aprender um protocolo.

Uma excecao: faltar uma dependencia OPCIONAL (ver OPCIONAIS) nao e falha, e pulo.
O nucleo do sistema roda com numpy e mais nada — essa promessa esta no README, no
INSTALL e no criterio de aceite da US-01, e quem clona com `pip install numpy` tem
de fechar em 0 falhas. So o caminho da nuvem de pontos precisa de scipy, e ele ja
e opcional por decisao (reprovado na transferencia, ver docs/matematica/06). O
pulo e NOMINAL: so vale para os modulos listados, e so quando o modulo ausente e
exatamente um deles. Qualquer outro import quebrado continua sendo falha — senao
um `import numpi` errado passaria despercebido como "pulado".

Nenhum destes precisa de hardware, de servidor, de nuvem de pontos nem de dado
gravado: rodam no sitio de exemplo, em segundos, e e o que a CI executa.

Ficam de FORA os tres que so tem sentido com campanha gravada — rtls.modelo.altura,
rtls.modelo.invariantes e rtls.modelo.padrao. Eles leem os JSONL da SUA medicao;
sem dado nao ha o que testar, e um teste que passa por ausencia de dado e pior que
nenhum. Rode-os a mao depois da primeira campanha (docs/INSTALL.md secao 8).

  PYTHONPATH=. python3 -m testes.roda_tudo          # tudo
  PYTHONPATH=. python3 -m testes.roda_tudo sitio    # so os que casam com 'sitio'
"""
import importlib, io, os, sys, time, traceback, contextlib

# (modulo, funcao). Ordem = dependencia: se o sitio nao carrega, o resto nao
# tem sentido e o relatorio fica ilegivel.
ALVOS = [
    ("rtls.sitio", "demo"),
    ("rtls.tracker", "demo"),
    ("rtls.ajuste", "demo"),
    ("rtls.loo", "demo"),
    ("rtls.campanha", "demo"),
    ("rtls.receptor", "demo"),
    ("rtls.rotulos", "demo"),
    ("rtls.estaticos", "demo"),
    ("rtls.vivo", "demo"),
    ("rtls.mapa_alvo", "demo"),
    ("rtls.revisao", "demo"),
    ("rtls.modelo.nucleo", "demo"),
    ("rtls.modelo.entidades", "demo"),
    ("rtls.modelo.testes", "demo"),
    ("rtls.modelo.nuvem", "demo"),
    ("rtls.modelo.material", "demo"),
    ("ferramentas.malha_viz", "demo"),
    ("ferramentas.loo_viz", "demo"),
    ("ferramentas.simula", "selftest"),
    ("ferramentas.gera_firmware_alvo", "demo"),
    ("ferramentas.gera_firmware_alvo", "confere"),   # o .h no disco == o gerado agora
    ("ferramentas.confere_citacoes", "confere"),     # nenhuma citacao orfa ou faltando
    ("ferramentas.confere_repo", "confere"),         # link morto / sitio real versionado
]


# Dependencia que o nucleo NAO usa. Ausente -> pulo; presente -> roda de verdade.
# A CI instala scipy justamente para que nada seja pulado la.
OPCIONAIS = {"scipy"}


def roda(filtro=None, verboso=False):
    ok, falhas, pulados = [], [], []
    for mod, fn in ALVOS:
        if filtro and filtro not in mod:
            continue
        t0 = time.time()
        buf = io.StringIO()
        try:
            m = importlib.import_module(mod)
            f = getattr(m, fn, None)
            if f is None:
                falhas.append((f"{mod}.{fn}", "nao existe", ""))
                continue
            with contextlib.redirect_stdout(buf):
                f()
            ok.append((f"{mod}.{fn}", time.time() - t0, buf.getvalue().strip()))
        except ModuleNotFoundError as e:
            if (e.name or "").split(".")[0] in OPCIONAIS:
                pulados.append((f"{mod}.{fn}", e.name))
            else:
                falhas.append((f"{mod}.{fn}", f"{type(e).__name__}: {e}", traceback.format_exc()))
        except Exception as e:
            falhas.append((f"{mod}.{fn}", f"{type(e).__name__}: {e}", traceback.format_exc()))

    for mod, dt, saida in ok:
        ultima = saida.splitlines()[-1] if saida else ""
        print(f"  ok    {mod:40s} {dt:5.1f}s  {ultima[:70]}")
        if verboso and saida:
            print("\n".join("          " + l for l in saida.splitlines()))
    for mod, dep in pulados:
        print(f"  pulado {mod:39s}        sem {dep} (opcional) — `pip install {dep}`")
    for mod, msg, tb in falhas:
        print(f"  FALHA {mod:40s}        {msg}")
        if verboso:
            print(tb)
    extra = f", {len(pulados)} pulado(s)" if pulados else ""
    print(f"\n{len(ok)} ok, {len(falhas)} falha(s){extra}")
    return 1 if falhas else 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    sys.exit(roda(a[0] if a else None, "-v" in sys.argv))
