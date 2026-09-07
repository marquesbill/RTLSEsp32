// Painel 3xN no CYD: RSSI das N ancoras C3 medido NO CYD, nas tres cadeias de radio.
//
// Linhas ESP-NOW e WiFi saem do MESMO modo promiscuo: ESP-NOW e action frame
// (mgmt, subtype 13) e o trafego UDP e data frame. Um callback, duas linhas, e
// nao dependemos do callback do esp_now (no core 2.x ele nem entrega RSSI).
// Linha BT vem do scan BLE, casando o anuncio da malha pelo CID + magica.
//
// O RSSI aqui e da cadeia de RX do CYD, que NAO e a da C3 (medido: corte -93 na
// C3 equivale a -85 no CYD). Isto e painel de diagnostico, nao instrumento de g_i.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <TFT_eSPI.h>
#include <BLEAdvertising.h>
#include <esp_bt.h>
#include "credenciais.h"

// MACS[] e N_ANC vem do sitio (ferramentas/gera_firmware_alvo.py). O painel usa
// so a tabela de MACs e a contagem; a geometria e da campanha.
#include "sitio_gerado.h"

#define CID_MALHA  0xFFFF   // Bluetooth SIG: reservado p/ teste/desenvolvimento
#define MAGICA_A   'R'
#define MAGICA_B   'A'
#define VELHO_MS   8000     // sem amostra ha mais que isto = cinza

// ---- transmissor de REFERENCIA ----
// O CYD anuncia com Ptx CONHECIDA e ciclica. E o que falta para o V1: com uma so
// posicao de emissor de Ptx desconhecida (o teclado) o A implicito variou 18,7 dB
// entre as ancoras, e nao da para separar "A" de "direcionalidade da antena".
// Variando a potencia num ponto FIXO, a inclinacao RSSI x Ptx tem de ser 1:1 —
// o que sobra depois disso e do ambiente, nao do radio.
#define MAGICA_C    'C'     // "RC" = referencia do CYD (a malha das ancoras usa "RA")
#define REF_MS      6000    // tempo em cada nivel
static const int8_t NIVEIS[] = {-12, -9, -6, -3, 0, 3, 6, 9};
static const esp_power_level_t LVL[] = {ESP_PWR_LVL_N12, ESP_PWR_LVL_N9, ESP_PWR_LVL_N6,
                                        ESP_PWR_LVL_N3, ESP_PWR_LVL_N0, ESP_PWR_LVL_P3,
                                        ESP_PWR_LVL_P6, ESP_PWR_LVL_P9};
#define N_NIVEIS   (sizeof(NIVEIS) / sizeof(NIVEIS[0]))
static BLEAdvertising *pAdv = nullptr;
static uint8_t g_nivel = 0;
static uint16_t g_seq = 0;

enum { LIN_ESPNOW = 0, LIN_BT = 1, LIN_WIFI = 2 };

// escritos nas tasks de WiFi/BLE, lidos no loop. Leitura rasgada de um int8 e
// inofensiva num display; nada de container compartilhado.
static volatile int8_t   rssi[3][N_ANC];
static volatile uint32_t visto[3][N_ANC];

TFT_eSPI tft = TFT_eSPI();

static inline int coluna_por_mac(const uint8_t *m) {
  for (int i = 0; i < N_ANC; i++) if (!memcmp(m, MACS[i], 6)) return i;
  return -1;
}
static inline void anota(int lin, int col, int8_t r) {
  rssi[lin][col] = r;
  visto[lin][col] = millis();
}

// ---- radio 1: promiscuo (ESP-NOW + WiFi) ----
static void sniff(void *buf, wifi_promiscuous_pkt_type_t tipo) {
  const wifi_promiscuous_pkt_t *p = (wifi_promiscuous_pkt_t *)buf;
  if (p->rx_ctrl.sig_len < 24) return;              // sem cabecalho completo
  const uint8_t *h = p->payload;
  uint8_t t = (h[0] >> 2) & 0x03;                   // 0=mgmt 1=ctrl 2=dados
  uint8_t st = (h[0] >> 4) & 0x0F;
  if (t == 1) return;                               // ctrl (ACK/CTS) nao tem addr2
  int col = coluna_por_mac(h + 10);                 // addr2 = transmissor
  if (col < 0) return;
  if (t == 0 && st == 13) anota(LIN_ESPNOW, col, p->rx_ctrl.rssi);   // action = ESP-NOW
  else if (t == 2)        anota(LIN_WIFI,   col, p->rx_ctrl.rssi);
}

// ---- radio 2: BLE ----
class AdvCB : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) {
    if (!d.haveManufacturerData()) return;
    std::string m = d.getManufacturerData();
    if (m.size() < 7) return;
    const uint8_t *b = (const uint8_t *)m.data();
    uint16_t cid = b[0] | (b[1] << 8);
    if (cid != CID_MALHA || b[2] != MAGICA_A || b[3] != MAGICA_B) return;
    // Identidade = 3 ultimos bytes do MAC STA, nao um numero de ancora: as N rodam
    // firmware identico e a tabela MAC->coluna vive so aqui.
    for (int i = 0; i < N_ANC; i++) {
      if (!memcmp(b + 4, MACS[i] + 3, 3)) { anota(LIN_BT, i, d.getRSSI()); return; }
    }
  }
};
static AdvCB advCB;
static BLEScan *pScan = nullptr;

// Reconfigura o anuncio com o nivel atual. O proprio payload carrega a Ptx, entao
// quem escuta nunca precisa adivinhar com que potencia aquele pacote saiu.
static void ref_aplica(void) {
  if (!pAdv) return;
  pAdv->stop();
  BLEDevice::setPower(LVL[g_nivel], ESP_BLE_PWR_TYPE_ADV);
  uint8_t p[7] = {0xFF, 0xFF, MAGICA_A, MAGICA_C, (uint8_t)NIVEIS[g_nivel],
                  (uint8_t)(g_seq & 0xFF), (uint8_t)(g_seq >> 8)};
  BLEAdvertisementData d;
  d.setManufacturerData(std::string((char *)p, sizeof(p)));
  pAdv->setAdvertisementData(d);
  pAdv->setScanResponse(false);
  pAdv->setMinInterval(160);          // 100 ms: denso, a campanha e curta
  pAdv->setMaxInterval(160);
  pAdv->start();
  g_seq++;
}

static void ref_tick(void) {
  static uint32_t ult = 0;
  if (millis() - ult < REF_MS) return;
  ult = millis();
  g_nivel = (g_nivel + 1) % N_NIVEIS;
  ref_aplica();
}

// ---- tela ----
#define X0   40
// A grade acompanha o numero de ancoras do sitio: 6 dao 46 px de coluna, 8 dao
// 25. Abaixo de ~24 px o numero da ancora nao cabe — a partir dai o painel
// precisa de duas linhas por ancora, nao de uma coluna mais fina.
#define LARG ((240 - X0) / N_ANC)
#define Y0   58
#define ALT  50
static const char *ROTULO[3] = {"NOW", "BT", "WiFi"};
static int16_t desenhado[3][N_ANC];                     // cache: rssi, +256 se velho, 1000 se nunca

static uint16_t cor(int8_t r, bool velho) {
  if (velho) return TFT_DARKGREY;
  if (r >= -60) return TFT_GREEN;
  if (r >= -80) return TFT_YELLOW;
  if (r >= -90) return TFT_ORANGE;
  return TFT_RED;
}

static void moldura(void) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextFont(2);
  for (int c = 0; c < N_ANC; c++) tft.drawString(String(c + 1), X0 + c * LARG + LARG / 2, 40);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  for (int l = 0; l < 3; l++) tft.drawString(ROTULO[l], X0 / 2, Y0 + l * ALT + ALT / 2);
  tft.drawFastHLine(0, 52, 320, TFT_DARKGREY);
  tft.drawFastVLine(X0 - 2, 30, 190, TFT_DARKGREY);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString("RSSI no CYD, dBm negativo", 4, 4);
}

static void celulas(void) {
  uint32_t agora = millis();
  tft.setTextDatum(MC_DATUM);
  tft.setTextFont(4);
  for (int l = 0; l < 3; l++) for (int c = 0; c < N_ANC; c++) {
    uint32_t v = visto[l][c];
    bool velho = (v == 0) || (agora - v > VELHO_MS);
    int8_t r = v ? rssi[l][c] : 0;
    int16_t chave = !v ? 1000 : (velho ? (int16_t)r + 256 : (int16_t)r);
    if (chave == desenhado[l][c]) continue;
    desenhado[l][c] = chave;
    int x = X0 + c * LARG, y = Y0 + l * ALT;
    tft.fillRect(x, y, LARG - 1, ALT - 1, TFT_BLACK);
    tft.setTextColor(cor(r, velho), TFT_BLACK);
    tft.drawString(v ? String(-r) : "--", x + LARG / 2, y + ALT / 2);
  }
}

static void serial_espelho(void) {
  static uint32_t ult = 0;
  if (millis() - ult < 2000) return;
  ult = millis();
  uint32_t agora = millis();
  for (int l = 0; l < 3; l++) {
    Serial.printf("@p %-5s", ROTULO[l]);
    for (int c = 0; c < N_ANC; c++) {
      uint32_t v = visto[l][c];
      if (!v || agora - v > VELHO_MS) Serial.print("   .");
      else Serial.printf(" %3d", rssi[l][c]);
    }
    Serial.println();
  }
  Serial.printf("@r ptx %d\n", NIVEIS[g_nivel]);
}

static void rodape(void) {
  static uint32_t ult = 0;
  if (millis() - ult < 3000) return;
  ult = millis();
  uint8_t ch; wifi_second_chan_t s; esp_wifi_get_channel(&ch, &s);
  tft.setTextDatum(TL_DATUM);
  tft.setTextFont(2);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.fillRect(0, 222, 320, 18, TFT_BLACK);
  tft.drawString((WiFi.isConnected() ? WiFi.localIP().toString() + "  ch" + String(ch)
                                     : String("sem rede"))
                 + "   ref " + String(NIVEIS[g_nivel]) + " dBm", 4, 222);
}

void setup() {
  Serial.begin(115200);
  tft.init(); tft.setRotation(1);
  pinMode(TFT_BL, OUTPUT); digitalWrite(TFT_BL, HIGH);
  moldura();
  memset((void *)visto, 0, sizeof(visto));
  memset(desenhado, 0xFF, sizeof(desenhado));       // != qualquer chave valida

  // BT PRIMEIRO. Habilitar o controlador BT com o promiscuo ja ligado aborta em
  // coex_core_enable (MEDIDO: boot loop) — a coexistencia nao arbitra sniffer
  // contra BT. Por isso o promiscuo vira fase, ligado e desligado no loop.
  BLEDevice::init("");
  pScan = BLEDevice::getScan();
  pScan->setAdvertisedDeviceCallbacks(&advCB);
  pScan->setActiveScan(false);   // passivo: nao transmite scan request, menos disputa
  pScan->setInterval(100);
  pScan->setWindow(90);
  pAdv = BLEDevice::getAdvertising();
  ref_aplica();

  WiFi.mode(WIFI_STA);
  // NAO desligar o modem sleep: com BT habilitado o IDF aborta ("Should enable
  // WiFi modem sleep when both WiFi and Bluetooth are enabled"). O sniffer so ouve
  // nas janelas acordadas do PS — por isso VELHO_MS e generoso.
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  for (int i = 0; i < 60 && !WiFi.isConnected(); i++) delay(500);
  // associado = estamos no canal do AP, que e o canal das ancoras. Nao chamar
  // esp_wifi_set_channel aqui: com STA associado isso derruba a associacao.
  wifi_promiscuous_filter_t f = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT |
                                                 WIFI_PROMIS_FILTER_MASK_DATA };
  esp_wifi_set_promiscuous_filter(&f);
  esp_wifi_set_promiscuous_rx_cb(&sniff);
  Serial.printf("@i wifi=%d ip=%s\n", WiFi.status(), WiFi.localIP().toString().c_str());
}

// Fases de 2 s: as duas linhas de radio 802.11 (promiscuo) e depois a linha BLE.
// Um radio so; alternar e a unica forma de ter as tres. A janela de 8 s do VELHO_MS
// cobre a fase perdida — as ancoras falam a 1 Hz em cada meio.
void loop() {
  esp_err_t e = esp_wifi_set_promiscuous(true);
  if (e) Serial.printf("@e promisc on: %d\n", e);
  for (uint32_t t = millis(); millis() - t < 2000; ) { celulas(); delay(50); }
  e = esp_wifi_set_promiscuous(false);
  if (e) Serial.printf("@e promisc off: %d\n", e);

  pScan->start(2, false);        // bloqueia 2 s na task do BLE; onResult roda dentro
  pScan->clearResults();
  celulas();
  rodape();
  ref_tick();
  serial_espelho();
}
