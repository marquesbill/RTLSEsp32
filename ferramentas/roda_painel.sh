#!/bin/bash
# Painel da malha: regenera o SVG a cada 30 s e serve numa porta. Ctrl-C para os dois.
# Uso: ./roda_painel.sh [dir do receptor] [porta]
set -u
DIR=${1:-${RTLS_DADOS:-$HOME/rtls-dados}}
PORTA=${2:-8099}
AQUI=$(cd "$(dirname "$0")" && pwd)
RAIZ=$(cd "$AQUI/.." && pwd)
export PYTHONPATH="$RAIZ:${PYTHONPATH:-}"
SAIDA="$AQUI/painel"
mkdir -p "$SAIDA"

# http.server em background; guardamos o PID porque pkill por nome nesta caixa ja
# matou o proprio shell (a string casa com a linha do ssh).
# UM filtro permanente publica wireless/vivo.json a 2 Hz; os SVGs so LEEM esse json.
# guarda: pgrep com a string na propria linha ja matou o shell nesta caixa, entao
# a classe do padrao entra entre colchetes.
if pgrep -f "[r]tls.vivo .* --daemon" >/dev/null; then
  VIVO=""; echo "daemon vivo.py ja rodando, nao subo outro"
else
  python3 -m rtls.vivo "$DIR" --daemon >"$SAIDA/vivo.log" 2>&1 &
  VIVO=$!
fi

# Nao mandar o erro para /dev/null: um "Address already in use" aqui deixava o
# laco de SVG rodando alegremente com NINGUEM na porta — o painel some e o log
# nao diz nada. Agora falha alto e cedo.
python3 -m http.server "$PORTA" --directory "$SAIDA" --bind 0.0.0.0 >"$SAIDA/http.log" 2>&1 &
HTTP=$!
sleep 1
if ! kill -0 "$HTTP" 2>/dev/null; then
  echo "http.server morreu ao subir na porta $PORTA:"; cat "$SAIDA/http.log"
  kill $VIVO 2>/dev/null; exit 1
fi
trap 'kill $HTTP $VIVO 2>/dev/null; exit 0' INT TERM EXIT
echo "painel em http://$(hostname -I | awk '{print $1}'):$PORTA/  (http.server $HTTP, vivo $VIVO)"

while true; do
  # Dentro do laco, nao antes dele: copiado uma vez so, editar painel.html com o
  # painel no ar nao tinha efeito ate reiniciar este script — e o laco ja
  # regenera os dois SVGs aqui do lado. Sao 2 KB a cada 30 s.
  cp -f "$AQUI/painel.html" "$SAIDA/index.html"
  python3 "$AQUI/malha_viz.py" "$DIR" "$SAIDA/malha.svg" || echo "viz falhou (rc=$?)"
  python3 "$AQUI/loo_viz.py" "$DIR" "$SAIDA/loo.svg" || echo "loo falhou (rc=$?)"
  sleep 30
done
