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

// Rolling capture of the last bytes the BMS sent us, kept so the
// firmware can publish a hex snapshot in each POST. 1 KB ≈ 5 full
// frame cycles at 60 B/s and stays well under the JSON payload
// budget we send to the server.
const size_t  RECENT_CAP = 1024;
uint8_t       recentBuf[RECENT_CAP];
size_t        recentHead = 0;
bool          recentWrapped = false;

uint16_t be16(const uint8_t* p) { return (uint16_t)p[0] << 8 | p[1]; }
int16_t  bes16(const uint8_t* p) { return (int16_t)((uint16_t)p[0] << 8 | p[1]); }

// Decode the 0x82 0x11 0x00 frame: 24 cells of big-endian uint16 mV
// starting right after the sub-cmd.
//
//   A5 5A 3B 82 11 00  CELL1_hi CELL1_lo  CELL2_hi CELL2_lo  ...
//
// The cell frame resets temp_count / temp values because the
// telemetry frames that carry them are independent — without this
// reset they'd accumulate across rounds and tempCount would walk
// off the end of the array.
void decodeCells(BmsData& out, const uint8_t* p, uint16_t len) {
    out.tempCount = 0;
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

    // Offsets in this frame's data section, pinned down against the JK
    // BMS app's Status screen (total V 54.47, SOC 1 %, T1 25.4 °C).
    // Values that aren't in whole-number degrees here also exist in
    // the per-sample 0x82 0x20 stream but only as constants — this
    // frame is the canonical place to read live state from.
    //
    //  offset 0..1   total V in 0.01 V steps      -> totalMv  (mv = cV*10)
    //  offset 4..5   ???   (saw 27 at standby)
    //  offset 6..7   ???   (saw 78)
    //  offset 8..9   ???   (saw 5)
    //  offset 10..11 ???   (saw 31 — possibly balance delta mV)
    //  offset 12..13 MOSFET temp °C (BE u16)      -> tempDeciC[2]
    //  offset 14..15 ???   (always 15 in capture, possibly fault flags)
    //  offset 16..17 average cell mV              (informational)
    //  offset 22..23 SOC %                        -> soc
    //
    // Cycle count, current_ma in mA, MOS state, balance bitmap not
    // yet placed. The 0x82 0x20 telemetry stream broadcasts the two
    // NTC probe temps (T1, T2 in the JK app) every second but in a
    // form we haven't decoded yet — the raw value is constant at
    // 0x07E0 regardless of probe placement. TODO when we can park a
    // hand on the probe and watch it walk.

    // Field map cross-checked against a synchronised JK app capture
    // (Total 52.38 V, Current -3.26 A, SOC 66 %, MOS 30.7 °C,
    // T1 27.5 °C, T2 26.5 °C, Cell delta 5 mV, Remain 79.1 Ah):
    //
    //  offset 0..1   total V in 0.01 V steps     -> totalMv (cV*10)
    //  offset 2..3   ???   (was -63 during -6 A, -98 during -3.26 A —
    //                       neither scale matches current, leaving TODO)
    //  offset 4..5   T2 °C, whole degrees BE u16 -> tempDeciC[1]
    //  offset 6..7   SOC %, low byte             -> soc
    //  offset 8..9   cell delta in mV BE u16     (we compute it from
    //                                             the cells frame too)
    //  offset 10..11 MOS temp °C, whole degrees  -> tempDeciC[2]
    //  offset 12..13 T1 °C, whole degrees        -> tempDeciC[0]
    //  offset 14..15 ???
    //  offset 16..17 avg cell mV (informational)
    //  offset 18..25 counters / status — not pinned down yet
    //  offset 34..35 Remain Capacity × 0.1 Ah    -> remainCapacityMah
    //  offset 40..41 cycle energy accumulator (?)— grows during
    //                                              discharge, TODO unit
    //
    // Sanity ranges discard SoftwareSerial-shifted nonsense (one byte
    // dropped mid-frame shows up as wild values at the new offsets).

    if (dlen >= 2) {
        uint16_t total_cv = be16(d);
        if (out.totalMv == 0) out.totalMv = (uint32_t)total_cv * 10;
    }
    if (dlen >= 4) {
        // Signed int16 BE in 0.1 A units. Latest cross-check:
        //   capture during JK -3.26 A: off 2-3 = -31 -> -3.1 A
        //   capture during JK -6 A:    off 2-3 = -63 -> -6.3 A
        // Reject out-of-range values to filter SoftwareSerial drops.
        int16_t cur_dA = bes16(d + 2);
        if (cur_dA >= -2000 && cur_dA <= 2000) {
            out.currentMa = (int32_t)cur_dA * 100;
        }
    }
    // We always expose three temperature slots — T1, T2, MOS in that
    // order. Even if a single reading is rejected by the sanity guard,
    // the index stays fixed so the dashboard can label each consistently.
    out.tempCount = 3;
    if (dlen >= 6) {
        int16_t t2 = bes16(d + 4);
        if (t2 >= -20 && t2 <= 100) out.tempDeciC[1] = t2 * 10;
    }
    if (dlen >= 8) {
        uint8_t soc = d[7];
        if (soc <= 100) out.soc = soc;
    }
    if (dlen >= 12) {
        int16_t mos = bes16(d + 10);
        if (mos >= -20 && mos <= 100) out.tempDeciC[2] = mos * 10;
    }
    if (dlen >= 14) {
        int16_t t1 = bes16(d + 12);
        if (t1 >= -20 && t1 <= 100) out.tempDeciC[0] = t1 * 10;
    }
    if (dlen >= 36) {
        // 0.1 Ah units; e.g. 0x0316 = 790 -> 79.0 Ah -> 79000 mAh.
        // JK app showed 79.1 Ah, within rounding. Cap at 2000 (= 200 Ah)
        // to drop SoftwareSerial-shifted reads where this offset lands
        // on an unrelated field (saw 3736 once, would have read out
        // as 373 Ah which is impossible).
        uint16_t remain_dAh = be16(d + 34);
        if (remain_dAh <= 2000) {
            out.remainCapacityMah = (uint32_t)remain_dAh * 100;
        }
    }
}

}  // namespace

bool jkFeedByte(uint8_t b) {
    recentBuf[recentHead] = b;
    recentHead = (recentHead + 1) % RECENT_CAP;
    if (recentHead == 0) recentWrapped = true;

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
                    } else if ((sub & 0xFF00) == 0x2000 && bufPos >= 8) {
                        // Telemetry stream: A5 5A 05 82 20 <slot> <val_hi> <val_lo>.
                        // The BMS broadcasts one tiny frame per metric per second;
                        // we map the known slots onto BmsData fields. Values that
                        // look like temperatures (slot 0x?3 family observed at
                        // 0x07E0 = ~20.16 °C with the probe in air) are scaled by
                        // /100 — the slot we don't recognise yet drops on the
                        // floor with a comment so future me can figure it out
                        // with a probe-in-hand calibration session.
                        uint8_t slot = (uint8_t)(sub & 0x00FF);
                        int16_t val  = bes16(buf + 6);
                        // Slot mapping in this 0x82 0x20 stream is NOT
                        // pinned down yet. During bring-up every slot we
                        // saw broadcast a constant 0x07E0 (2016) — which
                        // looked like 20.16 °C but turned out to be a
                        // placeholder: the JK app reports T1=25.4 / T2=24.1
                        // while the raw value never changes. The real temp
                        // bytes must live in one of the bigger frames
                        // (0x82 0x10 0x00 pack stats) at an offset we
                        // haven't found yet. Park the dispatch here until
                        // we can capture a frame stream while the
                        // temperatures move (heating one of the probes in
                        // hand) and correlate.
                        (void)slot; (void)val;
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

void jkRecentBytes(char* hexOut, size_t hexCap) {
    if (!hexOut || hexCap < 3) return;
    size_t available = recentWrapped ? RECENT_CAP : recentHead;
    size_t startIdx  = recentWrapped ? recentHead : 0;
    // Each byte -> 2 hex chars, no separators. Trim to fit hexCap-1.
    size_t maxBytes  = (hexCap - 1) / 2;
    if (available > maxBytes) {
        // Keep the most recent maxBytes; advance startIdx accordingly.
        size_t skip = available - maxBytes;
        startIdx = (startIdx + skip) % RECENT_CAP;
        available = maxBytes;
    }
    size_t w = 0;
    for (size_t i = 0; i < available; i++) {
        uint8_t b = recentBuf[(startIdx + i) % RECENT_CAP];
        static const char H[] = "0123456789ABCDEF";
        hexOut[w++] = H[b >> 4];
        hexOut[w++] = H[b & 0x0F];
    }
    hexOut[w] = 0;
}

void jkDumpLastFrame(Print& out) {
    out.print(F("frame: "));
    for (uint16_t i = 0; i < bufPos; i++) {
        if (buf[i] < 0x10) out.print('0');
        out.print(buf[i], HEX);
        out.print(' ');
    }
    out.println();
}
