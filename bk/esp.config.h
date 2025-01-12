#ifndef ESP_WIFI_SETTING_H
#define ESP_WIFI_SETTING_H

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>


#include "esp.config.h"
#include <LittleFS.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 2  // Přizpůsobte pin podle potřeby
#endif


class ESPConfig {

 public:
      ESPConfig(ConfigWifi_t *config,
                AsyncWebServer *server);

      void handleCss(AsyncWebServerRequest *request);
      void handleSetup(AsyncWebServerRequest *request);
      void handleData(AsyncWebServerRequest *request);
      void handleSaveData(AsyncWebServerRequest *request);
      void connect();

      uint16_t begin();

      bool apMode = false;

      ConfigWifi_t *_config;
      AsyncWebServer *_server;

 protected:
    void reconnect(AsyncWebServerRequest *request);
    void ap();
    

};

#endif
