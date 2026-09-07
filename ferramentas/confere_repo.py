"""Duas coisas que so quebram DEPOIS do clone, quando nao tem mais quem consertar.

1) Link interno morto. Todo o repositorio e prosa que aponta para arquivo: o PRD
   manda para o SAD, o SAD para o INSTALL, o INSTALL para a matematica. Um alvo
   que nao existe transforma o guia em labirinto para quem chegou agora — e e
   invisivel para quem escreveu, que sabe de cabeca onde a coisa esta.

2) Dado pessoal versionado. A planta de uma casa habitada, com comodos e MACs, e
   dado pessoal (LGPD art. 5, I) e este repositorio e publico. O .gitignore ja
   barra `sitios/*.json` e `credenciais.h`, mas `git add -f` passa por cima dele
   sem avisar. Aqui a rede embaixo: o que ESTA no indice tem de ser publicavel.

Roda sozinho ou pela suite:  python3 ferramentas/confere_repo.py
"""
import os, re, subprocess, sys

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Um sitio versionado so pode ser o de exemplo; credencial e nuvem, nenhum.
PROIBIDO = [
    (re.compile(r"^sitios/(?!exemplo\.json$)"), "sitio real (planta e dado pessoal)"),
    (re.compile(r"credenciais\.h$"), "credencial (use o .exemplo)"),
    (re.compile(r"\.(ply|pcd|jsonl)$"), "medicao/nuvem do sitio real"),
]


def versionados():
    """Arquivos no indice do git. Fora de um clone, devolve None (nao [])."""
    try:
        r = subprocess.run(["git", "-C", AQUI, "ls-files"], capture_output=True, text=True)
        return r.stdout.splitlines() if r.returncode == 0 else None
    except FileNotFoundError:
        return None


def links(raiz=AQUI):
    """(origem, alvo) de todo link relativo em .md, ja resolvido contra a raiz."""
    fora = []
    for base, dirs, arqs in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".pio", "build")]
        for a in arqs:
            if not a.endswith(".md"):
                continue
            p = os.path.join(base, a)
            for alvo in LINK.findall(open(p).read()):
                # âncora pura, URL e mailto nao sao arquivo; corta a âncora do resto
                if alvo.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                cru = alvo.split("#")[0]
                if not cru:
                    continue
                fora.append((os.path.relpath(p, raiz),
                             os.path.normpath(os.path.join(base, cru))))
    return fora


# Identificadores reais nao entram num repositorio publico. As duas regras abaixo
# sao objetivas o bastante para virar codigo — o resto (SSID, nome de pessoa) nao
# tem forma regular e fica com a revisao humana.
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Enderecos de documentacao: nao pertencem a maquina nenhuma.
IPS_OK = {"0.0.0.0", "127.0.0.1", "255.255.255.255", "8.8.8.8",
          "192.168.1.0", "192.168.1.1", "1.2.3.4"}
TEXTO = (".py", ".md", ".json", ".c", ".h", ".cpp", ".sh", ".ini", ".yml",
         ".yaml", ".bib", ".csv", ".txt", ".defaults", ".exemplo")


def identificadores(arqs):
    """MAC de fabricante e IP de maquina real, dentro do conteudo dos arquivos.

    O criterio do MAC nao e uma lista de excecoes: o bit 1 do primeiro octeto e o
    bit *localmente administrado* do IEEE 802. `02:...` e `AA:...` tem esse bit em
    1 — sao enderecos que a norma reserva para uso proprio e documentacao. Um MAC
    com o bit em 0 saiu de um OUI atribuido, ou seja, de um APARELHO que existe.
    """
    ruim = 0
    for f in arqs:
        if not f.endswith(TEXTO):
            continue
        p = os.path.join(AQUI, f)
        try:
            txt = open(p, errors="replace").read()
        except OSError:
            continue
        for m in set(MAC.findall(txt)):
            if not int(m[:2], 16) & 0b10:       # bit local apagado = MAC de fabricante
                print(f"  MAC REAL: {f}  {m}")
                ruim += 1
        for ip in set(IPV4.findall(txt)) - IPS_OK:
            if ip.count(".") == 3 and all(o.isdigit() and int(o) < 256 for o in ip.split(".")):
                print(f"  IP REAL: {f}  {ip}")
                ruim += 1
    return ruim


def protocolo():
    """O byte de versao do cabecalho mora em DOIS arquivos, em duas linguagens.

    Nao da para o C incluir o .py nem o contrario, entao a duplicacao e estrutural
    — mas divergir e o pior modo de falha que este sistema tem: firmware novo com
    host velho corrompe silenciosamente todo pacote gravado ate alguem notar. Aqui
    a divergencia morre no merge, nao na medicao.
    """
    import re as _re
    c = open(os.path.join(AQUI, "firmware/ancora-c3/main/wireless.c")).read()
    py = open(os.path.join(AQUI, "rtls/receptor.py")).read()
    a = int(_re.search(r"^#define VERSAO\s+(\d+)", c, _re.M).group(1))
    b = int(_re.search(r"^VERSAO\s*=\s*(\d+)", py, _re.M).group(1))
    if a != b:
        print(f"  PROTOCOLO DIVERGE: wireless.c={a} vs receptor.py={b}")
        return 1
    print(f"protocolo: versao {a} igual no C e no Python")
    return 0


def confere():
    ruim = protocolo()
    n = 0
    for origem, alvo in links():
        n += 1
        if not os.path.exists(alvo):
            print(f"  LINK MORTO: {origem} -> {os.path.relpath(alvo, AQUI)}")
            ruim += 1
    print(f"links: {n} relativos conferidos")

    vs = versionados()
    if vs is None:
        print("privacidade: pulado (fora de um clone git)")
    else:
        for f in vs:
            for pat, porque in PROIBIDO:
                if pat.search(f):
                    print(f"  VERSIONADO INDEVIDO: {f}  ({porque})")
                    ruim += 1
        ruim += identificadores(vs)
        print(f"privacidade: {len(vs)} arquivos no indice, nenhum sitio/MAC/IP real")

    assert ruim == 0, f"{ruim} problema(s) — veja acima"
    return True


if __name__ == "__main__":
    try:
        confere()
    except AssertionError as e:
        print(e); sys.exit(1)
