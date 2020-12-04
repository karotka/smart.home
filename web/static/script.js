
gEl = function(id) { return document.getElementById(id); }

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
