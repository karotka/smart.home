#!/usr/bin/make -f

REGISTRY := karotka
DOCKER_NAME := smart-home
DOCKER_BUILD := --no-cache
# Default to the locally-built image. The karotka/* registry tag is arm/v7
# (legacy Pi3 build) and won't run on the amd64 .224 host without an
# emulator, so `make run` would silently pull the wrong arch and crash.
# Override with `make run DOCKER_PATH=$(REGISTRY)/$(DOCKER_NAME):latest`
# only if you've explicitly built a matching-arch image for the registry.
DOCKER_PATH := $(DOCKER_NAME):latest

build:
	docker buildx build $(DOCKER_BUILD) -t $(DOCKER_PATH) -f Dockerfile .

build-bullseye:
	docker buildx build $(DOCKER_BUILD) -t $(DOCKER_PATH) -f Dockerfile.bullseye .

run:
	# Host port 8001 is what nginx on .222 proxies to; container still
	# listens on 8000 internally (gunicorn). Keep the public-facing port
	# stable across rebuilds.
	docker run -d --restart=always -it -p 8001:8000 \
		-e TZ=Europe/Prague \
		-v /etc/localtime:/etc/localtime:ro \
		-v $(shell pwd):/root/project \
		--name $(DOCKER_NAME) $(DOCKER_PATH)
	#docker run --rm -p 8000:8000 -v $(shell pwd):/root/project --name $(DOCKER_NAME) $(DOCKER_PATH) /bin/bash 2>&1 > log/smart-home_log

enter:
	docker exec -it `docker ps -qf name=$(DOCKER_NAME)` /bin/bash
