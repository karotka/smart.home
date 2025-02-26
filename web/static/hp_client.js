/*global WebSocket, $, window, console, alert, Blob, saveAs*/
"use strict";

/**
 * Function calls across the background TCP socket. Uses JSON RPC + a queue.
 */
var hpClient = {
    queue: {},
    connected: false,

    // Connects to Python through the websocket
    connect: function (port) {
        var self = this;

        if (port) {
            var port = ":" + port;
        }
        var wsUrl = "wss://" + window.location.hostname + port + "/websocket";
        this.socket = new WebSocket(wsUrl);
        
        this.socket.onopen = function () {
            console.log("Connected!");
            hpClient.connected = true;
            hpClient.heatPumpLoad();
            hpClient.headpump_hourlyCharts();
        };

        this.socket.onclose = function(e) {
            console.log('Socket is closed. Reconnect will be attempted in 1 second.', e.reason);
            setTimeout(function() {
                hpClient.connect("");
            }, 1000);
        };

        this.socket.onerror = function(err) {
            console.error('Socket encountered error: ', err.message, 'Closing socket');
            this.socket.close();
        };

        this.headpump_button = function(data) {
            if (data[1] == true) {
                gEl('hp_on').style.backgroundColor="#ff6746";
            } else {
                gEl('hp_on').style.backgroundColor="#555555";
            }

            if (data[2] == "mute") {
                gEl('hp_mute').style.backgroundColor="#ff6746";
                gEl('hp_smart').style.backgroundColor="#555555";
                gEl('hp_strong').style.backgroundColor="#555555";
            } else 
            if (data[2] == "smart") {
                gEl('hp_mute').style.backgroundColor="#555555";
                gEl('hp_smart').style.backgroundColor="#ff6746";
                gEl('hp_strong').style.backgroundColor="#555555";
            } else
            if (data[2] == "strong") {
                gEl('hp_mute').style.backgroundColor="#555555";
                gEl('hp_smart').style.backgroundColor="#555555";
                gEl('hp_strong').style.backgroundColor="#ff6746";
            }

            if (data[5] == "heat") {
                gEl('hp_heat').style.backgroundColor="#ff6746";
                gEl('hp_cool').style.backgroundColor="#555555";
            } else {
                gEl('hp_heat').style.backgroundColor="#555555";
                gEl('hp_cool').style.backgroundColor="#ff6746";
            }
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
            //console.log(router);
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

                //console.log(self.result.hpTuyaData);
                gEl('hp_targetTemp').value = self.result.heatingTargetWaterTemp;
                hpClient.headpump_button(self.result.hpTuyaData);

            } else
            if (router === "headpump_hourlyCharts") {
                self.result.data1.forEach(item => {
                    dps5.push({x: new Date(item.x),y: item.y});
                });
                chart4.render();
                dps5 = [];

            } else
            if (router === "heatpump_setOnOff") {
                //console.log(self.result);
                hpClient.headpump_button(self.result.hpTuyaData);
                //gEl('hp_targetTemp').value = self.result.temperature;

            } else  
            if (router === "heatpump_setMode") {
                hpClient.headpump_button(self.result.hpTuyaData);
                //console.log(self.result);

            } else
            if (router === "heatpump_setWorkMode") {
                hpClient.headpump_button(self.result.hpTuyaData);
                //console.log(self.result);

            } else
            if (router === "heatpump_setTemp") {
                //console.log(self.result.temperature);
                gEl('hp_targetTemp').value = self.result.temperature;

            } else
            if (router === "heatpump_status") {
                gEl('hp_cc').value = self.result.hpTuyaData[112] + "A";

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
        hpClient.socket.send(
            JSON.stringify( {
                method: "chart_heat_pump_load",
                id : "",
                router: "chart_head_pump_load",
                params: {}}));
    },

    headpump_hourlyCharts: function () {
        hpClient.socket.send(
            JSON.stringify( {
                method: "headpump_hourlyCharts",
                id : "",
                router: "headpump_hourlyCharts",
                params: {}}));
    },

    heatpump_setTemp: function (direction) {
        hpClient.socket.send(
            JSON.stringify( {
                method: "heatpump_setTemp",
                id : "",
                router: "heatpump_setTemp",
                params: {direction : direction}}));
    },

    heatpump_setOnOff: function () {
        hpClient.socket.send(
            JSON.stringify( {
                method: "heatpump_setOnOff",
                id : "",
                router: "heatpump_setOnOff",
                params: {} }));
    },

    heatpump_setMode: function (mode) {
        hpClient.socket.send(
            JSON.stringify( {
                method: "heatpump_setMode",
                id : "",
                router: "heatpump_setMode",
                params: {mode : mode}}));
    },

    heatpump_setWorkMode: function (mode) {
        hpClient.socket.send(
            JSON.stringify( {
                method: "heatpump_setWorkMode",
                id : "",
                router: "heatpump_setWorkMode",
                params: {mode : mode}}));
    },

    heatpump_status: function () {
        hpClient.socket.send(
            JSON.stringify( {
                method: "heatpump_status",
                id : "",
                router: "heatpump_status",
                params: {}}));
    },
};
