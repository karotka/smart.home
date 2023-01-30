function InvertorDisplay() {

    this.canvas = document.getElementById("display");
    this.ctx = this.canvas.getContext("2d");
    this.ctx.textAlign = 'right';
    this.counter = 0;
    this.arr = new Array();

    this.show = function(data) {
        //console.log(this.counter%3);
        this.clear();
        
        this.battery(data, 600, 150);
        this.home(data, 850, 60);

        if (data.gridVoltage > 210) {
            this.utility(data, 350, 60);
        }

        if (data.solarCurrent > 0) {
            this.mppt(data, 300, 310);
        }

        if (data.batteryCurrent - data.batteryDischargeCurrent > 0) {
            this.batteryToHome(data, 35, 0);
        }
        
        if (data.workingStatus == "L") {
            this.bypass(data, 0, 0);
            this.utilityToBattery(data, 0, 0);
        } else {
            this.dcToHome(data, 0, 0);
        }

        this.values(data, 0, 0);
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

        //region.closePath();
        if (bg) {
            ctx.fillStyle = "red";
        } else {
            ctx.fillStyle = '#50a8f7';
        }
        ctx.fill();
    }

    this.dcToHome = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = '#50a8f7';

        // convertor AC/DC
        this.convertor(400, 232, "DC", "AC");

        ctx.beginPath();
        ctx.lineWidth = 1;

        ctx.moveTo(900 + x, y + 125);
        ctx.lineTo(900 + x, y + 340);

        ctx.moveTo(660 + x, y + 370);
        ctx.lineTo(865 + x, y + 370);

        ctx.font = "20px Arial";
        ctx.fillStyle = "#50a8f7";
        ctx.fillText(data.outputVoltage + "V", x + 890, y + 280);
        ctx.fillText(data.outputFreq + "Hz", x + 890, y + 305);
        ctx.fillText(data.loadPercent + "%", x + 890, y + 330);

        var w = data.batteryVoltage * (data.batteryCurrent - data.batteryDischargeCurrent)
        ctx.fillText((data.solarVoltage * data.solarCurrent - w).toFixed(0) + "W", x + 800, y + 355)

        ctx.stroke();


        this.triangleAppend([x + 590, y + 370, 0]);
        this.triangleAppend([x + 640, y + 370, 0]);

        if (w > 0 && data.solarCurrent > 0) {
            this.triangleAppend([x + 690, y + 370, 0]);
            this.triangleAppend([x + 740, y + 370, 0]);
            this.triangleAppend([x + 790, y + 370, 0]);
            this.triangleAppend([x + 840, y + 370, 0]);
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
        ctx.strokeStyle = '#50a8f7';

        // MPPT to battery
        ctx.beginPath();
        ctx.lineWidth = 1;
        ctx.moveTo(x + 625, y + 370);
        ctx.lineTo(x + 625, y + 230);

        ctx.moveTo(x + 548, y + 370);
        ctx.lineTo(x + 625, y + 370);
        ctx.stroke();

        //ctx.beginPath();

        if (data.batteryCurrent - data.batteryDischargeCurrent > 0) {
            // up
            this.triangleAppend([x + 625, y + 330, 90]);
            this.triangleAppend([x + 625, y + 290, 90]);
            this.triangleAppend([x + 625, y + 250, 90]);
        } else {
            // down
            //console.log(this.triangleArray);
            this.triangleAppend([x + 625, y + 260, 270]);
            this.triangleAppend([x + 625, y + 300, 270]);
            this.triangleAppend([x + 625, y + 340, 270]);
        }
        this.triangleDraw(true);
        //ctx.fill();
        //ctx.stroke();

        ctx.beginPath();
        ctx.font = "20px Arial";
        ctx.fillStyle = "#50a8f7";

        ctx.fillText((data.batteryVoltage * (data.batteryCurrent - data.batteryDischargeCurrent)).toFixed(0) + "W", x + 610, y + 278);
        ctx.fillText(data.batteryCurrent - data.batteryDischargeCurrent + "A", x + 610, y + 302);

        ctx.stroke();
    }

    this.convertor = function(x, y, text1, text2) {
        var ctx = this.ctx;
        ctx.beginPath();
        ctx.strokeStyle = '#50a8f7';
        ctx.lineWidth = 3;
        ctx.moveTo(x + 527, y + 140);
        ctx.arc(x + 500, y + 140, 28, 0, 2 * Math.PI);
        ctx.moveTo(x + 512, y + 127);
        ctx.lineTo(x + 487, y + 155);

        ctx.font = "13px Arial";
        ctx.fillStyle = "#50a8f7";
        ctx.fillText(text1, x + 500, y + 136)
        ctx.fillText(text2, x + 521, y + 153)

        ctx.stroke();
    }

    this.utilityToBattery = function(data, x, y) {
        // charge from utility
        // bypass
        if (data.solarCurrent == 0 && data.batteryCurrent > 0 && data.workingStatus == L) {
            
            var ctx = this.ctx;
            ctx.strokeStyle = '#50a8f7';

            ctx.beginPath();
            ctx.lineWidth = 1;

            ctx.moveTo(x + 390, y + 85);
            ctx.lineTo(x + 470, y + 125);

            ctx.moveTo(x + 530, y + 155);
            ctx.lineTo(x + 590, y + 186);
            ctx.stroke();

            // convertor AC/DC
            this.convertor(x, y, AC, DC);
        }
    }

    this.bypass = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = '#50a8f7';

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
        ctx.fillStyle = "#50a8f7";
        ctx.fillText("BYPASS", x + 585, y + 50)

        if (data.batteryDischargeCurrent == 0 &&
            data.workingStatus != "L" &&
            outputPowerApparent > 0) {
            // power from utility
        }

        ctx.stroke();
    }

    this.values = function(data, x, y) {
        var ctx = this.ctx;

        ctx.font = "17px Courier New";
        ctx.fillStyle = "#50a8f7";


        ctx.beginPath();
        ctx.lineWidth = 1;
        this.ctx.textAlign = 'left';

        y = y + 200;
        ctx.fillText("Solar Char. Current: ", x + 5, y);
        ctx.fillText("Mains Char. Current: ", x + 5, y + 20);
        ctx.fillText("Batt. Fast Charge: ", x + 5, y + 40);
        ctx.fillText("Batt. Floating: ", x + 5, y + 60);
        ctx.fillText("Batt. Mains Switch: ", x + 5, y + 80);
        ctx.fillText("Batt. Shutdown: ", x + 5, y + 100);
        ctx.fillText("Charging Priority: ", x + 5, y + 120);
        ctx.fillText("Input Range: ", x + 5, y + 140);
        ctx.fillText("Load Source Priority: ", x + 5, y + 160);
        
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

        ctx.stroke();
    }

    this.mppt = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = '#50a8f7';

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

        //ctx.moveTo(x + 95, y - 13);
        ctx.beginPath();
        ctx.arc(x + 95, y - 13, 12, 9, .55 * Math.PI);

        // sun
        ctx.moveTo(x + 98, y - 3);
        ctx.lineTo(x + 102, y + 10);
        ctx.moveTo(x + 106, y - 6);
        ctx.lineTo(x + 116, y + 1);
        ctx.moveTo(x + 108, y - 14);
        ctx.lineTo(x + 120, y - 14);
        ctx.moveTo(x + 105, y - 22);
        ctx.lineTo(x + 116, y - 29);


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
        ctx.fillStyle = "#50a8f7";
        ctx.fillText("MPPT", x + 110, y + 90)

        ctx.fillText(Math.round(data.solarVoltage * data.solarCurrent) + "W", x + 40, y - 70)
        ctx.fillText(data.solarVoltage + "V", x + 40, y - 45)
        ctx.fillText(data.solarCurrent + "A", x + 40, y - 20)

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
        ctx.strokeStyle = '#50a8f7';

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
        ctx.fillStyle = "#50a8f7";
        ctx.fillText(data.gridVoltage + "V", x + 110, y - 30)
        ctx.fillText(data.gridFreq + "Hz", x + 110, y - 10)
        
        ctx.stroke();
    }

    this.home = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = '#50a8f7';

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
        ctx.fillStyle = "#50a8f7";
        ctx.fillText(Math.round(data.outputPowerActive) + "W", x + 73, y + 5)
        ctx.fillText(Math.round(data.outputPowerApparent) + "W", x + 73, y + 25)

        ctx.stroke();
    }

    this.battery = function(data, x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = '#50a8f7';

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
        ctx.fillStyle = "#50a8f7";
        ctx.fillText(data.batteryVoltage + "V", x + 85, y + 43)
        var v = ((data.batteryVoltage-42)/(58.8-42)*(100)).toFixed(2)
        ctx.fillText(v + "%", x + 97, y + 63)
        ctx.stroke();
    }

    this.clear = function(x, y) {
        var ctx = this.ctx;
        ctx.strokeStyle = '#50a8f7';

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

