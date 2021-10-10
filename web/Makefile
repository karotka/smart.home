#!/usr/bin/make -f

REGISTRY := docker
DOCKER_NAME := smart-home
DOCKER_BUILD := --no-cache
DOCKER_PATH := $(REGISTRY)/$(DOCKER_NAME):latest

build-docker:
	docker build $(DOCKER_BUILD) -t $(DOCKER_PATH) .

run:
	docker run -it --rm -p 8000:8000 -v $(shell pwd):/root/project  --name smart-home-web docker/smart-home
