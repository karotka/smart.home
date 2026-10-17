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
// ──────────────────────────────────────────────────────────────────
// PER-BOARD SLOT. Three values move together and all three must match
// the same row of [HeatingSensors] in web/conf/config.ini — SENSOR_ID
// against sensorIds, the Config_t ip against hwIp, and the MQTT topic
// against the room name. Getting them out of step gives a node that
// publishes under one identity and is addressed as another.
//
//   room      SENSOR_ID    IP              manifold port
//   obyvak    10178502     192.168.0.12     1, 2
//   kacka     10243897     192.168.0.13     7
//   petr      10200555     192.168.0.11     8
//   koupelna  10246875     192.168.0.17     3
//   kluci     10204017     192.168.0.14     4
//   vchod     10200594     192.168.0.19     0
//   loznice   10178453     192.168.0.16     6
//   garaz     10040010     192.168.0.18     5     ← flashed now
//   sklenik   10178599     192.168.0.15     none (external)
// ──────────────────────────────────────────────────────────────────
#define MQTT_TOPIC "temperature/garaz"

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

// 1 = wake, measure, publish, hold a short OTA window, sleep again.
//
// Here the reason is thermal, not battery: staying awake runs the
// ESP8266 at ~70 mA continuously a few centimetres from the BME280,
// which is what forced the -3.9 °C offset on the panel board. Sleeping
// between samples means the chip is cold when it measures, so the
// reading needs little or no correction — which is why TEMP_OFFSET_C
// starts at 0 on this board.
//
// ⚠ NEEDS THE GPIO16↔RST JUMPER (D0–RST on a NodeMCU). Without it the
// board sleeps and never wakes.
//
// Note the consequence for flashing: once this is on, OTA only lands
// inside OTA_WINDOW_MS after each wake. Do firmware changes over USB,
// or catch the window.
#define DEEP_SLEEP 1

// When DEEP_SLEEP=1, how long to keep ArduinoOTA listening after each
// publish before going back to sleep.
//
// 30 s rather than the old 10: this node is mains-powered, so the
// window costs no battery, and it costs almost nothing thermally
// either — the measurement is taken at the top of the wake, before
// the chip has had time to warm, so whatever happens afterwards does
// not contaminate it. What it does buy is a realistic chance of
// landing an OTA push without power-cycling the board.
#define OTA_WINDOW_MS 30000

// Sensor identifier sent in the GET ?id= parameter. We don't use
// ESP.getChipId() because two of our boards share the same chip ID
// (10178502, the obyvak / sklenik collision). Set this per board so
// each row in [HeatingSensors].sensorIds maps to exactly one device.
#define SENSOR_ID 10040010

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
        // .0.18 is the slot reserved for garaz in
        // [HeatingSensors].hwIp (web/conf/config.ini) — matches the
        // SENSOR_ID 10040010 row in sensorIds. Each room has a fixed
        // slot here so we can pin who is who without a registration
        // dance.
        ip(192, 168, 0, 18),
        dns(192, 168, 1, 1),
        gateway(192, 168, 1, 1),
        subnet(255, 255, 254, 0) {};

};


#endif
