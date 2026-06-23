#ifndef CONFIG_H
#define CONFIG_H

//#include "EEPROM.h"

//#define DEBUG 1

// WIFI_SSID, WIFI_PASSWORD, OTA_PASSWORD live in secrets.h (gitignored);
// see secrets.h.example for the template.
#include "secrets.h"

#define MQTT_BROKER "192.168.0.224"
#define MQTT_PORT 1883
#define MQTT_TOPIC "temperature/loznice"

// /sensorTemp endpoint on the smart-home web — same .222 every other
// sensor hits. nginx there proxies / through to the FastAPI app on .224.
#define SERVER_HOST "192.168.0.222"
#define SERVER_PORT 80

// How often to publish a fresh reading (ms). The node stays awake
// between samples so ArduinoOTA can answer flash requests at any time;
// deep sleep is gone because the node is AC-powered.
#define SAMPLE_INTERVAL_MS 20000


class Config_t {

public:
    String ssid = WIFI_SSID;
    String password = WIFI_PASSWORD;
    IPAddress ip;
    IPAddress dns;
    IPAddress gateway;
    IPAddress subnet;
    String hostname;
    uint8_t apMode;
    bool dhcp = false;
    bool ap = false;

    Config_t() :
        // .0.15 sits in the unused gap between sensor .14 and .16; pick a
        // new slot per board, the previously-baked .1.14 collided with the
        // "Roleta holky pravá" Tuya cover.
        ip(192, 168, 0, 15),
        dns(192, 168, 1, 1),
        gateway(192, 168, 1, 1),
        subnet(255, 255, 254, 0) {};

};


#endif
