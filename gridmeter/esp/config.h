// Non-secret config for the grid meter module. Edit before flashing.

#pragma once

#include <IPAddress.h>

// ---------------------------------------------------------------- network
// Static, like every other module here, so the dashboards and OTA can
// reach it without DHCP roulette. PICK A FREE ADDRESS before flashing:
// the house already has one collision on 192.168.0.17, where a bedroom
// module and the bathroom module were given the same address and only one
// of them is ever reachable.
static const IPAddress STATIC_IP(192, 168, 0, 30);
static const IPAddress GATEWAY  (192, 168, 0, 1);
static const IPAddress SUBNET   (255, 255, 255, 0);
static const IPAddress DNS1     (192, 168, 0, 1);

static const char* MQTT_BROKER = "192.168.0.224";
static const uint16_t MQTT_PORT = 1883;
static const char* MQTT_TOPIC   = "home/grid/meter/snapshot";
static const char* MQTT_CLIENT  = "gridmeter";

// 45 s keep-alive, as on the BMS modules: the tighter 15 s window was
// tripping broker-side timeouts on marginal Wi-Fi, and a distribution
// cabinet is not a good place for radio.
static const uint16_t MQTT_KEEPALIVE_S      = 45;
static const uint16_t MQTT_SOCKET_TIMEOUT_S = 8;

// Sentinel watchdog, same two stages as the BMS modules: kick the radio,
// then reboot. The board sits behind a cabinet door, so it has to recover
// without anyone opening it.
static const unsigned long MQTT_DEAD_SOFT_MS = 180UL * 1000UL;
static const unsigned long MQTT_DEAD_HARD_MS = 300UL * 1000UL;

// ------------------------------------------------------------------ rs485
// MAX485 breakout: RO -> RX, DI -> TX, DE and RE tied together -> DE_PIN.
//
// The module is a 5 V part. An ESP32 GPIO is not 5 V tolerant, so either
// power the breakout from 3V3 (out of spec for MAX485, reliable in
// practice at these baud rates and cable lengths) or put a divider on RO.
// Powering it from 5 V and wiring RO straight to the ESP kills the pin.
static const int RS485_RX_PIN = 16;
static const int RS485_TX_PIN = 17;
static const int RS485_DE_PIN = 4;

// Meter link. The KLEFR 6914 is a rebadged Inepro PRO1-Mod and leaves the
// factory at 9600 8E1, address 1 — even parity, which is why it stays
// silent for anyone who starts at 8N1. If the settings here are wrong the
// firmware sweeps for the right ones at boot and reports what it found,
// rather than sitting there publishing nothing.
static const uint8_t  METER_ADDRESS = 1;
static const uint32_t METER_BAUD    = 9600;
static const uint32_t METER_CONFIG  = SERIAL_8E1;
static const bool     METER_AUTODETECT = true;

static const unsigned long POLL_INTERVAL_MS = 2000;
// How often to re-run the link sweep when the meter is not answering. The
// sweep blocks for several seconds, so it must not run every poll.
static const unsigned long RELINK_INTERVAL_MS = 60UL * 1000UL;
static const unsigned long MODBUS_TIMEOUT_MS = 300;

// Registers, as Inepro document them — in hex, which is where most of the
// confusion about this meter comes from. Confirm them with
// gridmeter/probe.py against the real unit before trusting any value
// other than voltage and total energy; the rest of the map is the PRO1
// family convention rather than something read off this meter.
//
// Every one is a 32-bit float across two registers. The word order is NOT
// configured here: the firmware works it out at boot by checking which
// order makes the voltage register land near mains, which is the one
// question the meter can answer about itself.
struct MeterRegister {
    uint16_t    address;
    const char* field;      // JSON key in the published snapshot
    float       scale;      // to volts / amps / watts / Wh
};

static const MeterRegister METER_REGISTERS[] = {
    { 0x5000, "voltage_v",   1.0f    },
    { 0x500C, "current_a",   1.0f    },
    { 0x5012, "power_w",     1000.0f },   // meter reports kW
    { 0x502A, "power_factor", 1.0f   },
    { 0x5034, "freq_hz",     1.0f    },
    { 0x6000, "energy_wh",   1000.0f },   // meter reports kWh
    { 0x600C, "import_wh",   1000.0f },
    { 0x6018, "export_wh",   1000.0f },
};
static const size_t METER_REGISTER_COUNT =
    sizeof(METER_REGISTERS) / sizeof(METER_REGISTERS[0]);
