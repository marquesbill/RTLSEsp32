idf_component_register(SRCS "main.c" "espnow_fases.c" "led.c" "wireless.c" "malha.c"
                       REQUIRES bt nvs_flash esp_wifi esp_event esp_netif esp_driver_usb_serial_jtag)
