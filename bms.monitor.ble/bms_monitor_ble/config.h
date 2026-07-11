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

// This D32 covers battery-1, battery-3, battery-4 — the three packs
// whose PCB rev either has no UART on the GPS port or where the UART
// path proved unreliable. battery-2 stays on its ESP8266 UART monitor
// (it works). battery-5 moves onto a second D32 running this same
// firmware (or joins this one once we're happy with the 3-pack link).
// 3 packs is the ESP32 BLE central sweet-spot: NimBLE's 3-slot ceiling
// holds and rotation stays off (see the rotation gate in the .ino —
// it only fires when a fourth pack is actually waiting for a slot).
static const size_t PACK_COUNT = 3;
struct PackConfig {
    const char *pack_id;
    const char *mac;      // starting MAC; scan CB updates if the BMS
                          // rotates it after a reset (name-fallback)
    const char *advName;  // advertised device name (case-sensitive)
};
static const PackConfig PACKS[PACK_COUNT] = {
    // battery-1: JK FW V10.09 — MAC not yet observed; leave the placeholder
    // and let the name-fallback scan lock it in on first advert.
    { "battery-1", "00:00:00:00:00:00", "Battery 1" },
    { "battery-3", "c8:47:80:03:51:55", "Battery 3" },
    { "battery-4", "c8:47:8c:e9:1c:da", "Battery 4" },
};

// Cap on concurrent BLE connections. Set equal to PACK_COUNT so the
// rotation gate stays dormant in normal steady state; the eviction
// branch only fires if a fourth pack ever gets added and starts
// waiting for a slot.
static const size_t BLE_MAX_ACTIVE = 3;
static const unsigned long BLE_ROTATE_MS = 60UL * 1000UL;

// Set true to hex-dump every reassembled JK frame to Serial.
// Useful when a new BMS firmware ships new offsets and we need to
// re-pin the parser; keep off in steady state.
static const bool DEBUG_HEX_DUMP = false;

// How long a decoded snapshot is considered "fresh" — the MQTT
// publish clears the valid flag if we haven't seen a new frame in
// this long. On the BLE path a fragmented cell-info frame across a
// -70 dBm link arrives with 10–20 s cadence in the worst case, so
// a 10 s window flips the tile to "stale" during entirely normal
// operation. 30 s tolerates one dropped poll cycle and still catches
// a real dead link within the 60 s stall-watchdog window.
static const unsigned long BMS_STALE_AFTER_MS = 30UL * 1000UL;
