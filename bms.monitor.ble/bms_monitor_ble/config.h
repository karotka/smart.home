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

// Every pack goes over BLE. UART only works on battery-2 today,
// battery-1's UART port doesn't respond, and the newer PCB rev on
// battery-3/4/5 doesn't expose one at all. The D32 is the only
// realistic path to all five, so we cover all five here and
// time-slice.
//
// The ESP32 BLE stack refuses more than ~3 concurrent central
// connections in practice (anything above returns connect() =
// false silently) even with NimBLE's CONFIG_BT_NIMBLE_MAX_CONNECTIONS
// nominally raised. To cover 5 packs we rotate: hold 3 at once,
// evict the oldest every BLE_ROTATE_MS, let the scan CB pick up
// whoever advertises next. That gives each pack fresh data ~every
// ROTATE * 2 seconds — plenty for a monitor role.
static const size_t PACK_COUNT = 5;
struct PackConfig {
    const char *pack_id;
    const char *mac;
    const char *advName;   // fallback match against advertised device name
};
static const PackConfig PACKS[PACK_COUNT] = {
    { "battery-1", "c8:47:8c:e8:24:7e", "Battery 1" },
    { "battery-2", "28:d4:1e:6a:ef:21", "Battery 2" },
    { "battery-3", "c8:47:80:03:51:55", "Battery 3" },
    { "battery-4", "c8:47:8c:e9:1c:da", "Battery 4" },
    { "battery-5", "c8:47:80:1d:c2:ea", "Battery 5" },
};

// Max simultaneous BLE central connections we'll hold open.
// Anything > 3 is unreliable on the D32 (see rotate comment above).
static const size_t BLE_MAX_ACTIVE = 3;

// How long a pack keeps a live connection before we evict it to
// make room for another. Combined with ~4 packs cycling through 3
// slots, every pack sees ~2× ROTATE seconds between fresh reads —
// good enough for a monitor cadence.
static const unsigned long BLE_ROTATE_MS = 30UL * 1000UL;

// Set true to hex-dump every reassembled JK frame to Serial.
// Useful when a new BMS firmware ships new offsets and we need to
// re-pin the parser; keep off in steady state.
static const bool DEBUG_HEX_DUMP = false;

// How long a decoded snapshot is considered "fresh" — the MQTT
// publish clears the valid flag if we haven't seen a new frame in
// this long, so the dashboard's per-card age badge trips clearly.
static const unsigned long BMS_STALE_AFTER_MS = 10UL * 1000UL;
