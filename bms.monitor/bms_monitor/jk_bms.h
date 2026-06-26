// JK BMS frame decoder for the JK02 protocol used by the BD6A24S10P
// "Active Balance" series. The BMS broadcasts a complete status frame
// over its GPS-port UART roughly once per second; this decoder
// recognises the header, validates the CRC and pulls the fields we
// care about.
//
// Listening-only — never sends commands back to the BMS.

#pragma once

#include <Arduino.h>

// Maximum cells the parser will return. JK BD6A24S10P supports 24S
// in hardware; our packs are 14S but we leave headroom.
static const uint8_t MAX_CELLS = 24;

// Maximum frame size we will buffer. The largest status frame on a
// 24S BMS is ~300 bytes; round up generously.
static const uint16_t JK_BUF_MAX = 512;

struct BmsData {
    bool valid;

    // 14S = 14 cells reported; cellCount tells the consumer how many
    // entries in cellMv[] are populated.
    uint8_t cellCount;
    uint16_t cellMv[MAX_CELLS];          // millivolts per cell

    // Computed in-decoder for convenience.
    uint16_t cellMinMv;
    uint16_t cellMaxMv;
    uint16_t cellAvgMv;
    uint16_t cellDeltaMv;                // max - min

    // Pack-level
    uint32_t totalMv;                    // total voltage in mV
    int32_t  currentMa;                  // signed: + charge, - discharge
    uint8_t  soc;                        // 0..100

    // Temperatures, deci-Celsius (e.g. 257 = 25.7 °C). Counts how many
    // sensors were reported in tempCount.
    uint8_t  tempCount;
    int16_t  tempDeciC[4];

    // Counters
    uint16_t cycleCount;
    uint32_t cycleCapacityMah;        // accumulated discharge in current cycle
    uint32_t remainCapacityMah;       // estimated mAh left in the pack
                                      // (= JK app's "Remain Capacity")

    // MOSFET state bits.
    bool chargeMosOn;
    bool dischargeMosOn;

    // Balance state — true if the BMS is actively balancing something.
    bool balancing;
};

// Feeds one byte from the UART into the running frame parser. Returns
// true when a complete, CRC-valid frame has been decoded — the caller
// can then read the latest values from getLast(). Internally maintains
// a state machine plus a single static buffer.
bool jkFeedByte(uint8_t b);

// Latest decoded payload. Always safe to read; the `valid` flag tells
// you whether anything's been decoded yet.
const BmsData& jkGetLast();

// Optional: dump the most recent raw frame as hex to a Stream (e.g.
// Serial). Useful when bringing up a new module to verify the wiring
// before trusting the decoder.
void jkDumpLastFrame(Print& out);

// Rolling capture of the last 1024 raw UART bytes the BMS sent us.
// Useful for reverse-engineering frame layouts over OTA without a
// physical serial cable — the firmware ships the hex string in the
// next POST so the server log captures it.
void jkRecentBytes(char* hexOut, size_t hexCap);
