// Ver malha.h. Duas transmissoes de 1 Hz com a MESMA carga util:
//
//   CID 0xFFFF (reservado pela SIG p/ teste) + "RA" + 3 ultimos bytes do MAC STA
//   + boot_count + modo
//
// Por que os 3 ultimos bytes do MAC e nao um numero de ancora: as N placas rodam
// um firmware IDENTICO, sem numero gravado em lugar nenhum (mesma regra do transporte).
// Quem escuta e que tem a tabela MAC->numero; trocar uma placa nao reflasha as outras.
//
// Por que anuncio BLE e nao heartbeat ESP-NOW para o g_i: o ESP-NOW e OFDM/DSSS na
// cadeia do WiFi, o alvo e GFSK na cadeia do BLE. So o anuncio mede o que o alvo
// mede. O ESP-NOW vai junto porque e barato (1 quadro/s) e da a referencia de taxa
// FIXA que o trafego UDP nao da — o RSSI do UDP anda com o MCS que o rate control
// escolher.
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_mac.h"
#include "esp_wifi.h"
#include "esp_now.h"
#include "host/ble_gap.h"
#include "os/os_mbuf.h"
#include "malha.h"
#include "wireless.h"

#define CID          0xFFFF
#define INST         0            // instancia de ext adv (MAX_EXT_ADV_INSTANCES=1)
#define CARGA        10           // CID(2) magica(2) mac3(3) boot(2) modo(1)
#define AD_LEN       (CARGA + 2)  // + byte de tamanho + tipo 0xFF

static uint8_t g_addr_type;
// 3 Hz COMANDADOS para ~1 Hz NO AR. MEDIDO: com o scan da propria ancora a 75% de
// duty, so ~1/4 dos eventos de anuncio sai (1 Hz comandado -> 0,2/s no vizinho, com
// captura de ~0,75 por anuncio de 3 canais). E knob do farol; V4 acerta o valor.
static uint8_t g_adv_hz = 3;
static int8_t  g_tx_power = 0;
static bool    g_espnow_pronto;
static uint8_t g_ultimo[AD_LEN];
static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

uint16_t malha_boot(void) {
    static uint16_t n;
    static bool lido;
    if (lido) {
        return n;
    }
    lido = true;
    nvs_handle_t h;
    // RTC_NOINIT sobrevive a reset de software mas NAO a queda de energia, e e
    // exatamente a queda de energia que queremos flagrar. Por isso NVS.
    if (nvs_open("malha", NVS_READWRITE, &h) != ESP_OK) {
        return 0;
    }
    nvs_get_u16(h, "boot", &n);
    n++;
    nvs_set_u16(h, "boot", n);
    nvs_commit(h);
    nvs_close(h);
    return n;
}

// Monta a estrutura AD completa: [len][0xFF][CID lo][CID hi]['R']['A'][mac3][boot][modo]
static void monta(uint8_t *ad) {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    uint16_t b = malha_boot();
    ad[0] = AD_LEN - 1;
    ad[1] = 0xFF;
    ad[2] = CID & 0xFF;
    ad[3] = CID >> 8;
    ad[4] = 'R';
    ad[5] = 'A';
    ad[6] = mac[3];
    ad[7] = mac[4];
    ad[8] = mac[5];
    ad[9] = b & 0xFF;
    ad[10] = b >> 8;
    ad[11] = wireless_modo();
}

static int adv_liga(const uint8_t *ad) {
    int rc_cfg = 0, rc_dat = 0, rc_ini = 0;
    struct ble_gap_ext_adv_params p = {0};
    p.legacy_pdu = 1;            // legacy: e o unico PDU que um radio BLE 4.2 (CYD) ve
    p.connectable = 0;
    p.scannable = 0;             // ADV_NONCONN_IND: ninguem responde, ninguem conecta
    p.own_addr_type = g_addr_type;
    p.primary_phy = BLE_HCI_LE_PHY_1M;
    p.secondary_phy = BLE_HCI_LE_PHY_1M;
    p.sid = 0;
    // 0x07 = 37|38|39 EXPLICITO. Com channel_map = 0 medimos 0,28 capturado por
    // anuncio na ancora vizinha — a assinatura de mono-canal que a PROPOSTA ja
    // documenta (~25% mono, ~0,75 em 3 canais). Nao confiar no default.
    p.channel_map = 0x07;
    p.itvl_min = p.itvl_max = (uint32_t)(1600 / (g_adv_hz ? g_adv_hz : 1));  // 0,625 ms
    p.tx_power = g_tx_power;
    int8_t saiu;
    rc_cfg = ble_gap_ext_adv_configure(INST, &p, &saiu, NULL, NULL);
    if (rc_cfg == 0) {
        struct os_mbuf *m = os_msys_get_pkthdr(AD_LEN, 0);
        if (!m) {
            rc_dat = -1;
        } else {
            os_mbuf_append(m, ad, AD_LEN);
            rc_dat = ble_gap_ext_adv_set_data(INST, m);
            // set_data so assume o mbuf quando da certo; sem isto o pool vaza um
            // mbuf por segundo e o anuncio para de vez apos alguns minutos.
            if (rc_dat) {
                os_mbuf_free_chain(m);
            }
        }
        if (rc_dat == 0) {
            rc_ini = ble_gap_ext_adv_start(INST, 0 /*sem prazo*/, 0 /*sem limite*/);
        }
    }
    if (rc_cfg || rc_dat || rc_ini) {
        printf("= malha adv cfg=%d dat=%d ini=%d\n", rc_cfg, rc_dat, rc_ini);
    }
    return rc_cfg ? rc_cfg : (rc_dat ? rc_dat : rc_ini);
}

static void espnow_liga(void) {
    if (g_espnow_pronto || !wireless_conectado()) {
        return;
    }
    if (esp_now_init() != ESP_OK) {
        return;
    }
    esp_now_peer_info_t p = {0};
    memcpy(p.peer_addr, BROADCAST, 6);
    p.channel = 0;               // 0 = canal ATUAL, que e o do AP. Fixar canal aqui
    p.ifidx = WIFI_IF_STA;       // derrubaria a associacao (e as ancoras seguem o AP).
    p.encrypt = false;
    if (esp_now_add_peer(&p) == ESP_OK) {
        g_espnow_pronto = true;
    }
}

static void tarefa(void *arg) {
    uint8_t ad[AD_LEN];
    monta(ad);
    if (adv_liga(ad) == 0) {
        memcpy(g_ultimo, ad, AD_LEN);
    }
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000 / (g_adv_hz ? g_adv_hz : 1)));
        monta(ad);
        espnow_liga();
        if (g_espnow_pronto) {
            esp_now_send(BROADCAST, ad + 2, CARGA);   // sem o cabecalho AD do BLE
        }
        // Reconfigurar o anuncio custa parar/religar o advertiser e disputa radio
        // com o scan. So mexe quando a carga muda de verdade (modo, boot, knob).
        if (memcmp(g_ultimo, ad, AD_LEN) != 0) {
            printf("= malha reconfig modo=%d\n", ad[11]);
            ble_gap_ext_adv_stop(INST);
            if (adv_liga(ad) == 0) {
                memcpy(g_ultimo, ad, AD_LEN);
            }
        }
    }
}

void malha_set(uint8_t adv_hz, int8_t tx_power) {
    bool mudou = false;
    if (adv_hz && adv_hz != g_adv_hz) {
        g_adv_hz = adv_hz;
        mudou = true;
    }
    if (tx_power != g_tx_power) {
        g_tx_power = tx_power;
        mudou = true;
    }
    if (mudou) {
        memset(g_ultimo, 0, AD_LEN);   // forca a tarefa a reconfigurar no proximo ciclo
    }
}

void malha_start(uint8_t own_addr_type) {
    g_addr_type = own_addr_type;
    xTaskCreate(tarefa, "malha", 3072, NULL, 3, NULL);
}
