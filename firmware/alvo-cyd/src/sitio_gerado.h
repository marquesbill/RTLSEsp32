// GERADO por ferramentas/gera_firmware_alvo.py — NAO EDITE A MAO.
// sitio: Casa Exemplo (48.0 m2, 5 comodos)
// Regenere depois de mexer no sitio ou na campanha; a CI compara byte a byte.
#pragma once

#define SITIO_NOME "Casa Exemplo"
#define N_ANC 6
// MAC de fabrica do STA (esptool read_mac). Indice = numero instalado - 1:
// as N placas rodam o MESMO binario, quem da identidade e o MAC.
static const uint8_t MACS[N_ANC][6] = {
  {0x02,0x00,0x00,0x00,0x00,0x01},  // 1  A1 @ sala
  {0x02,0x00,0x00,0x00,0x00,0x02},  // 2  A2 @ sala
  {0x02,0x00,0x00,0x00,0x00,0x03},  // 3  A3 @ cozinha
  {0x02,0x00,0x00,0x00,0x00,0x04},  // 4  A4 @ sala
  {0x02,0x00,0x00,0x00,0x00,0x05},  // 5  A5 @ quarto1
  {0x02,0x00,0x00,0x00,0x00,0x06},  // 6  A6 @ quarto2
};
static const float ANC[N_ANC][2] = {   // metros, sistema do sitio
  {0.05f, 1.80f},  // 1
  {4.45f, 2.90f},  // 2
  {7.95f, 1.20f},  // 3
  {2.00f, 3.45f},  // 4
  {0.05f, 5.20f},  // 5
  {5.80f, 5.95f},  // 6
};

// Paredes com os vaos de porta JA abertos (rtls.sitio.paredes(): uniao por
// (eixo, posicao) antes de emitir — parede interna divide dois comodos e
// seria contada duas vezes se saisse poligono a poligono).
struct Seg { float x0, y0, x1, y1; };
static const Seg PAREDES[] = {
  {0.00f, 0.00f, 8.00f, 0.00f},
  {4.50f, 0.00f, 4.50f, 1.20f},
  {4.50f, 2.00f, 4.50f, 3.50f},
  {0.00f, 3.50f, 0.80f, 3.50f},
  {1.60f, 3.50f, 3.60f, 3.50f},
  {4.40f, 3.50f, 8.00f, 3.50f},
  {0.00f, 0.00f, 0.00f, 0.90f},
  {0.00f, 1.70f, 0.00f, 6.00f},
  {8.00f, 0.00f, 8.00f, 6.00f},
  {3.20f, 3.50f, 3.20f, 6.00f},
  {0.00f, 6.00f, 8.00f, 6.00f},
  {6.00f, 3.50f, 6.00f, 4.10f},
  {6.00f, 4.90f, 6.00f, 6.00f},
};
#define N_PAREDES (sizeof(PAREDES) / sizeof(PAREDES[0]))

struct Ponto { const char *nome; float x, y, z; };
#define POR_CM 3
static const char *CMS[] = {"1-3", "4-6", "7-9"};
#define N_CM (sizeof(CMS) / sizeof(CMS[0]))
// Uma ALTURA por aba, e o 1o ponto de cada aba e sempre o mesmo (x,y):
// os tres juntos medem a altura sem passar pelo modelo.
static const Ponto PONTOS[] = {
  {"1", 5.50f, 0.30f, 0.05f},
  {"2", 1.90f, 5.10f, 0.05f},
  {"3", 0.30f, 0.30f, 0.05f},
  {"4", 5.50f, 0.30f, 0.85f},
  {"5", 7.50f, 5.50f, 0.85f},
  {"6", 4.30f, 3.10f, 0.85f},
  {"7", 5.50f, 0.30f, 1.65f},
  {"8", 0.30f, 5.50f, 1.65f},
  {"9", 1.90f, 3.50f, 1.65f},
};
#define N_PONTOS (sizeof(PONTOS) / sizeof(PONTOS[0]))

// Tela 240x320 retrato. PLANTA GIRADA 90 GRAUS: o eixo y do sitio corre na horizontal da tela, o x na vertical.
// esc escolhida por ferramentas/gera_firmware_alvo.py:escala() — 14.5 px/m enche o retangulo util.
#define MX 4
#define MY 30
#define MXP 23   // origem do desenho: MX + raio do ponto + centragem
#define MYP 86
#define ESC 14.5f
#define U0P 0.00f   // origem do eixo horizontal da tela = y minimo
#define V0P 0.00f   // origem do eixo vertical da tela  = x minimo
#define PAN_X 134
#define BT_Y 258
#define RAIO_PX 10     // circulo do ponto; o desenho no C usa estes dois
#define DESVIO_PX 9   // desvio em x que separa alturas no mesmo (x,y)
#define PLX(x, y) (MXP + (int)(((y) - U0P) * ESC))
#define PLY(x, y) (MYP + (int)(((x) - V0P) * ESC))
