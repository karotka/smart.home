#!/usr/bin/make -f

REGISTRY := karotka
DOCKER_NAME := smart-home
DOCKER_BUILD := --no-cache
DOCKER_PATH := $(REGISTRY)/$(DOCKER_NAME):latest

build:
	docker buildx build $(DOCKER_BUILD) -t $(DOCKER_PATH) -f Dockerfile .

run:
	docker run --rm -d -it -p 8000:8000 -v $(shell pwd):/root/project --name $(DOCKER_NAME) $(DOCKER_PATH)

enter:
	docker exec -it `docker ps -qf name=$(DOCKER_NAME)` /bin/bash
