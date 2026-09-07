// Mede quanto o ESP-NOW custa ao trabalho principal da ancora: escutar BLE.
//
// O C3 tem UM radio 2.4 GHz. WiFi e BLE nao rodam juntos, se revezam: a doc do IDF
// (api-guides/coexist.rst) diz que no esquema WiFi CONNECTED + BLE cada um fica com
// 50% do periodo de coexistencia. Se isso valer aqui, por o ESP-NOW na ancora custa
// metade dos avistamentos — e a ancora existe para avistar.
//
// Em vez de tres firmwares, um so que ALTERNA as fases dentro da mesma captura. O
// trafego BLE varia muito de minuto a minuto (gente chegando, telefone acordando);
// comparar capturas feitas em horas diferentes mediria o ambiente, nao o radio.
// Ciclando as fases, cada uma pega um pedaco do mesmo ambiente.
//
// Fases, 120 s cada, em ciclo:
//   0 BLE puro           — WiFi parado (linha de base)
//   1 BLE + WiFi ligado  — STA sem AP, ESP-NOW pronto, sem trafego
//   2 BLE + ESP-NOW      — cada avistamento vai para o ar em lotes de ~200 B
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_now.h"
#include "esp_err.h"
#include "esp_mac.h"
#include "led.h"

#define FASE_SEG   120
#define CANAL      1
#define LOTE_MAX   200          // ESP-NOW v1 aceita 250 B; deixamos folga

static volatile int g_fase = 0;
static uint8_t lote[LOTE_MAX];
static size_t lote_n = 0;
static bool wifi_no_ar = false;
static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

int espnow_fase(void) {
    return g_fase;
}

// Chamado pelo on_gap a cada avistamento. So faz algo na fase 2.
void espnow_publica(const uint8_t *addr, int8_t rssi, uint8_t props) {
    if (g_fase != 2 || !wifi_no_ar) {
        return;
    }
    if (lote_n + 8 > LOTE_MAX) {
        esp_now_send(BROADCAST, lote, lote_n);
        lote_n = 0;
    }
    memcpy(lote + lote_n, addr, 6);
    lote[lote_n + 6] = (uint8_t)rssi;
    lote[lote_n + 7] = props;
    lote_n += 8;
}

static void wifi_liga(void) {
    if (wifi_no_ar) {
        return;
    }
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    // Sem AP: a ancora nao precisa de rede para falar ESP-NOW. Canal fixo porque
    // peers so se ouvem no MESMO canal (esp_now.rst); um AP obrigaria todas as
    // ancoras ao canal DELE, e o estado CONNECTED custa mais radio ainda.
    ESP_ERROR_CHECK(esp_wifi_set_channel(CANAL, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_now_init());
    esp_now_peer_info_t p = {0};
    memcpy(p.peer_addr, BROADCAST, 6);
    p.channel = CANAL;
    p.ifidx = WIFI_IF_STA;
    p.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&p));
    wifi_no_ar = true;
}

static void wifi_desliga(void) {
    if (!wifi_no_ar) {
        return;
    }
    esp_now_deinit();
    esp_wifi_stop();
    esp_wifi_deinit();
    wifi_no_ar = false;
    lote_n = 0;
}

static void tarefa_fases(void *arg) {
    // wireless.c tambem cria o loop; se o experimento for religado junto do
    // transporte, o segundo create devolve INVALID_STATE e nao e erro.
    esp_err_t e = esp_event_loop_create_default();
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
        ESP_ERROR_CHECK(e);
    }
    for (;;) {
        for (int f = 0; f < 3; f++) {
            if (f == 0) {
                wifi_desliga();
            } else {
                wifi_liga();
            }
            g_fase = f;
            led_fase(f);
            // marcador na mesma serial do fluxo @b: o analisador fatia por ele
            printf("= fase %d\n", f);
            vTaskDelay(pdMS_TO_TICKS(FASE_SEG * 1000));
        }
    }
}

void espnow_fases_start(void) {
    xTaskCreate(tarefa_fases, "fases", 4096, NULL, 5, NULL);
}
