/*global WebSocket, window, console, alert*/
"use strict";

// Chart-only WebSocket client for /heat_pump_chart.html.
// Split out of hp_client.js so the control page doesn't carry any
// chart/render code it never needs.
var hpChartClient = {
    connected: false,

    connect: function (port) {
        var self = this;
        var p = port ? ":" + port : "";
        this.socket = new WebSocket("wss://" + window.location.hostname + p + "/websocket");

        this.socket.onopen = function () {
            console.log("Connected (charts)!");
            hpChartClient.connected = true;
            hpChartClient.heatPumpLoad();
            hpChartClient.heatpump_hourlyCharts();
        };

        this.socket.onclose = function (e) {
            console.log("Socket closed, retrying in 1s.", e.reason);
            setTimeout(function () { hpChartClient.connect(""); }, 1000);
        };

        this.socket.onerror = function (err) {
            console.error("Socket error: ", err && err.message);
            this.socket.close();
        };

        this.socket.onmessage = function (messageEvent) {
            var jsonRpc = JSON.parse(messageEvent.data);
            var router = jsonRpc.router;
            self.result = jsonRpc.result;
            if (jsonRpc.error) return;

            if (router === "chart_head_pump_load") {
                dps1.length = 0;
                self.result.data1.forEach(item => dps1.push({x: new Date(item.x), y: item.y}));
                chart1.render();

                dps2.length = 0;
                self.result.data2.forEach(item => dps2.push({x: new Date(item.x), y: item.y}));
                chart2.render();

                dps3.length = 0;
                dps4.length = 0;
                self.result.data3.forEach(item => dps3.push({x: new Date(item.x), y: item.y}));
                self.result.data4.forEach(item => dps4.push({x: new Date(item.x), y: item.y}));
                chart3.render();

            } else if (router === "headpump_hourlyCharts") {
                dps5.length = 0;
                self.result.data1.forEach(item => dps5.push({x: new Date(item.x), y: item.y}));
                chart4.render();
            }
        };
    },

    heatPumpLoad: function () {
        hpChartClient.socket.send(JSON.stringify({
            method: "heatpump_chartLoad",
            id: "",
            router: "chart_head_pump_load",
            params: {}
        }));
    },

    heatpump_hourlyCharts: function () {
        hpChartClient.socket.send(JSON.stringify({
            method: "heatpump_hourlyCharts",
            id: "",
            router: "headpump_hourlyCharts",
            params: {}
        }));
    },
};
