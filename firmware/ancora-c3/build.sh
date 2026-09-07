#!/bin/bash
# Build do firmware da ancora. Envelope fino em volta do idf.py:
#   ./build.sh build            # compila
#   ./build.sh -p /dev/ttyACM0 flash monitor
#
# Existe por duas armadilhas do export.sh do ESP-IDF, as duas custaram horas:
#
# 1) Ele procura o venv pelo NOME da versao do python3 que estiver no PATH. Com o
#    python do sistema no PATH ele procura um idf5.4_pyX.Y_env que nao existe e
#    falha sem dizer o que faltou. RTLS_PY aponta para o python certo.
# 2) No macOS 26, o pyexpat do Homebrew em algumas versoes procura simbolos que o
#    libexpat do sistema nao tem: plistlib morre, platform.mac_ver() volta vazio e
#    o truststore do IDF quebra com "invalid literal for int()" em TODO subprocesso
#    do build. MEDIDO nesta caixa: 3.9 (sistema) e 3.13 devolvem '26.1'; 3.11, 3.12
#    e 3.14 devolvem ''. Se o seu build morrer assim, aponte RTLS_PY para outra.
set -e
IDF=${IDF_PATH:-$HOME/esp/esp-idf}
[ -f "$IDF/export.sh" ] || {
  echo "ESP-IDF nao encontrado em $IDF."
  echo "Instale (v5.1+) e/ou aponte:  export IDF_PATH=/caminho/do/esp-idf"; exit 1; }
# RTLS_PY = diretorio do python que o IDF deve usar; entra na frente do PATH.
#   macOS/Homebrew:  export RTLS_PY=/opt/homebrew/opt/python@3.13/libexec/bin
# `if` e nao `[ ... ] && ...`: sob set -e, um teste falso na ultima linha do && mata
# o script inteiro quando RTLS_PY esta vazio — que e o caso normal no Linux.
if [ -n "${RTLS_PY:-}" ]; then export PATH="$RTLS_PY:$PATH"; fi
cd "$(dirname "$0")"
. "$IDF/export.sh" >/dev/null
idf.py "$@"
