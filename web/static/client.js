/*global WebSocket, $, window, console, alert, Blob, saveAs*/
"use strict";

/**
 * Function calls across the background TCP socket. Uses JSON RPC + a queue.
 */
var client = {
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
            //console.log(self);
            client.connected = true;
            if (document.location.pathname == "/heating_setting.html") {
                client.heatingLoad(document.roomId);
            }
        };

        this.socket.onclose = function(e) {
            console.log('Socket is closed. Reconnect will be attempted in 1 second.', e.reason);
            setTimeout(function() {
                client.connect("");
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

            // server response handling
            } else if (router === "blinds") {
                var el = gEl(self.result.direction + "_" + self.result.id);
                el.style.backgroundColor="#2A4B7C";
            } else if (router === "heating") {
                $("#heating_" + self.result.id).html("(" + self.result.temperature + " C)");

            } else if (router === "lights_switch") {
                //console.log(self.result);
                if (self.result.direction == "on") {
                    $("#" + self.result.id + "On").addClass("active");
                    $("#" + self.result.id + "Off").removeClass("active");
                } else {
                    $("#" + self.result.id + "Off").addClass("active");
                    $("#" + self.result.id + "On").removeClass("active");
                }

            } else if (router === "heating_SensorRefresh") {
                var el = gEl("heatingDirection");
                el.value = "Mode: " + self.result.heating_direction;

                for (const [key, value] of Object.entries(self.result)) {
                    $("#actual_temp_" + key).html(parseFloat(value.temperature).toFixed(1));
                    $("#actual_humidity_" + key).html(parseFloat(value.humidity).toFixed(1)+ "%");
                    if (value.status == 1) {
                        //$("#" + key).css("background-color", "#374861;");
                        $("#" + key).css("background-color", "#577196;");
                    } else {
                        $("#" + key).css("background-color", "#303D54;"); 
                    }
                }
                $("#hFlame").attr("src", "/static/flame_" + self.result.heating_state + ".svg");

            } else if (router === "heating_load" ||
                       router === "heating_add" ||
                       router === "heating_setTemp" ||
                       router === "heating_delete") {
                var el = gEl("heatTime");
                el.innerHTML = "";

                for (var i = 0; i < self.result.items.length; i++) {
                    var item = self.result.items[i];
                    el.innerHTML += 
                        "<div class='divItem' id='item" + i +"'> "
                        + (i + 1) + ". " + item["value"] + " "
                        + "<input type='button' value='-' class='bDown' onclick='javascript:client.heatingSetTemp("+  i + ", \"down\")'> "
                        + "<input type='text' value='"+ item["temperature"] + "' size='4' id='itm" + i + "'> "
                        + "<input type='button' value='+' class='bUp' onclick='javascript:client.heatingSetTemp(" + i + ", \"up\")'> "
                        + "<input type='button' onclick='javascript:Heating.delete("
                        + i + ");' value='Delete' />"
                        + "</div>";
                }

            } else if (router === "heating_switch") {
                var el = gEl("heatingDirection");
                //console.log(el.value);
                el.value = "Mode: " + self.result.direction;
            } else if (router === "heating_setTemp") {
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
        this.socket.send(
            JSON.stringify( {
                method: "heating",
                id : "",
                router: "heating",
                params: {id : id, direction: direction}}));
    },

    heatingSwitch: function () {
        this.socket.send(
            JSON.stringify( {
                method: "heating_switch",
                id : "",
                router: "heating_switch",
                params: {}}));
    },

    heatingSensorRefresh: function(ids) {
        if (client.socket.readyState == 1) {
            client.socket.send(
                JSON.stringify( {
                    method : "heating_SensorRefresh",
                    router : "heating_SensorRefresh",
                    id: "", params: {ids : ids}}));
        }
    },

    lights: function(id, direction, type) {
        client.socket.send(
            JSON.stringify( {
                method: "lights_switch",
                id:  0,
                router : "lights_switch",
                params: {id : id, direction : direction, type : type}}));
    },

    heatingLoad: function(roomId) {
        client.socket.send(
            JSON.stringify( {
                method: "heating_load",
                id:  0,
                router : "heating_load",
                params: {roomId : roomId}}));
    },

    heatingAdd: function(value) {
        client.socket.send(
            JSON.stringify( {
                method: "heating_add",
                id:  0,
                router : "heating_add",
                params: {roomId : document.roomId, value : value}}));
    },

    heatingDelete: function(roomId, index) {

        client.socket.send(
            JSON.stringify( {
                method: "heating_delete",
                id:  0,
                router : "heating_delete",
                params: {roomId : roomId, index : index}}));
    },

    heatingSetTemp: function(index, direction) {

        client.socket.send(
            JSON.stringify( {
                method: "heating_setTemp",
                id:  0,
                router : "heating_setTemp",
                params: {roomId : document.roomId, index : index, direction : direction}}));
    },

    blinds: function(id, direction) {
    
        var el = gEl(direction + "_" + id);
        el.style.backgroundColor="#92ACD2";
        client.socket.send(
            JSON.stringify( {
                method: "blinds",
                id:  0,
                router : "blinds",
                params: {id : id, direction : direction}}));
    
    },
};
