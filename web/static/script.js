
gEl = function(id) { return document.getElementById(id); }
cEl = function(tagName, opts = null) { return document.createElement(tagName, opts); }

window.onload = function() { setInterval( timeNow, 500); }

function timeNow() {
    d = new Date();
    s = d.getSeconds();
    m = d.getMinutes();
    if ( s < 10 ) { s = "0" + s; }
    if ( m < 10 ) { m = "0" + m; }
    gEl("time").innerHTML =
        d.getDate() + "." +
        d.getMonth() + "." +
        d.getFullYear() + " " +
        d.getHours() + ":" +
        m + ":" + s;
}

var Heating = {

    add: function () {
        var value = gEl("heatTime0").value;
        client.heatingAdd(document.roomId, value);
    },

    delete: function(index) {
        client.heatingDelete(document.roomId, index);
    }

};
