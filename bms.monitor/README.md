# bms.monitor

WiFi monitoring of JK BMS units (JK BD6A24S10P "Active Balance"). One
small ESP8266 module per BMS, powered straight off the pack it monitors,
streams cell voltages / current / temperatures via HTTP to the local
server every ~30 s.

Independent of the `web/` codebase. The Tornado side will get a
`POST /bms` handler later, but the firmware is decoupled — anything
that accepts JSON on a known URL works.


## Architecture

```
   pack (47-58 V)
        │
        ├── JK BMS  ──UART (GPS port)──► D1 Mini (ESP8266)
        │                                       │
        ├── DC-DC buck 58 V→5 V ────────────────┘  (powers D1)
        │
        ▼
       WiFi → HTTP POST /bms → server.local
                                  │
                                  └── InfluxDB measurement bms_<pack_id>
```

One module = one BMS. Five BMS units in the house → five modules.
Each module has a unique `pack_id` (set in firmware config) it tags
its payloads with.


## Why ESP8266 and not ESP32

- ESP8266 has UART + WiFi, which is all this needs
- Cheaper, simpler, already familiar
- JK BMS communicates over UART (3.3 V logic) — no BLE needed, so ESP8266 suffices
- Slightly lower idle current than ESP32


## Phases

The work splits into three independent steps. Each can be exercised
on its own without the next being ready.

1. **HW** — see `hw/`
   - choose buck / connector / fuse, wire one module, verify D1 boots
     from the pack and the JK GPS port communicates
2. **Firmware** — `firmware/` (later)
   - Arduino IDE sketch (`.ino`), ESP8266 board package
   - JK protocol decoder (open-source reference implementations exist
     as Arduino-compatible libraries)
   - WiFi + HTTP POST + watchdog
3. **Server** — `server/` (latest)
   - Tornado handler `POST /bms`
   - Influx measurement schema
   - Dashboard on `/invertor.html` (or new page)


## Per-pack BMS mapping (current install)

The five BMS units cover eight packs:

| pack_id   | BMS     | Packs                                  |
|-----------|---------|----------------------------------------|
| tesla_pair| BMS #1  | 2× NCR18650PF 14s30p (parallel)        |
| tesla     | BMS #2  | 1× NCR18650PF 14s30p                   |
| samsung   | BMS #3  | 2× Samsung INR 14s20p (parallel)       |
| samsung_e | BMS #4  | 2× Samsung INR18650-30E 14s20p (par.)  |
| lg        | BMS #5  | 1× LG MH1 14s30p                       |


## Goals / non-goals

**Goals**
- See per-cell voltage of each BMS as Influx time-series
- Detect cell drift / failing packs months ahead of system-level decline
- Read-only: never send commands to the BMS

**Non-goals (for now)**
- Active control (turning packs off etc.)
- Battery balancing decisions
- Mobile UI (use existing dashboards)
