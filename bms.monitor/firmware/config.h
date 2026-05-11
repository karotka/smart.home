// Non-secret config. Edit per module before flashing.

#pragma once

// Which pack this module is attached to. Tags every payload so the
// server can route into the right Influx series. Must match one of
// the IDs in the top-level README (tesla / tesla_pair / samsung /
// samsung_e / lg).
static const char* PACK_ID = "tesla";

// Server endpoint that receives the POSTed JSON. Tornado handler
// in web/ will live at /bms once we get to the server phase.
static const char* SERVER_URL = "http://192.168.0.222:8000/bms";

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
static const bool DEBUG_HEX_DUMP = true;
