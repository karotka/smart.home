# Bill of materials — one module

| # | Part                       | Spec / model                                 | Note |
|---|----------------------------|----------------------------------------------|------|
| 1 | Wemos D1 Mini (ESP8266)    | V4 or clone, 4 MB flash                      | USB-C handy for first flash |
| 2 | DC-DC buck converter       | 60 V→5 V capable: LM2596HV module / MP1584HV | trimmer for fine adjust to 5.0 V |
| 3 | Pack-side connector        | XT30 / WAGO 221 / screw terminal             | depends on existing wiring |
| 4 | Resettable fuse (PTC)      | 100 mA hold / 200 mA trip @ 60 V             | inline on pack + lead |
| 5 | JST-XH 2.54 mm 4-pin       | 1× plug + 1× socket + crimp pins             | for JK GPS port (see `cable.md`) |
| 6 | Logic-level signal wire    | 28 AWG, ~10 cm                               | TX / RX / GND |
| 7 | Power wire pack→buck       | 22 AWG, ~30 cm                               | red / black |
| 8 | Enclosure                  | ABS 60×40×20 mm or 3D printed                | small, near BMS |
| 9 | Heat-shrink, cable ties    | assorted                                     | mechanical strain relief |

Total ≈ ~215 Kč / module at retail, less if from existing stock.

For five modules (one per BMS): ~1100 Kč.


## What to keep an eye on when picking parts

**Buck converter**: cheap LM2596 modules are rated 40 V max input.
Don't use those — at 58 V they explode. Look for one explicitly
labelled 60 V / HV, or use a small synchronous module like the
Mornsun K7805M-2000 (industrial-grade, ~150 Kč, 9-60 V → 5 V @ 2 A).

**Fuse**: PTC is preferred over a glass fuse — at 100 mA hold the PTC
just folds back on a fault and recovers when you fix it, no swap
needed. Look for 60 V rating.

**JST-XH connector**: 4-pin 2.54 mm pitch. JK ships their Bluetooth
dongle on the same connector, so any "JST-XH 4-pin male socket" plus
matching pre-crimped pigtail works.
