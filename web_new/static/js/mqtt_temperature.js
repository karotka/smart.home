/**
 * MQTT Temperature Dashboard
 * Extracted from mqtt.js.client/temp.html
 * Connects to MQTT broker and displays room temperature gauges
 */

function initTemperatureMQTT(config, rooms) {

    function getColor(value) {
        if (value < 20) {
            return "#ff6600";
        } else if (value >= 20 && value <= 24) {
            return "#00ffff";
        } else {
            return "#ff0000";
        }
    }

    // Create gauges for each room
    var gauges = {};
    rooms.forEach(function(room) {
        gauges[room.topic] = Gauge(
            document.getElementById(room.id), {
                min: room.min || 14,
                max: room.max || 30,
                pathSize: 8,
                title: room.title,
                label: function(value) {
                    return value.toFixed(1) + "C";
                },
                color: function(value) { return getColor(value); }
            }
        );
    });

    // MQTT connection
    var clientId = 'temp_' + Math.random().toString(16).substr(2, 8);
    var client = new Paho.MQTT.Client(config.host, Number(config.port), config.path, clientId);

    var connectOptions = {
        onSuccess: function() {
            console.log("Temperature MQTT connected");
            client.subscribe("home/temp/#", {});
        },
        useSSL: config.useSSL
    };

    client.connect(connectOptions);

    client.onConnectionLost = function(responseObject) {
        console.log("Temperature MQTT connection lost: " + responseObject.errorMessage);
        setTimeout(function() {
            client.connect(connectOptions);
        }, 3000);
    };

    client.onMessageArrived = function(message) {
        var topic = message.destinationName;
        var value = message.payloadString;

        if (gauges[topic]) {
            gauges[topic].setValueAnimated(parseFloat(value));
        }
    };
}
