#ifndef CONFIG_H
#define CONFIG_H

//#include "EEPROM.h"

//#define DEBUG 1

// WIFI_SSID, WIFI_PASSWORD, OTA_PASSWORD live in secrets.h (gitignored);
// see secrets.h.example for the template.
#include "secrets.h"

#define MQTT_BROKER "192.168.0.224"
#define MQTT_PORT 1883
#define MQTT_TOPIC "temperature/petr"

// /sensorTemp endpoint on the smart-home web — same .222 every other
// sensor hits. nginx there proxies / through to the FastAPI app on .224.
#define SERVER_HOST "192.168.0.222"
#define SERVER_PORT 80

// Two cadences now: display refreshes from a fresh BME read at
// DISPLAY_INTERVAL_MS so the hero number feels live, and the
// long-term publish (HTTP + MQTT) fires only at PUBLISH_INTERVAL_MS
// so we don't flood Influx / the broker. Both stand alone — the
// loop just ticks two timers in parallel.
#define DISPLAY_INTERVAL_MS  5000
#define PUBLISH_INTERVAL_MS 30000

// Legacy single-rate cadence kept for the DEEP_SLEEP path further
// down; battery mode wakes up, publishes once, OTA-waits and dives
// back to sleep at this interval.
#define SAMPLE_INTERVAL_MS 600000

// Set to 1 once the node moves back to battery; the loop will use
// ESP.deepSleep(SAMPLE_INTERVAL_MS) between samples instead of a
// delay() spin (needs GPIO16↔RST jumper).
// Currently 0 — board sits on the bench; we want it awake the whole
// time so OTA lands instantly and we can iterate without juggling
// flash buttons.
#define DEEP_SLEEP 0

// When DEEP_SLEEP=1, how long to keep ArduinoOTA listening after each
// publish before going back to sleep. Wider than ~10 s here just
// burns battery; tighter is harder to land an OTA invitation in.
#define OTA_WINDOW_MS 10000

// Sensor identifier sent in the GET ?id= parameter. We don't use
// ESP.getChipId() because two of our boards share the same chip ID
// (10178502, the obyvak / sklenik collision). Set this per board so
// each row in [HeatingSensors].sensorIds maps to exactly one device.
#define SENSOR_ID 10200555

// Calibration delta in °C applied to every BME280 read before we
// touch the OLED or publish. BME280 mounted right next to the ESP8266
// + regulator picks up 3-5 °C of self-heating; subtract it here per
// board after leaving the sensor next to a known-good thermometer
// for ~30 min and writing down the delta. Negative = sensor reads
// too high (the usual case).
#define TEMP_OFFSET_C (-3.9f)


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
        // .0.11 is the slot reserved for petr in
        // [HeatingSensors].hwIp (web/conf/config.ini) — matches the
        // SENSOR_ID 10200555 row in sensorIds. Each room has a fixed
        // slot here so we can pin who is who without a registration
        // dance.
        ip(192, 168, 0, 11),
        dns(192, 168, 1, 1),
        gateway(192, 168, 1, 1),
        subnet(255, 255, 254, 0) {};

};


#endif
