/**
 * MQTT Solar Dashboard
 * Extracted from mqtt.js.client/index.html
 * Connects to MQTT broker and displays solar inverter gauges + summary
 */

function initSolarMQTT(config) {

    // Helper functions
    function toDict(keys, values) {
        var result = {};
        keys.forEach(function(key, i) { result[key] = values[i]; });
        return result;
    }

    function map(value, inMin, inMax, outMin, outMax) {
        var ratio = (value - inMin) / (inMax - inMin);
        return ratio * (outMax - outMin) + outMin;
    }

    function chart(data, index, div, round) {
        var svg = '<svg viewBox="0 -83 200 83">';
        var d = [];
        for (var i = 0; i < data.length; i++) {
            d.push(data[i][index]);
        }

        var min = Math.min.apply(Math, d);
        var max = Math.max.apply(Math, d);
        var x = 5;

        for (var j = 0; j < d.length; j++) {
            var h = Math.round(map(d[j], min, max, 0, 40));
            svg += '<rect x="' + (x + 15 * j) + '" y="-' + h + '" height="60" width="15" style="fill:#00cc00;stroke:#808080;stroke-width:1" />';
            svg += '<text x="' + (x + h) + '" y="' + (x + 13 + 15 * j) + '" font-size="11px" style="fill:white" transform="rotate(-90)">' + (d[j]/div).toFixed(round) + '</text>';
        }

        svg += '</svg>';
        return svg;
    }

    // Create gauges
    var gauge = Gauge(
        document.getElementById("gauge"), {
            min: 0,
            max: 5200,
            pathSize: 8,
            dual: true,
            title: "MPPT",
            label: function(value) { return value.toFixed(0) + "W"; },
            label1: function(value) { return value.toFixed(0) + "V"; },
            label2: function(value) { return value.toFixed(1) + "A"; },
            labelSecondary: function(value) { return value.toFixed(0) + "W"; },
            label1Secondary: function(value) { return value.toFixed(0) + "V"; },
            label2Secondary: function(value) { return value.toFixed(1) + "A"; },
            color: function(value) {
                if (value < 1500) { return "#ff6600"; }
                else { return "#00cc00"; }
            }
        }
    );

    var gauge1 = Gauge(
        document.getElementById("gauge1"), {
            min: 0,
            max: 10400,
            pathSize: 8,
            title: "Output",
            label: function(value) { return value.toFixed(0) + "W"; },
            label1: function(value) { return value.toFixed(0) + " V"; },
            label2: function(value) { return value.toFixed(1) + " A"; },
            color: function(value) {
                if (value < 1000) { return "#00ff00"; }
                else if (value < 8000) { return "#00cc00"; }
                else { return "#ff0000"; }
            }
        }
    );

    var gauge2 = Gauge(
        document.getElementById("gauge2"), {
            min: 0,
            min1: 0,
            min2: -200,
            max: 100,
            max1: 100,
            max2: 200,
            value: 50,
            title: "Battery",
            pathSize: 8,
            label: function(value) { return value.toFixed(1) + " %"; },
            label1: function(value) { return value.toFixed(1) + " V"; },
            label2: function(value) { return value.toFixed(1) + " A"; },
            color: function(value) {
                if (value < 30) { return "#ff0000"; }
                else if (value < 50) { return "#ff6600"; }
                else { return "#00cc00"; }
            }
        }
    );

    var gauge3 = Gauge(
        document.getElementById("gauge3"), {
            min: 0,
            max: 5200,
            pathSize: 8,
            title: "MPPT2",
            label: function(value) { return value.toFixed(0) + "W"; },
            label1: function(value) { return value.toFixed(0) + " V"; },
            label2: function(value) { return value.toFixed(1) + " A"; },
            color: function(value) {
                if (value < 1500) { return "#ff6600"; }
                else { return "#00cc00"; }
            }
        }
    );

    // MQTT connection
    var clientId = 'solar_' + Math.random().toString(16).substr(2, 8);
    var client = new Paho.MQTT.Client(config.host, Number(config.port), config.path, clientId);

    var connectOptions = {
        onSuccess: function() {
            console.log("Solar MQTT connected");
            client.subscribe("home/invertor/#", {});
        },
        useSSL: config.useSSL
    };

    client.connect(connectOptions);

    client.onConnectionLost = function(responseObject) {
        console.log("Solar MQTT connection lost: " + responseObject.errorMessage);
        setTimeout(function() {
            client.connect(connectOptions);
        }, 3000);
    };

    client.onMessageArrived = function(message) {
        var dnow = new Date();
        var month = dnow.getMonth();
        var obj = JSON.parse(message.payloadString);

        if (message.destinationName == "home/invertor/monthly/rows/") {

            var dt = chart(obj['values'], 0, 1, 0);
            document.getElementById("chartDataMonthly").innerHTML = dt;
            document.getElementById("thisMonth").innerHTML = obj['values'][obj['values'].length - 1][0].toFixed(1) + "kWh";

            var sum = 0;
            for (var i = obj['values'].length - 1; i >= obj['values'].length - month - 1; i--) {
                sum = sum + obj['values'][i][0];
            }
            document.getElementById("thisYear").innerHTML = (sum / 1000).toFixed(2) + "MWh";

        } else if (message.destinationName == "home/invertor/daily/rows/") {

            var dict = toDict(obj["columns"], obj["values"].slice(-1)[0]);
            var dt = chart(obj['values'], 4, 1000, 1);
            document.getElementById("chartData").innerHTML = dt;

            document.getElementById("todaySolarIn").innerHTML = (dict["solarPowerIn"] / 1000).toFixed(1) + "kWh";
            document.getElementById("todayPowerOut").innerHTML = (dict["outputPowerActive"] / 1000).toFixed(1) + "kWh";

            var html = "<p>" + (dict["solarPowerIn"]/1000 - dict["outputPowerActive"]/1000).toFixed(1) + "kWh</p>";
            document.getElementById("todayPowerDiff").innerHTML = html;

            html =
                "<p>Today In</p>" +
                "<p>Today Out</p>" +
                "<p>Today In-Out</p>" +
                "<p>Max solar curr</p>" +
                "<p>Max mains curr</p>";
            document.getElementById("today-battery-name").innerHTML = html;
            html =
                "<p>" + (dict["batteryPowerIn"]/1000).toFixed(1) + "kWh</p>" +
                "<p>" + (dict["batteryPowerOut"]/1000).toFixed(1) + "kWh</p>" +
                "<p>" + (dict["batteryPowerIn"]/1000 - dict["batteryPowerOut"]/1000).toFixed(1) + "kWh</p><div id='status'/>";

            document.getElementById("today-battery-value").innerHTML = html;

        } else if (message.destinationName == "home/invertor/actual/") {

            var actual1 = obj["invertor1"];
            var actual2 = obj["invertor2"];
            var status = obj["status"];

            var batteryCurrent = (actual1.batteryCurrent + actual2.batteryCurrent) - (actual1.batteryDischargeCurrent + actual2.batteryDischargeCurrent);
            var ztrata = -(batteryCurrent) * 0.009;
            var batteryPower = actual1.batteryVoltage * batteryCurrent;
            // Battery: 4x14S30P + 4x14S20P LiPo, min 47V (0%), max 57.7V (100%)
            var percentZ = Math.max(0, Math.min(100, (actual1.batteryVoltage + ztrata - 47) / 10.7 * 100)).toFixed(2);

            var solarPower1 = actual1.solarCurrent * actual1.solarVoltage;
            var solarPower2 = actual2.solarCurrent * actual2.solarVoltage;
            var totalSolarPower = solarPower1 + solarPower2;

            var totalEl = document.getElementById("totalSolar");
            if (totalEl) {
                totalEl.textContent = totalSolarPower.toFixed(0) + "W";
            }

            // MPPT1
            gauge.setValueAnimated(solarPower1);
            gauge.setValueAnimated1(actual1.solarVoltage);
            gauge.setValueAnimated2(actual1.solarCurrent);
            // MPPT2 on dual gauge
            if (gauge.setValueAnimatedSec) {
                gauge.setValueAnimatedSec(solarPower2);
                gauge.setValueAnimated1Sec(actual2.solarVoltage);
                gauge.setValueAnimated2Sec(actual2.solarCurrent);
            }

            // MPPT2 separate gauge
            gauge3.setValueAnimated(solarPower2);
            gauge3.setValueAnimated1(actual2.solarVoltage);
            gauge3.setValueAnimated2(actual2.solarCurrent);

            var outputPower = actual1.outputPowerActive + actual2.outputPowerActive;
            gauge1.setValueAnimated(outputPower);
            gauge1.setValueAnimated1(actual1.outputVoltage);
            gauge1.setValueAnimated2(outputPower / actual1.outputVoltage);

            gauge2.setValueAnimated(percentZ);
            gauge2.setValueAnimated1(actual1.batteryVoltage);
            gauge2.setValueAnimated2(batteryCurrent);

            var html = "<p>" + batteryPower.toFixed(0) + "W (" + status.workingStatus + ")</p>";
            document.getElementById("batteryPower").innerHTML = html;

            html =
                "<p>" + status.solarMaxChargingCurrent + "A</p>" +
                "<p>" + status.mainsMaxChargingCurrent + "A</p>";
            document.getElementById("status").innerHTML = html;

            html =
                "<p>" + actual1.gridVoltage.toFixed(0) + "V/" + actual1.gridFreq.toFixed(0) + " " +
                actual2.gridVoltage.toFixed(0) + "V/" + actual2.gridFreq.toFixed(0) + "Hz</p>";
            document.getElementById("grid").innerHTML = html;
        }
    };
}
