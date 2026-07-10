// bms.monitor.ble non-secret config.

#pragma once

#include <Arduino.h>

// MQTT broker (mosquitto on .224) — same topic tree as the ESP8266
// bms.monitor firmware so /battery.html sees these packs without
// any server-side changes: home/bms/<pack_id>/snapshot.
static const char* MQTT_BROKER = "192.168.0.224";
static const uint16_t MQTT_PORT = 1883;
static const unsigned long MQTT_PUBLISH_MS = 2000;

// Server HTTP endpoint for long-term storage (Influx). Same URL the
// ESP8266 monitor uses.
static const char* SERVER_URL = "http://192.168.0.222/bms";
static const unsigned long SEND_INTERVAL_MS = 30 * 1000UL;

// MQTT keep-alive + sentinel — sized to match the retuned ESP8266
// firmware. 45 s keep-alive tolerates one BLE-adjacent Wi-Fi
// retransmit; 180/300 s sentinel avoids false-positive reconnect
// storms on marginal RSSI.
static const uint16_t MQTT_KEEPALIVE_S       = 45;
static const uint16_t MQTT_SOCKET_TIMEOUT_S  = 8;
static const unsigned long MQTT_DEAD_SOFT_MS = 180UL * 1000UL;
static const unsigned long MQTT_DEAD_HARD_MS = 300UL * 1000UL;

// Static IP on the /23 LAN. .1.23 sits in the unused gap after the
// two ESP8266 monitors (.1.21 / .1.22).
static const IPAddress STATIC_IP(192, 168, 1, 23);
static const IPAddress GATEWAY  (192, 168, 1, 1);
static const IPAddress SUBNET   (255, 255, 254, 0);
static const IPAddress DNS1     (192, 168, 1, 1);

// The three JK BMSes we cover — MACs pinned from the scan-only
// bring-up build. Battery 1 and Battery 2 stay on the ESP8266
// GPS-UART firmware (their PCB rev exposes UART on the GPS port);
// only the newer PCB rev needs BLE.
static const size_t PACK_COUNT = 3;
struct PackConfig {
    const char *pack_id;
    const char *mac;
};
static const PackConfig PACKS[PACK_COUNT] = {
    { "battery-3", "c8:47:80:03:51:55" },
    { "battery-4", "c8:47:8c:e9:1c:da" },
    { "battery-5", "c8:47:80:1d:c2:ea" },
};

// Set true to hex-dump every reassembled JK frame to Serial.
// Useful when a new BMS firmware ships new offsets and we need to
// re-pin the parser; keep off in steady state.
static const bool DEBUG_HEX_DUMP = false;

// How long a decoded snapshot is considered "fresh" — the MQTT
// publish clears the valid flag if we haven't seen a new frame in
// this long, so the dashboard's per-card age badge trips clearly.
static const unsigned long BMS_STALE_AFTER_MS = 10UL * 1000UL;
