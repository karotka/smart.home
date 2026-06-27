/*global WebSocket, window, console, alert*/
"use strict";

// Control-panel WebSocket client for /heat_pump.html.
// Charts moved to /heat_pump_chart.html (see hp_chart_client.js).
// One poll method (heatpump_status) now drives all live readouts —
// the target temp + work-mode were folded in server-side so the UI
// doesn't need a second round-trip.
var hpClient = {
    connected: false,

    connect: function (port) {
        var self = this;
        var p = port ? ":" + port : "";
        this.socket = new WebSocket("wss://" + window.location.hostname + p + "/websocket");

        this.socket.onopen = function () {
            console.log("Connected!");
            hpClient.connected = true;
            hpClient.heatpump_status();
        };

        this.socket.onclose = function (e) {
            console.log("Socket closed, retrying in 1s.", e.reason);
            setTimeout(function () { hpClient.connect(""); }, 1000);
        };

        this.socket.onerror = function (err) {
            console.error("Socket error: ", err && err.message);
            this.socket.close();
        };

        // Paint every reactive control from a single response payload:
        // we get hpTuyaData (live DPS dict) + targetTemp + workMode.
        this.applyState = function (dps, targetTemp, workMode) {
            if (!dps) return;

            // Power
            if (dps[1] === true) {
                gEl('hp_on').classList.add('on');
                gEl('hp_on').classList.remove('off');
            } else {
                gEl('hp_on').classList.add('off');
                gEl('hp_on').classList.remove('on');
            }

            // Operating mode (silent / smart / max).
            ['hp_mute', 'hp_smart', 'hp_strong'].forEach(function (id) {
                gEl(id).classList.remove('active');
            });
            if (dps[2] === "mute")   gEl('hp_mute').classList.add('active');
            if (dps[2] === "smart")  gEl('hp_smart').classList.add('active');
            if (dps[2] === "strong") gEl('hp_strong').classList.add('active');

            // Work mode (heat / cool).
            gEl('hp_heat').classList.toggle('active', dps[5] === "heat");
            gEl('hp_cool').classList.toggle('active', dps[5] === "cool");

            // Temperatures.
            setReading('hp_waterOut', dps[102]);
            setReading('hp_waterIn',  dps[101]);
            setReading('hp_waterTank',dps[108]);
            setReading('hp_ambient',  dps[103]);

            // Current draw — Tuya reports in A directly.
            var cur = dps[112];
            gEl('hp_cc').textContent = (cur == null ? "—" : Number(cur).toFixed(1)) + " A";

            // Target temp (cached from PG1 read by checker.py).
            if (targetTemp != null) {
                gEl('hp_targetTemp').textContent = targetTemp + "°C";
            }
        };

        // Display a temperature reading or em-dash if missing.
        function setReading(id, val) {
            var el = gEl(id);
            if (val == null || val === "") {
                el.textContent = "—";
            } else {
                el.textContent = val + "°C";
            }
        }

        this.socket.onmessage = function (messageEvent) {
            var jsonRpc = JSON.parse(messageEvent.data);
            var router = jsonRpc.router;
            self.result = jsonRpc.result;
            if (jsonRpc.error) return;

            if (router === "heatpump_status") {
                self.applyState(self.result.hpTuyaData,
                                self.result.targetTemp,
                                self.result.workMode);

            } else if (router === "heatpump_setOnOff" ||
                       router === "heatpump_setMode"  ||
                       router === "heatpump_setWorkMode") {
                // The set_* methods return the freshly-read hpTuyaData
                // dict (so the UI repaints immediately), but they don't
                // refresh the target temp / workMode (PG1 is slow).
                // The next heatpump_status poll fills those in.
                self.applyState(self.result.hpTuyaData, null, null);

            } else if (router === "heatpump_setTemp") {
                // Server echoes the new target after writing it.
                if (self.result.temperature != null) {
                    gEl('hp_targetTemp').textContent = self.result.temperature + "°C";
                }
            }
        };
    },

    heatpump_setTemp: function (direction) {
        hpClient.socket.send(JSON.stringify({
            method: "heatpump_setTemp", id: "", router: "heatpump_setTemp",
            params: {direction: direction}
        }));
    },

    heatpump_setOnOff: function () {
        hpClient.socket.send(JSON.stringify({
            method: "heatpump_setOnOff", id: "", router: "heatpump_setOnOff",
            params: {}
        }));
    },

    heatpump_setMode: function (mode) {
        hpClient.socket.send(JSON.stringify({
            method: "heatpump_setMode", id: "", router: "heatpump_setMode",
            params: {mode: mode}
        }));
    },

    heatpump_setWorkMode: function (mode) {
        hpClient.socket.send(JSON.stringify({
            method: "heatpump_setWorkMode", id: "", router: "heatpump_setWorkMode",
            params: {mode: mode}
        }));
    },

    heatpump_status: function () {
        hpClient.socket.send(JSON.stringify({
            method: "heatpump_status", id: "", router: "heatpump_status",
            params: {}
        }));
    },
};
