"""Re-discover current IPs of every Tuya device after a DHCP shuffle.

Listens for Tuya broadcasts on UDP 6666/6667 long enough to catch
each device, then maps device-id to current IP. When --write is set
we patch conf/snapshot.json in place — the web app's lazy reload
(mtime-watched on conf.Tuya) picks up the new IPs on next access,
no container restart needed.

Designed to be invoked by a systemd .timer (see
service/tuya_rediscover.timer); the per-run cost is one ~12 s
broadcast listen and a stat() call from the web app, so we can run
it hourly without weighing on checker.py's 15 s tick.

Usage:
  python3 tuya_rediscover.py                 # report only
  python3 tuya_rediscover.py --write          # update snapshot.json
"""
import json
import os
import sys
import tinytuya

# Resolved relative to the script so the timer can call us with cwd /.
SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "conf", "snapshot.json",
)
HP_DEVICE_ID = "bf06f140ee20807fdaalyq"


def main():
    write = "--write" in sys.argv

    with open(SNAPSHOT_PATH) as f:
        snap = json.load(f)
    by_id = {d["id"]: d for d in snap.get("devices", [])}

    print("=== Scanning LAN for Tuya broadcasts (12 s) ===")
    # maxretry around 12 has been enough to catch every responsive
    # device we have; raising it isn't free (each retry is a fresh
    # listen window) so 12 is the sweet spot.
    found = tinytuya.deviceScan(verbose=False, maxretry=12)
    found_by_id = {}
    for ip, dev in found.items():
        did = dev.get("gwId") or dev.get("id")
        if did:
            found_by_id[did] = ip
    print("found %d unique device(s) on the wire" % len(found_by_id))
    print()

    changes = []
    for did, dev in by_id.items():
        old_ip = dev.get("ip")
        new_ip = found_by_id.get(did)
        name = dev.get("name", "?")
        if new_ip and new_ip != old_ip:
            marker = " (HEAT PUMP)" if did == HP_DEVICE_ID else ""
            print("CHANGE  %-28s %s -> %s%s" % (name[:28], old_ip, new_ip, marker))
            changes.append((did, old_ip, new_ip))
            dev["ip"] = new_ip
        elif new_ip:
            print("same    %-28s %s" % (name[:28], old_ip))
        else:
            print("missing %-28s last=%s (not seen on wire)" % (name[:28], old_ip))

    for did, ip in found_by_id.items():
        if did not in by_id:
            pkey = found.get(ip, {}).get("productKey", "?")
            print("new     id=%s ip=%s pkey=%s" % (did, ip, pkey))

    print()
    print("%d device(s) need an IP update" % len(changes))
    if not changes:
        return
    if write:
        with open(SNAPSHOT_PATH, "w") as f:
            json.dump(snap, f, indent=4, ensure_ascii=False)
        print("snapshot.json updated (mtime bump signals lazy reload in web app)")
    else:
        print("(dry run — re-run with --write to persist)")


if __name__ == "__main__":
    main()
