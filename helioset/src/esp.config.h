#ifndef ESP_WIFI_SETTING_H
#define ESP_WIFI_SETTING_H

#include "config.wifi.h"

#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 2  // Přizpůsobte pin podle potřeby
#endif


class ESPConfig {
public:
     ESPConfig(ConfigWifi_t *config, AsyncWebServer *server);
     void ap();
     void connect();
     void handleCss(AsyncWebServerRequest *request);
     void handleSetup(AsyncWebServerRequest *request);
     void handleData(AsyncWebServerRequest *request);
     void handleSaveData(AsyncWebServerRequest *request);
     uint16_t begin();
     bool apMode = false;

private:
     ConfigWifi_t *_config;
     AsyncWebServer *_server;

     void reconnect(AsyncWebServerRequest *request);
     
    

};

#endif
