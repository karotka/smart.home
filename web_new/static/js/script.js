function gEl(el) { return document.querySelector(el); }
function cEl(el) { return document.createElement(el); }

function timeNow() {
    var d = new Date();
    var s = d.getSeconds();
    var m = d.getMinutes();
    var h = d.getHours();
    gEl("#time").textContent =
        ("0" + h).substr(-2) + ":" + ("0" + m).substr(-2) + ":" + ("0" + s).substr(-2);
}
setInterval(timeNow, 500);
