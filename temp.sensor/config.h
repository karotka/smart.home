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

// Time between publishes (ms). With DEEP_SLEEP=0 the node stays awake
// and just delays this many ms between samples while servicing
// ArduinoOTA — handy for live debugging when you're cycling RESET and
// want immediate feedback.
#define SAMPLE_INTERVAL_MS 600000

// Set to 1 once the node moves back to battery; the loop will use
// ESP.deepSleep(SAMPLE_INTERVAL_MS) between samples instead of a
// delay() spin (needs GPIO16↔RST jumper).
#define DEEP_SLEEP 1

// When DEEP_SLEEP=1, how long to keep ArduinoOTA listening after each
// publish before going back to sleep. Wider than ~10 s here just
// burns battery; tighter is harder to land an OTA invitation in.
#define OTA_WINDOW_MS 10000

// Sensor identifier sent in the GET ?id= parameter. We don't use
// ESP.getChipId() because two of our boards share the same chip ID
// (10178502, the obyvak / sklenik collision). Set this per board so
// each row in [HeatingSensors].sensorIds maps to exactly one device.
#define SENSOR_ID 10178599


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
