#!/bin/bash
rm -rf /home/pi/.cache/mozilla/
#rm -rf /home/pi/.cache/chromium/
DISPLAY=:0  /usr/bin/firefox http://192.168.0.222/ \
	--kiosk 
	#--noerrdialogs \
	#--disable-session-crashed-bubble \
	#--disable-infobars \
	#--disable-pinch	
