
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


function addHeatingValue(   ) {
    var el = gEl("heatTime");
    var value = gEl("heatTime0").value;
    el.innerHTML += "<div>" + value+" <input type='button' onclick='javascript:deleteHeatingValue(this);' value='Delete' /></div>";

}

function deleteHeatingValue(item) {

    console.log(item);
}
