// LED de estado da ancora (WS2812 no GPIO8 da C3 SuperMini Plus).
// Ver led.c para o significado de cada cor.
#pragma once
void led_init(void);        // azul: inicializando
void led_pacote(void);      // chamar a cada avistamento (qualquer task; so incrementa)
void led_fase(int fase);    // cor do pulso: 0 verde (producao), 1 ciano, 2 magenta
void led_erro(void);        // vermelho fixo; estado terminal
void led_rede(int ok);      // 0 = sem rede: pulso AZUL (dado sendo perdido)
