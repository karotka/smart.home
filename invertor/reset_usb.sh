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
  # Look the adapter up by vendor id, NOT via ttyUSB0. The tty number is
  # assigned in plug order, so it is not a reliable pointer to our adapter:
  # on 2026-10-20 a temperature sensor powered from the Pi's USB took ttyUSB0
  # and this script spent the next twelve hours faithfully resetting *it*
  # while the inverter's CH340 sat untouched on ttyUSB1.
  local x
  for x in /sys/bus/usb/devices/*/; do
    if [ "$(cat "$x/idVendor" 2>/dev/null)" = "1a86" ] && [ -e "$x/busnum" ]; then
      # usbreset takes BBB/DDD and the digits must be ZERO-PADDED to three.
      # Given a bare "1/4" it finds no such device and falls through to
      # matching the argument as a product name, which on 2026-10-23 reset the
      # FT232R temperature board instead of the CH341 — while the log
      # cheerfully reported "resetting CH341". `usbreset` with no args prints
      # the table it matches against.
      printf '%03d/%03d\n' "$(cat "$x/busnum")" "$(cat "$x/devnum")"; return
    fi
  done
}

BD=$(resolve)
if [ -n "$BD" ] && [ -e "/dev/bus/usb/$BD" ]; then
  # No fallback to "whatever backs ttyUSB0". On a host where the inverter is
  # the only CH340, ttyUSB0 is something else entirely, and resetting it is
  # both useless and disruptive. If the CH340 is absent there is nothing here
  # to reset: say so and let the daemon fail loudly instead.
  echo "reset_usb: resetting CH341 at bus/dev $BD"
  usbreset "$BD" || true
  sleep 2
else
  echo "reset_usb: no CH341 (1a86:*) on the bus — nothing to reset"
fi
exit 0
