// CYD BLE advertising sniffer -> serial (formato "@b ...") -> extcap -> Wireshark.
// Mesma lógica BLE validada no T-Embed (API BLEScan; o ESP32 só expõe advertising,
// não segue conexão). A CYD é ESP32 original (BLE 4.2). Telinha mostra o status.
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <TFT_eSPI.h>

TFT_eSPI tft = TFT_eSPI();
// contadores cosméticos p/ a tela: incrementados na task BT, lidos no loop.
// leitura "rasgada" aqui é inofensiva (é só display) — nada de container compartilhado.
static volatile unsigned long g_reports = 0;
static volatile int g_lastRssi = 0;
static BLEScan* pScan = nullptr;

// onResult roda na task do BLE enquanto o loop está parado dentro de start();
// é o único escritor da serial -> seguro imprimir direto (igual ao Beacon_Scanner).
class AdvCB : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) {
    static const char hx[] = "0123456789abcdef";
    BLEAddress addr = d.getAddress();          // manter vivo: getNative() aponta p/ dentro
    uint8_t* bda = *addr.getNative();          // arduino-esp32 2.x: retorna uint8_t(*)[6]
    uint8_t* pl = d.getPayload();
    size_t n = d.getPayloadLength(); if (n > 62) n = 62;
    // 2.x não expõe getAdvType(); manda 0 (ADV_IND). O extcap ainda separa adv/scan-resp
    // pela fronteira das estruturas AD, então nomes/UUIDs continuam dissecando certo.
    Serial.print("@b "); Serial.print(0); Serial.print(' ');
    Serial.print((int)d.getAddressType()); Serial.print(' ');
    Serial.print((int)d.getRSSI()); Serial.print(' ');
    for (int i = 0; i < 6; i++) { Serial.print(hx[bda[i] >> 4]); Serial.print(hx[bda[i] & 0x0F]); }
    Serial.print(' ');
    for (size_t i = 0; i < n; i++) { Serial.print(hx[pl[i] >> 4]); Serial.print(hx[pl[i] & 0x0F]); }
    Serial.print('\n');
    g_reports++;
    g_lastRssi = d.getRSSI();
  }
};
static AdvCB advCB;

static void screenBase() {
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(TC_DATUM);
  tft.setTextColor(TFT_CYAN, TFT_BLACK); tft.setTextFont(4);
  tft.drawString("BLE SNIFFER", 120, 20);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK); tft.setTextFont(2);
  tft.drawString("advertising -> Wireshark", 120, 56);
  tft.drawFastHLine(24, 80, 192, 0x2965);
  tft.setTextColor(0x7BEF, TFT_BLACK);
  tft.drawString("pacotes capturados", 120, 120);
}

static void screenStats() {
  char buf[32];
  tft.setTextDatum(TC_DATUM);
  tft.fillRect(0, 142, 240, 44, TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK); tft.setTextFont(6);
  snprintf(buf, sizeof(buf), "%lu", g_reports);
  tft.drawString(buf, 120, 142);
  tft.fillRect(0, 250, 240, 24, TFT_BLACK);
  tft.setTextColor(TFT_CYAN, TFT_BLACK); tft.setTextFont(2);
  snprintf(buf, sizeof(buf), "ultimo RSSI: %d dBm", g_lastRssi);
  tft.drawString(buf, 120, 252);
}

void setup() {
  Serial.begin(115200);
  pinMode(TFT_BL, OUTPUT); digitalWrite(TFT_BL, HIGH);
  tft.init();
  tft.setRotation(0);                 // retrato 240x320
  screenBase();
  tft.setTextColor(TFT_YELLOW, TFT_BLACK); tft.setTextFont(2); tft.setTextDatum(TC_DATUM);
  tft.drawString("iniciando BLE...", 120, 160);

  BLEDevice::init("");
  pScan = BLEDevice::getScan();
  pScan->setAdvertisedDeviceCallbacks(&advCB, true, true);   // wantDuplicates: pega tudo
  pScan->setActiveScan(true);                                // ativo: pega scan responses
  pScan->setInterval(80);
  pScan->setWindow(60);

  screenBase();                       // limpa o "iniciando"
  Serial.println("= rtls-alvo ready");
}

void loop() {
  pScan->start(1, false);             // rajada de 1s; onResult imprime @b durante
  pScan->clearResults();
  screenStats();
}
