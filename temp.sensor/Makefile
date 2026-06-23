# temp.sensor — ESP8266 + BME280 publishing to smart-home /sensorTemp.
#
# Replaces the old makeEspArduino.mk include with arduino-cli, so a clean
# Mac/Linux box can build it after `brew install arduino-cli` + one core
# install + two libs. First flash on any board must go over USB-UART; from
# then on `make ota OTA_ADDR=<ip>` pushes new firmware over WiFi using the
# OTA_PASSWORD baked into config.h.

SKETCH       := temp.sensor.ino
FQBN         := esp8266:esp8266:nodemcuv2
BUILD_DIR    := build

# Auto-detect the first plausible USB-UART when one is plugged in.
# Override with `make upload UPLOAD_PORT=/dev/cu.usbserial-XYZ` if needed.
UPLOAD_PORT  ?= $(firstword $(wildcard /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART))
UPLOAD_SPEED ?= 460800

# OTA: pass OTA_ADDR=192.168.0.12 (or temp-<chipid>.local with avahi).
OTA_ADDR     ?=
OTA_PASS     ?= heslicko12345

# espota.py ships with the ESP8266 core; the version directory varies,
# pick the first one that exists.
ESPOTA       := $(firstword $(wildcard $(HOME)/Library/Arduino15/packages/esp8266/hardware/esp8266/*/tools/espota.py))

.PHONY: build upload ota clean help

build:
	arduino-cli compile --fqbn $(FQBN) --build-path $(BUILD_DIR) .

upload: build
	@test -n "$(UPLOAD_PORT)" || \
		(echo "no USB serial detected; set UPLOAD_PORT=/dev/cu.xxx" && exit 1)
	arduino-cli upload --fqbn "$(FQBN):baud=$(UPLOAD_SPEED)" \
		-p $(UPLOAD_PORT) --input-dir $(BUILD_DIR) .

ota: build
	@test -n "$(OTA_ADDR)" || (echo "set OTA_ADDR=<ip-or-hostname>" && exit 1)
	@test -n "$(ESPOTA)" || (echo "espota.py not found; check ESP8266 core install" && exit 1)
	python3 $(ESPOTA) -i $(OTA_ADDR) -p 8266 -a $(OTA_PASS) \
		-f $(BUILD_DIR)/$(SKETCH).bin

clean:
	rm -rf $(BUILD_DIR)

help:
	@echo "Targets:"
	@echo "  make build                          — compile firmware"
	@echo "  make upload                         — flash via USB (autodetects /dev/cu.*)"
	@echo "  make ota OTA_ADDR=192.168.0.12      — push firmware over WiFi"
	@echo "  make clean                          — wipe build/"
