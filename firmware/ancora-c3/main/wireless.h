#pragma once
#include <stdint.h>
#include <stdbool.h>
void wireless_start(void);
void wireless_publica(const uint8_t *addr, int8_t rssi, uint8_t props,
                      uint8_t tipo_addr, const uint8_t *dados, uint8_t len);
bool wireless_conectado(void);
uint8_t wireless_modo(void);   // 0 sem rede - 1 broadcast - 2 unicast
void wireless_stats(uint32_t *vistos, uint32_t *enviados, uint32_t *perdidos);
