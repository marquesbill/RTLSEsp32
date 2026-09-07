idf_component_register(SRCS "main.c" "espnow_fases.c" "led.c" "wireless.c" "malha.c"
                       REQUIRES bt nvs_flash esp_wifi esp_event esp_netif driver)
# `driver` e nao `esp_driver_usb_serial_jtag`: main.c chama
# usb_serial_jtag_is_connected(). Ate a v5.2 essa API morava em `driver`; da v5.3
# em diante ela foi para o componente proprio, e `driver` virou o guarda-chuva que
# depende de todos os esp_driver_*. Pedir o nome novo compila na v5.4 e QUEBRA na
# v5.1.2 com "Failed to resolve component" — que foi exatamente o que a CI pegou
# e a minha maquina (v5.4) nao pegava. `driver` resolve nas duas pontas.
