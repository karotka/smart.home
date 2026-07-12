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
from dataclasses import dataclass, field
from typing import Optional

from bleak import BleakClient, BleakScanner
import paho.mqtt.client as mqtt

MQTT_BROKER = "192.168.0.224"
MQTT_PORT = 1883

# BMS list. MACs are the primary key — bleak's find-by-name path is
# unreliable on Pi 3 BlueZ, and `BleakClient(mac_string)` tolerates
# the same edge cases while doing its own device lookup.
PACKS_DEFAULT = [
    {"pack_id": "battery-3", "mac": "C8:47:80:03:51:55"},
    {"pack_id": "battery-5", "mac": "C8:47:80:1D:C2:EA"},
    {"pack_id": "battery-1", "mac": "C8:47:8C:E8:24:7E"},
    {"pack_id": "battery-2", "mac": "28:D4:1E:6A:EF:21"},  # HM-10 bridge
    {"pack_id": "battery-4", "mac": "C8:47:8C:E9:1C:DA"},
]

_env = os.environ.get("BMS_PACKS", "").strip()
if _env:
    _wanted = {n.strip() for n in _env.split(",") if n.strip()}
    PACKS = [p for p in PACKS_DEFAULT if p["pack_id"] in _wanted]
else:
    PACKS = PACKS_DEFAULT

JK_NOTIFY = "0000ffe1-0000-1000-8000-00805f9b34fb"
JK_WRITE = "0000ffe2-0000-1000-8000-00805f9b34fb"
JK_HEADER = bytes([0x55, 0xAA, 0xEB, 0x90])
JK_FRAME_SIZE = 300


def _cmd_frame(cmd: int) -> bytes:
    """20-byte JK request: `AA 55 90 EB <cmd> 00×14 <crc>`, crc = sum mod 256."""
    b = bytearray([0xAA, 0x55, 0x90, 0xEB, cmd] + [0] * 15)
    b[19] = sum(b[:19]) & 0xFF
    return bytes(b)


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


LAYOUT_32S = Layout("JK02_32S", 32, 70, 74, 76, 80,
                    144, 162, 164, 150, 158, 173, 174, 182)
LAYOUT_24S = Layout("JK02_24S", 24, 54, 58, 60, 64,
                    130, 132, 134, 118, 126, 141, 142, 150)


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
        "charge_mos": False,
        "discharge_mos": False,
        "balancing": struct.unpack_from("<H", buf, L.cell_delta)[0] > 20,
        "layout": L.name,
    }


@dataclass
class PackState:
    pack_id: str
    mac: str
    buf: bytearray = field(default_factory=bytearray)
    last_frame_ts: float = 0


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
        if ftype == 0x02:
            snap = parse_cell_info(bytes(pack.buf))
            if snap is not None:
                snap["pack_id"] = pack.pack_id
                snap["ts"] = time.time()
                pack.last_frame_ts = snap["ts"]
                mqtt_client.publish(
                    f"home/bms/{pack.pack_id}/snapshot",
                    json.dumps(snap), retain=True)
        pack.buf.clear()

    return _handle


async def pack_task(pack: PackState, mqtt_client, log):
    """One coroutine per pack. Reconnect loop with exponential backoff
    on error, watchdog that drops the link if broadcasts stop for
    30 s. Nudge poll (0x97) once we've been dry for 15 s so packs
    whose broadcast stream falters silently get restarted without a
    full disconnect."""
    backoff = 5
    while True:
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
                    JK_WRITE, _cmd_frame(0x96), response=False)
                await asyncio.sleep(0.15)
                await client.write_gatt_char(
                    JK_WRITE, _cmd_frame(0x97), response=False)
                pack.last_frame_ts = time.time()
                log.info("[%s] streaming", pack.pack_id)
                backoff = 5

                while client.is_connected:
                    await asyncio.sleep(2.0)
                    dry = time.time() - pack.last_frame_ts
                    if dry > 30:
                        log.warning(
                            "[%s] stall %.0fs — dropping",
                            pack.pack_id, dry)
                        break
                    if dry > 15:
                        try:
                            await client.write_gatt_char(
                                JK_WRITE, _cmd_frame(0x97), response=False)
                        except Exception as e:
                            log.warning("[%s] nudge failed: %s",
                                        pack.pack_id, e)
            log.info("[%s] disconnected", pack.pack_id)
        except Exception as e:
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
    mqtt_client.loop_start()

    log.info("bringing up %d packs: %s",
             len(PACKS), ", ".join(p["pack_id"] for p in PACKS))

    # Prime BlueZ's device cache with a discover() burst before any
    # pack coroutine touches BleakClient. Without this the first
    # BleakClient(mac_string) fails with "Device not found" because
    # BlueZ doesn't have that MAC's D-Bus object yet — the interactive
    # session that our earlier dev iterations used had already run a
    # scan, but systemd starts us cold.
    log.info("priming BlueZ device cache")
    try:
        found = await BleakScanner.discover(timeout=15.0,
                                             scanning_mode="active")
        want = {p["mac"].lower() for p in PACKS}
        seen = {d.address.lower() for d in found}
        log.info("scan saw %d devices, %d of our %d packs present",
                 len(found), len(seen & want), len(want))
    except Exception as e:
        log.warning("priming scan failed: %s — trying anyway", e)

    packs = [PackState(pack_id=p["pack_id"], mac=p["mac"]) for p in PACKS]
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

    try:
        await asyncio.gather(*tasks)
    finally:
        mqtt_client.publish("home/bms/daemon/status", "offline", retain=True)
        mqtt_client.loop_stop()


if __name__ == "__main__":
    asyncio.run(main())
