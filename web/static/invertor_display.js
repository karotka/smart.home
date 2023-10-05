function InvertorDisplay() {

    this.canvas = document.getElementById("display");
    this.ctx = this.canvas.getContext("2d");
    this.ctx.textAlign = 'right';
    this.counter = 0;
    this.arr = new Array();

    this.workingStatus = new Object();
    this.workingStatus["B"] = "Battery";
    this.workingStatus["L"] = "Utility";
    this.fillColor = '#ddd';

    this.show = function(data) {
        //console.log(data);
        this.clear();
        
        this.battery(data, 650, 150);
        this.home(data, 890, 60);

        if (data.gridVoltage > 210) {
            this.utility(data, 400, 60);
        }

        if (data.solarCurrent > 0) {
            this.mppt1(data, 350, 140);
        }

        if (data.solarCurrent > 0) {
            this.mppt2(data, 350, 335);
        }

        this.batteryToHome(data, 85, 0);
        
        if (data.workingStatus == "L") {
            this.bypass(data, 50, 0);

            if (data.solarCurrent == 0 && data.batteryCurrent > 0) {
                this.utilityToBattery(data, 50, 0);
            }
        }
        this.dcToHome(data, 50, 0);
        this.values(data, 20, 0);
    }

    this.triangle = function(ctx, x, y, angle, bg = true) {

        ctx.beginPath();
        ctx.lineWidth = 1;
        switch (angle) {
            case 0:
                ctx.moveTo(x, y + 7);
                ctx.lineTo(x, y - 7);
                ctx.lineTo(x + 7, y);
                ctx.lineTo(x, y + 7);
                break;
            case 90:
                ctx.moveTo(x - 7, y);
                ctx.lineTo(x + 7, y);
                ctx.lineTo(x, y - 7);
                ctx.lineTo(x - 7, y);
                break;
            case 180:
                ctx.moveTo(x - 7, y);
                ctx.lineTo(x + 7, y);
                ctx.lineTo(x, y - 7);
                ctx.lineTo(x - 7, y);
                break;
            case 270:
                ctx.moveTo(x - 7, y);
                ctx.lineTo(x + 7, y);
                ctx.lineTo(x, y + 7);
                ctx.lineTo(x - 7, y);
                break;
        }
        ctx.stroke();
        
        if (bg) {
            ctx.fillStyle = "white";
        } else {
            ctx.fillStyle = "#aaa";
        }
        ctx.fill();
    }

    this.dcToHome = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;

        // convertor AC/DC
        this.convertor(x + 400, y + 232, "DC", "AC");

        ctx.beginPath();
        ctx.lineWidth = 1;

        ctx.moveTo(900 + x, y + 125);
        ctx.lineTo(900 + x, y + 340);

        ctx.font = "20px Arial";
        ctx.fillStyle = this.fillColor;
        ctx.fillText(data.outputVoltage + "V", x + 890, y + 280);
        ctx.fillText(data.outputFreq + "Hz", x + 890, y + 305);
        ctx.fillText(data.loadPercent + "%", x + 890, y + 330);
        ctx.stroke();

        if (data.solarCurrent > 0) {
            ctx.moveTo(x + 581, y + 370);
            ctx.lineTo(x + 660, y + 370);
            ctx.stroke();

            this.triangleAppend([x + 590, y + 370, 0]);
            this.triangleAppend([x + 640, y + 370, 0]);
        }

        var batteryPower = data.batteryVoltage * (data.batteryCurrent - data.batteryDischargeCurrent);
        var batSolarDiff = data.solarVoltage * data.solarCurrent - batteryPower;
        
        if (batSolarDiff > 0) {
            ctx.fillText((data.solarVoltage * data.solarCurrent - batteryPower).toFixed(0) + "W", x + 800, y + 355);
            ctx.moveTo(660 + x, y + 370);
            ctx.lineTo(865 + x, y + 370);

            ctx.stroke();
            this.triangleAppend([x + 690, y + 370, 0]);
            this.triangleAppend([x + 740, y + 370, 0]);
            this.triangleAppend([x + 790, y + 370, 0]);
            this.triangleAppend([x + 840, y + 370, 0]);
            
            this.triangleAppend([x + 900, y + 310, 90]);
            this.triangleAppend([x + 900, y + 260, 90]);
            this.triangleAppend([x + 900, y + 210, 90]);
            this.triangleAppend([x + 900, y + 160, 90]);
        }
        this.triangleDraw(true);
    }

    this.triangleAppend = function(data) {
        this.arr.push(data);
    }

    this.triangleDraw = function() {

        for (var i = 0; i < this.arr.length; i++) {
            //console.log(this.counter == i%3);
            this.triangle(
                    this.ctx,
                    this.arr[i][0],
                    this.arr[i][1],
                    this.arr[i][2], this.counter == i%3);
        }
        this.arr = new Array();
    }

    this.batteryToHome = function(data, x, y) {
        //console.log(data);   
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;
        ctx.beginPath();
        ctx.lineWidth = 1;

        // MPPT to battery
        if (data.batteryCurrent > 0 || data.batteryDischargeCurrent > 0) {
            ctx.moveTo(x + 625, y + 370);
            ctx.lineTo(x + 625, y + 230);
            
            ctx.font = "20px Arial";
            ctx.fillStyle = this.fillColor;

            ctx.fillText((data.batteryVoltage * (data.batteryCurrent - data.batteryDischargeCurrent)).toFixed(0) + "W", x + 610, y + 278);
            ctx.fillText(data.batteryCurrent - data.batteryDischargeCurrent + "A", x + 610, y + 302);
        }
        ctx.stroke();

        if (data.batteryCurrent > 0) {
            // up
            this.triangleAppend([x + 625, y + 330, 90]);
            this.triangleAppend([x + 625, y + 290, 90]);
            this.triangleAppend([x + 625, y + 250, 90]);
        } else
        if (data.batteryDischargeCurrent > 0) {
            // down
            //console.log(this.triangleArray);
            this.triangleAppend([x + 625, y + 260, 270]);
            this.triangleAppend([x + 625, y + 300, 270]);
            this.triangleAppend([x + 625, y + 340, 270]);
        }
        this.triangleDraw(true);
    }

    this.convertor = function(x, y, text1, text2) {
        var ctx = this.ctx;
        ctx.beginPath();
        ctx.strokeStyle = this.fillColor;
        ctx.lineWidth = 3;
        ctx.moveTo(x + 527, y + 140);
        ctx.arc(x + 500, y + 140, 28, 0, 2 * Math.PI);
        ctx.moveTo(x + 512, y + 127);
        ctx.lineTo(x + 487, y + 155);

        ctx.font = "13px Arial";
        ctx.fillStyle = this.fillColor;
        ctx.fillText(text1, x + 500, y + 136)
        ctx.fillText(text2, x + 521, y + 153)

        ctx.stroke();
    }

    this.utilityToBattery = function(data, x, y) {
        // charge from utility
        // bypass
            
            var ctx = this.ctx;
            ctx.strokeStyle = this.fillColor;

            ctx.beginPath();
            ctx.lineWidth = 1;

            ctx.moveTo(x + 390, y + 85);
            ctx.lineTo(x + 470, y + 125);

            ctx.moveTo(x + 530, y + 155);
            ctx.lineTo(x + 590, y + 186);
            ctx.stroke();

            // convertor AC/DC
            this.convertor(x, y, "AC", "DC");
    }

    this.bypass = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;

        // bypass
        ctx.beginPath();
        ctx.lineWidth = 1;

        // utility to home
        ctx.moveTo(x + 400, y + 60);
        ctx.lineTo(x + 830, y + 60);
        ctx.stroke();

        this.triangleAppend([x + 430, y + 60, 0]);
        this.triangleAppend([x + 490, y + 60, 0]);
        this.triangleAppend([x + 550, y + 60, 0]);
        this.triangleAppend([x + 610, y + 60, 0]);
        this.triangleAppend([x + 670, y + 60, 0]);
        this.triangleAppend([x + 730, y + 60, 0]);
        this.triangleAppend([x + 790, y + 60, 0]);
        this.triangleDraw();


        // bypass text
        ctx.beginPath();
        ctx.font = "20px Arial";
        ctx.fillStyle = this.fillColor;
        ctx.fillText("BYPASS", x + 585, y + 50)

        if (data.batteryDischargeCurrent == 0 &&
            data.workingStatus != "L" &&
            outputPowerApparent > 0) {
            // power from utility
        }

        ctx.stroke();
    }

    this.values = function(data, x, y) {
        /*var ctx = this.ctx;

        ctx.font = "17px Helvetica";
        ctx.fillStyle = this.fillColor;

        ctx.beginPath();
        ctx.lineWidth = 1;
        this.ctx.textAlign = 'left';

        y = y + 60;
        ctx.fillText("Solar Char. Current: ", x + 5, y);
        ctx.fillText("Mains Char. Current: ", x + 5, y + 20);
        ctx.fillText("Batt. Fast Charge: ", x + 5, y + 40);
        ctx.fillText("Batt. Floating: ", x + 5, y + 60);
        ctx.fillText("Batt. Mains Switch: ", x + 5, y + 80);
        ctx.fillText("Batt. Shutdown: ", x + 5, y + 100);
        ctx.fillText("Charging Priority: ", x + 5, y + 120);
        ctx.fillText("Input Range: ", x + 5, y + 140);
        ctx.fillText("Load Source Priority: ", x + 5, y + 160);
        ctx.fillText("Working status: ", x + 5, y + 180);
        ctx.fillText("Temperature: ", x + 5, y + 200);
        ctx.fillText("Rated current: ", x + 5, y + 220);
        ctx.fillText("Last 2 days: ", x + 5, y + 250);
        ctx.fillText("Solar In: ", x + 5, y + 270);
        ctx.fillText("In - Out: ", x + 5, y + 290);
        ctx.fillText("Battery In: ", x + 5, y + 310);
        ctx.fillText("Power Out: ", x + 5, y + 330);
        ctx.fillText("Battery: ", x + 5, y + 350);
        
        this.ctx.textAlign = 'right';
        ctx.fillText(data.solarMaxChargingCurrent + "A", x + 255, y);
        ctx.fillText(data.mainsMaxChargingCurrent + "A", x + 255, y + 20);
        ctx.fillText(data.batteryVoltageFastCharge + "V", x + 255, y + 40);
        ctx.fillText(data.batteryVoltageFloating + "V", x + 255, y + 60);
        ctx.fillText(data.batteryVoltageMainsSwitchingPoint.toFixed(1) + "V", x + 255, y + 80);
        ctx.fillText(data.batteryVoltageShutdown + "V", x + 255, y + 100);
        ctx.fillText(data.chargingSourcePriority, x + 255, y + 120);
        ctx.fillText(data.inputRange, x + 255, y + 140);
        ctx.fillText(data.loadPowerSourcePriority, x + 255, y + 160);
        ctx.fillText(this.workingStatus[data.workingStatus], x + 255, y + 180);
        ctx.fillText(data.temperature + "C°", x + 255, y + 200);
        ctx.fillText(data.ratedInputCurrent + "A", x + 255, y + 220);
        ctx.fillText((data["last"]["solarPowerIn"]/1000).toFixed(1) + "kWh", x + 255, y + 270);
        ctx.fillText((data["last"]["solarPowerIn"]/1000 - data["last"]["outputPowerActive"]/1000).toFixed(1) + "kWh", x + 255, y + 290);
        ctx.fillText((data["last"]["batteryPowerIn"]/1000).toFixed(1) + "kWh", x + 255, y + 310);
        ctx.fillText((data["last"]["batteryPowerOut"]/1000).toFixed(1) + "kWh", x + 255, y + 330);
        ctx.fillText((data["last"]["batteryPowerIn"]/1000 - data["last"]["batteryPowerOut"]/1000).toFixed(1) + "kWh", x + 255, y + 350);
        ctx.stroke();*/


        html = "<p><strong>Setting</strong></p>" +
            "<p>Solar Char. Current:</p>" +
            "<p>Mains Char. Current:</p>" +
            "<p>Batt. Fast Charge:</p>" +
            "<p>Batt. Floating:</p>" +
            "<p>Batt. Mains Switch:</p>" +
            "<p>Batt. Shutdown:</p>" +
            "<p>Charging Priority:</p>" +
            "<p>Input Range:</p>" +
            "<p>Load Source Priority:</p>" +
            "<p>Working status:</p>" +
            "<p>Temperature:</p>" +
            "<p>Rated current:</p>" +
            "<p>&nbsp;</p>" +
            "<p><strong>Today</strong></p>" +
            "<p>Power Out:</p>" +
            "<p>Solar In:</p>" +
            "<p>In - Out:</p>" +
            "<p>Battery In:</p>" +
            "<p>Battery Out:</p>" +
            "<p>Battery:</p>";

            gEl("name").innerHTML = html;

            html = 
            "<p>&nbsp;</p>" +
            "<p>" + data.solarMaxChargingCurrent + "A</p>" +
            "<p>" + data.mainsMaxChargingCurrent + "A</p>" +
            "<p>" + data.batteryVoltageFastCharge + "V</p>" +
            "<p>" + data.batteryVoltageFloating + "V</p>" +
            "<p>" + data.batteryVoltageMainsSwitchingPoint.toFixed(1) + "V</p>" +
            "<p>" + data.batteryVoltageShutdown + "V</p>" +
            "<p>" + data.chargingSourcePriority + "</p>" +
            "<p>" + data.inputRange + "</p>" +
            "<p>" + data.loadPowerSourcePriority + "</p>" +
            "<p>" + this.workingStatus[data.workingStatus] + "</p>" +
            "<p>" + data.temperature + "C°</p>" +
            "<p>" + data.ratedInputCurrent + "A</p>" +
            "<p>&nbsp;</p>" +
            "<p>&nbsp;</p>" +
            "<p>" + (data["last"]["outputPowerActive"]/1000).toFixed(1) + "kWh</p>" +
            "<p>" + (data["last"]["solarPowerIn"]/1000).toFixed(1) + "kWh</p>" +
            "<p>" + (data["last"]["solarPowerIn"]/1000 - data["last"]["outputPowerActive"]/1000).toFixed(1) + "kWh</p>" +
            "<p>" + (data["last"]["batteryPowerIn"]/1000).toFixed(1) + "kWh</p>" +
            "<p>" + (data["last"]["batteryPowerOut"]/1000).toFixed(1) + "kWh</p>" +
            "<p>" + (data["last"]["batteryPowerIn"]/1000 - data["last"]["batteryPowerOut"]/1000).toFixed(1) + "kWh</p>";
            gEl("value").innerHTML = html;

        }


        this.mppt1 = function(data, x, y) {
            var ctx = this.ctx;
            ctx.strokeStyle = this.fillColor;

            // line
            ctx.beginPath();
            ctx.lineWidth = 1;
            ctx.moveTo(x + 105, y + 60);
            ctx.lineTo(x + 218, y + 60);
            ctx.stroke();

            // convertor AC/DC
            this.convertor(x - 250, y - 80, "DC", "DC");

            // picture
            ctx.beginPath();
            ctx.lineWidth = 3;

            ctx.moveTo(x, y);
            ctx.lineTo(x + 10, y + 80);
            ctx.moveTo(x + 10, y + 80);
            ctx.lineTo(x + 100, y + 60);
            ctx.moveTo(x + 100, y + 60);
            ctx.lineTo(x + 90, y - 10);
            ctx.moveTo(x + 90, y - 10);
            ctx.lineTo(x, y);
            ctx.stroke();

            // sun
            ctx.beginPath();
            ctx.arc(x + 95, y - 13, 12, 9, .55 * Math.PI);
            ctx.moveTo(x + 98, y - 3);
            ctx.lineTo(x + 102, y + 10);
            ctx.moveTo(x + 106, y - 6);
            ctx.lineTo(x + 116, y + 1);
            ctx.moveTo(x + 108, y - 14);
            ctx.lineTo(x + 120, y - 14);
            ctx.moveTo(x + 105, y - 22);
            ctx.lineTo(x + 116, y - 31);
            ctx.moveTo(x + 96, y - 25);
            ctx.lineTo(x + 97, y - 38);
            ctx.moveTo(x + 86, y - 22);
            ctx.lineTo(x + 76, y - 31);


            ctx.lineWidth = 2;
            ctx.moveTo(x + 9, y + 40);
            ctx.lineTo(x + 90, y + 26);

            ctx.moveTo(x + 18, y + 2);
            ctx.lineTo(x + 28, y + 73);

            ctx.moveTo(x + 36, y + 1);
            ctx.lineTo(x + 46, y + 69);

            ctx.moveTo(x + 54, y - 1);
            ctx.lineTo(x + 64, y + 65);

            ctx.moveTo(x + 72, y - 3);
            ctx.lineTo(x + 82, y + 61);
            
            ctx.stroke();

            ctx.beginPath();
            ctx.font = "20px Arial";
            ctx.fillStyle = this.fillColor;

            //var solarPower = data.solarVoltage * data.solarCurrent + data.solarVoltage2 * data.solarCurrent2;
            
            ctx.fillText(Math.round(data.solarVoltage * data.solarCurrent) + "W", x + 65, y - 70)
            ctx.fillText(data.solarVoltage + "V", x + 65, y - 45)
            ctx.fillText(data.solarCurrent + "A", x + 65, y - 20)
            
            //ctx.fillText(Math.round(solarPower) + "W", x + 190, y + 45)

            ctx.stroke();
            
            if (data.solarCurrent > 0) {
                this.triangleAppend([x + 115, y + 60, 0]);
                this.triangleAppend([x + 157, y + 60, 0]);
                this.triangleAppend([x + 200, y + 60, 0]);
                this.triangleDraw();
            }
        }

        this.mppt2 = function(data, x, y) {
            var ctx = this.ctx;
            ctx.strokeStyle = this.fillColor;

            // line
            ctx.beginPath();
            ctx.lineWidth = 1;
            ctx.moveTo(x + 105, y + 60);
            ctx.lineTo(x + 218, y + 60);
            ctx.stroke();

            // convertor AC/DC
            this.convertor(x - 250, y - 80, "DC", "DC");

            // picture
            ctx.beginPath();
            ctx.lineWidth = 3;

            ctx.moveTo(x, y);
            ctx.lineTo(x + 10, y + 80);
            ctx.moveTo(x + 10, y + 80);
            ctx.lineTo(x + 100, y + 60);
            ctx.moveTo(x + 100, y + 60);
            ctx.lineTo(x + 90, y - 10);
            ctx.moveTo(x + 90, y - 10);
            ctx.lineTo(x, y);
            ctx.stroke();

            // sun
            ctx.beginPath();
            ctx.arc(x + 95, y - 13, 12, 9, .55 * Math.PI);
            ctx.moveTo(x + 98, y - 3);
            ctx.lineTo(x + 102, y + 10);
            ctx.moveTo(x + 106, y - 6);
            ctx.lineTo(x + 116, y + 1);
            ctx.moveTo(x + 108, y - 14);
            ctx.lineTo(x + 120, y - 14);
            ctx.moveTo(x + 105, y - 22);
            ctx.lineTo(x + 116, y - 31);
            ctx.moveTo(x + 96, y - 25);
            ctx.lineTo(x + 97, y - 38);
            ctx.moveTo(x + 86, y - 22);
            ctx.lineTo(x + 76, y - 31);


            ctx.lineWidth = 2;
            ctx.moveTo(x + 9, y + 40);
            ctx.lineTo(x + 90, y + 26);

            ctx.moveTo(x + 18, y + 2);
            ctx.lineTo(x + 28, y + 73);

            ctx.moveTo(x + 36, y + 1);
            ctx.lineTo(x + 46, y + 69);

            ctx.moveTo(x + 54, y - 1);
            ctx.lineTo(x + 64, y + 65);

            ctx.moveTo(x + 72, y - 3);
            ctx.lineTo(x + 82, y + 61);
            
            ctx.stroke();

            ctx.beginPath();
            ctx.font = "20px Arial";
            ctx.fillStyle = this.fillColor;

            //var solarPower = data.solarVoltage * data.solarCurrent + data.solarVoltage2 * data.solarCurrent2;
            
            ctx.fillText(Math.round(data.solarVoltage2 * data.solarCurrent2) + "W", x + 65, y - 70)
            ctx.fillText(data.solarVoltage2 + "V", x + 65, y - 45)
            ctx.fillText(data.solarCurrent2 + "A", x + 65, y - 20)
            
            //ctx.fillText(Math.round(solarPower) + "W", x + 190, y + 45)

            ctx.stroke();
            
            if (data.solarCurrent > 0) {
                this.triangleAppend([x + 115, y + 60, 0]);
                this.triangleAppend([x + 157, y + 60, 0]);
                this.triangleAppend([x + 200, y + 60, 0]);
                this.triangleDraw();
            }
        }

        this.mpptLine = function(data, x, y) {
            var ctx = this.ctx;
            ctx.strokeStyle = this.fillColor;

            // line
            ctx.beginPath();
            ctx.lineWidth = 1;
            ctx.moveTo(x + 105, y + 60);
            ctx.lineTo(x + 218, y + 60);
            ctx.stroke();

            // convertor AC/DC
            this.convertor(x - 250, y - 80, "DC", "DC");

            // picture
            ctx.beginPath();
            ctx.lineWidth = 3;

            ctx.moveTo(x, y);
            ctx.lineTo(x + 10, y + 80);
            ctx.moveTo(x + 10, y + 80);
            ctx.lineTo(x + 100, y + 60);
            ctx.moveTo(x + 100, y + 60);
            ctx.lineTo(x + 90, y - 10);
            ctx.moveTo(x + 90, y - 10);
            ctx.lineTo(x, y);
            ctx.stroke();

            // sun
            ctx.beginPath();
            ctx.arc(x + 95, y - 13, 12, 9, .55 * Math.PI);
            ctx.moveTo(x + 98, y - 3);
            ctx.lineTo(x + 102, y + 10);
            ctx.moveTo(x + 106, y - 6);
            ctx.lineTo(x + 116, y + 1);
            ctx.moveTo(x + 108, y - 14);
            ctx.lineTo(x + 120, y - 14);
            ctx.moveTo(x + 105, y - 22);
            ctx.lineTo(x + 116, y - 31);
            ctx.moveTo(x + 96, y - 25);
            ctx.lineTo(x + 97, y - 38);
            ctx.moveTo(x + 86, y - 22);
            ctx.lineTo(x + 76, y - 31);


            ctx.lineWidth = 2;
            ctx.moveTo(x + 9, y + 40);
            ctx.lineTo(x + 90, y + 26);

            ctx.moveTo(x + 18, y + 2);
            ctx.lineTo(x + 28, y + 73);

            ctx.moveTo(x + 36, y + 1);
            ctx.lineTo(x + 46, y + 69);

            ctx.moveTo(x + 54, y - 1);
            ctx.lineTo(x + 64, y + 65);

            ctx.moveTo(x + 72, y - 3);
            ctx.lineTo(x + 82, y + 61);
            
            ctx.stroke();

            ctx.beginPath();
            ctx.font = "20px Arial";
            ctx.fillStyle = this.fillColor;

            //var solarPower = data.solarVoltage * data.solarCurrent + data.solarVoltage2 * data.solarCurrent2;
            
            ctx.fillText(Math.round(data.solarVoltage * data.solarCurrent) + "W", x + 65, y - 70)
            ctx.fillText(data.solarVoltage + "V", x + 65, y - 45)
            ctx.fillText(data.solarCurrent + "A", x + 65, y - 20)
            
            //ctx.fillText(Math.round(solarPower) + "W", x + 190, y + 45)

            ctx.stroke();
            
            if (data.solarCurrent > 0) {
                this.triangleAppend([x + 115, y + 60, 0]);
                this.triangleAppend([x + 157, y + 60, 0]);
                this.triangleAppend([x + 200, y + 60, 0]);
                this.triangleDraw();
            }
    }



    this.utility = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;

        ctx.beginPath();
        ctx.lineWidth = 3;
        ctx.arc(x, y, 40, 0, 2 * Math.PI);

        ctx.moveTo(x - 40, y);
        ctx.lineTo(x + 40, y);

        var amplitude = 20;
        var frequency = 10;
        var i = 0;
        ctx.moveTo(x - 35, y);
        while (i < 64) {
            yy = y + amplitude * Math.sin(i/frequency);
            ctx.lineTo(i + x - 32, yy);
            i = i + 1;
        }

        // utility
        ctx.font = "20px Arial";
        ctx.fillStyle = this.fillColor;
        ctx.fillText(data.gridVoltage + "V", x + 110, y - 30)
        ctx.fillText(data.gridFreq + "Hz", x + 110, y - 10)
        
        ctx.stroke();
    }

    this.home = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;

        // border
        ctx.beginPath();
        ctx.lineWidth = 3;
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + 60);

        ctx.moveTo(x, y + 60);
        ctx.lineTo(x + 15, y + 60);
        ctx.moveTo(x + 15, y + 60);
        ctx.lineTo(x + 15, y + 30);
        ctx.moveTo(x + 15, y + 30);
        ctx.lineTo(x + 30, y + 30);
        ctx.moveTo(x + 30, y + 30);
        ctx.lineTo(x + 30, y + 60);
        ctx.moveTo(x + 30, y + 60);
        ctx.lineTo(x + 90, y + 60);
        ctx.moveTo(x + 90, y + 60);
        ctx.lineTo(x + 90, y);

        ctx.moveTo(x - 10, y + 10);
        ctx.lineTo(x + 45, y - 45);
        ctx.moveTo(x + 45, y - 45);
        ctx.lineTo(x + 100, y + 10);

                // utility
        ctx.font = "16px Arial";
        ctx.fillStyle = this.fillColor;
        ctx.fillText(Math.round(data.outputPowerActive) + "W", x + 73, y + 5)
        ctx.fillText(Math.round(data.outputPowerApparent) + "W", x + 73, y + 25)

        ctx.stroke();
    }

    this.battery = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;

        // border
        ctx.beginPath();
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.rect(x, y, 120, 70, 0);
        ctx.stroke();

        // left contact
        ctx.beginPath();
        ctx.lineWidth = 10;
        ctx.moveTo(x + 10, y - 4);
        ctx.lineTo(x + 30, y - 4);
        ctx.stroke();

        // right contact
        ctx.beginPath();
        ctx.lineWidth = 10;
        ctx.moveTo(x +  90, y - 4);
        ctx.lineTo(x + 110, y - 4);
        ctx.stroke();

        // minus
        ctx.beginPath();
        ctx.lineWidth = 8;
        ctx.moveTo(x + 90, y + 20);
        ctx.lineTo(x + 110, y + 20);
        ctx.stroke();

        // plus
        ctx.beginPath();
        ctx.lineWidth = 8;
        ctx.moveTo(x + 10, y + 20);
        ctx.lineTo(x + 30, y + 20);

        ctx.moveTo(x + 20, y + 10);
        ctx.lineTo(x + 20, y + 30);

        ctx.font = "20px Arial";
        ctx.fillStyle = this.fillColor;
        ctx.fillText(data.batteryVoltage + "V", x + 85, y + 43)
        var v = ((data.batteryVoltage-42)/(58.8-42)*(100)).toFixed(2)
        ctx.fillText(v + "%", x + 97, y + 63)
        ctx.stroke();
    }

    this.clear = function(x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = this.fillColor;

        ctx.beginPath();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        ctx.stroke();
    }

    this.timer = function() {
        window.displ.counter++;
        if (window.displ.counter == 3) {
            window.displ.counter = 0;
        }
        if (client.hasOwnProperty("result")) {
            window.displ.show(client.result.data);
        }
    }
}

