#!/bin/bash
# Re-enumerate the CH341 USB-serial adapter backing /dev/ttyUSB0 so a wedged
# adapter comes back clean before the invertor daemon opens it. The CH341 chip
# occasionally wedges across a daemon restart (reads return empty forever until a
# full reboot) — a USB reset re-enumerates it, same as a reboot but just this port.
#
# Wired as `ExecStartPre=+-/home/pi/smart.home/invertor/reset_usb.sh` in the unit:
#   +  run as root (usbreset needs it; the service itself runs as pi)
#   -  ignore failure — this must NEVER block the daemon from starting.
# Hence it always exits 0.

resolve() {   # print "BUS/DEV" for the CH341, or nothing
  local d
  d=$(readlink -f /sys/class/tty/ttyUSB0/device 2>/dev/null)
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -e "$d/busnum" ]; do d=$(dirname "$d"); done
  if [ -e "$d/busnum" ]; then
    echo "$(cat "$d/busnum")/$(cat "$d/devnum")"; return
  fi
  # fallback (ttyUSB0 gone): find the adapter by vendor id 1a86 (CH340/CH341)
  local x
  for x in /sys/bus/usb/devices/*/; do
    if [ "$(cat "$x/idVendor" 2>/dev/null)" = "1a86" ] && [ -e "$x/busnum" ]; then
      echo "$(cat "$x/busnum")/$(cat "$x/devnum")"; return
    fi
  done
}

BD=$(resolve)
if [ -n "$BD" ]; then
  echo "reset_usb: resetting CH341 at bus/dev $BD"
  usbreset "$BD" || true
  sleep 2
else
  echo "reset_usb: CH341 not found, skipping"
fi
exit 0
