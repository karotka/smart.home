# bms.monitor.ble — one LOLIN D32 talking to 3 JK BMSes over BLE.
#
# First-flash: `make upload` over USB. From then on `make ota
# OTA_ADDR=192.168.1.NN` pushes the new firmware over WiFi using
# the OTA_PASSWORD baked into secrets.h.

SKETCH    := bms_monitor_ble.ino
FQBN      := esp32:esp32:d32
BUILD_DIR := build

# Bump NimBLE's max central connections from the 3-slot arduino
# default to 9 so a single D32 can cover the whole battery cabinet
# (5 packs today, headroom for expansion). NimBLE reads this from
# nimconfig.h behind an `#ifndef` guard — the -D on the cpp
# command line wins.
BUILD_FLAGS := -DCONFIG_BT_NIMBLE_MAX_CONNECTIONS=9 \
               -DCONFIG_BT_NIMBLE_MAX_BONDS=9 \
               -DCONFIG_BT_NIMBLE_MAX_CCCDS=9 \
               -DCONFIG_BT_NIMBLE_L2CAP_COC_MAX_NUM=9 \
               -DCONFIG_BT_NIMBLE_ATT_PREFERRED_MTU=200

UPLOAD_PORT  ?= $(firstword $(wildcard /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART))
UPLOAD_SPEED ?= 921600

OTA_ADDR  ?=
OTA_PASS  ?= heslicko12345
ESPOTA    := $(firstword $(wildcard $(HOME)/Library/Arduino15/packages/esp32/hardware/esp32/*/tools/espota.py))

.PHONY: build upload monitor ota clean help

build:
	arduino-cli compile --fqbn $(FQBN) --build-path $(BUILD_DIR) \
		--build-property "compiler.cpp.extra_flags=$(BUILD_FLAGS)" \
		bms_monitor_ble

upload: build
	@test -n "$(UPLOAD_PORT)" || \
		(echo "no USB serial detected; set UPLOAD_PORT=/dev/cu.xxx" && exit 1)
	arduino-cli upload --fqbn "$(FQBN)" \
		-p $(UPLOAD_PORT) --input-dir $(BUILD_DIR) bms_monitor_ble

monitor:
	@test -n "$(UPLOAD_PORT)" || (echo "set UPLOAD_PORT" && exit 1)
	arduino-cli monitor -p $(UPLOAD_PORT) -c baudrate=115200

ota: build
	@test -n "$(OTA_ADDR)" || (echo "set OTA_ADDR=<ip>" && exit 1)
	@test -n "$(ESPOTA)"   || (echo "espota.py not found; check esp32 core install" && exit 1)
	python3 $(ESPOTA) -i $(OTA_ADDR) -p 3232 -a $(OTA_PASS) \
		-f $(BUILD_DIR)/$(SKETCH).bin

clean:
	rm -rf $(BUILD_DIR)

help:
	@echo "make build                          — compile"
	@echo "make upload                         — flash via USB (autodetects port)"
	@echo "make monitor                        — serial monitor 115200 baud"
	@echo "make ota OTA_ADDR=192.168.1.NN      — push over WiFi"
