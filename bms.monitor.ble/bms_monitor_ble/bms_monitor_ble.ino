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
    uint32_t lastPollMs;         // last time we wrote 0x96 to this pack

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

static char mqttClientId[32];
static uint32_t lastPublishOkMs = 0;
static bool     softKicked      = false;
static uint32_t lastMqttEnsureMs = 0;
static uint32_t lastMqttPublishMs = 0;

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
    // Only feed the JK reassembler with 0xFFE1 bytes; the other
    // notify chars (0xFFC1/0xFFC2, 0x2A19) speak different formats
    // and would confuse the header hunt.
    if (!c->getUUID().equals(NimBLEUUID((uint16_t)0xFFE1))) return;
    handleNotify(p, data, len);
}

class PackClientCallbacks : public NimBLEClientCallbacks {
    void onConnect(NimBLEClient *cli) override {
        Pack *p = packForAddr(cli->getPeerAddress());
        Serial.printf("[%s] connected\n", p ? p->pack_id : "?");
    }
    void onDisconnect(NimBLEClient *cli, int reason) override {
        Pack *p = packForAddr(cli->getPeerAddress());
        Serial.printf("[%s] disconnected (reason=%d)\n",
                      p ? p->pack_id : "?", reason);
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
        if (!p) return;
        if (p->client && p->client->isConnected()) return;
        if (p->connectPending) return;
        Serial.printf("[%s] advert rssi=%d, marking for connect\n",
                      p->pack_id, dev->getRSSI());
        p->wantConnect = true;
    }
    void onScanEnd(const NimBLEScanResults &, int) override {}
};
static ScanCallbacks scanCb;

static void ensureScan() {
    // We always want a scan running whenever ANY pack is unconnected.
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
    }
}

static void doConnect(Pack *p) {
    p->connectPending = true;
    p->lastConnectAttemptMs = millis();
    NimBLEScan *scan = NimBLEDevice::getScan();
    if (scan->isScanning()) scan->stop();

    if (!p->client) {
        p->client = NimBLEDevice::createClient();
        p->client->setClientCallbacks(&clientCb, false);
        p->client->setConnectionParams(12, 12, 0, 400);
    }
    Serial.printf("[%s] connecting to %s ...\n",
                  p->pack_id, p->addr.toString().c_str());
    if (!p->client->connect(p->addr)) {
        Serial.printf("[%s] connect() returned false\n", p->pack_id);
        p->connectPending = false;
        return;
    }
    p->client->exchangeMTU();

    // Enumerate every service/characteristic so we can pick up
    // notify characteristics under 0xFEE7 (or wherever JK actually
    // ships cell info) instead of guessing.
    std::vector<NimBLERemoteService*> svcs = p->client->getServices(true);
    Serial.printf("[%s] discovered %u services\n", p->pack_id,
                  (unsigned)svcs.size());
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
        p->client->disconnect();
        return;
    }
    p->notifyChar = svc->getCharacteristic(JK_NOTIFY);
    p->writeChar  = svc->getCharacteristic(JK_WRITE);
    if (!p->writeChar) {
        Serial.printf("[%s] missing 0xFFE2 write char\n", p->pack_id);
        p->client->disconnect();
        return;
    }
    jkSetCommand(0x96);
    if (!p->writeChar->writeValue(JK_CMD_CELL_INFO,
                                  sizeof(JK_CMD_CELL_INFO), false)) {
        Serial.printf("[%s] write activation failed\n", p->pack_id);
        p->client->disconnect();
        return;
    }
    p->bufLen = 0;
    p->lastFrameMs = millis();
    p->wantConnect = false;
    Serial.printf("[%s] streaming\n", p->pack_id);
    return;
}

// Rotate through candidate poll commands so we discover which one
// this firmware rev associates with the cell-info response. Once we
// see a type 0x02 reply from any pack we can freeze on that byte.
static const uint8_t POLL_COMMANDS[] = { 0x96, 0x93, 0x89, 0x98 };
static uint8_t pollCmdIdx = 0;

static void pollNextCommand(Pack *p) {
    uint8_t cmd = POLL_COMMANDS[pollCmdIdx % (sizeof(POLL_COMMANDS))];
    jkSetCommand(cmd);
    if (DEBUG_HEX_DUMP) {
        Serial.printf("[%s] poll cmd=0x%02X\n", p->pack_id, cmd);
    }
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
    if (DEBUG_HEX_DUMP) {
        Serial.printf("[%s] complete frame type=0x%02X len=%u\n",
                      p->pack_id, type, (unsigned)p->bufLen);
        // Full-frame hex dump so we can eyeball offsets against
        // the JK app's live readings. Only one pack (battery-5) so
        // we don't drown the console.
        if (strcmp(p->pack_id, "battery-5") == 0) {
            for (size_t i = 0; i < p->bufLen; i++) {
                if (i && i % 32 == 0) Serial.println();
                Serial.printf("%02X ", p->buf[i]);
            }
            Serial.println();
        }
    }
    // Some firmware revs deliver cell info under type 0x01 rather
    // than 0x02 — parse both and let the sanity checks in
    // parseCellInfo reject a wrong pick.
    if (type == 0x02 || type == 0x01) {
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

// Cell-info offsets pinned against esphome-jk-bms's JkBmsBleHardware
// mapping for JK-B*A20S/24S/... (the "software version >= 11" layout
// that all our packs run). Offsets are relative to the start of the
// 300-byte JK BLE message.
static const size_t OFF_CELL_MV_ARRAY = 6;    // 32 × uint16 LE mV
static const size_t OFF_CELL_AVG_MV   = 74;   // uint16 LE mV
static const size_t OFF_CELL_DELTA_MV = 76;   // uint16 LE mV
static const size_t OFF_MOS_TEMP      = 112;  // int16 LE, 0.1 °C
static const size_t OFF_TEMP_1        = 130;  // int16 LE, 0.1 °C
static const size_t OFF_TEMP_2        = 132;  // int16 LE, 0.1 °C
static const size_t OFF_TOTAL_MV      = 118;  // uint32 LE, mV
static const size_t OFF_CURRENT_MA    = 126;  // int32  LE, mA (charge +)
static const size_t OFF_SOC           = 141;  // uint8, %
static const size_t OFF_REMAIN_MAH    = 142;  // uint32 LE, mAh
static const size_t OFF_CYCLE_COUNT   = 150;  // uint32 LE
static const size_t OFF_CHARGE_MOS    = 166;  // uint8, 0/1
static const size_t OFF_DISCHARGE_MOS = 167;  // uint8, 0/1
static const size_t OFF_BALANCING     = 191;  // uint8, 0/1

static bool parseCellInfo(Pack *p) {
    const uint8_t *b = p->buf;
    BmsData &d = p->data;

    // Figure out which of the 32 slots are populated by scanning
    // until we hit a zero cell — every JK model we field has
    // contiguous cells starting at index 0.
    d.cellCount = 0;
    d.cellMinMv = 0xFFFF;
    d.cellMaxMv = 0;
    for (uint8_t c = 0; c < MAX_CELLS; c++) {
        uint16_t mv = rdU16(b + OFF_CELL_MV_ARRAY + c * 2);
        if (mv == 0 || mv > 5000) break;   // typical li-ion sanity ceiling
        d.cellMv[c] = mv;
        d.cellCount++;
        if (mv < d.cellMinMv) d.cellMinMv = mv;
        if (mv > d.cellMaxMv) d.cellMaxMv = mv;
    }
    if (d.cellCount == 0) return false;

    d.cellAvgMv   = rdU16(b + OFF_CELL_AVG_MV);
    d.cellDeltaMv = rdU16(b + OFF_CELL_DELTA_MV);
    d.totalMv     = rdU32(b + OFF_TOTAL_MV);
    d.currentMa   = rdS32(b + OFF_CURRENT_MA);
    d.soc         = b[OFF_SOC];
    d.remainMah   = rdU32(b + OFF_REMAIN_MAH);
    d.cycleCount  = rdU32(b + OFF_CYCLE_COUNT);
    d.chargeMosOn    = b[OFF_CHARGE_MOS]    != 0;
    d.dischargeMosOn = b[OFF_DISCHARGE_MOS] != 0;
    d.balancing      = b[OFF_BALANCING]     != 0;

    d.tempCount = 3;
    d.tempDeciC[0] = rdS16(b + OFF_MOS_TEMP);
    d.tempDeciC[1] = rdS16(b + OFF_TEMP_1);
    d.tempDeciC[2] = rdS16(b + OFF_TEMP_2);

    d.updatedMs = millis();
    d.valid = true;
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
    if (mqtt.connect(mqttClientId)) {
        Serial.printf("MQTT connected as %s\n", mqttClientId);
    } else {
        Serial.printf("MQTT connect failed rc=%d\n", mqtt.state());
    }
}

// Serialise a Pack's snapshot to JSON matching the ESP8266 monitor's
// payload shape so /battery.html renders it identically.
static void mqttPublishPack(Pack *p) {
    if (!mqtt.connected()) return;

    char body[1400];
    // The Arduino JSON print API is fine but heavier than we need
    // for a fixed schema; a hand-rolled printer keeps the whole
    // payload out of the heap.
    int n = snprintf(body, sizeof(body),
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
        n += snprintf(body + n, sizeof(body) - n,
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
        n += snprintf(body + n, sizeof(body) - n, ",\"cells_mv\":[");
        for (uint8_t c = 0; c < d.cellCount; c++) {
            n += snprintf(body + n, sizeof(body) - n,
                          c == 0 ? "%u" : ",%u", d.cellMv[c]);
        }
        n += snprintf(body + n, sizeof(body) - n, "],\"temps_dC\":[");
        for (uint8_t t = 0; t < d.tempCount; t++) {
            n += snprintf(body + n, sizeof(body) - n,
                          t == 0 ? "%d" : ",%d", d.tempDeciC[t]);
        }
        n += snprintf(body + n, sizeof(body) - n, "]");
    }
    n += snprintf(body + n, sizeof(body) - n, "}");

    if (n <= 0 || n >= (int)sizeof(body)) {
        Serial.printf("[%s] payload too big (%d B)\n", p->pack_id, n);
        return;
    }
    bool ok = mqtt.publish(p->mqttTopic, (const uint8_t*)body, n, true);
    if (ok) {
        lastPublishOkMs = millis();
        softKicked = false;
    }
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
    scan->setInterval(500);
    scan->setWindow(450);
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
    for (size_t i = 0; i < PACK_COUNT; i++) {
        Pack &p = packs[i];
        if (p.wantConnect && !p.connectPending) {
            // Rate-limit reconnect attempts to avoid stalling the
            // MQTT loop with back-to-back BLE handshakes.
            if (millis() - p.lastConnectAttemptMs > 5000) {
                doConnect(&p);
            }
        }
        // Periodic poll — rotates through candidate command bytes
        // until we discover which one this firmware rev uses for
        // cell info (see POLL_COMMANDS above).
        if (p.client && p.client->isConnected() && p.writeChar &&
            millis() - p.lastPollMs > BMS_POLL_INTERVAL_MS) {
            p.lastPollMs = millis();
            pollNextCommand(&p);
        }
    }

    // MQTT publish cadence.
    if (millis() - lastMqttPublishMs >= MQTT_PUBLISH_MS) {
        lastMqttPublishMs = millis();
        for (size_t i = 0; i < PACK_COUNT; i++) {
            mqttPublishPack(&packs[i]);
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

    delay(20);
}
