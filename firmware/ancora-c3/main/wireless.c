// Transporte wireless da ancora: WiFi STA -> UDP broadcast para o host.
//
// Por que broadcast e nao IP fixo nem mDNS: IP fixo ja quebrou duas vezes neste
// parque com troca de DHCP, e mDNS e um protocolo inteiro para resolver algo que
// o broadcast resolve sem descoberta nenhuma. O host so escuta a porta. Custo:
// ~1,7 kB/s por ancora numa LAN domestica.
//
// Por que WiFi/UDP e nao ESP-NOW: ESP-NOW nao chega ao servidor sem uma placa
// gateway no USB dele, e nao ha placa sobrando (todas vao para tomada). Medido
// antes: so LIGAR o radio WiFi ja custa -38% dos avistamentos BLE, e transmitir
// em cima disso nao custa nada mensuravel — entao o gateway economizaria pouco
// e custaria uma placa e um protocolo.
//
// Identidade: cada pacote leva o MAC da STA, que no C3 e o MAC base — o MESMO
// que aparece no numero de serie USB e em ancoras.txt. Assim as N placas rodam
// um firmware IDENTICO, sem numero gravado em lugar nenhum (a regra "ancoras
// identicas" do projeto vale para o firmware tambem).
//
// O tempo autoritativo e o do HOST, no momento em que o pacote chega. Nao se
// tenta sincronizar relogio entre ancoras: foi exatamente isso que quebrou no
// ruview (offsets de ate 825 s). O contador de ms da placa vai junto so para
// medir jitter de transporte, nunca para datar avistamento.
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "lwip/sockets.h"
#include "credenciais.h"
#include "malha.h"
#include "led.h"
#include "wireless.h"

// Mede o custo REAL do transporte: alterna 120 s com WiFi conectado e 120 s com
// o radio WiFi parado, dentro da MESMA captura. Comparar capturas de horas
// diferentes mediria o ambiente — as 03:00 ha muito menos BLE no ar que as 21:00.
// Com 1, o firmware nao serve para producao (fica metade do tempo sem rede).
#define MEDIR_WIFI 0
// 0=parado 1=conectado sem power save 2=conectado com power save
#define MODO_PS   WIFI_PS_MAX_MODEM

#define PORTA        5007
#define PORTA_FAROL  5008          // o host se anuncia aqui; ver tarefa_farol
#define FAROL_VALE_MS 30000        // sem farol por isso, volta a broadcast
#define MTU          1200          // folga confortavel sob o MTU de 1500
// magica(4) mac(6) seq(4) n(2) perdidos(4) heap(4) rssi_ap(1) canal(1) boot(2) modo(1) versao(1)
#define CAB          30
#define VERSAO       1             // byte 29: receptor antigo ve versao errada em vez
#define MAGICA       0x52544c53    // "RTLS"   de contar tudo como "ruins" calado
#define ENVIO_MS     1000          // E1: era 250. Ver a fila abaixo.
// A 1000 ms um buffer unico de 1200 B enche em ~0,7 s com 45 avist/s e o resto ia
// para o lixo. Fila de 4: quem enche vira PRONTO e o flush despacha todos em rajada.
#define NBUF         4
enum { LIVRE = 0, ENCHENDO, PRONTO };

static uint8_t bufs[NBUF][MTU];
static size_t ns[NBUF];
static uint16_t regs_[NBUF];
static uint8_t estado[NBUF];
static int atual = -1;
static uint32_t seq;
static uint16_t envio_ms = ENVIO_MS;
static uint8_t backoff_max_s;
static int sock = -1;
static SemaphoreHandle_t mtx;
static struct sockaddr_in destino;
static volatile bool conectado;
static volatile int64_t farol_em;      // ultimo farol ouvido (us)
static const uint16_t BACKOFF_S[4] = {5, 15, 30, 60};
static volatile int tent;
static volatile int64_t religa_em;     // us; 0 = nada pendente


// Estatistica que a propria ancora reporta — e assim que medimos o custo do
// WiFi sem precisar de cabo: o contador conta TUDO que o BLE viu, inclusive o
// que foi descartado por falta de rede.
static volatile uint32_t vistos, enviados, perdidos;

void wireless_stats(uint32_t *v, uint32_t *e, uint32_t *p) {
    *v = vistos; *e = enviados; *p = perdidos;
}

bool wireless_conectado(void) {
    return conectado;
}

uint8_t wireless_modo(void) {
    return !conectado ? 0 : (farol_em ? 2 : 1);
}

// Fecha o cabecalho do buffer i e marca para despacho. Sempre com o mutex tomado.
static void finaliza(int i) {
    uint8_t *b = bufs[i];
    uint32_t m = MAGICA;
    memcpy(b, &m, 4);
    esp_read_mac(b + 4, ESP_MAC_WIFI_STA);
    memcpy(b + 10, &seq, 4);
    memcpy(b + 14, &regs_[i], 2);
    // Telemetria que so existe aqui: sem cabo, e o unico jeito de saber se a
    // ancora descarta por dentro ou vaza memoria ao longo de dias.
    uint32_t p = perdidos;
    uint32_t h = (uint32_t)heap_caps_get_free_size(MALLOC_CAP_DEFAULT);
    memcpy(b + 16, &p, 4);
    memcpy(b + 20, &h, 4);
    int rssi = 0;                       // so vale conectado; senao fica 0
    esp_wifi_sta_get_rssi(&rssi);
    b[24] = (int8_t)rssi;
    uint8_t ch = 0;
    wifi_second_chan_t sec;
    esp_wifi_get_channel(&ch, &sec);    // ch1 cobre BLE 37, ch6 cobre 38
    b[25] = ch;
    uint16_t bt = malha_boot();
    memcpy(b + 26, &bt, 2);
    b[28] = wireless_modo();
    b[29] = VERSAO;
    seq++;
    estado[i] = PRONTO;
}

// Escolhe o proximo buffer livre. false = os 4 estao cheios (rede parada ha ~4 s).
static bool abre(void) {
    for (int i = 0; i < NBUF; i++) {
        if (estado[i] == LIVRE) {
            ns[i] = CAB; regs_[i] = 0; estado[i] = ENCHENDO; atual = i;
            return true;
        }
    }
    atual = -1;
    return false;
}

// O sendto NAO pode acontecer com o mutex tomado: ele leva milissegundos e o
// callback do NimBLE, que so tenta o mutex sem esperar, desistia e descartava.
// Medido assim: ~100 descartes internos por minuto em ~1400 avistamentos (7%).
// Um buffer PRONTO nunca e escrito pelo publica, entao da para le-lo sem o mutex.
static void despacha(void) {
    int fila[NBUF], k = 0;
    if (xSemaphoreTake(mtx, pdMS_TO_TICKS(50)) != pdTRUE) {
        return;
    }
    if (atual >= 0 && regs_[atual]) {
        finaliza(atual);
        abre();
    }
    for (int i = 0; i < NBUF; i++) {
        if (estado[i] == PRONTO) {
            fila[k++] = i;
        }
    }
    xSemaphoreGive(mtx);
    for (int j = 0; j < k; j++) {
        int i = fila[j];
        if (sock >= 0 && conectado
            && sendto(sock, bufs[i], ns[i], 0, (struct sockaddr *)&destino, sizeof(destino)) > 0) {
            enviados += regs_[i];
        } else {
            perdidos += regs_[i];
        }
        xSemaphoreTake(mtx, portMAX_DELAY);
        estado[i] = LIVRE;
        xSemaphoreGive(mtx);
    }
    if (atual < 0) {
        xSemaphoreTake(mtx, portMAX_DELAY);
        abre();
        xSemaphoreGive(mtx);
    }
}

// Chamado da task do NimBLE a cada avistamento. Nunca bloqueia por rede:
// o sendto e nao-bloqueante e um datagrama perdido e so um avistamento perdido.
void wireless_publica(const uint8_t *addr, int8_t rssi, uint8_t props,
                      uint8_t tipo_addr, const uint8_t *dados, uint8_t len) {
    vistos++;
    if (!mtx) {
        return;
    }
    if (len > 62) {
        len = 62;
    }
    size_t prec = 10 + len;
    if (xSemaphoreTake(mtx, 0) != pdTRUE) {
        perdidos++;              // outra task despachando; nao espera
        return;
    }
    if (atual < 0 || ns[atual] + prec > MTU) {
        if (atual >= 0) {
            finaliza(atual);     // cheio: fecha e pega o proximo, em vez de descartar
        }
        if (!abre()) {           // os 4 cheios = ~4 s sem rede; ai sim descarta
            perdidos++;
            xSemaphoreGive(mtx);
            return;
        }
    }
    uint8_t *b = bufs[atual];
    size_t n = ns[atual];
    b[n++] = len;
    memcpy(b + n, addr, 6); n += 6;
    b[n++] = (uint8_t)rssi;
    b[n++] = props;
    b[n++] = tipo_addr;
    memcpy(b + n, dados, len); n += len;
    ns[atual] = n;
    regs_[atual]++;
    xSemaphoreGive(mtx);
}

// Broadcast em WiFi nao e ACKed nem retransmitido pelo MAC, e sai na taxa basica
// mais baixa: com 4 ancoras transmitindo medimos ~7% de perda (contra 1,2% com
// uma so). Unicast e ACKed e retransmitido. Para nao voltar a IP fixo, o HOST se
// anuncia num farol periodico e a ancora aprende o endereco dele; se o farol
// sumir por 30 s, volta a broadcast e o sistema continua funcionando pior, nunca
// parado.
// [0..1] envio_ms  [2] adv_hz  [3] adv_tx_power  [4] listen_interval  [5] backoff_max_s
// Zero em qualquer campo = nao mexe. Assim o farol de 4 bytes continua valendo e o
// rollback de qualquer knob e mandar zero — nenhuma fase de teste exige reflash.
static void aplica_params(const uint8_t *p) {
    uint16_t e = (uint16_t)p[0] | ((uint16_t)p[1] << 8);
    if (e >= 50 && e <= 10000) {
        envio_ms = e;
    }
    malha_set(p[2], (int8_t)p[3]);
    if (p[4]) {
        wifi_config_t wc;
        if (esp_wifi_get_config(WIFI_IF_STA, &wc) == ESP_OK) {
            wc.sta.listen_interval = p[4];    // vale na proxima associacao
            esp_wifi_set_config(WIFI_IF_STA, &wc);
        }
    }
    if (p[5]) {
        backoff_max_s = p[5];
    }
}

static void tarefa_farol(void *arg) {
    int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct sockaddr_in meu = {.sin_family = AF_INET, .sin_port = htons(PORTA_FAROL),
                              .sin_addr.s_addr = htonl(INADDR_ANY)};
    bind(s, (struct sockaddr *)&meu, sizeof(meu));
    struct timeval tv = {.tv_sec = 5, .tv_usec = 0};
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    for (;;) {
        uint8_t b[32];
        struct sockaddr_in de;
        socklen_t dl = sizeof(de);
        int r = recvfrom(s, b, sizeof(b), 0, (struct sockaddr *)&de, &dl);
        int64_t agora = esp_timer_get_time();
        if (r >= 4 && memcmp(b, "RTLS", 4) == 0) {
            destino.sin_addr = de.sin_addr;        // passa a unicast
            farol_em = agora;
            if (r >= 10) {
                aplica_params(b + 4);
            }
        } else if (farol_em && agora - farol_em > (int64_t)FAROL_VALE_MS * 1000) {
            destino.sin_addr.s_addr = htonl(INADDR_BROADCAST);
            farol_em = 0;
        }
    }
}

// Segura a latencia quando o trafego BLE e baixo: sem isto um pacote meio cheio
// esperaria indefinidamente pelo proximo avistamento.
static void tarefa_flush(void *arg) {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(envio_ms));
        despacha();
        // A escada de reconexao mora aqui em vez de num timer proprio: esta task
        // ja acorda a cada segundo e a precisao exigida e de segundos.
        if (!conectado && religa_em && esp_timer_get_time() >= religa_em) {
            religa_em = 0;
            esp_wifi_connect();
        }
    }
}

static void ev(void *arg, esp_event_base_t base, int32_t id, void *dados) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        conectado = false;
        led_rede(false);
        // Antes: esp_wifi_connect() aqui mesmo, em laco. Com o AP fora do ar isso
        // vira uma tentativa continua que come radio do BLE — que e o trabalho que
        // a ancora ainda CONSEGUE fazer sem rede. Escada 5/15/30/60 s.
        uint16_t esp = BACKOFF_S[tent < 4 ? tent : 3];
        if (backoff_max_s && esp > backoff_max_s) {
            esp = backoff_max_s;
        }
        if (tent < 4) {
            tent++;
        }
        religa_em = esp_timer_get_time() + (int64_t)esp * 1000000;
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        conectado = true;
        led_rede(true);
        tent = 0;
        religa_em = 0;
    }
}

#if MEDIR_WIFI
static void tarefa_fases_wifi(void *arg) {
    int f = 1;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(120000));
        f = (f + 1) % 3;
        if (f == 0) {
            esp_wifi_stop();
            conectado = false;
            led_rede(0);
        } else {
            if (f == 1) {
                esp_wifi_start();
            }
            esp_wifi_set_ps(f == 1 ? WIFI_PS_NONE : WIFI_PS_MAX_MODEM);
        }
        printf("= fase %d\n", f);   // 0 parado · 1 conectado s/ PS · 2 com PS
    }
}
#endif

void wireless_start(void) {
    mtx = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, ev, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, ev, NULL, NULL));
    wifi_config_t wc = {0};
    strncpy((char *)wc.sta.ssid, WIFI_SSID, sizeof(wc.sta.ssid) - 1);
    strncpy((char *)wc.sta.password, WIFI_SENHA, sizeof(wc.sta.password) - 1);
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    // Power save MAX_MODEM: o radio WiFi dorme entre beacons DTIM e devolve
    // tempo de antena ao BLE. Adia RECEPCAO — e a ancora so TRANSMITE, entao
    // nao ha o que atrasar. (PS_NONE, o default anterior, era um erro meu:
    // "nao perder pacote nosso" nao se aplica a quem nunca recebe.)
    ESP_ERROR_CHECK(esp_wifi_set_ps(MODO_PS));
    ESP_ERROR_CHECK(esp_wifi_start());

    sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    int um = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &um, sizeof(um));
    struct timeval tv = {.tv_sec = 0, .tv_usec = 50000};
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    destino.sin_family = AF_INET;
    destino.sin_port = htons(PORTA);
    destino.sin_addr.s_addr = htonl(INADDR_BROADCAST);

    abre();                            // primeiro buffer
    xTaskCreate(tarefa_flush, "flush", 3072, NULL, 4, NULL);
    xTaskCreate(tarefa_farol, "farol", 3072, NULL, 3, NULL);
#if MEDIR_WIFI
    printf("= fase 1\n");
    xTaskCreate(tarefa_fases_wifi, "fasewifi", 3072, NULL, 3, NULL);
#endif
}
