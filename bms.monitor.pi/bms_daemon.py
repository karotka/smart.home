#!/usr/bin/env python3
# bms_daemon — Pi-side BLE central for the JK BD6A24S10P family.
#
# Runs on the Pi hosting the invertor script (its BT range covers the
# battery cabinet at -60 to -70 dBm on all packs). One process, one
# coroutine per pack, MQTT-publishes decoded snapshots to the same
# home/bms/<pack_id>/snapshot tree the ESP32 firmware already uses so
# /battery.html renders without any server-side change.
#
# Connect pattern lifted from RondaYummy/bms-monitor-ble (proven to
# survive multi-BMS load on Pi 3 BlueZ):
#   * `BleakClient(mac_string)` — the string variant does its own
#     device lookup right before connect, so it isn't tripped up by
#     stale D-Bus device paths from earlier scans.
#   * 3 s sleep between spawning each pack's coroutine — enough for
#     BlueZ to finish the previous GATT handshake before the next
#     one races the D-Bus adapter queue.
#   * `async with BleakClient(...) as client:` context manager — its
#     `__aexit__` guarantees disconnect() on any exception, which
#     kept BlueZ from wedging on half-open connections.
#
# Frame parsing (JK02_32S and JK02_24S layouts, activation via 0x96
# then 0x97 with a 150 ms gap) is ported straight from the ESP32
# firmware — see bms.monitor.ble/bms_monitor_ble/bms_monitor_ble.ino.

import asyncio
import json
import logging
import os
import struct
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from bleak import BleakClient, BleakScanner
import paho.mqtt.client as mqtt

MQTT_BROKER = "192.168.0.224"
MQTT_PORT = 1883

# The dashboard reads packs from InfluxDB's `bms_<pack>` measurements
# — a fresh MQTT snapshot alone won't refresh the /battery.html tile
# on a hard reload. POST every snapshot to the same /bms endpoint the
# ESP32 firmware used so the server writes a row into Influx.
BMS_HTTP_URL = "http://192.168.0.222/bms"
# Post cadence — 60 s per pack is enough for state-of-charge history
# in Grafana; MQTT still carries every ~250 ms frame for the live tile.
HTTP_POST_INTERVAL_S = 60.0

# What identifies the machine posting to /bms in InfluxDB. Was
# client_ip in the ESP32 era (which broke as soon as more than one
# Pi/board ended up on the same subnet) — a short name is stabler.
SOURCE = "invertor"

# BMS list. MACs are the primary key — bleak's find-by-name path is
# unreliable on Pi 3 BlueZ, and `BleakClient(mac_string)` tolerates
# the same edge cases while doing its own device lookup.
#
# `write_uuid` overrides the default JK02 write char (FFE2) for packs
# whose firmware routes writes through the same char it notifies on
# (FFE1). Cracked by pulling the JK app APK's Android HCI bugreport
# and seeing it write to ATT handle 0x000E — that's FFE1's value
# handle, not FFE2. On battery-2 (firmware V19.27) the FFE2 write is
# silently accepted but nothing on the pack actually consumes it, so
# our activation went nowhere and the notify char just spammed
# "AT\r\n" indefinitely.
DEFAULT_WRITE = "0000ffe2-0000-1000-8000-00805f9b34fb"
# nominal_mah = "1 cycle worth of discharge" for our own lifetime counter
# (see bms_lifetime_*). Values are the Ah the user set on each JK on
# 2026-07-15 — the BMS's own cycle counter resets whenever that value is
# rewritten, which is why we run a parallel counter on the Pi and never
# reset it. Match the JK Ah settings if you ever re-calibrate a pack.
PACKS_DEFAULT = [
    {"pack_id": "battery-3", "mac": "C8:47:80:03:51:55", "nominal_mah": 70000},
    {"pack_id": "battery-5", "mac": "C8:47:80:1D:C2:EA", "nominal_mah": 80000},
    {"pack_id": "battery-1", "mac": "C8:47:8C:E8:24:7E", "nominal_mah": 107000},
    {"pack_id": "battery-2", "mac": "28:D4:1E:6A:EF:21", "nominal_mah": 119000,
     "write_uuid": "0000ffe1-0000-1000-8000-00805f9b34fb"},
    {"pack_id": "battery-4", "mac": "C8:47:8C:E9:1C:DA", "nominal_mah": 134000},
    # 16S LiFePO4 (EVE LF230, 230 Ah) — different chemistry from the 14S NMC
    # packs above, hence the lfp- prefix: alert thresholds per cell differ
    # (LFP 3.65 V full / 2.5 V empty vs NMC 4.2 / 3.0).
    {"pack_id": "lfp-1", "mac": "C8:47:80:52:39:71", "nominal_mah": 230000},
]

# Persistent lifetime counters. Written atomically every LIFETIME_SAVE_S
# seconds and on daemon exit. Survives JK Ah reconfig (which resets the
# BMS's own cycle_count) and daemon restarts. Path is fine to hard-code
# for the invertor Pi — the daemon only runs there.
LIFETIME_FILE = "/home/pi/bms_lifetime.json"
LIFETIME_SAVE_S = 60.0
# Cap on how far we're willing to extrapolate current between two frames.
# ~4 Hz stream → dt is normally 0.25 s. After a reconnect it can be tens
# of seconds; those gaps get skipped (we have no idea what the current
# did in between) instead of poisoning the integral.
LIFETIME_MAX_DT_S = 5.0

_env = os.environ.get("BMS_PACKS", "").strip()
if _env:
    _wanted = {n.strip() for n in _env.split(",") if n.strip()}
    PACKS = [p for p in PACKS_DEFAULT if p["pack_id"] in _wanted]
else:
    PACKS = PACKS_DEFAULT

JK_NOTIFY = "0000ffe1-0000-1000-8000-00805f9b34fb"
JK_HEADER = bytes([0x55, 0xAA, 0xEB, 0x90])
JK_FRAME_SIZE = 300


def _cmd_frame(cmd: int) -> bytes:
    """20-byte JK request: `AA 55 90 EB <cmd> 00×14 <crc>`, crc = sum mod 256."""
    b = bytearray([0xAA, 0x55, 0x90, 0xEB, cmd] + [0] * 15)
    b[19] = sum(b[:19]) & 0xFF
    return bytes(b)


# JK setting write: same 20-byte envelope as _cmd_frame, but byte 5 carries the
# payload length and bytes 6..9 the little-endian value. (_cmd_frame is just this
# with a zero-length, zero-value payload.)
def _write_frame(reg: int, value: int, length: int = 4) -> bytes:
    b = bytearray([0xAA, 0x55, 0x90, 0xEB, reg, length] + [0] * 14)
    b[6] = value & 0xFF
    b[7] = (value >> 8) & 0xFF
    b[8] = (value >> 16) & 0xFF
    b[9] = (value >> 24) & 0xFF
    b[19] = sum(b[:19]) & 0xFF
    return bytes(b)


# Setting registers. Verified by writing one and diffing the whole settings
# frame: only the named byte may move (plus byte 5, a frame counter, and 299,
# a crc, which always change).
#
# The settings frame is a run of 4-byte little-endian fields and the register
# ids advance in step with them — one id per field — so a field at frame offset
# X has register 0x1D + (X - 118) // 4. That rule is confirmed across
# 118/0x1D and 122/0x1E; anything further out is an extrapolation and must be
# proven by a diff before it is trusted. `setreg` exists for exactly that.
REG_CHARGE_SW = 0x1D        # frame offset 118
REG_DISCHARGE_SW = 0x1E     # frame offset 122
REG_BALANCER_SW = 0x1F      # frame offset 126
REG_BAL_START_V = 0x22      # frame offset 138 — balancer start voltage, mV

# Guard rails for the named setting writes: (min, max) in the field's own unit.
WRITE_LIMITS = {
    # An LFP balancer wants to work near the knee, not down on the plateau
    # where a few mV of spread is noise rather than state of charge. Below
    # ~3.2 V that is all it would be chasing; above 3.6 V it would never run.
    REG_BAL_START_V: (3000, 3600),
}


@dataclass
class Layout:
    name: str
    cell_slots: int
    cell_mask: int
    cell_avg: int
    cell_delta: int
    cell_res: int
    temp_mos: int
    temp_t1: int
    temp_t2: int
    total_mv: int
    current_ma: int
    soc: int
    remain_mah: int
    cycle_count: int
    # Active-balancer telemetry. Offsets verified by correlating against
    # cell delta across all six packs: 2 mV delta reads 0 mA, 11-13 mV
    # reads ~0.6 A, and the 80 mV LFP pack pegs at its 2.0 A maximum.
    # State is 0 = idle, 1/2 = active; the sign alternates as the balancer
    # shuttles charge between cells, so magnitude is the useful number.
    bal_current: int
    bal_state: int


LAYOUT_32S = Layout("JK02_32S", 32, 70, 74, 76, 80,
                    144, 162, 164, 150, 158, 173, 174, 182, 170, 172)
LAYOUT_24S = Layout("JK02_24S", 24, 54, 58, 60, 64,
                    130, 132, 134, 118, 126, 141, 142, 150, 138, 140)


def _mask_valid(mask: int, slots: int) -> bool:
    """Real JK cell masks are the low N bits set contiguously — rejects
    a resistance byte that coincidentally has 4 bits set from being
    misread as a mask."""
    if mask == 0 or mask == 0xFFFFFFFF:
        return False
    bits = bin(mask).count("1")
    if bits < 4 or bits > slots:
        return False
    return mask == ((1 << bits) - 1)


def _pick_layout(buf: bytes) -> Optional[Layout]:
    """Try 24S first — its mask lives at byte 54 where a 32S frame has
    cell voltages, which never look like a low-bits-contiguous mask."""
    if _mask_valid(struct.unpack_from("<I", buf, LAYOUT_24S.cell_mask)[0],
                   LAYOUT_24S.cell_slots):
        return LAYOUT_24S
    if _mask_valid(struct.unpack_from("<I", buf, LAYOUT_32S.cell_mask)[0],
                   LAYOUT_32S.cell_slots):
        return LAYOUT_32S
    return None


def parse_cell_info(buf: bytes) -> Optional[dict]:
    """Decode a type-0x02 cell-info frame into the same shape the
    ESP32 firmware publishes on home/bms/<pack>/snapshot."""
    if len(buf) < 200:
        return None
    L = _pick_layout(buf)
    if L is None:
        return None

    mask = struct.unpack_from("<I", buf, L.cell_mask)[0]
    cells_mv, cells_res = [], []
    for i in range(min(L.cell_slots, 24)):
        if not (mask & (1 << i)):
            continue
        mv = struct.unpack_from("<H", buf, 6 + i * 2)[0]
        if 2500 <= mv <= 4500:
            cells_mv.append(mv)
            cells_res.append(struct.unpack_from("<H", buf, L.cell_res + i * 2)[0])

    if len(cells_mv) < 4:
        return None

    total_mv = struct.unpack_from("<I", buf, L.total_mv)[0]
    cell_sum = sum(cells_mv)
    if abs(total_mv - cell_sum) > cell_sum // 10:
        total_mv = cell_sum

    soc = buf[L.soc]
    if soc > 100:
        soc = 0

    return {
        "valid": True,
        "cell_count": len(cells_mv),
        "cells_mv": cells_mv,
        "cells_res_r10": cells_res,
        "cell_min_mv": min(cells_mv),
        "cell_max_mv": max(cells_mv),
        "cell_avg_mv": struct.unpack_from("<H", buf, L.cell_avg)[0],
        "cell_delta_mv": struct.unpack_from("<H", buf, L.cell_delta)[0],
        "total_mv": total_mv,
        "current_ma": struct.unpack_from("<i", buf, L.current_ma)[0],
        "soc": soc,
        "cycle_count": struct.unpack_from("<I", buf, L.cycle_count)[0],
        "remain_mah": struct.unpack_from("<I", buf, L.remain_mah)[0],
        "temps_dC": [
            struct.unpack_from("<h", buf, L.temp_t1)[0],
            struct.unpack_from("<h", buf, L.temp_t2)[0],
            struct.unpack_from("<h", buf, L.temp_mos)[0],
        ],
        # Filled in from the 0x01 settings frame (see parse_settings).
        # These bits are NOT in the 0x02 cell-info frame — which is why they
        # used to be a hardcoded False. None = not seen yet, never "off".
        "charge_mos": None,
        "discharge_mos": None,
        # Real balancer telemetry, not the old "cell_delta > 20" guess —
        # that claimed "balancing" on any imbalanced pack even when the
        # balancer was provably idle.
        "balance_current_ma": struct.unpack_from("<h", buf, L.bal_current)[0],
        "balancing": buf[L.bal_state] != 0,
        "layout": L.name,
    }


# --- Settings frame (type 0x01) -----------------------------------------
# The charge/discharge MOSFET switches live HERE, not in the 0x02 cell-info
# frame. Offsets verified against our own packs: byte 114 is the configured
# cell count and reads 14 on these 14S packs, which anchors the rest of the
# map (118/122/126 then line up as charge / discharge / balancer switches).
SET_CELL_COUNT = 114
SET_CHARGE_SW = 118
SET_DISCHARGE_SW = 122
SET_BALANCER_SW = 126


def parse_settings(buf: bytes):
    """Decode a type-0x01 settings frame -> MOSFET switch states."""
    if len(buf) < 130:
        return None
    cells = struct.unpack_from("<I", buf, SET_CELL_COUNT)[0]
    # Alignment guard: real packs are 8S..32S. Anything else means the frame
    # isn't laid out how we think, so publish nothing rather than lie.
    if not (8 <= cells <= 32):
        return None
    return {
        "cell_count_cfg": cells,
        "charge_mos": bool(struct.unpack_from("<I", buf, SET_CHARGE_SW)[0]),
        "discharge_mos": bool(struct.unpack_from("<I", buf, SET_DISCHARGE_SW)[0]),
        "balancer_on": bool(struct.unpack_from("<I", buf, SET_BALANCER_SW)[0]),
    }


@dataclass
class PackState:
    pack_id: str
    mac: str
    write_uuid: str = DEFAULT_WRITE
    buf: bytearray = field(default_factory=bytearray)
    last_frame_ts: float = 0
    last_snapshot: Optional[dict] = None
    last_http_post_ts: float = 0
    ble_rssi_dbm: Optional[int] = None
    # Manual disconnect from the dashboard. When set true the pack's
    # coroutine drops its BleakClient and blocks until it's cleared
    # again — the point is to hand the pack over to the JK phone app
    # without stopping the whole daemon (or all other packs).
    pause_requested: bool = False
    # last decoded 0x01 settings frame (MOSFET switch states)
    settings: Optional[dict] = None
    # comparable form of the last 0x01 frame (counter + crc stripped)
    settings_key: Optional[str] = None
    # (register, value) queued by MQTT, written by the pack coroutine
    pending_write: Optional[tuple] = None
    # Persistent lifetime accumulators (mAh) — integrated on the Pi and
    # written to LIFETIME_FILE so JK factory resets and daemon restarts
    # never lose them. our_cycles = lifetime_dch_mah / nominal_mah.
    nominal_mah: int = 100000
    lifetime_dch_mah: float = 0.0
    lifetime_ch_mah: float = 0.0
    last_current_sample_ts: float = 0.0


def _load_lifetime(packs, log) -> None:
    """Populate lifetime counters from LIFETIME_FILE. Missing file / bad
    JSON / unknown pack IDs are all fine — that just means the counter
    starts at 0 for those packs."""
    try:
        with open(LIFETIME_FILE) as f:
            state = json.load(f)
    except FileNotFoundError:
        log.info("lifetime: no prior state at %s — starting at 0",
                 LIFETIME_FILE)
        return
    except Exception as e:
        log.warning("lifetime: could not read %s (%s) — starting at 0",
                    LIFETIME_FILE, e)
        return
    for p in packs:
        row = state.get("packs", {}).get(p.pack_id)
        if not isinstance(row, dict):
            continue
        p.lifetime_dch_mah = float(row.get("dch_mah", 0) or 0)
        p.lifetime_ch_mah = float(row.get("ch_mah", 0) or 0)
        log.info("lifetime: [%s] loaded dch=%.0f mAh ch=%.0f mAh",
                 p.pack_id, p.lifetime_dch_mah, p.lifetime_ch_mah)


def _save_lifetime(packs, log) -> None:
    """Atomic rewrite of LIFETIME_FILE — write to a sibling .tmp then
    os.replace so a mid-write crash never leaves a truncated file."""
    payload = {
        "version": 1,
        "ts": time.time(),
        "packs": {
            p.pack_id: {
                "dch_mah": round(p.lifetime_dch_mah, 1),
                "ch_mah": round(p.lifetime_ch_mah, 1),
                "nominal_mah": p.nominal_mah,
                "cycles": round(p.lifetime_dch_mah / p.nominal_mah, 3)
                if p.nominal_mah else 0,
            } for p in packs
        },
    }
    tmp = LIFETIME_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, LIFETIME_FILE)
    except Exception as e:
        log.warning("lifetime: save failed: %s", e)


async def _lifetime_saver(packs, log) -> None:
    """Persist lifetime counters every LIFETIME_SAVE_S. main() also
    calls _save_lifetime() from its finally block, so a clean shutdown
    also flushes; this task covers the SIGKILL / power-cut case."""
    while True:
        await asyncio.sleep(LIFETIME_SAVE_S)
        _save_lifetime(packs, log)


def _notify_cb(pack: PackState, mqtt_client, log):
    def _handle(_char, data):
        data = bytes(data)
        if data[:4] == JK_HEADER:
            pack.buf.clear()
        pack.buf.extend(data)
        if len(pack.buf) < JK_FRAME_SIZE:
            return
        if pack.buf[:4] != JK_HEADER:
            pack.buf.clear()
            return
        ftype = pack.buf[4]
        if ftype == 0x01:
            # Trim to exactly one frame: pack.buf keeps accumulating until the
            # next header, so slicing to the end made every frame look different.
            buf = bytes(pack.buf)[:JK_FRAME_SIZE]
            st = parse_settings(buf)
            if st is not None:
                pack.settings = st
            # Audit trail. Byte 5 is a frame counter and the last byte a crc, so
            # strip both before comparing or every frame looks "changed". Any real
            # settings change — ours, the JK app's, or the BMS's own — gets the
            # full frame logged, which is what makes a write verifiable.
            key = (buf[:5] + buf[6:JK_FRAME_SIZE - 1]).hex()
            if key != pack.settings_key:
                log.warning("[%s] SETTINGS %s", pack.pack_id, buf.hex())
                pack.settings_key = key
            return
        if ftype == 0x02:
            snap = parse_cell_info(bytes(pack.buf))
            if snap is not None:
                now = time.time()
                snap["pack_id"] = pack.pack_id
                snap["ts"] = now
                snap["bms_age_ms"] = 0  # fresh frame, age is zero
                snap["ble_rssi_dbm"] = pack.ble_rssi_dbm
                snap["source"] = SOURCE
                if pack.settings is not None:
                    snap["charge_mos"] = pack.settings["charge_mos"]
                    snap["discharge_mos"] = pack.settings["discharge_mos"]
                # power_w derived from V × I. Instantaneous, signed:
                # positive charges the pack, negative discharges.
                snap["power_w"] = round(
                    (snap["total_mv"] / 1000.0) *
                    (snap["current_ma"] / 1000.0), 1)
                # Lifetime integration. dt against the previous frame's
                # arrival, capped so a reconnect gap doesn't dump a
                # bogus chunk of Ah into the counter. Discharge and
                # charge tallied separately so we can compare against
                # the invertor totals for sanity.
                if pack.last_current_sample_ts > 0:
                    dt = now - pack.last_current_sample_ts
                    if 0 < dt <= LIFETIME_MAX_DT_S:
                        dq_mah = snap["current_ma"] * dt / 3600.0
                        if dq_mah >= 0:
                            pack.lifetime_ch_mah += dq_mah
                        else:
                            pack.lifetime_dch_mah += -dq_mah
                pack.last_current_sample_ts = now
                snap["our_dch_ah"] = round(pack.lifetime_dch_mah / 1000.0, 2)
                snap["our_ch_ah"] = round(pack.lifetime_ch_mah / 1000.0, 2)
                snap["our_cycles"] = (
                    round(pack.lifetime_dch_mah / pack.nominal_mah, 2)
                    if pack.nominal_mah else 0)
                pack.last_frame_ts = now
                pack.last_snapshot = snap
                mqtt_client.publish(
                    f"home/bms/{pack.pack_id}/snapshot",
                    json.dumps(snap), retain=True)
        pack.buf.clear()

    return _handle


def _http_post_snapshot(pack: PackState, log) -> None:
    """POST the pack's most-recent snapshot to /bms so the server
    writes a row into InfluxDB (`bms_<pack_id>`). /battery.html reads
    from Influx on page load, so without this the tile never refreshes
    on a hard reload."""
    snap = pack.last_snapshot
    if snap is None:
        return
    now = time.time()
    if now - pack.last_http_post_ts < HTTP_POST_INTERVAL_S:
        return
    pack.last_http_post_ts = now
    try:
        data = json.dumps(snap).encode()
        req = urllib.request.Request(
            BMS_HTTP_URL, data=data,
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            resp.read()
    except Exception as e:
        log.warning("[%s] http POST /bms failed: %s", pack.pack_id, e)


def _publish_state(mqtt_client, pack: PackState, state: str) -> None:
    """Push connection state (streaming|paused|connecting|disconnected)
    to home/bms/<pack>/state so the dashboard can render the connect
    / disconnect button label."""
    mqtt_client.publish(
        f"home/bms/{pack.pack_id}/state", state, retain=True)


async def pack_task(pack: PackState, mqtt_client, log):
    """One coroutine per pack. Reconnect loop with exponential backoff
    on error, watchdog that drops the link if broadcasts stop for
    30 s. Nudge poll (0x97) once we've been dry for 15 s so packs
    whose broadcast stream falters silently get restarted without a
    full disconnect. Honours pack.pause_requested so the dashboard
    can hand a pack over to the phone without stopping the daemon."""
    backoff = 5
    while True:
        if pack.pause_requested:
            _publish_state(mqtt_client, pack, "paused")
            await asyncio.sleep(1.0)
            continue
        _publish_state(mqtt_client, pack, "connecting")
        try:
            log.info("[%s] connecting to %s", pack.pack_id, pack.mac)
            async with BleakClient(pack.mac, timeout=20.0) as client:
                await client.start_notify(
                    JK_NOTIFY, _notify_cb(pack, mqtt_client, log))
                # Two-shot activation. 0x96 wakes the BMS out of its
                # "AT\r\n" keep-alive spam; 0x97 opens the type-0x02
                # broadcast stream. Both writes need response=False —
                # the JK BLE FW answers by broadcast, not GATT reply.
                await client.write_gatt_char(
                    pack.write_uuid, _cmd_frame(0x96), response=False)
                await asyncio.sleep(0.15)
                await client.write_gatt_char(
                    pack.write_uuid, _cmd_frame(0x97), response=False)
                pack.last_frame_ts = time.time()
                _publish_state(mqtt_client, pack, "streaming")
                log.info("[%s] streaming", pack.pack_id)
                backoff = 5

                loop = asyncio.get_running_loop()
                while client.is_connected and not pack.pause_requested:
                    await asyncio.sleep(2.0)
                    now = time.time()
                    # Fire-and-forget HTTP POST to /bms — Influx rows
                    # need to appear even when nobody's watching the
                    # WebSocket. Runs in the default thread pool so a
                    # slow HTTP roundtrip doesn't block BLE handling.
                    if pack.last_snapshot is not None:
                        loop.run_in_executor(
                            None, _http_post_snapshot, pack, log)
                    if pack.pending_write is not None:
                        reg, val = pack.pending_write
                        pack.pending_write = None
                        try:
                            await client.write_gatt_char(
                                pack.write_uuid, _write_frame(reg, val),
                                response=False)
                            log.warning("[%s] MOSFET write reg=0x%02X value=%d",
                                        pack.pack_id, reg, val)
                            await asyncio.sleep(0.3)
                            # nudge the BMS to re-broadcast its settings so the
                            # audit line above shows what actually changed
                            await client.write_gatt_char(
                                pack.write_uuid, _cmd_frame(0x96), response=False)
                        except Exception as e:
                            log.warning("[%s] MOSFET write failed: %s",
                                        pack.pack_id, e)

                    dry = now - pack.last_frame_ts
                    if dry > 30:
                        log.warning(
                            "[%s] stall %.0fs — dropping",
                            pack.pack_id, dry)
                        break
                    if dry > 15:
                        try:
                            await client.write_gatt_char(
                                pack.write_uuid, _cmd_frame(0x97), response=False)
                        except Exception as e:
                            log.warning("[%s] nudge failed: %s",
                                        pack.pack_id, e)
            _publish_state(mqtt_client, pack, "disconnected")
            log.info("[%s] disconnected", pack.pack_id)
        except Exception as e:
            _publish_state(mqtt_client, pack, "disconnected")
            msg = str(e) or repr(e) or "empty error"
            log.warning("[%s] error: %s", pack.pack_id, msg)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("bms")

    mqtt_client = mqtt.Client(client_id="bms-daemon-pi")
    mqtt_client.will_set("home/bms/daemon/status", "offline", retain=True)
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.publish("home/bms/daemon/status", "online", retain=True)

    # Per-pack command channel — the dashboard publishes "disconnect"
    # or "connect" to home/bms/<pack>/cmd to release a pack for the JK
    # phone app and then hand it back.
    packs_by_id: dict = {}

    def _on_cmd(_c, _u, msg):
        parts = msg.topic.split("/")
        if len(parts) < 4:
            return
        pack = packs_by_id.get(parts[2])
        if pack is None:
            return
        raw = msg.payload.decode("utf-8", errors="replace").strip().lower()
        if raw == "disconnect":
            pack.pause_requested = True
        elif raw == "connect":
            pack.pause_requested = False
        elif raw in ("charge_on", "charge_off",
                     "discharge_on", "discharge_off"):
            # Queue only — the BLE client lives in the pack coroutine, this
            # callback runs on the paho thread.
            reg = (REG_CHARGE_SW if raw.startswith("charge")
                   else REG_DISCHARGE_SW)
            pack.pending_write = (reg, 1 if raw.endswith("_on") else 0)
            log.warning("[%s] cmd %s queued (reg=0x%02X)",
                        pack.pack_id, raw, reg)
            return
        elif raw in ("balancer_on", "balancer_off"):
            pack.pending_write = (REG_BALANCER_SW, 1 if raw.endswith("_on") else 0)
            log.warning("[%s] cmd %s queued (reg=0x%02X)",
                        pack.pack_id, raw, REG_BALANCER_SW)
            return
        elif raw.startswith("bal_start:"):
            # Balancer start voltage, in mV: "bal_start:3400".
            try:
                mv = int(raw.split(":", 1)[1])
            except ValueError:
                log.warning("[%s] bal_start: bad value in %r", pack.pack_id, raw)
                return
            lo, hi = WRITE_LIMITS[REG_BAL_START_V]
            if not lo <= mv <= hi:
                log.warning("[%s] bal_start %d mV outside %d-%d, refused",
                            pack.pack_id, mv, lo, hi)
                return
            pack.pending_write = (REG_BAL_START_V, mv)
            log.warning("[%s] bal_start %d mV queued (reg=0x%02X)",
                        pack.pack_id, mv, REG_BAL_START_V)
            return
        elif raw.startswith("setreg:"):
            # Raw register write — "setreg:<hex reg>:<decimal value>", e.g.
            # "setreg:1F:0". This is the tool for establishing what a register
            # actually does: write it, then diff the SETTINGS hex this daemon
            # logs on every change and see which byte moved. Nothing validates
            # the register, so it can reach a protection threshold — always
            # capture the frame beforehand so the old value can be put back.
            try:
                _, reg_s, val_s = raw.split(":", 2)
                reg, val = int(reg_s, 16), int(val_s)
            except ValueError:
                log.warning("[%s] setreg: cannot parse %r", pack.pack_id, raw)
                return
            if not 0 <= reg <= 0xFF or not 0 <= val <= 0xFFFFFFFF:
                log.warning("[%s] setreg: out of range %r", pack.pack_id, raw)
                return
            pack.pending_write = (reg, val)
            log.warning("[%s] RAW setreg 0x%02X = %d queued — verify by diffing "
                        "the next SETTINGS frame", pack.pack_id, reg, val)
            return
        else:
            log.info("[%s] cmd %s ignored (unknown)", pack.pack_id, raw)
            return
        log.info("[%s] cmd %s -> pause=%s",
                 pack.pack_id, raw, pack.pause_requested)

    mqtt_client.message_callback_add("home/bms/+/cmd", _on_cmd)
    mqtt_client.subscribe("home/bms/+/cmd")
    mqtt_client.loop_start()

    log.info("bringing up %d packs: %s",
             len(PACKS), ", ".join(p["pack_id"] for p in PACKS))

    # Prime BlueZ's device cache with a discover() burst before any
    # pack coroutine touches BleakClient. Without this the first
    # BleakClient(mac_string) fails with "Device not found" because
    # BlueZ doesn't have that MAC's D-Bus object yet — the interactive
    # session that our earlier dev iterations used had already run a
    # scan, but systemd starts us cold. Also snapshots the RSSI each
    # pack advertises with — real-time RSSI over an active GATT link
    # isn't exposed on this BlueZ, so we bank the advert value and let
    # the reconnect path refresh it on each drop.
    log.info("priming BlueZ device cache")
    prime_rssi: dict = {}
    try:
        def _rssi_cb(dev, ad):
            r = getattr(ad, "rssi", None)
            if r is None:
                r = getattr(dev, "rssi", None)
            if isinstance(r, int):
                prime_rssi[dev.address.lower()] = r

        async with BleakScanner(detection_callback=_rssi_cb,
                                scanning_mode="active"):
            await asyncio.sleep(15.0)
        want = {p["mac"].lower() for p in PACKS}
        log.info("scan captured RSSI for %d/%d packs",
                 len(want & prime_rssi.keys()), len(want))
    except Exception as e:
        log.warning("priming scan failed: %s — trying anyway", e)

    packs = [PackState(pack_id=p["pack_id"], mac=p["mac"],
                       write_uuid=p.get("write_uuid", DEFAULT_WRITE),
                       nominal_mah=int(p.get("nominal_mah", 100000)))
             for p in PACKS]
    for p in packs:
        r = prime_rssi.get(p.mac.lower())
        if isinstance(r, int) and -127 <= r <= 20:
            p.ble_rssi_dbm = r
    _load_lifetime(packs, log)
    packs_by_id.update({p.pack_id: p for p in packs})
    tasks = []
    for p in packs:
        # 6 s gap between spawning tasks. RondaYummy uses 3 s but on
        # this Pi (Raspberry Pi 3B, BlueZ 5.66, kernel 6.1) a single
        # BleakClient handshake takes 3-5 s including service discovery,
        # so 3 s puts the next connect right on top of the previous
        # one's finish and every subsequent pack gets "Operation
        # already in progress" from BlueZ. 6 s clears every packs.
        tasks.append(asyncio.create_task(pack_task(p, mqtt_client, log)))
        await asyncio.sleep(6)

    # Whole-daemon health watchdog. If NOTHING is streaming for
    # WATCHDOG_MAX_DRY_S seconds, exit non-zero — systemd's
    # RestartSec=15 restarts us AND the ExecStartPre bounces
    # bluetoothd, which is what clears the "InProgress" state that
    # our own retry loops can't fix. Belt-and-braces safety net for
    # the case where every pack silently stops in lockstep.
    WATCHDOG_MAX_DRY_S = 180
    tasks.append(asyncio.create_task(
        _daemon_watchdog(packs, WATCHDOG_MAX_DRY_S, log)))
    tasks.append(asyncio.create_task(_lifetime_saver(packs, log)))

    try:
        await asyncio.gather(*tasks)
    finally:
        # Flush lifetime counters one last time. The periodic saver
        # writes every LIFETIME_SAVE_S so worst-case data loss on a
        # hard kill is that interval; on graceful shutdown, zero.
        _save_lifetime(packs, log)
        mqtt_client.publish("home/bms/daemon/status", "offline", retain=True)
        mqtt_client.loop_stop()


async def _daemon_watchdog(packs, max_dry_s: int, log) -> None:
    """Exit the process if no pack has produced a valid frame within
    `max_dry_s`. Systemd's ExecStartPre restarts bluetoothd on the
    next boot so we come back clean — this catches the state where
    every pack has silently wedged and per-pack retries aren't helping."""
    import sys
    start = time.time()
    grace_until = start + 60  # let the first-connect flow finish
    while True:
        await asyncio.sleep(15.0)
        now = time.time()
        if now < grace_until:
            continue
        latest = max((p.last_frame_ts for p in packs), default=0)
        if latest == 0 or now - latest > max_dry_s:
            log.error("watchdog: no valid frame for %.0fs — exiting",
                      now - max(latest, start))
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
