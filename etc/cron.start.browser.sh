#!/bin/bash

if [[ ! $(pgrep -f firefox-esr)  ]]; then
    /bin/bash /home/pi/smart.home/etc/browser start
fi

