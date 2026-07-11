# bms.monitor.ble

BLE-central firmware for the LOLIN D32 (ESP32) that monitors JK BMSes
whose PCB revision doesn't expose UART on the GPS port, plus revisions
where the UART link proved flaky. This D32 covers **battery-1**,
**battery-3** and **battery-4**; battery-2 stays on its ESP8266
GPS-UART monitor in `../bms.monitor/`, and battery-5 will move to a
second D32 running this same firmware.

## Status

Working end-to-end. Live pack voltage, per-cell mV, current, SoC,
cycle count, remaining capacity and temperatures reach the dashboard
under 600 ms after the BMS emits a fresh frame.

Recognised firmware revisions and their frame layouts:

* **JK02\_32S** — firmware V15.29 (BD6A24S10P, battery-3). 32 cell
  slots @ 6..69, mask @ 70, `total_mv` @ 150, `current_mA` @ 158,
  temps @ 144/162/164, SoC @ 173, cycle @ 182.
* **JK02\_24S** — firmware V10.09/V10.10 (battery-1, battery-4).
  24 cell slots @ 6..53, mask @ 54, everything after the resistance
  block shifts -32 bytes vs 32S: `total_mv` @ 118, `current_mA` @ 126,
  temps @ 130/132/134, SoC @ 141, cycle @ 150.

`parseCellInfo()` picks the layout at runtime by validating the mask
byte position: JK cell masks are the low N bits set contiguously
(`0x0000_3FFF` = 14 cells), so a cell-resistance byte accidentally
landing on the mask offset is easy to reject.

Everything else:

* WiFi + OTA + MQTT plumbing on a static .1.23 IP, sentinel watchdog
  cloned from the ESP8266 firmware (45 s keep-alive, 180 s soft kick,
  300 s hard restart).
* BLE central state machine: one shared scan → per-pack scan-callback
  match (by MAC first, then by advertised device name — some JK revs
  rotate their public MAC after a reset). Low-duty active scan
  (interval 1600, window 32, active) keeps enough air time for the
  existing GATT connections while still catching scan responses that
  carry the device name.
* Rotation gate is dormant when `PACK_COUNT == BLE_MAX_ACTIVE == 3`;
  it only evicts the oldest connection when a fourth pack is actually
  waiting for a slot.
* Frame reassembler that fuses BLE fragments (~128 + 22 bytes on the
  current NimBLE MTU) into complete 300-byte JK messages, gated on
  the leading `55 AA EB 90` header.
* MQTT publisher writing `home/bms/<pack_id>/snapshot` on the same
  schema `/battery.html` already consumes, plus HTTP POST to `/bms`
  every 30 s for Influx.

Nice-to-haves left for later:

* Actual MOSFET charge/discharge state bits and the balance bitmap.
  Right now `charge_mos` / `discharge_mos` are always false and
  `balancing` falls back to `delta > 20 mV`. Enough for the dashboard,
  short on protection-flag detail if a pack starts throwing errors.

## Debugging a new firmware rev

Set `DEBUG_HEX_DUMP = true` in `bms_monitor_ble.ino` and re-flash.
Every complete 300 B frame is published on
`home/bms/debug/hex/<pack>/cmd<XX>_type<YY>` — the `cmd` byte is the
poll we sent right before the reply, `type` is the reply frame type
(0x01 settings, 0x02 cell info, 0x03 device info). Grep for a known
value (e.g. cell mV as LE hex) to pin offsets, then extend the
`Layout` table.

## Build + flash

    make build
    make upload                                    # first flash over USB
    make ota   OTA_ADDR=192.168.1.23               # subsequent updates

## Notes

* LOLIN D32 has an internal PCB antenna; at the current permanent
  location in the cabinet RSSI is around -60 to -75 dBm which is
  fine.
* Serial monitor at 115200 baud. Autoreset uses RTS only (leave DTR
  high) — pulsing DTR pulls IO0 low and boots into flash mode.
* If OTA stops responding while BLE is heavily loaded, physically
  reset the board — the espota UDP handler can starve under long
  service-discovery bursts and won't reply to the invitation.
