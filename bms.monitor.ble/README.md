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

- The BD6A24S10P at firmware 15.29 replies to command `0x96` with
  frame type `0x01` (settings/status). Neither `0x93`, `0x89` nor
  `0x98` elicit a type `0x02` reply — this BMS likely never emits
  cell info under the offsets `syssi/esphome-jk-bms` documents.
- Type `0x03` (device info) is confirmed working — the model name
  (`JK_BD6A24S10P`), firmware version (`15.29`) and custom name
  (`Battery 5`) parse out of the 300-byte payload.
- Cell voltages / current / SOC need offset re-pinning against JK
  app readings. Turn `DEBUG_HEX_DUMP` on in `config.h` to dump full
  frames on the USB serial and cross-reference.

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
