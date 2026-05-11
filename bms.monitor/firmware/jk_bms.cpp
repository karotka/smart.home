// JK BMS JK02 protocol decoder. Reference: open-source ESPHome
// component "syssi/esphome-jk-bms" — the field IDs and offsets
// below match what those parsers extract.

#include "jk_bms.h"

namespace {

// Stream parser state
enum ParserState : uint8_t {
    LOOK_HEADER0,
    LOOK_HEADER1,
    READ_LENHI,
    READ_LENLO,
    READ_BODY,
};

ParserState  state    = LOOK_HEADER0;
uint16_t     bodyLen  = 0;          // length field as reported by BMS
uint16_t     bufPos   = 0;
uint8_t      buf[JK_BUF_MAX];

BmsData      lastData = {};

// CRC over a JK frame is simple: 16-bit sum of every byte before the
// last two bytes (the CRC itself), modulo 0x10000.
bool validateCrc(const uint8_t* p, uint16_t n) {
    if (n < 5) return false;
    uint16_t sum = 0;
    for (uint16_t i = 0; i < n - 2; i++) sum += p[i];
    uint16_t want = (uint16_t)p[n - 2] << 8 | p[n - 1];
    return sum == want;
}

// Pull a big-endian unsigned 16/32 out of the buffer.
uint16_t be16(const uint8_t* p) { return (uint16_t)p[0] << 8 | p[1]; }
int16_t  bes16(const uint8_t* p) { return (int16_t)((uint16_t)p[0] << 8 | p[1]); }
uint32_t be32(const uint8_t* p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16)
         | ((uint32_t)p[2] << 8)  |  (uint32_t)p[3];
}

// Decode the data records inside a validated frame. The data area
// starts right after the 11-byte fixed header (header2 + len2 +
// terminal4 + cmd1 + src1 + transport1).
//
// Each record is one type byte followed by a fixed-width payload.
// Lengths come from the JK02 spec; unknown types are skipped by
// looking at the rest of the frame for the next known type.
void decodeRecords(BmsData& out, const uint8_t* p, uint16_t end) {
    out = BmsData{};   // clear
    out.valid = true;

    // We'll walk the data section. The tail is record_count(1) +
    // timestamp(4) + field_count(1) + crc(2), but the records that
    // matter to us all have unambiguous type IDs, so a simple
    // type-dispatch walk is enough.
    uint16_t i = 11;
    uint16_t tail = (end >= 8) ? (end - 8) : end;   // stop before trailer
    uint32_t sumMv = 0;
    uint8_t  cellsSeen = 0;

    while (i < tail) {
        uint8_t type = p[i++];
        if (i >= tail) break;

        switch (type) {
            case 0x79: {   // cell voltages
                uint8_t bytes = p[i++];                  // payload length in bytes
                uint8_t n = bytes / 3;                   // 3 bytes per cell entry
                if (n > MAX_CELLS) n = MAX_CELLS;
                for (uint8_t c = 0; c < n; c++) {
                    if (i + 2 >= end) break;
                    uint8_t  cellIdx = p[i] - 1;         // 1-based in stream
                    uint16_t mv      = be16(p + i + 1);
                    i += 3;
                    if (cellIdx < MAX_CELLS) {
                        out.cellMv[cellIdx] = mv;
                        if (mv > 0) {
                            sumMv     += mv;
                            cellsSeen += 1;
                        }
                    }
                }
                out.cellCount = cellsSeen;
                break;
            }
            case 0x80:   // MOS temp (deci-C)
                if (i + 2 <= end) {
                    if (out.tempCount < 4) out.tempDeciC[out.tempCount++] = bes16(p + i);
                    i += 2;
                }
                break;
            case 0x81:   // battery temp 1
            case 0x82:   // battery temp 2
                if (i + 2 <= end) {
                    if (out.tempCount < 4) out.tempDeciC[out.tempCount++] = bes16(p + i);
                    i += 2;
                }
                break;
            case 0x83:   // total voltage in 0.01 V steps -> mV
                if (i + 2 <= end) {
                    out.totalMv = (uint32_t)be16(p + i) * 10;
                    i += 2;
                }
                break;
            case 0x84:   // current in 0.01 A signed -> mA
                if (i + 2 <= end) {
                    out.currentMa = (int32_t)bes16(p + i) * 10;
                    i += 2;
                }
                break;
            case 0x85:   // SOC %
                if (i < end) out.soc = p[i++];
                break;
            case 0x86:   // temperature sensor count -- just skip it
                if (i < end) i++;
                break;
            case 0x87:   // cycle count
                if (i + 2 <= end) {
                    out.cycleCount = be16(p + i);
                    i += 2;
                }
                break;
            case 0x89:   // cycle capacity in mAh
                if (i + 4 <= end) {
                    out.cycleCapacityMah = be32(p + i);
                    i += 4;
                }
                break;
            case 0x8A:   // cell count
                if (i + 2 <= end) i += 2;
                break;
            case 0x8C:   // balance state bitmap, 2 bytes
                if (i + 2 <= end) {
                    out.balancing = (p[i] | p[i + 1]) != 0;
                    i += 2;
                }
                break;
            case 0xAB:   // charge MOS state
                if (i < end) out.chargeMosOn = p[i++] != 0;
                break;
            case 0xAC:   // discharge MOS state
                if (i < end) out.dischargeMosOn = p[i++] != 0;
                break;
            default:
                // Skip the unknown type byte and move on; a type we
                // don't model just gets dropped. This is fine because
                // type IDs are unique anchors — the next known type
                // we see will resync the walk.
                break;
        }
    }

    // Derived cell stats — only meaningful when we actually saw cells.
    if (cellsSeen > 0) {
        uint16_t mn = 0xFFFF, mx = 0;
        for (uint8_t c = 0; c < out.cellCount && c < MAX_CELLS; c++) {
            uint16_t v = out.cellMv[c];
            if (v == 0) continue;
            if (v < mn) mn = v;
            if (v > mx) mx = v;
        }
        out.cellMinMv  = mn;
        out.cellMaxMv  = mx;
        out.cellAvgMv  = (uint16_t)(sumMv / cellsSeen);
        out.cellDeltaMv = mx - mn;
    }
}

}  // namespace

bool jkFeedByte(uint8_t b) {
    switch (state) {
        case LOOK_HEADER0:
            if (b == 0x4E) { buf[0] = 0x4E; state = LOOK_HEADER1; }
            return false;

        case LOOK_HEADER1:
            if (b == 0x57) { buf[1] = 0x57; bufPos = 2; state = READ_LENHI; }
            else if (b != 0x4E) state = LOOK_HEADER0;
            return false;

        case READ_LENHI:
            buf[bufPos++] = b;
            bodyLen = (uint16_t)b << 8;
            state = READ_LENLO;
            return false;

        case READ_LENLO:
            buf[bufPos++] = b;
            bodyLen |= b;
            // JK length field includes everything from itself to the CRC,
            // so total frame on the wire = 2 (header) + bodyLen.
            if (bodyLen > JK_BUF_MAX - 4) {
                state = LOOK_HEADER0;
                bufPos = 0;
                return false;
            }
            state = READ_BODY;
            return false;

        case READ_BODY:
            buf[bufPos++] = b;
            // body finished when we've collected bodyLen bytes after
            // the length field; total = 2 + bodyLen
            if (bufPos >= 2 + bodyLen) {
                bool ok = validateCrc(buf, bufPos);
                if (ok) decodeRecords(lastData, buf, bufPos);
                else    lastData.valid = false;
                uint16_t frameLen = bufPos;
                bufPos = 0;
                state  = LOOK_HEADER0;
                return ok;
            }
            if (bufPos >= JK_BUF_MAX) {
                state = LOOK_HEADER0;
                bufPos = 0;
            }
            return false;
    }
    return false;
}

const BmsData& jkGetLast() { return lastData; }

void jkDumpLastFrame(Print& out) {
    out.print(F("frame: "));
    uint16_t shown = bufPos > 0 ? bufPos : 0;
    for (uint16_t i = 0; i < shown; i++) {
        if (buf[i] < 0x10) out.print('0');
        out.print(buf[i], HEX);
        out.print(' ');
    }
    out.println();
}
