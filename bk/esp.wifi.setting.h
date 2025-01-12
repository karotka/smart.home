#ifndef ESP_WIFI_SETTING_H
#define ESP_WIFI_SETTING_H

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>

//#if defined(__AVR__)
//	#include "Arduino.h"
//#elif defined(__PIC32MX__)
//	#include "WProgram.h"
//#elif defined(__arm__)
//	#include "Arduino.h"
//#endif

#include "config.wifi.h"
#include <LittleFS.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 2  // Přizpůsobte pin podle potřeby
#endif


class ESPWifiSetting {

 public:
      ESPWifiSetting(ConfigWifi_t *config,
                     AsyncWebServer *server);

      void handleCss(AsyncWebServerRequest *request);
      void handleSetup(AsyncWebServerRequest *request);
      void handleData(AsyncWebServerRequest *request);
      void handleSaveData(AsyncWebServerRequest *request);
      void connect();

      uint16_t begin();

      bool apMode = false;

      ConfigWifi_t *_config;

 protected:
    void reconnect();
    void ap();
    
    //AsyncWebServer *_server;
};

#endif
