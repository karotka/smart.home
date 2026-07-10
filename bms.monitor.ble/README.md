# bms.monitor.ble

BLE-central firmware for the LOLIN D32 (ESP32) that monitors JK BMSes
whose PCB revision doesn't expose UART on the GPS port. One D32 covers
battery-3, battery-4 and battery-5 in parallel; the two older packs
(battery-1, battery-2) stay on the ESP8266 GPS-UART firmware in
`../bms.monitor/`.

## Status

Phase C bring-up in progress. What works:

- WiFi + OTA + MQTT plumbing on a static .1.23 IP, sentinel watchdog
  cloned from the ESP8266 firmware (45 s keep-alive, 180 s soft kick,
  300 s hard restart).
- BLE central state machine: one shared scan → per-pack scan-callback
  match → per-pack `NimBLEClient` with independent connection state.
- Full GATT enumeration of every advertised service (0x1800, 0x1801,
  0xFFE0, 0x180A, 0x180F and the TI-style vendor UUID
  `f000ffc0-0451-4000-b000-000000000000`); every notify characteristic
  we find is subscribed.
- Activation write to 0xFFE2 with the JK header
  `AA 55 90 EB 96 00 …` + sum-mod-256 CRC (0x10). This flips the BMS
  out of its "AT\r\n" keep-alive spam and into 300-byte frame
  responses.
- Frame reassembler that fuses BLE fragments (~128 + 22 bytes on the
  current NimBLE MTU) into complete 300-byte JK messages, gated on
  the leading `55 AA EB 90` header.
- MQTT publisher writing `home/bms/<pack_id>/snapshot` on the same
  schema the `/battery.html` dashboard already consumes.

What still needs work:

- The BD6A24S10P at firmware 15.29 collapses settings + live status
  into a single 300-byte frame under type `0x01` (there is no
  separate type `0x02` cell-info emission on this rev — we tried
  poll commands 0x93, 0x89, 0x98 alongside 0x96 and only 0x96
  elicited a reply, always type 0x01).
- Type `0x03` (device info) is confirmed — model `JK_BD6A24S10P`,
  firmware `15.29`, custom name (e.g. `Battery 5`) all parse cleanly.
- Parser is currently a stub: `parseCellInfo()` reads `total_mv` from
  offset 130 (0x00013880 → 80.000 V for a mid-SOC 24S Li-ion pack,
  cross-checked against expected pack topology) and marks
  `valid=true` so the /battery.html tile renders. Per-cell mV,
  current, SOC, temps and MOS state stay 0 until we pin them
  against a JK-app reading with the D32 in the cabinet.
- Cross-referencing tips for the next session: set
  `DEBUG_HEX_DUMP=true`, capture ~10 frames while pushing the pack
  through several SOC / current states, then look for uint32 fields
  whose values change monotonically with the observed metric.

Cabinet-deployment checklist (once RSSI is healthy):

1. Unplug the ESP8266 UART monitors from battery-1 and battery-2 —
   the D32 covers all five packs.
2. Watch `mosquitto_sub -h .224 -t "home/bms/+/snapshot"` and confirm
   all five packs report `valid=true` within a few seconds.
3. Pin the remaining offsets against the JK app.

## Build + flash

    make build
    make upload                                    # first flash over USB
    make ota   OTA_ADDR=192.168.1.23               # subsequent updates

## Notes

- LOLIN D32 has an internal PCB antenna and lives with a 30-40 cm
  range through concrete — RSSI at the current bench location is
  around -95 dBm which is marginal. Once the ESP32 has a permanent
  home in the battery cabinet the link will be much better.
- Serial monitor at 115200 baud. Autoreset uses RTS only (leave DTR
  high) — pulsing DTR pulls IO0 low and boots into flash mode.
