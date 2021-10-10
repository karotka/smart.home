/*global WebSocket, $, window, console, alert, Blob, saveAs*/
"use strict";

/**
 * Function calls across the background TCP socket. Uses JSON RPC + a queue.
 */
var client = {
    queue: {},
    led_on: false,

    // Connects to Python through the websocket
    connect: function (port) {
        var self = this;
        this.socket = new WebSocket("ws://" + window.location.hostname + ":" + port + "/websocket");

        this.socket.onopen = function () {
            console.log("Connected!");
        };

        this.socket.onmessage = function (messageEvent) {
            var router, current, updated, jsonRpc;

            jsonRpc = JSON.parse(messageEvent.data);
            router = self.queue[jsonRpc.id];
            delete self.queue[jsonRpc.id];
            self.result = jsonRpc.result;

            // Alert on error
            if (jsonRpc.error) {
                alert(jsonRpc.result);

            // server response handling
            } else if (router === "heating") {
                $("#heating_temp").html("(" + self.result + " C)");

            // No other functions should exist
            } else {
                alert("Unsupported function: " + router);
            }
        };
    },

    // Generates a unique identifier for request ids
    // Code from http://stackoverflow.com/questions/105034/
    // how-to-create-a-guid-uuid-in-javascript/2117523#2117523
    uuid: function () {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            var r = Math.random()*16|0, v = c == 'x' ? r : (r&0x3|0x8);
            return v.toString(16);
        });
    },

    heating: function (id, direction) {
        var uuid = this.uuid();
        this.socket.send(
            JSON.stringify( {
                method: "heating",
                id: uuid,
                params: {id : id, direction: direction}}));
        this.queue[uuid] = "heating";
    }
};
