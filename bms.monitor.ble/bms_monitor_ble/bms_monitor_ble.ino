// bms.monitor.ble — phase C
//
// One LOLIN D32 is the BLE central for battery-3/4/5 (newer JK BMS
// PCB rev, no UART on the GPS port). For each pack:
//   * scan → connect → discover 0xFFE0 → subscribe 0xFFE1
//   * send the AA 55 90 EB 96 ... "get cell info" activation frame
//   * reassemble BLE fragments into full 300-byte 0x02 (cell info)
//     and 0x03 (device info) messages, parse cell info into a
//     BmsData snapshot
//   * publish that snapshot to home/bms/<pack_id>/snapshot every
//     MQTT_PUBLISH_MS, same shape as the ESP8266 monitor uses so
//     /battery.html eats it without any server-side changes
//
// Same sentinel philosophy as the ESP8266 firmware: layered
// recovery (WiFi + MQTT soft-kick at 180 s, ESP.restart() at 300 s)
// so a stuck socket / marginal WiFi doesn't need a manual reset.

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <NimBLEDevice.h>

#include "config.h"
#include "secrets.h"

// Forward-declared so the Arduino IDE's auto-generated prototypes,
// which are inserted before any struct definitions in the .ino,
// can name `Pack *` without a compile error.
struct Pack;

// ---- JK BLE protocol ---------------------------------------------

static const NimBLEUUID JK_SVC   ((uint16_t)0xFFE0);
static const NimBLEUUID JK_NOTIFY((uint16_t)0xFFE1);
static const NimBLEUUID JK_WRITE ((uint16_t)0xFFE2);

// Header of every JK BLE reply. The 5th byte is the frame type
// (0x01 = settings, 0x02 = cell info, 0x03 = device info).
static const uint8_t JK_HEADER[4] = { 0x55, 0xAA, 0xEB, 0x90 };

// Full "get cell info" activation frame. CRC = sum-mod-256 of the
// 19 preceding bytes. Command 0x96 turned out to return type 0x01
// (settings) on our BD6A24S10P firmware rev, so we cycle through
// three candidate command bytes on the poll loop until we see a
// type-0x02 reply come back.
static uint8_t JK_CMD_CELL_INFO[20] = {
    0xAA, 0x55, 0x90, 0xEB, 0x96, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

// Recompute the CRC after mutating byte 4 (command). Sum-mod-256 of
// bytes 0..18 lands in byte 19.
static void jkSetCommand(uint8_t cmd) {
    JK_CMD_CELL_INFO[4] = cmd;
    uint8_t crc = 0;
    for (int i = 0; i < 19; i++) crc += JK_CMD_CELL_INFO[i];
    JK_CMD_CELL_INFO[19] = crc;
}

// A single JK BLE message is 300 bytes on the wire (header, type,
// counter, payload, CRC). BLE splits it into MTU-sized chunks —
// on the D32 with MTU 517 that's typically two fragments (~128 + 22
// on the current stack).
static const size_t JK_FRAME_SIZE = 300;

// ---- BmsData snapshot --------------------------------------------

static const uint8_t MAX_CELLS = 24;   // BD6A24S10P and up

struct BmsData {
    bool valid;
    uint32_t updatedMs;

    uint8_t  cellCount;
    uint16_t cellMv[MAX_CELLS];
    uint16_t cellResMohm10[MAX_CELLS];   // per-cell wire resistance
                                         // in mΩ × 10 (e.g. 173 = 17.3 mΩ)
    uint16_t cellMinMv, cellMaxMv, cellAvgMv, cellDeltaMv;

    uint32_t totalMv;
    int32_t  currentMa;
    uint8_t  soc;

    uint8_t  tempCount;
    int16_t  tempDeciC[3];  // MOS temp + 2 sensors

    uint32_t cycleCount;
    uint32_t remainMah;
    bool     chargeMosOn;
    bool     dischargeMosOn;
    bool     balancing;
};

// ---- Per-pack state ----------------------------------------------

struct Pack {
    const char *pack_id;
    const char *advName;
    NimBLEAddress addr;
    NimBLEClient *client;
    NimBLERemoteCharacteristic *notifyChar;
    NimBLERemoteCharacteristic *writeChar;

    // Frame reassembly buffer — cleared when we see a fresh
    // JK_HEADER at offset 0, appended otherwise.
    uint8_t  buf[JK_FRAME_SIZE + 16];
    size_t   bufLen;

    // Latest fully-parsed snapshot.
    BmsData data;

    volatile bool wantConnect;   // scan CB flipped it — main loop connects
    bool connectPending;         // main loop already scheduled the connect
    uint32_t lastFrameMs;        // last time we saw any bytes from this pack
    uint32_t lastConnectAttemptMs;
    uint32_t connectedSinceMs;   // when the current connection was established
    uint32_t lastPollMs;         // last time we wrote 0x96 to this pack
    uint8_t  lastPollCmd;        // the command byte we last sent to this pack

    char mqttTopic[64];          // home/bms/<pack_id>/snapshot
    char clientId[32];           // per-pack MAC only used for logging
};

// How often to re-send the cell-info request. Some JK firmwares
// broadcast unsolicited; this rev doesn't, so we ask on a fixed
// cadence and the cell info arrives as the reply.
static const unsigned long BMS_POLL_INTERVAL_MS = 2000;

static Pack packs[PACK_COUNT];

// ---- WiFi + MQTT + sentinel --------------------------------------

WiFiClient mqttNet;
PubSubClient mqtt(mqttNet);

// Debug channel — every state transition goes here in text form so
// we can watch the D32 from mosquitto_sub without USB serial. Cheap
// to leave on; drop when we're happy.
static void dbg(const char *fmt, ...) {
    if (!mqtt.connected()) return;
    char buf[192];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) mqtt.publish("home/bms/debug/log", (const uint8_t*)buf,
                            (unsigned)n, false);
}

static char mqttClientId[32];
static uint32_t lastPublishOkMs = 0;
static bool     softKicked      = false;
static uint32_t lastMqttEnsureMs = 0;
static uint32_t lastMqttPublishMs = 0;
static uint32_t lastHttpPostMs   = 0;

// Forward decl of the JK02 layout descriptor — Arduino auto-prototypes
// pickLayout() near the top of the sketch and pickLayout returns a
// Layout*, so it needs to know the tag exists before the auto-proto
// is emitted. The real definition sits with the parser lower down.
struct Layout {
    uint8_t cellSlots;
    size_t  cellMask;
    size_t  cellAvg;
    size_t  cellDelta;
    size_t  cellMaxIdx;
    size_t  cellMinIdx;
    size_t  cellRes;      // start of the 24 or 32 u16 wire-resistance block
    size_t  tempMos;
    size_t  tempT1;
    size_t  tempT2;
    size_t  totalMv;
    size_t  currentMa;
    size_t  soc;
    size_t  remainMah;
    size_t  cycleCount;
};

// ---- Forward decls ------------------------------------------------
static void handleNotify(Pack *p, const uint8_t *data, size_t len);
static bool parseCellInfo(Pack *p);

// ---- BLE plumbing -------------------------------------------------

static Pack *packForAddr(const NimBLEAddress &a) {
    for (size_t i = 0; i < PACK_COUNT; i++) {
        if (packs[i].addr == a) return &packs[i];
    }
    return nullptr;
}

// notifyCB fires from a NimBLE stack task; we snapshot the bytes
// into the owning pack's buffer and let the main loop parse. We
// route on the client pointer so multiple packs don't smear into
// each other's buffers.
static void notifyCB(NimBLERemoteCharacteristic *c,
                     uint8_t *data, size_t len, bool isNotify) {
    NimBLEClient *cli = c->getClient();
    if (!cli) return;
    Pack *p = packForAddr(cli->getPeerAddress());
    if (!p) return;
    if (DEBUG_HEX_DUMP) {
        Serial.printf("[%s] notify from %s len=%u : ",
                      p->pack_id, c->getUUID().toString().c_str(),
                      (unsigned)len);
        for (size_t i = 0; i < len && i < 40; i++) {
            Serial.printf("%02X ", data[i]);
        }
        Serial.println();
    }
    // Some JK firmwares emit type 0x02 (cell info) on a separate
    // notify char (0xFFC1 in the TI-style vendor service). Rather than
    // hard-code that, log every notify we receive so we can spot which
    // UUID starts spitting fragments beginning with `55 AA EB 90 02`,
    // then feed EVERY notify into the same reassembler — the header
    // check drops anything that isn't a JK frame anyway.
    // Only remember which UUIDs we've logged once MQTT is up — that
    // way the first-notify log fires the first time we have a working
    // dbg() sink, not on boot when dbg() silently drops.
    if (mqtt.connected()) {
        static char seenUuid[8][40] = {{0}};
        const std::string us = c->getUUID().toString();
        for (size_t i = 0; i < 8; i++) {
            if (seenUuid[i][0] && strcmp(seenUuid[i], us.c_str()) == 0) break;
            if (seenUuid[i][0] == 0) {
                strncpy(seenUuid[i], us.c_str(), sizeof(seenUuid[i]) - 1);
                dbg("[%s] first notify from %s len=%u %02X %02X %02X %02X",
                    p->pack_id, us.c_str(), (unsigned)len,
                    len > 0 ? data[0] : 0, len > 1 ? data[1] : 0,
                    len > 2 ? data[2] : 0, len > 3 ? data[3] : 0);
                break;
            }
        }
    }
    handleNotify(p, data, len);
}

class PackClientCallbacks : public NimBLEClientCallbacks {
    void onConnect(NimBLEClient *cli) override {
        Pack *p = packForAddr(cli->getPeerAddress());
        Serial.printf("[%s] connected\n", p ? p->pack_id : "?");
        dbg("[%s] onConnect", p ? p->pack_id : "?");
    }
    void onDisconnect(NimBLEClient *cli, int reason) override {
        Pack *p = packForAddr(cli->getPeerAddress());
        Serial.printf("[%s] disconnected (reason=%d)\n",
                      p ? p->pack_id : "?", reason);
        dbg("[%s] onDisconnect reason=%d", p ? p->pack_id : "?", reason);
        if (p) {
            p->notifyChar = nullptr;
            p->writeChar  = nullptr;
            p->connectPending = false;
            // wantConnect stays false until the next scan CB sees us
            // — otherwise we'd race the scan restart.
        }
    }
};
static PackClientCallbacks clientCb;

class ScanCallbacks : public NimBLEScanCallbacks {
    void onResult(const NimBLEAdvertisedDevice *dev) override {
        Pack *p = packForAddr(dev->getAddress());
        // Fallback: match by advertised name. Some JK BMS firmware
        // revs rotate their public MAC after a reset — the name we
        // set in the JK app is stable, so it's a reliable second
        // key. When we match by name, patch the addr so subsequent
        // client operations use the current one.
        if (!p && dev->haveName()) {
            const char *nm = dev->getName().c_str();
            for (size_t i = 0; i < PACK_COUNT; i++) {
                if (strcmp(nm, packs[i].advName) == 0) {
                    p = &packs[i];
                    if (!(p->addr == dev->getAddress())) {
                        dbg("[%s] MAC changed %s -> %s",
                            p->pack_id,
                            p->addr.toString().c_str(),
                            dev->getAddress().toString().c_str());
                        p->addr = dev->getAddress();
                    }
                    break;
                }
            }
        }
        if (!p) return;
        if (p->client && p->client->isConnected()) return;
        if (p->connectPending) return;
        Serial.printf("[%s] advert rssi=%d, marking for connect\n",
                      p->pack_id, dev->getRSSI());
        dbg("[%s] advert rssi=%d addrType=%d", p->pack_id,
            dev->getRSSI(), dev->getAddress().getType());
        p->wantConnect = true;
    }
    void onScanEnd(const NimBLEScanResults &, int) override {}
};
static ScanCallbacks scanCb;

static void ensureScan() {
    // Scan only while at least one pack is disconnected. Once every
    // pack is streaming, stop the radio — passive scan is cheap but
    // still competes with the ongoing GATT traffic and turns any
    // marginal RSSI link into a flapping one.
    bool needAny = false;
    for (size_t i = 0; i < PACK_COUNT; i++) {
        if (!packs[i].client || !packs[i].client->isConnected()) {
            needAny = true;
            break;
        }
    }
    NimBLEScan *scan = NimBLEDevice::getScan();
    if (needAny && !scan->isScanning()) {
        scan->start(0, false);
    } else if (!needAny && scan->isScanning()) {
        scan->stop();
    }
}

static void doConnect(Pack *p) {
    p->connectPending = true;
    p->lastConnectAttemptMs = millis();
    NimBLEScan *scan = NimBLEDevice::getScan();
    if (scan->isScanning()) scan->stop();

    // Recreate the client each time. NimBLE's internal client pool is
    // capped and reusing a stale client after a failed handshake
    // seemed to be blocking battery-4/5 permanently on the D32.
    if (p->client) {
        NimBLEDevice::deleteClient(p->client);
        p->client = nullptr;
    }
    p->client = NimBLEDevice::createClient();
    p->client->setClientCallbacks(&clientCb, false);
    p->client->setConnectionParams(12, 12, 0, 400);
    Serial.printf("[%s] connecting to %s ...\n",
                  p->pack_id, p->addr.toString().c_str());
    dbg("[%s] connecting", p->pack_id);
    if (!p->client->connect(p->addr)) {
        Serial.printf("[%s] connect() returned false\n", p->pack_id);
        dbg("[%s] connect() false", p->pack_id);
        p->connectPending = false;
        return;
    }
    // NOTE: no exchangeMTU() — JK BMS FW V10.10 (seen on battery-4)
    // silently drops connections when the central asks for anything
    // above the 23 B default. Sticking to the default is slower
    // (each notify max ~20 B payload → cell-info frame arrives in
    // ~15 fragments instead of 3) but it's the only shape those
    // buggy firmwares tolerate. Every other FW rev we field
    // negotiates fine at default too, so this is the safe pick.

    // Enumerate every service/characteristic so we can pick up
    // notify characteristics under 0xFEE7 (or wherever JK actually
    // ships cell info) instead of guessing.
    std::vector<NimBLERemoteService*> svcs = p->client->getServices(true);
    Serial.printf("[%s] discovered %u services\n", p->pack_id,
                  (unsigned)svcs.size());
    dbg("[%s] discovered %u svcs", p->pack_id, (unsigned)svcs.size());
    for (auto *svc : svcs) {
        Serial.printf("  service %s\n", svc->getUUID().toString().c_str());
        auto chars = svc->getCharacteristics(true);
        for (auto *ch : chars) {
            Serial.printf("    char %s  N=%d W=%d WNR=%d R=%d\n",
                          ch->getUUID().toString().c_str(),
                          ch->canNotify(), ch->canWrite(),
                          ch->canWriteNoResponse(), ch->canRead());
            if (ch->canNotify()) {
                if (ch->subscribe(true, notifyCB)) {
                    Serial.printf("    -> subscribed\n");
                }
            }
        }
    }
    // Keep the FFE0/FFE2 write handle for the activation poke.
    NimBLERemoteService *svc = p->client->getService(JK_SVC);
    if (!svc) {
        Serial.printf("[%s] service 0xFFE0 missing\n", p->pack_id);
        dbg("[%s] no 0xFFE0 svc", p->pack_id);
        p->client->disconnect();
        return;
    }
    p->notifyChar = svc->getCharacteristic(JK_NOTIFY);
    p->writeChar  = svc->getCharacteristic(JK_WRITE);
    if (!p->writeChar) {
        Serial.printf("[%s] missing 0xFFE2 write char\n", p->pack_id);
        dbg("[%s] no 0xFFE2 char", p->pack_id);
        p->client->disconnect();
        return;
    }
    jkSetCommand(0x96);
    if (!p->writeChar->writeValue(JK_CMD_CELL_INFO,
                                  sizeof(JK_CMD_CELL_INFO), false)) {
        Serial.printf("[%s] write activation failed\n", p->pack_id);
        dbg("[%s] activation write failed", p->pack_id);
        p->client->disconnect();
        return;
    }
    p->bufLen = 0;
    p->lastFrameMs = millis();
    p->wantConnect = false;
    p->connectPending = false;    // release the GAP-busy interlock
    p->connectedSinceMs = millis();
    Serial.printf("[%s] streaming\n", p->pack_id);
    dbg("[%s] streaming", p->pack_id);
    return;
}

// Rotate through candidate poll commands so we discover which one
// this firmware rev associates with the cell-info response. Once we
// see a type 0x02 reply from any pack we can freeze on that byte.
// On the BD6A24S10P/V15.29 rev the BMS emits type 0x02 (cell info)
// frames after 0x97 polls, interleaved with type 0x03 (device info).
// Type 0x01 (settings) shows up in response to 0x96/0x95 and is
// useless for live data, so poll 0x97 exclusively.
static const uint8_t POLL_COMMANDS[] = { 0x97 };
static uint8_t pollCmdIdx = 0;

static void pollNextCommand(Pack *p) {
    uint8_t cmd = POLL_COMMANDS[pollCmdIdx % (sizeof(POLL_COMMANDS))];
    jkSetCommand(cmd);
    p->lastPollCmd = cmd;
    dbg("[%s] poll cmd=0x%02X", p->pack_id, cmd);
    p->writeChar->writeValue(JK_CMD_CELL_INFO,
                             sizeof(JK_CMD_CELL_INFO), false);
    pollCmdIdx++;
}

// ---- JK parser ---------------------------------------------------

static bool bufHasHeader(const uint8_t *b, size_t n) {
    return n >= 4 &&
           b[0] == JK_HEADER[0] && b[1] == JK_HEADER[1] &&
           b[2] == JK_HEADER[2] && b[3] == JK_HEADER[3];
}

// Accumulate BLE fragments into `buf`. When the accumulator starts
// with the JK header AND we have JK_FRAME_SIZE bytes, hand off to
// the parser. Anything else (like the "AT\r\n" spam during boot)
// gets dropped.
static void handleNotify(Pack *p, const uint8_t *data, size_t len) {
    if (len == 0) return;

    // A fresh chunk starting with the JK header resets the buffer.
    // In steady state each 300-byte message arrives as two chunks
    // (~128 + 22 in the current NimBLE stack) — the header lands in
    // the first chunk, the second is pure continuation.
    if (bufHasHeader(data, len)) {
        p->bufLen = 0;
    }
    if (p->bufLen + len > sizeof(p->buf)) {
        // Overrun: something went wrong (maybe two messages fused).
        // Discard and wait for the next header.
        p->bufLen = 0;
        return;
    }
    memcpy(p->buf + p->bufLen, data, len);
    p->bufLen += len;

    if (DEBUG_HEX_DUMP) {
        Serial.printf("[%s] chunk len=%u bufLen=%u\n",
                      p->pack_id, (unsigned)len, (unsigned)p->bufLen);
    }

    // Not yet the whole 300 B — wait for more chunks.
    if (p->bufLen < JK_FRAME_SIZE) return;
    if (!bufHasHeader(p->buf, p->bufLen)) {
        p->bufLen = 0;
        return;
    }

    uint8_t type = p->buf[4];
    // Optional MQTT hex-dump on `home/bms/debug/hex/<pack>/cmdXX_typeYY`
    // — off by default so the broker isn't drowned during steady state.
    // Flip DEBUG_HEX_DUMP to true and re-flash to spy on every frame
    // when a new firmware rev arrives and the parser stops recognising
    // the layout; throttled to one publish per pack per type per 5 s
    // and includes the poll command that preceded the reply so a
    // subscriber can correlate command byte → reply type.
    size_t pidx = p - packs;
    if (DEBUG_HEX_DUMP && pidx < PACK_COUNT && p->bufLen <= 512) {
        static uint32_t lastHexMs[PACK_COUNT][4] = {{0}};
        uint8_t tslot = type < 4 ? type : 0;
        uint32_t nowMs = millis();
        if (nowMs - lastHexMs[pidx][tslot] > 5000) {
            lastHexMs[pidx][tslot] = nowMs;
            static char hexBuf[1024];
            int n = 0;
            for (size_t i = 0; i < p->bufLen && n < (int)sizeof(hexBuf) - 4; i++) {
                n += snprintf(hexBuf + n, sizeof(hexBuf) - n, "%02X ", p->buf[i]);
            }
            char topic[96];
            snprintf(topic, sizeof(topic),
                     "home/bms/debug/hex/%s/cmd%02X_type%02X",
                     p->pack_id, p->lastPollCmd, type);
            mqtt.publish(topic, (const uint8_t*)hexBuf, (unsigned)n, false);
        }
    }
    // Only type 0x02 (cell info) carries live pack data on this
    // firmware family; type 0x01 is settings-only (cell OVP/UVP,
    // balance thresholds) and type 0x03 is device info. Feeding
    // 0x01 into parseCellInfo produced 4-cell garbage on
    // battery-1/4 (V10.09/V10.10 — those revs never emit 0x02)
    // because the mask at offset 70 happened to have 4 bits set
    // by coincidence in the settings payload.
    if (type == 0x02) {
        if (parseCellInfo(p)) {
            p->lastFrameMs = millis();
            if (DEBUG_HEX_DUMP) {
                const BmsData &d = p->data;
                Serial.printf("[%s] parsed: cells=%u total=%umV I=%ldmA "
                              "soc=%u%% Tmos=%d.%d T1=%d.%d T2=%d.%d\n",
                              p->pack_id, d.cellCount,
                              (unsigned)d.totalMv, (long)d.currentMa, d.soc,
                              d.tempDeciC[0]/10, abs(d.tempDeciC[0]%10),
                              d.tempDeciC[1]/10, abs(d.tempDeciC[1]%10),
                              d.tempDeciC[2]/10, abs(d.tempDeciC[2]%10));
            }
        }
    }
    // 0x01 (settings) and 0x03 (device info) we currently ignore —
    // device info is nice-to-have for the "which model" string but
    // the dashboard doesn't need it.
    p->bufLen = 0;
}

// Little-endian readers (JK BLE is LE throughout).
static inline uint16_t rdU16(const uint8_t *b) { return b[0] | (b[1] << 8); }
static inline int16_t  rdS16(const uint8_t *b) { return (int16_t)rdU16(b); }
static inline uint32_t rdU32(const uint8_t *b) {
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) |
           ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}
static inline int32_t  rdS32(const uint8_t *b) { return (int32_t)rdU32(b); }

// JK BMS BLE type-0x02 (cell info) frame layout. Two variants exist
// in the field, corresponding to the size of the fixed cell-slot area
// carved into the frame header:
//
//   JK02_32S (V15.29 rev, battery-3): 32 cell slots @ 6..69,
//     mask @ 70, live pack fields at higher offsets.
//   JK02_24S (V10.09/V10.10 revs, battery-1/battery-4):
//     24 cell slots @ 6..53, mask @ 54, live pack fields shifted
//     -32 bytes vs 32S (8 fewer cell slots × 2 bytes = -16 for the
//     cell area, and 8 fewer cell-resistance slots × 2 bytes = another
//     -16 for the resistance area).
//
// Numbers pinned by capturing the frame on the wire and matching known
// live values from the JK app + the battery-2 UART reference (same
// cabinet, ~85 % SoC, ~5–15 A charge, ~28 °C ambient). The Layout
// struct itself is forward-declared near the top of this file so
// Arduino's auto-generated prototype for pickLayout() sees the tag.
static const Layout LAYOUT_32S = {
    // slots mask avg dlt mxi mni res tmos t1  t2  totV  curr soc rem cyc
    32,    70,  74, 76, 78, 79, 80, 144, 162, 164, 150, 158, 173, 174, 182,
};
static const Layout LAYOUT_24S = {
    24,    54,  58, 60, 62, 63, 64, 130, 132, 134, 118, 126, 141, 142, 150,
};

// Every layout puts cell voltages at offset 6.
static const size_t OFF_CELL_MV0 = 6;

// Decide which layout the frame uses by counting mask bits. Rejects
// cases where the "mask" is actually a cell-resistance byte reading
// (e.g. 0xA6 = 0b10100110 has 4 bits set but they're non-contiguous
// — a real JK cell mask is always the low N bits set contiguously
// because cell N is packed at slot N).
static bool maskLooksValid(uint32_t m, uint8_t slots) {
    if (m == 0 || m == 0xFFFFFFFFu) return false;
    int bits = 0;
    for (uint8_t i = 0; i < 32; i++) if (m & (1u << i)) bits++;
    if (bits < 4 || bits > slots) return false;
    // Contiguity check: for `bits` set, the mask must equal
    // (1 << bits) - 1 (all low bits set, nothing above). Real JK
    // packs enumerate cells starting from index 0 with no gaps.
    uint32_t expected = ((uint64_t)1 << bits) - 1;
    return m == expected;
}

static bool parseCellInfo(Pack *p) {
    if (p->bufLen < 200) return false;
    const uint8_t *b = p->buf;
    // Pick the layout that matches this frame. Try 24S first because
    // its mask sits earlier in the frame — a 32S mask read on a
    // 24S frame lands on the cell-resistance region where the bytes
    // sometimes coincidentally form a "looks like a mask" value, but
    // the reverse (24S mask read on a 32S frame) lands on cell 24's
    // voltage bytes which never look like a low-bits-contiguous mask
    // in practice.
    const Layout *L = nullptr;
    uint32_t m24 = rdU32(b + LAYOUT_24S.cellMask);
    if (maskLooksValid(m24, LAYOUT_24S.cellSlots)) {
        L = &LAYOUT_24S;
    } else {
        uint32_t m32 = rdU32(b + LAYOUT_32S.cellMask);
        if (maskLooksValid(m32, LAYOUT_32S.cellSlots)) L = &LAYOUT_32S;
    }
    if (!L) return false;

    BmsData d = {};
    d.updatedMs = millis();

    uint32_t mask = rdU32(b + L->cellMask);
    uint8_t  cellCount = 0;
    uint16_t mn = 0xFFFF, mx = 0;
    uint32_t sumMv = 0;
    for (uint8_t i = 0; i < MAX_CELLS && i < L->cellSlots; i++) {
        if (!(mask & (1u << i))) continue;
        uint16_t mv = rdU16(b + OFF_CELL_MV0 + i * 2);
        if (mv < 2500 || mv > 4500) continue;
        // The wire-resistance block is packed the same way as the cell
        // voltage block — one u16 per physical cell slot, so we take
        // the value at the same index as the cell we just accepted.
        // Unit is mΩ × 10 on all JK BLE firmware revs we've seen.
        d.cellResMohm10[cellCount] = rdU16(b + L->cellRes + i * 2);
        d.cellMv[cellCount] = mv;
        cellCount++;
        sumMv += mv;
        if (mv < mn) mn = mv;
        if (mv > mx) mx = mv;
    }
    if (cellCount < 4) return false;

    d.cellCount   = cellCount;
    d.cellMinMv   = mn;
    d.cellMaxMv   = mx;
    d.cellAvgMv   = rdU16(b + L->cellAvg);
    d.cellDeltaMv = rdU16(b + L->cellDelta);
    d.totalMv     = rdU32(b + L->totalMv);
    if (d.totalMv < sumMv - sumMv / 10 || d.totalMv > sumMv + sumMv / 10) {
        d.totalMv = sumMv;
    }
    d.currentMa   = rdS32(b + L->currentMa);
    d.soc         = b[L->soc];
    if (d.soc > 100) d.soc = 0;

    d.tempCount    = 3;
    d.tempDeciC[0] = rdS16(b + L->tempT1);
    d.tempDeciC[1] = rdS16(b + L->tempT2);
    d.tempDeciC[2] = rdS16(b + L->tempMos);

    d.cycleCount = rdU32(b + L->cycleCount);
    d.remainMah  = rdU32(b + L->remainMah);

    d.chargeMosOn    = false;
    d.dischargeMosOn = false;
    d.balancing      = (d.cellDeltaMv > 20);

    d.valid = true;
    p->data = d;
    return true;
}

// ---- WiFi + OTA + MQTT -------------------------------------------

static void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS1);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("WiFi: connecting");
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
        delay(250);
        Serial.print('.');
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\nWiFi: %s rssi=%d dBm\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
        Serial.println("\nWiFi: connect timeout, will retry");
    }
}

static void otaSetup() {
    ArduinoOTA.setHostname("bms-ble");
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() { Serial.println("OTA start"); });
    ArduinoOTA.onEnd  ([]() { Serial.println("OTA done");  });
    ArduinoOTA.onError([](ota_error_t e) {
        Serial.printf("OTA error %u\n", (unsigned)e);
    });
    ArduinoOTA.begin();
    Serial.println("OTA ready as bms-ble");
}

static void mqttEnsure() {
    if (mqtt.connected()) return;
    if (WiFi.status() != WL_CONNECTED) return;
    if (millis() - lastMqttEnsureMs < 5000) return;
    lastMqttEnsureMs = millis();
    static bool bootAnnounced = false;
    if (mqtt.connect(mqttClientId)) {
        if (!bootAnnounced) {
            bootAnnounced = true;
            char b[80];
            int n = snprintf(b, sizeof(b), "boot build=%s %s", __DATE__, __TIME__);
            mqtt.publish("home/bms/debug/log", (const uint8_t*)b, (unsigned)n, false);
        }
        Serial.printf("MQTT connected as %s\n", mqttClientId);
    } else {
        Serial.printf("MQTT connect failed rc=%d\n", mqtt.state());
    }
}

// Serialise a Pack's snapshot to JSON matching the ESP8266 monitor's
// payload shape so /battery.html renders it identically. Returns
// the number of bytes written; -1 on overflow.
static int buildPayload(Pack *p, char *body, size_t bodyLen) {
    // The Arduino JSON print API is fine but heavier than we need
    // for a fixed schema; a hand-rolled printer keeps the whole
    // payload out of the heap.
    int n = snprintf(body, bodyLen,
        "{\"pack_id\":\"%s\",\"uptime_s\":%lu,"
        "\"wifi_rssi\":%d,\"bms_age_ms\":%lu,\"valid\":%s",
        p->pack_id,
        (unsigned long)(millis() / 1000UL),
        (int)WiFi.RSSI(),
        (unsigned long)(millis() - p->lastFrameMs),
        (p->data.valid &&
         millis() - p->data.updatedMs < BMS_STALE_AFTER_MS) ? "true" : "false");
    if (p->data.valid) {
        const BmsData &d = p->data;
        n += snprintf(body + n, bodyLen - n,
            ",\"cell_count\":%u,\"cell_min_mv\":%u,\"cell_max_mv\":%u,"
            "\"cell_avg_mv\":%u,\"cell_delta_mv\":%u,"
            "\"total_mv\":%u,\"current_ma\":%ld,\"soc\":%u,"
            "\"remain_mah\":%u,\"cycle_count\":%u,"
            "\"charge_mos\":%s,\"discharge_mos\":%s,\"balancing\":%s",
            d.cellCount, d.cellMinMv, d.cellMaxMv,
            d.cellAvgMv, d.cellDeltaMv,
            (unsigned)d.totalMv, (long)d.currentMa, d.soc,
            (unsigned)d.remainMah, (unsigned)d.cycleCount,
            d.chargeMosOn    ? "true" : "false",
            d.dischargeMosOn ? "true" : "false",
            d.balancing      ? "true" : "false");
        n += snprintf(body + n, bodyLen - n, ",\"cells_mv\":[");
        for (uint8_t c = 0; c < d.cellCount; c++) {
            n += snprintf(body + n, bodyLen - n,
                          c == 0 ? "%u" : ",%u", d.cellMv[c]);
        }
        // Wire resistance in mΩ × 10 — same index as cells_mv. Server
        // renders it as tooltip on the per-cell bars and as an
        // aggregate min/avg/max row, so a bad crimp or a drying cell
        // stands out.
        n += snprintf(body + n, bodyLen - n, "],\"cells_res_r10\":[");
        for (uint8_t c = 0; c < d.cellCount; c++) {
            n += snprintf(body + n, bodyLen - n,
                          c == 0 ? "%u" : ",%u", d.cellResMohm10[c]);
        }
        n += snprintf(body + n, bodyLen - n, "],\"temps_dC\":[");
        for (uint8_t t = 0; t < d.tempCount; t++) {
            n += snprintf(body + n, bodyLen - n,
                          t == 0 ? "%d" : ",%d", d.tempDeciC[t]);
        }
        n += snprintf(body + n, bodyLen - n, "]");
    }
    n += snprintf(body + n, bodyLen - n, "}");

    if (n <= 0 || n >= (int)bodyLen) return -1;
    return n;
}

static void mqttPublishPack(Pack *p) {
    if (!mqtt.connected()) return;
    char body[1400];
    int n = buildPayload(p, body, sizeof(body));
    if (n < 0) {
        Serial.printf("[%s] payload too big\n", p->pack_id);
        return;
    }
    bool ok = mqtt.publish(p->mqttTopic, (const uint8_t*)body, n, true);
    if (ok) {
        lastPublishOkMs = millis();
        softKicked = false;
    }
}

// HTTP POST the same payload to /bms so the server writes a row
// into InfluxDB (measurement bms_<pack_id>) — that's the source
// /battery.html enumerates for its cards, so without this the tile
// never appears no matter how good the MQTT feed is.
static void httpPostPack(Pack *p) {
    if (WiFi.status() != WL_CONNECTED) return;
    char body[1400];
    int n = buildPayload(p, body, sizeof(body));
    if (n < 0) return;

    WiFiClient net;
    HTTPClient http;
    http.setTimeout(4000);
    if (!http.begin(net, SERVER_URL)) return;
    http.addHeader("Content-Type", "application/json");
    int code = http.POST((uint8_t*)body, n);
    if (code > 0 && DEBUG_HEX_DUMP) {
        Serial.printf("[%s] POST /bms -> %d\n", p->pack_id, code);
    }
    http.end();
}

// ---- setup / loop ------------------------------------------------

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("bms.monitor.ble — phase C");

    for (size_t i = 0; i < PACK_COUNT; i++) {
        Pack &p = packs[i];
        p.pack_id = PACKS[i].pack_id;
        p.advName = PACKS[i].advName;
        p.addr = NimBLEAddress(PACKS[i].mac, BLE_ADDR_PUBLIC);
        p.client = nullptr;
        p.notifyChar = nullptr;
        p.writeChar = nullptr;
        p.bufLen = 0;
        p.data = {};
        p.wantConnect = false;
        p.connectPending = false;
        p.lastFrameMs = 0;
        p.lastConnectAttemptMs = 0;
        p.connectedSinceMs = 0;
        snprintf(p.mqttTopic, sizeof(p.mqttTopic),
                 "home/bms/%s/snapshot", p.pack_id);
        snprintf(p.clientId, sizeof(p.clientId), "%s@%s",
                 p.pack_id, PACKS[i].mac);
        Serial.printf("  pack %s -> %s topic=%s\n",
                      p.pack_id, PACKS[i].mac, p.mqttTopic);
    }

    NimBLEDevice::init("");
    NimBLEDevice::setPower(9);
    NimBLEScan *scan = NimBLEDevice::getScan();
    scan->setScanCallbacks(&scanCb, false);
    // Low-duty ACTIVE scan. Two competing failure modes to balance:
    //   * 90 % duty cycle (old interval 500/window 450) starves the
    //     ongoing GATT connections and trips HCI reason 520 timeouts.
    //   * Passive scan drops the scan-request round-trip and with it
    //     the device NAME, which we need for the name-fallback path
    //     when a pack's MAC hasn't been observed yet (battery-1 ships
    //     without a fixed MAC in config.h — we lock it in on first
    //     advert).
    // 2 % duty active scan (32 * 0.625 = 20 ms every 1000 ms) satisfies
    // both: enough air time for the GATT keep-alive to survive and
    // still enough scan responses to catch the name.
    scan->setInterval(1600);   // 1.0 s window
    scan->setWindow(32);       // 20 ms of listening → ~2 % duty
    scan->setActiveScan(true);

    connectWifi();
    otaSetup();

    snprintf(mqttClientId, sizeof(mqttClientId), "bms-ble-%06X",
             (unsigned)(ESP.getEfuseMac() & 0xFFFFFF));
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setBufferSize(2048);
    mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
    mqtt.setSocketTimeout(MQTT_SOCKET_TIMEOUT_S);
    Serial.printf("MQTT client id: %s\n", mqttClientId);

    lastPublishOkMs = millis();  // grace period for the sentinel
}

void loop() {
    ArduinoOTA.handle();

    if (WiFi.status() != WL_CONNECTED) {
        static uint32_t lastRetryMs = 0;
        if (millis() - lastRetryMs > 10000) {
            lastRetryMs = millis();
            WiFi.reconnect();
        }
    }

    mqttEnsure();
    mqtt.loop();

    // BLE state machine — one central per pack, sharing one scan.
    ensureScan();
    // Only one pack in the middle of a connect handshake at a time.
    // The ESP32 BLE stack lets you queue up back-to-back connect()
    // calls but the second one bails out with `false` while the
    // first GAP procedure hasn't been dismantled — that turned out
    // to be why battery-4/5 kept ping-ponging between "advert
    // seen" and "connect() false" without ever making it through.
    // Rotation: if we're already holding BLE_MAX_ACTIVE connections,
    // the ESP32 BLE stack refuses new ones. Every BLE_ROTATE_MS we
    // evict the oldest connection so somebody else gets a turn.
    size_t activeCount = 0;
    Pack *oldest = nullptr;
    for (size_t i = 0; i < PACK_COUNT; i++) {
        Pack &p = packs[i];
        if (p.client && p.client->isConnected()) {
            activeCount++;
            if (!oldest || p.connectedSinceMs < oldest->connectedSinceMs) {
                oldest = &p;
            }
        }
    }
    // Only evict when a pack is actually waiting for a slot. With
    // PACK_COUNT == BLE_MAX_ACTIVE we never need to rotate — kicking a
    // healthy connection just to reconnect it drops us below the
    // dashboard's 10 s freshness window while the handshake replays.
    bool waiting = false;
    for (size_t i = 0; i < PACK_COUNT; i++) {
        Pack &p = packs[i];
        if (p.wantConnect && !(p.client && p.client->isConnected())) {
            waiting = true; break;
        }
    }
    if (waiting && activeCount >= BLE_MAX_ACTIVE && oldest &&
        millis() - oldest->connectedSinceMs > BLE_ROTATE_MS) {
        dbg("[%s] rotate evict (age=%lus)", oldest->pack_id,
            (unsigned long)((millis() - oldest->connectedSinceMs) / 1000UL));
        oldest->client->disconnect();
        activeCount--;
    }

    bool anyBusy = false;
    for (size_t i = 0; i < PACK_COUNT; i++) {
        if (packs[i].connectPending) { anyBusy = true; break; }
    }
    // Also gate on the active-count ceiling — don't even try to open
    // a 4th connection because it'll fail silently.
    if (!anyBusy && activeCount < BLE_MAX_ACTIVE) {
        for (size_t i = 0; i < PACK_COUNT; i++) {
            Pack &p = packs[i];
            if (p.wantConnect && !p.connectPending &&
                millis() - p.lastConnectAttemptMs > 8000) {
                doConnect(&p);
                break;  // one connect per loop pass — GAP is single-shot
            }
        }
    }

    // Periodic poll for cell info — independent of the connect flow
    // above so poll ticks keep firing even when another pack is in
    // the middle of a handshake.
    for (size_t i = 0; i < PACK_COUNT; i++) {
        Pack &p = packs[i];
        if (p.client && p.client->isConnected() && p.writeChar &&
            millis() - p.lastPollMs > BMS_POLL_INTERVAL_MS) {
            p.lastPollMs = millis();
            pollNextCommand(&p);
        }
    }

    // MQTT publish cadence — 2 s per pack.
    if (millis() - lastMqttPublishMs >= MQTT_PUBLISH_MS) {
        lastMqttPublishMs = millis();
        for (size_t i = 0; i < PACK_COUNT; i++) {
            mqttPublishPack(&packs[i]);
        }
    }

    // HTTP POST cadence — 30 s per pack. Skips packs whose latest
    // snapshot is stale so we don't spam Influx with empty rows for
    // BLE clients that haven't come up yet.
    if (millis() - lastHttpPostMs >= SEND_INTERVAL_MS) {
        lastHttpPostMs = millis();
        for (size_t i = 0; i < PACK_COUNT; i++) {
            Pack &p = packs[i];
            if (p.data.valid &&
                millis() - p.data.updatedMs < BMS_STALE_AFTER_MS) {
                httpPostPack(&p);
            }
        }
    }

    // Sentinel watchdog: no successful MQTT publish for 3 min ->
    // soft kick, for 5 min -> hard restart.
    unsigned long sincePub = millis() - lastPublishOkMs;
    if (sincePub > MQTT_DEAD_HARD_MS) {
        Serial.printf("MQTT silent %lus, ESP.restart()\n", sincePub / 1000UL);
        delay(200);
        ESP.restart();
    } else if (sincePub > MQTT_DEAD_SOFT_MS && !softKicked) {
        Serial.printf("MQTT silent %lus, forcing WiFi+MQTT reconnect\n",
                      sincePub / 1000UL);
        mqtt.disconnect();
        WiFi.disconnect(false);
        delay(100);
        WiFi.reconnect();
        softKicked = true;
    }

    // Per-pack stall watchdog. NimBLE occasionally holds a client
    // in "isConnected=true" state after the peer has silently dropped
    // — no onDisconnect fires, no supervision timeout, we just stop
    // seeing frames. Break out of that stuck state by forcing a
    // disconnect once we've been dry for STALL_FORCE_DROP_MS; the
    // scan-cb → doConnect path picks it back up.
    static const unsigned long STALL_FORCE_DROP_MS = 60UL * 1000UL;
    for (size_t i = 0; i < PACK_COUNT; i++) {
        Pack &p = packs[i];
        if (!p.client || !p.client->isConnected()) continue;
        if (p.lastFrameMs == 0) continue;  // never streamed yet
        if (millis() - p.lastFrameMs > STALL_FORCE_DROP_MS) {
            dbg("[%s] stall watchdog: force disconnect (dry %lus)",
                p.pack_id,
                (unsigned long)((millis() - p.lastFrameMs) / 1000UL));
            p.client->disconnect();
            p.lastFrameMs = millis();  // debounce the trigger
        }
    }

    // Whole-D32 BLE deadlock watchdog. If the NimBLE stack silently
    // wedges (scan appears "isScanning=true" but never fires callbacks,
    // no advert seen, no client transitions) the mainloop stays alive
    // but no pack ever produces a valid parse. Hard-restart after
    // 3 min without any valid parse.
    static uint32_t lastAnyValidMs = 0;
    for (size_t i = 0; i < PACK_COUNT; i++) {
        if (packs[i].data.valid &&
            millis() - packs[i].data.updatedMs < BMS_STALE_AFTER_MS) {
            lastAnyValidMs = millis();
            break;
        }
    }
    if (lastAnyValidMs == 0) lastAnyValidMs = millis();  // grace at boot
    static const unsigned long BLE_DEAD_HARD_MS = 180UL * 1000UL;
    if (millis() - lastAnyValidMs > BLE_DEAD_HARD_MS) {
        Serial.printf("BLE silent %lus, ESP.restart()\n",
                      (millis() - lastAnyValidMs) / 1000UL);
        dbg("BLE deadlock watchdog: ESP.restart()");
        delay(200);
        ESP.restart();
    }

    delay(20);
}
