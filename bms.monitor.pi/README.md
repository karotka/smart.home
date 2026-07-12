# bms.monitor.pi

Pi-side BLE central for the JK BD6A24S10P family. Runs on the Pi that
hosts the invertor readout script — it happens to sit ~1 m from the
battery cabinet, so BLE RSSI to every pack is -60 to -70 dBm (better
than any ESP32 we tried).

One `bms_daemon.py` process serves all packs. Each pack gets its own
asyncio coroutine that reconnects on error; on the wire everything is
serialised through the shared BlueZ D-Bus adapter.

## Status

Live for 4 of 5 packs at ~3.8 msg/s each:

* battery-1 (V10.09, JK02\_24S) ✓
* battery-3 (V15.29, JK02\_32S) ✓
* battery-4 (V10.10, JK02\_24S) ✓  — requires JK app reconfig once
  after any factory reset (defaults leave charge/discharge MOSFETs OFF,
  which physically isolates the pack)
* battery-5 (V15.29, JK02\_32S) ✓

battery-2 (V19.27) has a different BLE bridge chip (HM-10-style, emits
`AT\r\n` keep-alive on its notify char instead of the JK02 stream).
Neither 0x96 nor 0x97 activation flips it into transparent mode. Left
in the config so it keeps trying — one nudge sequence away from
working, we just haven't cracked which one yet.

## Files

* `bms_daemon.py` — the daemon. Config is at the top: `MQTT_BROKER`,
  `PACKS_DEFAULT`. Override the pack subset with `BMS_PACKS=battery-3,
  battery-5` when launching.
* `bms-monitor-pi.service` — systemd unit that runs the daemon on boot,
  restart-on-failure with a 15 s hold-off.
* `restart_daemon.sh` — dev helper that kills the running daemon and
  starts a new one with an override pack list. Used only when tuning
  the config; production runs through systemd.

## Install (on the Pi)

    sudo apt install python3-venv
    python3 -m venv ~/bms
    ~/bms/bin/pip install bleak
    # paho-mqtt is available system-wide as python3-paho-mqtt (1.6.1),
    # which is the API the daemon uses — no need to install into venv.

    # copy the daemon + service unit
    cp bms_daemon.py       ~/
    sudo cp bms-monitor-pi.service /etc/systemd/system/

    sudo systemctl daemon-reload
    sudo systemctl enable --now bms-monitor-pi.service
    journalctl -u bms-monitor-pi.service -f

## Dev iteration

    # kill + restart with a subset, for tuning
    BMS_PACKS=battery-3 ./restart_daemon.sh
    tail -f /tmp/bms_run.log

## Notes

* Layout tables and offsets are ported from
  `bms.monitor.ble/bms_monitor_ble/bms_monitor_ble.ino` — same magic
  values, same auto-detect between JK02\_24S / JK02\_32S based on the
  cell-mask bit pattern.
* Activation is the two-shot recipe (`0x96` then `0x97` with a 150 ms
  gap) we found on the ESP32 side. After that we just receive
  unsolicited type-0x02 broadcasts; a periodic 0x97 nudge fires when
  the stream has been dry for 15 s.
* The 3 s sleep between spawning per-pack coroutines is not just
  polish — parallel `BleakClient.__aenter__` calls silently return
  "empty error" on BlueZ. See the RondaYummy/bms-monitor-ble project
  for the pattern this is copied from.
