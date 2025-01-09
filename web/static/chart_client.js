/*global WebSocket, $, window, console, alert, Blob, saveAs*/
"use strict";

/**
 * Function calls across the background TCP socket. Uses JSON RPC + a queue.
 */
var chartClient = {
    queue: {},
    connected: false,

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
            chartClient.connected = true;
            chartClient.heatPumpLoad();
        };

        this.socket.onclose = function(e) {
            console.log('Socket is closed. Reconnect will be attempted in 1 second.', e.reason);
            setTimeout(function() {
                chartClient.connect("");
            }, 1000);
        };

        this.socket.onerror = function(err) {
            console.error('Socket encountered error: ', err.message, 'Closing socket');
            this.socket.close();
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


            } else
            if (router === "chart_head_pump_load") {
                self.result.data1.forEach(item => {
                    dps1.push({x: new Date(item.x),y: item.y});
                });
                chart1.render();
                dps1 = [];

                self.result.data2.forEach(item => {
                    dps2.push({x: new Date(item.x),y: item.y});
                });
                chart2.render();
                dps2 = [];
                
                self.result.data3.forEach(item => {
                    dps3.push({x: new Date(item.x),y: item.y});
                });
                self.result.data4.forEach(item => {
                    dps4.push({x: new Date(item.x),y: item.y});
                });
                chart3.render();
                dps3 = [];
                dps4 = [];


            } else {
                // No other functions should exist
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

    heatPumpLoad: function () {
        chartClient.socket.send(
            JSON.stringify( {
                method: "chart_heat_pump_load",
                id : "",
                router: "chart_head_pump_load",
                params: {}}));
    },

};
