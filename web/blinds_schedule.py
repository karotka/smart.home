#!/usr/bin/env python3
"""Drive the scheduled blinds open or closed, once, for a systemd timer.

    python3 blinds_schedule.py close     # evening
    python3 blinds_schedule.py open      # morning

Which blinds is `[BlindsSchedule] items` in conf/config.ini; when is
service/blinds_close.timer and service/blinds_open.timer. Nothing here
knows a time of day, on purpose — a schedule that is half in a config
file and half in a timer is a schedule nobody can read.

It goes through `methods.blinds_command`, the same call the buttons in the
UI make, rather than opening its own Tuya socket. That matters more than
the few lines it saves: this house has already paid for the same test
living in three files (the grid-voltage bypass check, fixed three times in
one evening), and a second implementation of "close a blind" would drift
from the first the moment a DP code or a retry changed. The command speaks
the `open`/`close` enum on DP 1, which is semantic, so it is right however
a given motor happens to have its position scale inverted.

Run it inside the web container, where tinytuya and the keys already work:

    docker exec -w /root/project smart-home python3 blinds_schedule.py close

Exit status is 1 if any blind refused, so a failure is visible in
`systemctl status` instead of only in a log nobody opens.
"""
import sys
import time

import methods
from config import conf


RETRY_WAIT = 3.0


def drive(blind_id, direction):
    """One blind, one retry. True if it took the command.

    The retry is not superstition: these covers accept a single local
    connection at a time, and the control tab re-polls every 20 s, so a
    command can genuinely arrive while the socket is busy and come back
    refused. Sleeping once and asking again costs three seconds at 22:00
    and converts a flaky failure into a working blind.
    """
    for attempt in (1, 2):
        res = methods.blinds_command(id=blind_id, direction=direction)
        if res.get("ok"):
            print("%-10s %-5s ok (pos=%s, via=%s)"
                  % (blind_id, direction, res.get("position"), res.get("via")))
            return True
        print("%-10s %-5s pokus %d selhal: %s"
              % (blind_id, direction, attempt, res.get("msg")))
        if attempt == 1:
            time.sleep(RETRY_WAIT)
    return False


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("open", "close"):
        sys.exit("pouziti: blinds_schedule.py open|close")
    direction = sys.argv[1]

    ids = conf.BlindsSchedule.items
    if not ids:
        print("[BlindsSchedule] items je prazdne — nic k ovladani")
        return 0

    unknown = [i for i in ids if i not in conf.Blinds.items]
    if unknown:
        # Loudly, not silently: a typo here means a blind that looks
        # scheduled in the config and never moves at night.
        print("NEZNAME rolety v [BlindsSchedule]: %s" % ", ".join(unknown))

    failed = [i for i in ids if not drive(i, direction)]
    print("%s: %d/%d rolet" % (direction, len(ids) - len(failed), len(ids)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
