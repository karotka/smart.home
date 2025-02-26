#ifndef ESP_WIFI_SETTING_H
#define ESP_WIFI_SETTING_H

#include <Arduino.h>
//#if defined(__AVR__)
//	#include "Arduino.h"
//#elif defined(__PIC32MX__)
//	#include "WProgram.h"
//#elif defined(__arm__)
//	#include "Arduino.h"
//#endif

#include "config.wifi.h"
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <LittleFS.h>

class ESPConfig {

 public:
      ESPConfig(ConfigWifi_t *config,
                   ESP8266WebServer *server);

      void handleCss();
      void handleSetup();
      void handleData();
      void handleSaveData();
      void connect();

      uint16_t begin();

      bool apMode = false;

      ConfigWifi_t *_config;

 protected:
    void reconnect();
    void ap();
    
    ESP8266WebServer *_server;
};

#endif
