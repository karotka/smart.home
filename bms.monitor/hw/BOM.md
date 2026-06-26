# Bill of materials — one module

| # | Part                       | Spec / model                                 | Note |
|---|----------------------------|----------------------------------------------|------|
| 1 | Wemos D1 Mini (ESP8266)    | V4 or clone, 4 MB flash                      | USB-C handy for first flash |
| 2 | DC-DC buck converter       | **DCE003 5V fixed** (7-100V in, 2A cont., 96% eff) | 25.5×16.5×7 mm, ~42 Kč ≥10 ks |
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

**Buck converter — DCE003 (recommended)**:
- 7-100 V input, fixed 5 V output, 2 A continuous (3 A peak)
- 96 % efficiency, 1 mA no-load, 1 MHz switching
- 25.5 × 16.5 × 7 mm, non-isolated
- EN pin available for remote disable. **Tie EN to VIN+** for always-on
  operation; some revs of the IC interpret a floating EN as off, so
  don't trust "just leave it" — short it to VIN+ on the board.
- Order the 5 V fixed-output variant; the 9 V / 12 V / 24 V variants of the same module exist for other projects.
- Cheap LM2596 modules without explicit "HV" rating are rated 40 V max — those will explode on a 14S pack. Don't substitute.

**Fuse**: PTC is preferred over a glass fuse — at 100 mA hold the PTC
just folds back on a fault and recovers when you fix it, no swap
needed. Look for 60 V rating.

**JST-XH connector**: 4-pin 2.54 mm pitch. JK ships their Bluetooth
dongle on the same connector, so any "JST-XH 4-pin male socket" plus
matching pre-crimped pigtail works.
