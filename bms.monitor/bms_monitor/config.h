// Non-secret config. Edit per module before flashing.

#pragma once

// Which pack this module is attached to. Tags every payload so the
// server can route into the right Influx series. The repo README
// suggests slot names (tesla / tesla_pair / samsung / samsung_e / lg)
// but plain "battery-N" is fine — Influx just uses it as the
// measurement suffix.
static const char* PACK_ID = "battery-2";

// Server endpoint that receives the POSTed JSON. nginx on .222 proxies
// / to the FastAPI smart-home app on .224:8001 — same path every other
// sensor uses.
static const char* SERVER_URL = "http://192.168.0.222/bms";

// How often to push a sample to the server.
static const unsigned long SEND_INTERVAL_MS = 30 * 1000UL;

// JK BMS broadcasts a status frame roughly once a second; we buffer
// the most recent one and ship it on the interval above.
static const unsigned long BMS_STALE_AFTER_MS = 5 * 1000UL;

// Software serial pins talking to the JK BMS GPS port.
//   D7 / GPIO13 = RX (BMS TX -> D1 RX)
//   D8 / GPIO15 = TX (D1 TX -> BMS RX, optional / unused for now)
static const uint8_t BMS_RX_PIN = 13;
static const uint8_t BMS_TX_PIN = 15;
static const uint32_t BMS_BAUD  = 115200;

// Set true to dump every BMS frame as hex to USB serial. Helpful when
// bringing up a new module; switch off in production to keep the
// serial quiet.
static const bool DEBUG_HEX_DUMP = false;

// Static network config. Picked from the unused gap on the /23 LAN
// after grepping the repo and pinging — bump the last octet for
// each additional BMS module. Subnet matches every other static-IP
// device on this network (255.255.254.0 covers 192.168.0.0/23).
static const IPAddress STATIC_IP(192, 168, 1, 22);
static const IPAddress GATEWAY  (192, 168, 1, 1);
static const IPAddress SUBNET   (255, 255, 254, 0);
static const IPAddress DNS1     (192, 168, 1, 1);

// How long ArduinoOTA stays reachable each loop iteration; the
// listener also runs while the parser is idle, so a flash invitation
// arriving at any time will land.
static const unsigned long OTA_KEEPALIVE_MS = 50;
