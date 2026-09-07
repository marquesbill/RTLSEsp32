#pragma once
#include <stdint.h>
// Malha ancora-ancora: o mesmo carimbo de identidade sai por BLE (anuncio legacy
// nao-conectavel) e por ESP-NOW (quadro action). Quem escuta mede as duas cadeias
// de radio do MESMO emissor no MESMO receptor — e a unica comparacao honesta
// entre GFSK e OFDM, e o unico g_i na mesma modulacao do alvo.
void malha_start(uint8_t own_addr_type);   // chamar no on_sync, com o scan ja de pe
void malha_set(uint8_t adv_hz, int8_t tx_power);  // knobs do farol; 0 = nao mexe
uint16_t malha_boot(void);                 // contador de boot em NVS (expoe reboot loop)
