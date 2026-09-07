// Campanha de rotulos no proprio CYD: planta na tela, eu toco onde estou,
// INICIAR / FINALIZAR, e cada rotulo sai por UDP no instante em que e feito.
//
// Por que o rotulo no CYD e nao no caderno: o modelo tem 405 mil avistamentos do
// CYD e UM ponto de gabarito. Rotulo e o insumo que falta, e anotar hora a mao
// e onde a campanha morre. Aqui o inicio e o fim da janela sao o toque.
//
// Por que UDP na hora e nao SD no fim: o CYD ja esta associado com IP. Gravar
// tudo no cartao e mandar no final so cria o modo de falha em que a campanha
// inteira mora no cartao ate o fim. Cada evento vai 3x (UDP cai), o servidor
// deduplica por (seq, ev). ponytail: sem SD, sem ACK — se o receptor mostrar
// buraco, ai sim cartao.
//
// O transmissor de referencia (Ptx ciclica, magica "RC") e o mesmo do painel e
// NAO muda: e a inclinacao RSSI x Ptx num ponto fixo que torna a campanha
// separavel. Um ciclo inteiro leva 48 s, entao a permanencia util num ponto e
// de uns 2-3 min — dois a quatro ciclos.
//
// A estrutura de abas continua (um terco da campanha por aba + a aba do mapa).
// Uma campanha curta de tres pontos pode nao fitar nada, e a culpa costuma ser
// do PISO e nao da geometria: o desenho D-otimo conta N ancoras por ponto e o
// comodo isolado entrega 2. Por isso a busca pesa cada enlace pela
// probabilidade de ele EXISTIR (P[RSSI > limiar]) antes de somar informacao.
// Ver rtls/modelo/padrao.py e docs/matematica/05-campanha-dotima.md.
//
// Novidade que muda a tela: agora o ponto tem ALTURA propria (0,05 ou 1,65 m).
// Elevacao e o eixo que a malha nao ve — as ancoras estao todas em 0,30 ou
// 1,10 — e por isso a busca so escolhe chao e acima da cabeca. Errar a altura
// estraga o ponto tanto quanto errar o comodo, entao ela e o texto grande em
// cima do cronometro, e dois pontos com o MESMO (x,y) e alturas diferentes
// sao desenhados com um desvio lateral para nao se cobrirem.
//
// O promiscuo do painel saiu daqui: aquilo obrigava o loop a alternar fases de
// 2 s e com isso o toque ficava surdo. A contagem de ancoras na tela vem so do
// scan BLE da malha, com janela curta (30/200 = 15%) para nao roubar o ar do
// anuncio de referencia. E semaforo de vida, nao medida.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertising.h>
#include <BLEAdvertisedDevice.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <esp_bt.h>
#include <Preferences.h>
#include "credenciais.h"

#define PORTA_ROTULO 5009      // rtls/receptor.py usa 5007/5008; rotulo e outro bicho
#define PORTA_MAPA   5010      // rtls/mapa_alvo.py manda a posicao estimada a 2 Hz
#define ALVO_S       180       // permanencia sugerida por ponto
#define VELHO_MS     8000
#define CID_MALHA    0xFFFF
#define MAGICA_A     'R'
#define MAGICA_B     'A'       // "RA" = anuncio da malha (as ancoras entre si)
#define MAGICA_C     'C'       // "RC" = referencia do CYD

// ---- geometria, ancoras e campanha: TUDO gerado do sitio ----
// Este bloco era copia a mao da planta e do desenho da campanha. Agora vem de
// ferramentas/gera_firmware_alvo.py, e a CI reprova o .h desatualizado (ele
// regera em memoria e compara byte a byte). MACS, ANC, PAREDES, PONTOS, CMS,
// POR_CM, MX/MY/MXP/MYP/ESC/U0P/V0P/PAN_X/BT_Y/RAIO_PX/DESVIO_PX e PLX/PLY
// moram la. Numero de tela que aparece nos DOIS lados e drift esperando acontecer.
#include "sitio_gerado.h"

// 3 alturas agora. O desvio em x separa na tela os que dividem o mesmo (x,y).
// DESVIO_PX vem do .h: o gerador RESERVA essa folga na borda ao escolher a
// escala, entao os dois tem de ser o MESMO numero ou o ponto da parede estoura.
#define DX(i) (PONTOS[i].z > 1.2f ? -DESVIO_PX : PONTOS[i].z > 0.4f ? 0 : DESVIO_PX)
#define COR_Z(i) (PONTOS[i].z > 1.2f ? TFT_MAGENTA : PONTOS[i].z > 0.4f ? TFT_CYAN : TFT_YELLOW)
#define NOME_Z(i) (PONTOS[i].z > 1.2f ? "1,65 m  ALTO" : PONTOS[i].z > 0.4f ? "0,85 m  MEIO" : "0,05 m  CHAO")
#define N_PONTOS (sizeof(PONTOS) / sizeof(PONTOS[0]))

// ---- tela: retrato 240x320. A escala e a orientacao da planta sao escolhidas
// pelo gerador (ver sitio_gerado.h): ele gira 90 graus quando isso ganha mais de
// 5% de px/m, porque px/m e o que decide se o dedo acerta o ponto certo.
// A calibracao de toque abaixo e da placa, nao do sitio: vale para qualquer planta.
#define ROT   0
#define AB_H  28                  // faixa das abas, acima da planta
#define N_ABAS ((int)N_CM + 1)   // as abas da campanha + a aba do mapa
#define AB_W  (240 / N_ABAS)
// Dois pontos no MESMO (x,y) e alturas diferentes cairiam no mesmo pixel. O
// desvio e em X (alto para a esquerda, baixo para a direita) e nao em Y porque
// em Y ele ANULA a separacao real da planta. DESVIO_PX de mentira no desenho; a
// altura de verdade esta escrita no painel. O gerador ja garante que dentro de
// uma aba nenhum par fica a menos de 2*RAIO_PX — inclusive com este desvio.
#define PXP(i) (max(RAIO_PX + 2, PLX(PONTOS[i].x, PONTOS[i].y) + DX(i)))
#define PYP(i) PLY(PONTOS[i].x, PONTOS[i].y)
#define SPK   26                  // alto-falante da placa: o bip dos 3 min

// Touch XPT2046 — SPI separado do display. Estes 4 limites sao DA SUA PLACA:
// se o toque sair deslocado, remeça com o sketch de calibracao (docs/INSTALL.md).
#define T_CLK 25
#define T_CS  33
#define T_MOSI 32
#define T_MISO 39
#define T_IRQ 36
#define TOUCH_X_MIN 439
#define TOUCH_X_MAX 3749
#define TOUCH_Y_MIN 189
#define TOUCH_Y_MAX 3701

TFT_eSPI tft = TFT_eSPI();
SPIClass touchSPI(HSPI);
XPT2046_Touchscreen ts(T_CS, T_IRQ);
WiFiUDP udp;
WiFiUDP udpm;                 // 5010: so escuta o mapa; 5009 e o rotulo

// ---- referencia: identica a do painel ----
#define REF_MS 6000
static const int8_t NIVEIS[] = {-12, -9, -6, -3, 0, 3, 6, 9};
static const esp_power_level_t LVL[] = {ESP_PWR_LVL_N12, ESP_PWR_LVL_N9, ESP_PWR_LVL_N6,
                                        ESP_PWR_LVL_N3, ESP_PWR_LVL_N0, ESP_PWR_LVL_P3,
                                        ESP_PWR_LVL_P6, ESP_PWR_LVL_P9};
#define N_NIVEIS (sizeof(NIVEIS) / sizeof(NIVEIS[0]))
static BLEAdvertising *pAdv = nullptr;
static BLEScan *pScan = nullptr;
static uint8_t g_nivel = 0;
static uint16_t g_seq = 0;

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
  pAdv->setMinInterval(160);        // 100 ms
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

// ---- semaforo: quantas ancoras ouvi anunciar agora ----
static volatile uint32_t visto[N_ANC];
class AdvCB : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) {
    if (!d.haveManufacturerData()) return;
    std::string m = d.getManufacturerData();
    if (m.size() < 7) return;
    const uint8_t *b = (const uint8_t *)m.data();
    if ((b[0] | (b[1] << 8)) != CID_MALHA || b[2] != MAGICA_A || b[3] != MAGICA_B) return;
    for (int i = 0; i < N_ANC; i++)
      if (!memcmp(b + 4, MACS[i] + 3, 3)) { visto[i] = millis(); return; }
  }
};
static AdvCB advCB;

static int vivas(void) {
  int n = 0;
  for (int i = 0; i < N_ANC; i++) if (visto[i] && millis() - visto[i] < VELHO_MS) n++;
  return n;
}

// ---- estado da campanha ----
static int  cm  = 0;              // campanha ativa; so os 5 pontos dela na tela
#define P0 (cm * POR_CM)
#define P1 (min(P0 + POR_CM, (int)N_PONTOS))   // a ultima aba tem 2, nao 3
#define N_ABA(i) (min(((i) + 1) * POR_CM, (int)N_PONTOS) - (i) * POR_CM)
static int  sel = -1;             // ponto selecionado (indice global), -1 = nenhum
static bool medindo = false;
static uint32_t t_ini = 0;
static uint8_t feitos[N_PONTOS];  // quantas janelas fechadas em cada ponto
static Preferences nvs;           // feitos[] sobrevive a reset. Isto foi aprendido
                                  // em campo: a placa reiniciou no meio da 1a aba
                                  // e o memset do setup apagou a unica confirmacao
                                  // visivel do que ja tinha sido medido. O dado ja
                                  // estava salvo no servidor; o que sumiu foi a
                                  // marca na tela, e sem ela nao da para saber se
                                  // o toque pegou.
static void salva(void) { nvs.putBytes("feitos", feitos, sizeof(feitos)); }
static uint16_t g_rot = 0;        // sequencia do rotulo, para o servidor deduplicar
static uint16_t g_boot = 0;       // sorteado no boot: g_rot reinicia em 0 num reset
                                  // e sem isto a 1a janela seguinte viraria "copia"
static char status[40] = "";
static uint32_t t_aba = 0;        // 1o toque na aba ativa; 2o em 2 s zera a campanha
static bool bipou = false;        // ja avisei os 3 min desta janela?

// Broadcast: sem IP de servidor para configurar e sobrevive a troca de DHCP.
// 3 copias porque UDP cai e perder um FINALIZAR estraga o ponto inteiro.
static void envia(const char *ev, float dur_s) {
  char b[220];
  int n = snprintf(b, sizeof b,
    "{\"ev\":\"%s\",\"cm\":\"%s\",\"boot\":%u,\"seq\":%u,\"ponto\":\"%s\",\"x\":%.2f,\"y\":%.2f,\"z\":%.2f,"
    "\"dur_s\":%.1f,\"ptx\":%d,\"ancoras\":%d}",
    ev, CMS[cm], g_boot, g_rot, PONTOS[sel].nome, PONTOS[sel].x, PONTOS[sel].y, PONTOS[sel].z,
    dur_s, NIVEIS[g_nivel], vivas());
  for (int i = 0; i < 3; i++) {
    udp.beginPacket(WiFi.broadcastIP(), PORTA_ROTULO);
    udp.write((const uint8_t *)b, n);
    udp.endPacket();
    delay(30);
  }
  Serial.printf("@rot %s\n", b);
}

// ---- mapa ao vivo (aba 4) ----
// So display: o pacote vem pronto do rtls/mapa_alvo.py, que le o vivo.json. A confianca
// chega ja em decimos (0..10) porque a regra de quem manda na confianca e do
// servidor — aqui nao tem como saber que o spread mente quando so 2 ancoras ouvem.
static bool  mapa = false;
static float m_x = 0, m_y = 0;
static int   m_q = 0, m_n = 0;
static uint32_t m_t = 0;          // millis do ultimo pacote; 0 = nunca
static int   m_px = -1, m_py = -1;   // onde a bolinha esta DESENHADA agora

// 0..10 -> vermelho -> amarelo -> verde. Passar POR amarelo (e nao interpolar
// vermelho->verde direto, que faz um marrom escuro no meio) e o que da a
// impressao de ceu mudando de cor: o meio do caminho e a hora mais clara.
static uint16_t cor_conf(int q) {
  int r = q <= 5 ? 255 : 255 - (q - 5) * 51;
  int g = q <= 5 ? q * 51 : 255;
  return tft.color565(r, g, 0);
}

static bool mapa_le(void) {
  bool novo = false;
  for (int n; (n = udpm.parsePacket()) > 0; ) {
    char b[64];
    int k = udpm.read((uint8_t *)b, sizeof b - 1);
    if (k <= 0) continue;
    b[k] = 0;
    float x, y; int q, na;
    if (sscanf(b, "M %f %f %d %d", &x, &y, &q, &na) == 4) {
      m_x = x; m_y = y; m_q = constrain(q, 0, 10); m_n = na; m_t = millis();
      novo = true;
    }
  }
  return novo;
}

// ---- desenho ----
// Sem fillScreen: quem apaga e quem chama. A bolinha do mapa se apaga sozinha
// (um circulo preto no lugar velho) e depois manda redesenhar o fundo por cima —
// se este fundo limpasse tudo, a tela piscaria 2x por segundo.
static void planta_fundo(void) {
  for (unsigned i = 0; i < N_PAREDES; i++) {
    const Seg &w = PAREDES[i];
    tft.drawLine(PLX(w.x0, w.y0), PLY(w.x0, w.y0),
                 PLX(w.x1, w.y1), PLY(w.x1, w.y1), TFT_DARKGREY);
  }
  tft.setTextFont(1);
  tft.setTextDatum(MC_DATUM);
  for (int i = 0; i < N_ANC; i++) {
    int x = PLX(ANC[i][0], ANC[i][1]), y = PLY(ANC[i][0], ANC[i][1]);
    tft.fillCircle(x, y, 5, TFT_BLUE);
    tft.setTextColor(TFT_WHITE, TFT_BLUE);
    tft.drawString(String(i + 1), x, y);
  }
}

static void planta(void) {
  tft.fillRect(0, MY - 4, PAN_X - 4, 320 - MY, TFT_BLACK);
  planta_fundo();
}

static void pontos(void) {
  tft.setTextFont(1);
  tft.setTextDatum(MC_DATUM);
  for (int i = P0; i < P1; i++) {
    int x = PXP(i), y = PYP(i);
    uint16_t c = feitos[i] ? TFT_GREEN : TFT_ORANGE;
    if (i == sel) {
      tft.fillCircle(x, y, 8, c);
      tft.drawCircle(x, y, RAIO_PX, TFT_WHITE);
      tft.setTextColor(TFT_BLACK, c);
    } else {
      tft.drawCircle(x, y, 8, c);
      tft.setTextColor(c, TFT_BLACK);
    }
    tft.drawString(PONTOS[i].nome, x, y);
  }
}

// O piscado era este painel: apagava 106x224 px em preto e redesenhava por cima,
// 2x por segundo. Todo drawString daqui ja escreve com fundo opaco, entao o
// fillRect so servia para varrer o rabo das strings que encurtam — que e
// exatamente o que setTextPadding faz, sem o flash preto no meio.
static void painel(void) {
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(240 - PAN_X);
  tft.setTextFont(2);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.drawString(sel < 0 ? "toque o ponto" : ("ponto " + String(PONTOS[sel].nome)), PAN_X, MY);
  // A altura vem antes do x,y porque e o unico numero que o desenho na planta
  // NAO diz: dois pontos podem cair no mesmo lugar e diferir so nela.
  tft.setTextColor(sel < 0 ? TFT_DARKGREY : COR_Z(sel), TFT_BLACK);
  tft.drawString(sel < 0 ? "" : NOME_Z(sel), PAN_X, MY + 20);

  uint32_t s = medindo ? (millis() - t_ini) / 1000 : 0;
  tft.setTextFont(6);
  tft.setTextColor(s >= ALVO_S ? TFT_GREEN : (medindo ? TFT_YELLOW : TFT_DARKGREY), TFT_BLACK);
  char t[8]; snprintf(t, sizeof t, "%u:%02u", s / 60, s % 60);
  tft.drawString(t, PAN_X, MY + 46);

  tft.setTextFont(2);
  int n = vivas();
  tft.setTextColor(n >= 4 ? TFT_GREEN : (n >= 2 ? TFT_YELLOW : TFT_RED), TFT_BLACK);
  tft.drawString(String(n) + "/" + String(N_ANC) + " ancoras", PAN_X, MY + 98);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString("ref " + String(NIVEIS[g_nivel]) + " dBm", PAN_X, MY + 118);
  int done = 0;
  for (int i = P0; i < P1; i++) if (feitos[i]) done++;
  tft.setTextColor(done == P1 - P0 ? TFT_GREEN : TFT_WHITE, TFT_BLACK);
  tft.drawString(String(done) + "/" + String(P1 - P0) + " pontos", PAN_X, MY + 138);

  // Aqui morava o cronometro da campanha, que contava do 1o INICIAR e NAO
  // parava entre os pontos — dava para ler 14:32 e nao saber se a JANELA fechou
  // os 3 min. Agora e a conta regressiva da janela atual: zera junto com o
  // cronometro de cima toda vez que uma janela comeca, e o unico jeito de ver
  // 3 MIN OK e ter ficado 3 min neste ponto.
  tft.setTextFont(4);
  if (!medindo) {
    tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
    tft.drawString("--:--", PAN_X, MY + 158);
  } else if (s >= ALVO_S) {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.drawString("3 MIN OK", PAN_X, MY + 158);
  } else {
    uint32_t f = ALVO_S - s;
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
    snprintf(t, sizeof t, "-%u:%02u", f / 60, f % 60);
    tft.drawString(t, PAN_X, MY + 158);
  }

  tft.setTextFont(2);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawString(status, PAN_X, MY + 190);
  tft.setTextPadding(0);
}

// Bolinha + numeros do mapa. Apaga so o circulo velho e repinta o fundo por
// cima; nada mais na tela e tocado, entao a 2 Hz nao ha piscado nenhum.
static void alvo(void) {
  bool velho = !m_t || millis() - m_t > 3000;
  int x = PLX(m_x, m_y), y = PLY(m_x, m_y);
  if (m_px >= 0) tft.fillCircle(m_px, m_py, 8, TFT_BLACK);
  planta_fundo();
  if (m_t) {
    if (velho) tft.drawCircle(x, y, 6, TFT_DARKGREY);
    else       tft.fillCircle(x, y, 6, cor_conf(m_q));
    m_px = x; m_py = y;
  } else {
    m_px = -1;
  }

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(240 - PAN_X);
  tft.setTextFont(2);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.drawString("ao vivo", PAN_X, MY);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString(m_t ? (String(m_x, 2) + " , " + String(m_y, 2)) : "", PAN_X, MY + 20);

  tft.setTextFont(6);
  tft.setTextColor(velho ? TFT_DARKGREY : cor_conf(m_q), TFT_BLACK);
  tft.drawString(String(m_q * 10) + "%", PAN_X, MY + 46);

  tft.setTextFont(2);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString(m_t ? (String(m_n) + " ancoras") : "", PAN_X, MY + 98);
  tft.setTextColor(velho ? TFT_RED : TFT_DARKGREY, TFT_BLACK);
  tft.drawString(velho ? "SEM DADO" : "confianca", PAN_X, MY + 118);
  tft.setTextPadding(0);
}

// Abas no topo: qual campanha esta na tela e quanto falta em cada uma. Ficam
// acima da planta e nao no rodape porque o rodape inteiro e o botao — e um dedo
// que erra o INICIAR custa uma janela.
static void abas(void) {
  tft.setTextDatum(MC_DATUM);
  tft.setTextFont(2);
  for (int i = 0; i < N_ABAS; i++) {
    bool at = mapa ? (i == (int)N_CM) : (i == cm);
    uint16_t c = at ? TFT_NAVY : TFT_BLACK;
    tft.fillRect(i * AB_W, 1, AB_W - 2, AB_H - 3, c);
    tft.drawRect(i * AB_W, 1, AB_W - 2, AB_H - 3, at ? TFT_CYAN : TFT_DARKGREY);
    if (i == (int)N_CM) {
      tft.setTextColor(at ? TFT_WHITE : TFT_DARKGREY, c);
      tft.drawString("mapa", i * AB_W + AB_W / 2 - 1, AB_H / 2);
      continue;
    }
    int f = 0;
    for (int k = i * POR_CM; k < i * POR_CM + N_ABA(i); k++) if (feitos[k]) f++;
    // Com 3 campanhas a aba tem 60 px e "1-3 0/3" nao cabe: quem conta e a cor
    // (verde = os 3 fechados) e o "n/3 pontos" do painel.
    tft.setTextColor(f == N_ABA(i) ? TFT_GREEN : (at ? TFT_WHITE : TFT_DARKGREY), c);
    tft.drawString(CMS[i], i * AB_W + AB_W / 2 - 1, AB_H / 2);
  }
}

static void botao(void) {
  bool ok = medindo || sel >= 0;
  uint16_t c = !ok ? TFT_DARKGREY : (medindo ? TFT_RED : TFT_DARKGREEN);
  tft.fillRoundRect(8, BT_Y, 224, 54, 8, c);
  tft.setTextDatum(MC_DATUM);
  tft.setTextFont(4);
  tft.setTextColor(TFT_WHITE, c);
  tft.drawString(medindo ? "FINALIZAR" : "INICIAR", 120, BT_Y + 27);
}

// ---- toque ----
static bool le(int &sx, int &sy) {
  if (!(ts.tirqTouched() && ts.touched())) return false;
  TS_Point p = ts.getPoint();
  sx = constrain((int)map(p.x, TOUCH_X_MIN, TOUCH_X_MAX, 0, tft.width()), 0, tft.width() - 1);
  sy = constrain((int)map(p.y, TOUCH_Y_MIN, TOUCH_Y_MAX, 0, tft.height()), 0, tft.height() - 1);
  return true;
}

// Ponto mais proximo do dedo, com teto. Alvo por distancia e nao por retangulo:
// a 23 px/m os pontos ficam a ~23 px e um dedo cobre mais que isso — quem manda
// e o mais perto, nao quem tem a caixa maior.
//
// Com 9 pontos cabe mais de um debaixo do mesmo dedo (4 e 6 sao o mesmo x,y em
// alturas diferentes, a 18 px um do outro). Por isso: tocar DE NOVO perto do
// ponto ja selecionado passa para o proximo candidato em vez de teimar no mais
// perto. Sem isto o ponto de baixo de um par seria inalcancavel pelo toque.
static int perto(int x, int y) {
  int cand[N_PONTOS], n = 0; const long d2 = 32 * 32;
  for (int i = P0; i < P1; i++) {
    long dx = x - PXP(i), dy = y - PYP(i);
    if (dx * dx + dy * dy < d2) cand[n++] = i;
  }
  if (!n) return -1;
  // ordena por distancia (n <= 3, insercao e o suficiente)
  for (int a = 1; a < n; a++)
    for (int b = a; b > 0; b--) {
      long da = (long)(x - PXP(cand[b])) * (x - PXP(cand[b])) +
                (long)(y - PYP(cand[b])) * (y - PYP(cand[b]));
      long db = (long)(x - PXP(cand[b - 1])) * (x - PXP(cand[b - 1])) +
                (long)(y - PYP(cand[b - 1])) * (y - PYP(cand[b - 1]));
      if (da < db) { int t = cand[b]; cand[b] = cand[b - 1]; cand[b - 1] = t; }
    }
  for (int a = 0; a < n; a++)
    if (cand[a] == sel) return cand[(a + 1) % n];   // 2o toque = proximo do par
  return cand[0];
}

static void toque(int x, int y) {
  if (y < AB_H) {
    if (medindo) return;          // trocar de campanha no meio da janela e rotulo errado
    int i = x / AB_W;
    if (i < 0 || i >= N_ABAS) return;
    if (i == (int)N_CM) {         // aba do mapa: nao rotula nada, so olha
      if (mapa) return;
      mapa = true; sel = -1; m_px = -1;
      tft.fillRect(0, MY - 4, 240, 320 - MY + 4, TFT_BLACK);
      planta_fundo(); alvo(); abas();
      return;
    }
    if (mapa) {                   // voltando do mapa para uma campanha
      mapa = false; cm = i; sel = -1; t_aba = millis();
      tft.fillRect(0, MY - 4, 240, 320 - MY + 4, TFT_BLACK);
      planta(); pontos(); abas(); painel(); botao();
      return;
    }
    if (i != cm) {
      cm = i; sel = -1; t_aba = millis();
      planta(); pontos(); abas(); painel(); botao();
      return;
    }
    // Aba JA ativa: 2 toques em 2 s zeram as marcas desta campanha. Refazer uma
    // campanha e o caso normal aqui, e sem isto as marcas antigas do NVS ficam
    // mentindo "ja fiz" na segunda passada. Nao apaga nada no servidor.
    if (millis() - t_aba < 2000) {
      for (int k = P0; k < P1; k++) feitos[k] = 0;
      salva(); sel = -1; t_aba = 0;
      snprintf(status, sizeof status, "%s zerada", CMS[cm]);
      pontos(); abas(); painel(); botao();
    } else {
      t_aba = millis();
    }
    return;
  }
  if (mapa) return;               // no mapa so a barra de abas responde
  if (y >= BT_Y) {
    if (medindo) {
      float dur = (millis() - t_ini) / 1000.0f;
      envia("fim", dur);
      if (feitos[sel] < 255) feitos[sel]++;
      salva();
      medindo = false;
      // sel = -1 e o conserto do erro que comeu a cm1: FINALIZAR deixava o ponto
      // selecionado, entao ANDAR ate o proximo ponto e apertar INICIAR rearmava
      // o ponto ANTERIOR, em silencio. Foi assim que 21 min medidos no ponto 5
      // sairam rotulados como ponto 2. Agora o botao apaga ate eu tocar a planta
      // de novo: nao da para iniciar uma janela sem dizer onde estou.
      sel = -1;
      snprintf(status, sizeof status, "fim %.0fs — toque o ponto", dur);
      g_rot++;
      pontos(); abas();
    } else if (sel >= 0) {
      t_ini = millis();
      bipou = false;
      medindo = true;
      envia("ini", 0.0f);
      snprintf(status, sizeof status, "medindo...");
    }
    botao();
    painel();
    return;
  }
  if (medindo) return;            // trocar de ponto no meio da janela e rotulo errado
  int i = perto(x, y);
  if (i >= 0 && i != sel) { sel = i; pontos(); painel(); botao(); }
}

void setup() {
  Serial.begin(115200);
  memset((void *)visto, 0, sizeof(visto));
  memset(feitos, 0, sizeof(feitos));
  nvs.begin("campanha", false);
  nvs.getBytes("feitos", feitos, sizeof(feitos));  // ausente = fica no memset
  // Chave nova de proposito: o blob antigo tem 3 bytes {1,1,1} da campanha
  // de 06/09 e seria lido como "1, 2 e 3 ja feitos" nos pontos NOVOS.
  g_boot = (uint16_t)(esp_random() & 0xFFFF);
  tft.init();
  tft.setRotation(ROT);
  pinMode(TFT_BL, OUTPUT); digitalWrite(TFT_BL, HIGH);
  tft.fillScreen(TFT_BLACK);
  touchSPI.begin(T_CLK, T_MISO, T_MOSI, T_CS);
  ts.begin(touchSPI);
  ts.setRotation(ROT);

  // BT antes do WiFi, como no painel: e a ordem que nao aborta em coex.
  BLEDevice::init("");
  pAdv = BLEDevice::getAdvertising();
  ref_aplica();
  pScan = BLEDevice::getScan();
  // O segundo argumento (wantDuplicates) e o que faz o semaforo funcionar: sem ele
  // a lib guarda cada endereco ja visto e NUNCA mais chama onResult para aquele
  // endereco. O painel escapava disso porque reiniciava o scan a cada volta do
  // loop; aqui o scan e continuo, entao cada ancora era contada UMA vez e depois
  // envelhecia para sempre — MEDIDO: ZERO ancora na tela com a malha inteira no ar.
  pScan->setAdvertisedDeviceCallbacks(&advCB, true);
  pScan->setActiveScan(false);
  pScan->setInterval(200);        // 30% de janela; o anuncio de referencia fica com o resto
  pScan->setWindow(60);

  WiFi.mode(WIFI_STA);            // NAO desligar modem sleep com BT ligado
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  for (int i = 0; i < 60 && !WiFi.isConnected(); i++) delay(500);
  udp.begin(PORTA_ROTULO);
  udpm.begin(PORTA_MAPA);

  if (!WiFi.isConnected()) snprintf(status, sizeof status, "SEM REDE");
  abas(); planta(); pontos(); painel(); botao();
  pScan->start(0, nullptr, false);   // assincrono: o loop fica livre para o toque
  Serial.printf("@i wifi=%d ip=%s\n", WiFi.status(), WiFi.localIP().toString().c_str());
}

void loop() {
  int x, y;
  if (le(x, y)) {
    toque(x, y);
    for (uint32_t t = millis(); ts.touched() && millis() - t < 2000; ) delay(20);
  }
  ref_tick();
  // Bip dos 3 min. Sem isto o aviso e so a cor de um numero na tela de um
  // aparelho que esta na mao dele, virado para baixo, no chao ou acima da
  // cabeca — os dois extremos que esta campanha pede. Alto-falante do
  // ESP32-2432S028R no GPIO 26; se a placa nao tiver, tone() e inofensivo.
  if (medindo && !bipou && millis() - t_ini >= ALVO_S * 1000UL) {
    bipou = true;
    for (int i = 0; i < 3; i++) { tone(SPK, 2400, 120); delay(180); }
    noTone(SPK);
  }
  static uint32_t ult = 0, ults = 0;
  if (mapa) {
    // So redesenha quando chega pacote (ou quando o dado esfria): repintar sem
    // novidade e o que faz a tela piscar sem motivo.
    static bool era_velho = true;
    bool velho = !m_t || millis() - m_t > 3000;
    if (mapa_le() || velho != era_velho) { era_velho = velho; alvo(); }
  } else if (millis() - ult > 500) { ult = millis(); painel(); }
  if (millis() - ults > 5000) { ults = millis(); Serial.printf("@v %d/6\n", vivas()); }
  delay(20);
}
