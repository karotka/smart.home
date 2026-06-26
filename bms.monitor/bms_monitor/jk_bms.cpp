// JK BMS LCD V2.0 protocol decoder (option 010 in the UART menu of the
// BD6A24S10P / Active-Balance BD series). Frames look like
//
//   A5 5A LEN CMD SUB1 SUB2 [data ...]
//
// LEN is the number of bytes after itself, big enough to cover cmd +
// sub-cmd + data + optional CRC. The BMS broadcasts a handful of
// frame types in rapid succession every ~1 s; this decoder only acts
// on the ones we've reverse-engineered so far. Unknown frames are
// accepted and dropped without complaint so the stream keeps flowing.
//
// Recognised so far:
//   cmd=0x82 sub=0x1100 — per-cell voltages, 24 × 2 bytes big-endian mV
//   cmd=0x82 sub=0x1000 — pack stats (total V, current, SOC, …) — partial,
//                         marked TODO below where the field meaning is
//                         still a guess.
//
// CRC is not validated yet; the dump suggests a simple summed checksum
// in the last 2 bytes but a few frames don't add up cleanly so we'd
// rather lose a CRC check than throw away usable data while we figure
// it out.

#include "jk_bms.h"

namespace {

enum ParserState : uint8_t {
    LOOK_SYNC0,
    LOOK_SYNC1,
    READ_LEN,
    READ_BODY,
};

ParserState  state    = LOOK_SYNC0;
uint16_t     bodyLen  = 0;          // bytes still to read after the length byte
uint16_t     bufPos   = 0;
uint8_t      buf[JK_BUF_MAX];

BmsData      lastData = {};

uint16_t be16(const uint8_t* p) { return (uint16_t)p[0] << 8 | p[1]; }
int16_t  bes16(const uint8_t* p) { return (int16_t)((uint16_t)p[0] << 8 | p[1]); }

// Decode the 0x82 0x11 0x00 frame: 24 cells of big-endian uint16 mV
// starting right after the sub-cmd.
//
//   A5 5A 3B 82 11 00  CELL1_hi CELL1_lo  CELL2_hi CELL2_lo  ...
void decodeCells(BmsData& out, const uint8_t* p, uint16_t len) {
    // p points at the byte after the length field, len = bodyLen.
    // p[0]=cmd, p[1..2]=sub-cmd, then 24 × 2 bytes cells.
    const uint8_t* cells = p + 3;
    uint32_t sumMv = 0;
    uint8_t  seen  = 0;
    uint16_t mn = 0xFFFF, mx = 0;

    for (uint8_t c = 0; c < MAX_CELLS; c++) {
        // Stop if we'd run past the frame body.
        if (3u + (uint16_t)c * 2u + 1u >= len) break;
        uint16_t mv = be16(cells + (uint16_t)c * 2u);
        out.cellMv[c] = mv;
        if (mv > 1000 && mv < 5000) {       // sane Li-ion / Lifepo4 range
            sumMv += mv;
            seen  += 1;
            if (mv < mn) mn = mv;
            if (mv > mx) mx = mv;
        }
    }

    // Reject obvious misframings before publishing them. SoftwareSerial
    // at 115200 baud drops a byte under interrupt pressure once in a
    // while and the parser will then sync on what looks like A5 5A in
    // the middle of a payload — typically yielding 1-3 "cells" of
    // garbage. Demanding at least MIN_GOOD_CELLS keeps such partial
    // reads from poisoning the Influx series.
    static const uint8_t MIN_GOOD_CELLS = 12;
    if (seen >= MIN_GOOD_CELLS) {
        out.cellCount   = seen;
        out.cellMinMv   = mn;
        out.cellMaxMv   = mx;
        out.cellAvgMv   = (uint16_t)(sumMv / seen);
        out.cellDeltaMv = mx - mn;
        // Total derived from the cells themselves — more reliable than
        // trying to parse the pack-stats frame for now.
        out.totalMv     = sumMv;
        out.valid       = true;
    }
}

// Decode the 0x82 0x10 0x00 frame: pack-wide stats. The reverse-
// engineering here is partial — field offsets are educated guesses
// from the bring-up dump:
//   bytes 0..1 of the data section: total V in 0.01 V steps (54.48 V → 0x1548)
//   bytes 12..13: signed current in 0.01 A steps
//   bytes 22..23: SOC % (single byte at low side)
// Anything we can't decode yet is left at zero and the cell-frame
// stats above are what the consumer sees.
void decodePackStats(BmsData& out, const uint8_t* p, uint16_t len) {
    if (len < 6) return;
    const uint8_t* d = p + 3;        // after cmd + 2-byte sub-cmd
    uint16_t dlen   = (uint16_t)(len - 3);

    if (dlen >= 2) {
        uint16_t total_cv = be16(d);          // hundredths of a volt
        // Only adopt if cells frame hasn't already filled it.
        if (out.totalMv == 0) out.totalMv = (uint32_t)total_cv * 10;
    }
    if (dlen >= 14) {
        out.currentMa = (int32_t)bes16(d + 12) * 10;
    }
    if (dlen >= 23) {
        out.soc = d[22];
    }
    // TODO: temps, cycle count, MOS state, balance bitmap. Need
    // another bring-up session with the BMS in known states (charging
    // vs discharging vs balancing) to pin these down.
}

}  // namespace

bool jkFeedByte(uint8_t b) {
    switch (state) {
        case LOOK_SYNC0:
            if (b == 0xA5) { buf[0] = 0xA5; state = LOOK_SYNC1; }
            return false;

        case LOOK_SYNC1:
            if (b == 0x5A) { buf[1] = 0x5A; bufPos = 2; state = READ_LEN; }
            else if (b != 0xA5) state = LOOK_SYNC0;
            return false;

        case READ_LEN:
            buf[bufPos++] = b;
            bodyLen = b;
            if (bodyLen < 3 || bodyLen > JK_BUF_MAX - 3) {
                // unrealistic length — resync
                state = LOOK_SYNC0;
                bufPos = 0;
                return false;
            }
            state = READ_BODY;
            return false;

        case READ_BODY: {
            buf[bufPos++] = b;
            // Frame body finished when we've collected bodyLen bytes
            // after the length byte. Total frame = 3 + bodyLen.
            if (bufPos >= 3 + bodyLen) {
                BmsData tmp = lastData;     // keep previous values
                // Dispatch by cmd + 2-byte sub-cmd. Body starts at
                // index 3 (buf[2] is the length byte itself).
                if (buf[3] == 0x82 && bufPos >= 6) {
                    uint16_t sub = be16(buf + 4);
                    if (sub == 0x1100) {
                        decodeCells(tmp, buf + 3, bodyLen);
                    } else if (sub == 0x1000) {
                        decodePackStats(tmp, buf + 3, bodyLen);
                    }
                }
                lastData = tmp;
                bufPos = 0;
                state  = LOOK_SYNC0;
                return tmp.valid;
            }
            if (bufPos >= JK_BUF_MAX) {
                state = LOOK_SYNC0;
                bufPos = 0;
            }
            return false;
        }
    }
    return false;
}

const BmsData& jkGetLast() { return lastData; }

void jkDumpLastFrame(Print& out) {
    out.print(F("frame: "));
    for (uint16_t i = 0; i < bufPos; i++) {
        if (buf[i] < 0x10) out.print('0');
        out.print(buf[i], HEX);
        out.print(' ');
    }
    out.println();
}
