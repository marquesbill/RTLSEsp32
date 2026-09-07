#!/bin/bash
# Grava o firmware de ancora em toda C3 nova no USB do servidor. Idempotente:
# roda de novo a vontade, so mexe em placa que ainda nao esta em ancoras.txt.
#
# Por que existe: sao N placas iguais, e as tres regras que custam tempo sao
# faceis de esquecer na quinta placa — identificar por MAC (a porta re-enumera a
# cada reset), backup antes de gravar (mesmo em placa nova) e nao gravar em placa
# que nao e sua (ver RTLS_NAO_GRAVAR abaixo).
#
# Uso, na maquina que tem as placas no USB:  ferramentas/flash_ancoras.sh
# O binario tem de estar em firmware/ancora-c3/build (rode build.sh antes).
set -u
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
BUILD=${RTLS_BUILD:-../firmware/ancora-c3/build}
for b in bootloader/bootloader.bin partition_table/partition-table.bin rtls-ancora-c3.bin; do
  [ -s "$BUILD/$b" ] || { echo "falta $BUILD/$b — rode firmware/ancora-c3/build.sh build"; exit 1; }
done
MAPA=ancoras.txt            # "<n> <mac> <data>" — o ID da ancora e o MAC, nao a porta
# Placas a NAO tocar, por MAC, separadas por espaco. Existe porque outras placas
# Espressif no mesmo USB (S3, S2) tem o MESMO VID:PID 303a:1001 das C3 e apareceriam
# aqui. Se voce tem outra placa Espressif ligada, ponha o MAC dela:
#   RTLS_NAO_GRAVAR="AA:BB:CC:DD:EE:FF ..." ferramentas/flash_ancoras.sh
NUNCA=${RTLS_NAO_GRAVAR:-}
touch "$MAPA"

for link in /dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_*-if00; do
  [ -e "$link" ] || { echo "nenhuma placa Espressif no USB"; exit 0; }
  mac=$(basename "$link" | sed -E 's/.*unit_([0-9A-F:]+)-if00/\1/')
  porta=$(readlink -f "$link")
  case " $NUNCA " in *" $mac "*) echo "$mac  $porta  na lista RTLS_NAO_GRAVAR — pulando"; continue;; esac
  if grep -qi " $mac " "$MAPA"; then
    echo "$mac  $porta  ja gravada (ancora $(grep -i " $mac " "$MAPA" | cut -d' ' -f1)) — pulando"
    continue
  fi

  n=$(( $(wc -l < "$MAPA") + 1 ))
  m=$(echo "$mac" | tr -d ':' | tr 'A-F' 'a-f')
  echo "=== $mac  $porta  -> ancora $n"

  # esptool recusa um chip que nao seja C3: segunda barreira contra o T-Embed
  chip=$(esptool --port "$porta" --chip esp32c3 flash-id 2>&1 | grep -oE "Detected flash size: [0-9]+MB")
  [ -z "$chip" ] && { echo "   !! nao e C3 ou nao respondeu — pulando"; continue; }
  echo "   $chip"

  mkdir -p backups
  bk="backups/c3_${m}_virgem.bin"
  if [ ! -s "$bk" ]; then
    esptool --port "$porta" --baud 921600 read-flash 0x0 0x400000 "$bk" >/dev/null 2>&1 \
      && echo "   backup $bk" || { echo "   !! backup falhou — NAO grava"; continue; }
  fi

  # NUNCA "| grep -q" aqui: ele fecha o pipe no primeiro match e o esptool morre de
  # SIGPIPE depois de gravar SO o bootloader — a placa 2 ficou muda assim. Captura
  # tudo e exige as TRES verificacoes.
  saida=$(esptool --port "$porta" --baud 921600 --chip esp32c3 write-flash --flash-size detect \
    0x0 "$BUILD/bootloader/bootloader.bin" \
    0x8000 "$BUILD/partition_table/partition-table.bin" \
    0x10000 "$BUILD/rtls-ancora-c3.bin" 2>&1)
  nv=$(echo "$saida" | grep -c "Hash of data verified")
  [ "$nv" -eq 3 ] || { echo "   !! gravacao incompleta ($nv/3 verificadas)"; echo "$saida" | tail -3; continue; }
  echo "   gravado: 3/3 verificadas"

  # o hard reset do esptool re-enumera o USB nativo: resolver a porta DE NOVO
  sleep 3
  porta=$(readlink -f "$link")

  # so entra no mapa quem provou que esta varrendo
  # open() bloqueante do stty pode esperar carrier para sempre (ancora 1 ficou 2 min presa)
  timeout 5 stty -F "$porta" 115200 raw -echo 2>/dev/null
  pk=$(timeout 6 cat "$porta" 2>/dev/null | grep -c "^@b")
  if [ "$pk" -gt 20 ]; then
    echo "$n $mac $(date +%F)" >> "$MAPA"
    echo "   OK: $pk pacotes em 6 s — ancora $n registrada (LED deve estar verde pulsando)"
  else
    echo "   !! gravou mas so $pk pacotes em 6 s — NAO registrada; olhe o LED"
  fi
done
echo; echo "mapa de ancoras ($MAPA):"; cat "$MAPA"
