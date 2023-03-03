/*global WebSocket, $, window, console, alert, Blob, saveAs*/
"use strict";

/**
 * Function calls across the background TCP socket. Uses JSON RPC + a queue.
 */
var client = {
    queue: {},

    // Connects to Python through the websocket
    connect: function (port) {
        var self = this;

        if (port) {
            var port = ":" + port;
        }
        var wsUrl = "ws://" + window.location.hostname + port + "/websocket";
        this.socket = new WebSocket(wsUrl);
        
        this.socket.onopen = function () {
            console.log("Connected!");
            setInterval(client.load, 1000);
        };

        this.socket.onclose = function(e) {
            console.log('Socket is closed. Reconnect will be attempted in 1 second.', e.reason);
            setTimeout(function() {
                client.connect("");
            }, 1000);
        };

        this.socket.onerror = function(err) {
            console.error('Socket encountered error: ', err.message, 'Closing socket');
            try {
                this.socket.close();
            } catch (error) {}
        };

        this.socket.onmessage = function (messageEvent) {
            var router, current, updated, jsonRpc;
            jsonRpc = JSON.parse(messageEvent.data);

	        if (jsonRpc.router == "") {
                router = self.queue[jsonRpc.id];
                delete self.queue[jsonRpc.id];
            } else {
                router = jsonRpc.router;
            }
            self.result = jsonRpc.result;
            // Alert on error
            if (jsonRpc.error) {

            // server response handling
            } else if (router === "load") {
                //displ = window.displ;
                //displ.show(self.result.data);

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
        return 'xxxxxxxx-xaaa-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            var r = Math.random()*16|0, v = c == 'x' ? r : (r&0x3|0x8);
            return v.toString(16);
        });
    },

    load: function () {
        if (client.socket.readyState == 1) {
            client.socket.send(
                JSON.stringify( {
                    method: "invertor_load",
                    id : "",
                    router: "load",
                    params: {}}));
        }
    },

};
