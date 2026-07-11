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

struct PackConfig {
    const char *pack_id;
    const char *mac;      // starting MAC; scan CB updates if the BMS
                          // rotates it after a reset (name-fallback)
    const char *advName;  // advertised device name (case-sensitive)
};

// The battery cabinet is split across multiple D32 boards to sidestep
// the JK BMS-side stall bug (a stuck V10 pack starves its neighbours
// on the same BLE central). Pick which board this build is for by
// passing -DVARIANT=SOLO_BAT4 (or leaving it unset for the main board).
//
//   Main D32 (VARIANT unset)  .1.23  battery-1 + battery-3
//   Solo D32 (SOLO_BAT4)      .1.24  battery-4 only
//
// battery-2 stays on its ESP8266 UART monitor. battery-5 joins later
// on its own D32 with the same firmware and a fresh VARIANT.
#define VARIANT_MAIN      1
#define VARIANT_SOLO_BAT4 2
#ifndef VARIANT
#  define VARIANT VARIANT_MAIN
#endif

#if VARIANT == VARIANT_SOLO_BAT4
    static const IPAddress STATIC_IP(192, 168, 1, 24);
    static const size_t PACK_COUNT = 1;
    static const PackConfig PACKS[PACK_COUNT] = {
        { "battery-4", "c8:47:8c:e9:1c:da", "Battery 4" },
    };
#else
    static const IPAddress STATIC_IP(192, 168, 1, 23);
    static const size_t PACK_COUNT = 2;
    static const PackConfig PACKS[PACK_COUNT] = {
        // battery-1: JK FW V10.09 — MAC placeholder; name-fallback locks
        // it in on the first advert.
        { "battery-1", "00:00:00:00:00:00", "Battery 1" },
        { "battery-3", "c8:47:80:03:51:55", "Battery 3" },
    };
#endif
static const IPAddress GATEWAY  (192, 168, 1, 1);
static const IPAddress SUBNET   (255, 255, 254, 0);
static const IPAddress DNS1     (192, 168, 1, 1);

// Cap on concurrent BLE connections. Set equal to PACK_COUNT so the
// rotation gate stays dormant in normal steady state.
static const size_t BLE_MAX_ACTIVE = PACK_COUNT;
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
