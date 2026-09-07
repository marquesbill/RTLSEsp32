// LED de estado da ancora. A ancora vai ficar sem tela num canto da casa; o LED e
// o unico jeito de saber, de longe, se ela esta viva, varrendo e ouvindo.
//
//   azul escuro      inicializando (NimBLE ainda nao sincronizou)
//   verde            varrendo, recebendo e COM rede — tudo certo
//   azul             varrendo mas SEM rede: o dado esta sendo perdido
//   ambar            varrendo mas SEM pacote ha >2 s: antena/ambiente morto
//   vermelho         erro (scan nao iniciou, host reset) — terminal
//   ciano/magenta    fase 1/2 do experimento de coexistencia (espnow_fases.c)
//
// Luz CONTINUA, sem pulso: a atividade continua visivel pela
// transicao verde<->ambar — 2 s sem pacote e o LED muda de cor.
//
// A distincao azul-vs-ambar e de proposito: azul = problema de REDE, ambar =
// problema de RADIO. De longe, numa ancora no alto de um armario, e o unico
// diagnostico disponivel.
//
// Hardware: C3 SuperMini Plus tem um WS2812 no GPIO8 (placa vermelha com u.FL).
// GPIO8 e strapping pin (nao pode estar LOW no boot); o WS2812 nao puxa a linha,
// e o exemplo blink do IDF usa exatamente esse pino no devkit C3 — caminho provado.
// Brilho baixo de proposito: a 255 o WS2812 cega e esquenta.
//
// Concorrencia: led_pacote() vem da task do NimBLE e so incrementa um contador.
// Quem fala com o driver e SO a task do LED — nada de RMT em duas tasks.
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"
#include "led.h"

#define GPIO_LED     8
#define TICK_MS      250
#define SILENCIO_TICKS 8        // 8 x 250 ms = 2 s sem pacote -> ambar

static led_strip_handle_t strip;
static volatile uint32_t pacotes;
static volatile int fase;
static volatile bool erro;
static volatile int rede_ok = 1;   // sem transporte compilado, nao ha o que faltar

static void cor(uint8_t r, uint8_t g, uint8_t b) {
    led_strip_set_pixel(strip, 0, r, g, b);
    led_strip_refresh(strip);
}

static void tarefa(void *arg) {
    uint32_t visto = 0;
    int quietos = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(TICK_MS));
        if (erro) {
            cor(16, 0, 0);
            continue;
        }
        uint32_t agora = pacotes;
        if (agora != visto) {
            visto = agora;
            quietos = 0;
            if (fase == 1) {
                cor(0, 10, 10);             // ciano
            } else if (fase == 2) {
                cor(10, 0, 10);             // magenta
            } else if (!rede_ok) {
                cor(0, 0, 14);              // azul: varrendo, mas sem rede
            } else {
                cor(0, 12, 0);              // verde
            }
        } else if (++quietos >= SILENCIO_TICKS) {
            cor(12, 6, 0);                  // ambar fixo
        }
    }
}

void led_init(void) {
    led_strip_config_t sc = {
        .strip_gpio_num = GPIO_LED,
        .max_leds = 1,
        .led_model = LED_MODEL_WS2812,
    };
    led_strip_rmt_config_t rc = {
        .resolution_hz = 10 * 1000 * 1000,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&sc, &rc, &strip));
    cor(0, 0, 4);                           // azul escuro: inicializando
    xTaskCreate(tarefa, "led", 2048, NULL, 3, NULL);
}

void led_pacote(void) {
    pacotes++;
}

void led_fase(int f) {
    fase = f;
}

void led_erro(void) {
    erro = true;
}

void led_rede(int ok) {
    rede_ok = ok;
}
