"""Toda chave citada em docs/matematica/*.md existe no .bib, e vice-versa.

Uma referencia que nao existe e uma equacao sem justificativa; uma entrada nunca
citada e peso morto que envelhece sem ninguem notar. A CI roda isto.

  python3 ferramentas/confere_citacoes.py
"""
import glob, os, re, sys

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(AQUI, "docs", "matematica")
BIB = os.path.join(DOCS, "referencias.bib")
CHAVE = re.compile(r"`([a-z][a-z-]+\d{4}|itu-p\d+)`")


def confere(docs=DOCS, bib=BIB):
    tem = set(re.findall(r"^@\w+\{([^,]+),", open(bib).read(), re.M))
    cit = {}
    for f in sorted(glob.glob(os.path.join(docs, "*.md"))):
        for k in CHAVE.findall(open(f).read()):
            cit.setdefault(k, set()).add(os.path.basename(f))
    faltam = sorted(set(cit) - tem)
    orfas = sorted(tem - set(cit))
    for k in faltam:
        print(f"  FALTA no .bib: {k}  (citada em {', '.join(sorted(cit[k]))})")
    for k in orfas:
        print(f"  ORFA no .bib: {k}  (nao citada em nenhum .md)")
    if faltam or orfas:
        return 1
    print(f"citacoes ok: {len(tem)} entradas, todas citadas, nenhuma faltando")
    return 0


if __name__ == "__main__":
    sys.exit(confere())
