#!/usr/bin/make -f

REGISTRY := karotka
DOCKER_NAME := smart-home
DOCKER_BUILD := --no-cache
DOCKER_PATH := $(REGISTRY)/$(DOCKER_NAME):latest

build:
	docker buildx build $(DOCKER_BUILD) -t $(DOCKER_PATH) -f Dockerfile .

build-bullseye:
	docker buildx build $(DOCKER_BUILD) -t $(DOCKER_PATH) -f Dockerfile.bullseye .

run:
	docker run --rm -d --restart=always -it -p 8000:8000 -v $(shell pwd):/root/project --name $(DOCKER_NAME) $(DOCKER_PATH)
	#docker run --rm -p 8000:8000 -v $(shell pwd):/root/project --name $(DOCKER_NAME) $(DOCKER_PATH) /bin/bash 2>&1 > log/smart-home_log

enter:
	docker exec -it `docker ps -qf name=$(DOCKER_NAME)` /bin/bash
