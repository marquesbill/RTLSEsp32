// Sniffer de advertising BLE na ESP32-C3, com EXTENDED SCAN (BLE 5.0).
// Emite o MESMO formato do sniffer da CYD ("@b e a rssi bda payload"), para que
// um sniffer USB de advertising gravaria, e o host le sem mudanca nenhuma.
//
// Por que ESP-IDF e nao Arduino: as libs pre-compiladas do core Arduino para C3
// vem com CONFIG_BT_NIMBLE_EXT_ADV e EXT_SCAN DESLIGADOS, e a API de ext scan do
// wrapper BLE do Arduino so existe sob CONFIG_BLUEDROID_ENABLED (o C3 usa NimBLE).
// Sem este build, a C3 nao ve nada que a CYD (BLE 4.2) ja nao veja.
//
// O campo "e" carrega o props do relatorio estendido, entao o bit 0x10
// (BLE_HCI_ADV_LEGACY_MASK) diz se o anuncio era legacy ou estendido — e a medida
// que responde "quanto o BLE 5.0 acrescenta" a partir de UMA captura.
#include <stdio.h>
#include <string.h>
#include "nvs_flash.h"
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "led.h"
#include "wireless.h"
#include "malha.h"
#include "driver/usb_serial_jtag.h"

// Experimento de coexistencia: ver espnow_fases.c. Com 0, firmware de producao.
#define MEDIR_ESPNOW 0
#if MEDIR_ESPNOW
void espnow_fases_start(void);
void espnow_publica(const uint8_t *addr, int8_t rssi, uint8_t props);
int espnow_fase(void);
#endif

static uint8_t own_addr_type;
static const char HX[] = "0123456789abcdef";
static int on_gap(struct ble_gap_event *ev, void *arg);

static void start_scan(void) {
    struct ble_gap_ext_disc_params uncoded = {
        .itvl = 128,      // 80 ms em unidades de 0.625 ms — mesmo duty da CYD
        .window = 96,     // 60 ms
        .passive = 0,     // ativo: pega scan response, como a CYD
    };
    // ponytail: so PHY nao-codificado. Varrer coded PHY tambem divide o tempo de
    // escuta no 1M e estragaria a comparacao com a CYD; entra depois, se interessar.
    int rc = ble_gap_ext_disc(own_addr_type, 0 /*forever*/, 0 /*period*/,
                              0 /*filter_duplicates: queremos TODO pacote*/,
                              0 /*filter_policy*/, 0 /*limited*/,
                              &uncoded, NULL, on_gap, NULL);
    printf("= rtls-ancora ext scan rc=%d\n", rc);
    if (rc != 0) {
        led_erro();
    } else {
        led_fase(0);                    // verde: varrendo
    }
}

static int on_gap(struct ble_gap_event *ev, void *arg) {
    if (ev->type != BLE_GAP_EVENT_EXT_DISC) {
        return 0;
    }
    const struct ble_gap_ext_disc_desc *d = &ev->ext_disc;
    // Uma linha montada em buffer e escrita de uma vez: um printf por byte custa
    // caro no ritmo de milhares de anuncios por minuto.
    char line[600];
    int n = snprintf(line, sizeof(line), "@b %d %d %d ",
                     d->props, d->addr.type, d->rssi);
    // NimBLE guarda o endereco em little-endian; a CYD (Bluedroid) imprime big-endian.
    // Sem inverter aqui, os dois sniffers nunca concordariam sobre um mesmo aparelho.
    for (int i = 5; i >= 0; i--) {
        line[n++] = HX[d->addr.val[i] >> 4];
        line[n++] = HX[d->addr.val[i] & 0x0F];
    }
    line[n++] = ' ';
    int len = d->length_data;
    if (len > 251) {
        len = 251;
    }
    for (int i = 0; i < len; i++) {
        line[n++] = HX[d->data[i] >> 4];
        line[n++] = HX[d->data[i] & 0x0F];
    }
    line[n++] = '\n';
    // Em powerbank nao ha host lendo: escrever no CDC sem leitor bloqueia ate o
    // timeout e estrangularia a task do NimBLE. So imprime se alguem escuta.
    if (usb_serial_jtag_is_connected()) {
        fwrite(line, 1, n, stdout);
    }
    led_pacote();
    wireless_publica(d->addr.val, d->rssi, d->props, d->addr.type, d->data, len);
#if MEDIR_ESPNOW
    espnow_publica(d->addr.val, d->rssi, d->props);
#endif
    return 0;
}

static void on_sync(void) {
    int rc = ble_hs_util_ensure_addr(0);
    if (rc != 0) {
        printf("= erro ensure_addr rc=%d\n", rc);
        led_erro();
        return;
    }
    rc = ble_hs_id_infer_auto(0, &own_addr_type);
    if (rc != 0) {
        printf("= erro infer_addr rc=%d\n", rc);
        led_erro();
        return;
    }
    start_scan();
    malha_start(own_addr_type);
}

static void on_reset(int reason) {
    printf("= host reset, reason=%d\n", reason);
    led_erro();
}

static void host_task(void *param) {
    nimble_port_run();
    nimble_port_freertos_deinit();
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    led_init();                         // azul ate o host sincronizar
    led_rede(0);                        // ainda sem WiFi
    malha_boot();                       // le/incrementa o contador antes de qualquer uso
    // BLE ANTES do WiFi: o sensor nao espera a rede. Antes o wireless_start()
    // vinha primeiro e o scan so comecava depois da associacao (ou do timeout dela).
    ESP_ERROR_CHECK(nimble_port_init());
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.reset_cb = on_reset;
    nimble_port_freertos_init(host_task);
    wireless_start();
#if MEDIR_ESPNOW
    espnow_fases_start();
#endif
}
