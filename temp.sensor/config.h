#ifndef CONFIG_H
#define CONFIG_H

// Config_t below uses String / IPAddress / uint8_t. The Arduino build
// prepends Arduino.h to the .ino so this used to come for free, but
// config.h is now included first (it decides HAS_OLED before the u8g2
// include) — so pull it in here and stop depending on include order.
#include <Arduino.h>
// IPAddress is not in Arduino.h on ESP8266 — it used to arrive via
// ESP8266WiFi.h because config.h was included after it.
#include <IPAddress.h>

//#include "EEPROM.h"

//#define DEBUG 1

// WIFI_SSID, WIFI_PASSWORD, OTA_PASSWORD live in secrets.h (gitignored);
// see secrets.h.example for the template.
#include "secrets.h"

#define MQTT_BROKER "192.168.0.224"
#define MQTT_PORT 1883
#define MQTT_TOPIC "temperature/petr"

// /sensorTemp endpoint on the smart-home web. The older sensors have
// 192.168.0.222 baked in from the Pi4 era and .224 answers for them by
// holding that address as an alias (servers.conf/sensor-ip.service) —
// but there is no reason for a fresh flash to depend on that shim, so
// point it straight at .224.
//
// Port 8000 rather than 80: that is the dedicated `sensor-ingest`
// vhost, which has no basic auth at all. Port 80 only works because
// LAN clients are exempted from auth there, and that exemption is a
// thing that could reasonably change one day.
#define SERVER_HOST "192.168.0.224"
#define SERVER_PORT 8000

// Set to 0 on boards built without the I2C OLED. Drops the u8g2
// include, the 1 KB framebuffer and the render path; renderOled()
// becomes an empty inline so the rest of the sketch is identical
// between the two variants.
#define HAS_OLED 0

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
// 0 for this board: it is a fresh one and carries no OLED, so neither
// the old -3.9 (measured on the panel board for petr) nor any other
// figure applies. Leave it at zero, let it run a few hours next to a
// known-good thermometer, and set the delta you actually see.
#define TEMP_OFFSET_C (0.0f)


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
