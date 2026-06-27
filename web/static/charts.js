// Minimal SVG line / column chart for the heat-pump dashboard.
// One file, no dependencies, no remote links, no watermark. Replaces
// CanvasJS for the use case we actually have:
//   * one or two time-series per chart
//   * linear axes, no zooming/panning
//   * tooltip on hover (desktop) and on tap (mobile)
//
// Public API:
//   var c = new SimpleChart("containerId", {
//       title: "…",
//       bgColor: "#303D54",                       // optional
//       series: [
//           {points: refToDpsArray, type: "line"|"column",
//            color: "#ff6746", name: "in"}        // name => legend
//       ],
//       xFormat: "D.M." | "HH:mm",
//       yFormat: "#0.#°C" | "#0W",                // unit + precision
//       tooltipUnit: "°C" | " W",
//   });
//   ...mutate the dps arrays externally and then...
//   c.render();
(function (global) {
    "use strict";

    var SVG_NS = "http://www.w3.org/2000/svg";

    function svg(tag, attrs) {
        var el = document.createElementNS(SVG_NS, tag);
        if (attrs) {
            for (var k in attrs) {
                if (attrs[k] != null) el.setAttribute(k, attrs[k]);
            }
        }
        return el;
    }

    function pad2(n) { return n < 10 ? "0" + n : "" + n; }

    function fmtX(d, fmt) {
        if (fmt === "D.M.")  return d.getDate() + "." + (d.getMonth() + 1) + ".";
        if (fmt === "HH:mm") return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
        return d.toLocaleString();
    }
    function fmtTooltipDate(d) {
        return pad2(d.getDate()) + "." + pad2(d.getMonth() + 1) + ". " +
               pad2(d.getHours()) + ":" + pad2(d.getMinutes());
    }
    function fmtY(v, fmt) {
        if (fmt === "#0.#°C") return v.toFixed(1) + "°C";
        if (fmt === "#0W")    return Math.round(v) + "W";
        return "" + v;
    }

    function SimpleChart(containerId, opts) {
        this.container = typeof containerId === "string"
            ? document.getElementById(containerId)
            : containerId;
        this.opts = opts || {};
    }

    SimpleChart.prototype.render = function () {
        var c = this.container;
        if (!c) return;
        var W = c.clientWidth, H = c.clientHeight;
        if (W < 80 || H < 80) return;

        // Wipe any previous drawing.
        while (c.firstChild) c.removeChild(c.firstChild);

        var o = this.opts;
        var bg = o.bgColor || "#303D54";
        var padL = 46, padR = 12, padT = o.title ? 32 : 14, padB = 36;
        var plotW = W - padL - padR;
        var plotH = H - padT - padB;
        if (plotW < 20 || plotH < 20) return;

        var root = svg("svg", {width: W, height: H});
        root.style.display = "block";
        root.style.background = bg;
        c.appendChild(root);

        // Title
        if (o.title) {
            var title = svg("text", {
                x: W / 2, y: 18, "text-anchor": "middle",
                fill: "#e6e6e6", "font-size": "14",
                "font-family": "Lato, Helvetica, sans-serif",
            });
            title.textContent = o.title;
            root.appendChild(title);
        }

        // Collect extents.
        var series = (o.series || []).filter(function (s) {
            return s && Array.isArray(s.points) && s.points.length;
        });
        var xs = [], ys = [];
        series.forEach(function (s) {
            s.points.forEach(function (p) {
                var x = p.x instanceof Date ? p.x.getTime() :
                        typeof p.x === "string" ? Date.parse(p.x) : p.x;
                if (!isFinite(x)) return;
                if (p.y == null) return;
                xs.push(x);
                ys.push(p.y);
            });
        });
        // No data yet — leave the title and a faint frame so the user
        // still sees the slot. The next render() call (after data
        // arrives) will repaint the whole thing.
        if (!xs.length) {
            var frame = svg("rect", {
                x: padL, y: padT, width: plotW, height: plotH,
                fill: "none", stroke: "#e6e6e6", "stroke-opacity": "0.12",
            });
            root.appendChild(frame);
            var hint = svg("text", {
                x: padL + plotW / 2, y: padT + plotH / 2,
                "text-anchor": "middle",
                fill: "#e6e6e6", "fill-opacity": "0.4",
                "font-size": "11",
            });
            hint.textContent = "loading…";
            root.appendChild(hint);
            return;
        }

        var xMin = Math.min.apply(null, xs);
        var xMax = Math.max.apply(null, xs);
        if (xMin === xMax) xMax = xMin + 1;
        var yMin = Math.min.apply(null, ys);
        var yMax = Math.max.apply(null, ys);
        var yPad = (yMax - yMin) * 0.08 || 1;
        yMin -= yPad;
        yMax += yPad;

        var anyColumn = series.some(function (s) { return s.type === "column"; });
        if (anyColumn) {
            yMin = Math.min(0, yMin);
            yMax = Math.max(0, yMax);
        }

        function xp(t) { return padL + plotW * (t - xMin) / (xMax - xMin); }
        function yp(v) { return padT + plotH * (1 - (v - yMin) / (yMax - yMin)); }

        // Y grid + labels
        var nY = 5;
        for (var i = 0; i <= nY; i++) {
            var yv = yMin + (yMax - yMin) * i / nY;
            var py = yp(yv);
            root.appendChild(svg("line", {
                x1: padL, x2: W - padR, y1: py, y2: py,
                stroke: "#e6e6e6", "stroke-opacity": "0.15",
            }));
            var t = svg("text", {
                x: padL - 6, y: py + 4, "text-anchor": "end",
                fill: "#e6e6e6", "font-size": "11",
            });
            t.textContent = fmtY(yv, o.yFormat);
            root.appendChild(t);
        }

        // X labels (rotated, ~5 of them).
        var nX = 5;
        for (var i = 0; i <= nX; i++) {
            var xv = xMin + (xMax - xMin) * i / nX;
            var px = xp(xv);
            root.appendChild(svg("line", {
                x1: px, x2: px, y1: padT, y2: H - padB,
                stroke: "#e6e6e6", "stroke-opacity": "0.08",
            }));
            var lbl = svg("text", {
                x: px, y: H - padB + 14, "text-anchor": "end",
                fill: "#e6e6e6", "font-size": "11",
                transform: "rotate(-40 " + px + "," + (H - padB + 14) + ")",
            });
            lbl.textContent = fmtX(new Date(xv), o.xFormat);
            root.appendChild(lbl);
        }

        // Series.
        series.forEach(function (s, idx) {
            if (s.type === "column") {
                var pts = s.points.filter(function (p) { return p.y != null; });
                var barW = Math.max(2, plotW / pts.length * 0.7);
                var py0 = yp(0);
                pts.forEach(function (p) {
                    var x = p.x instanceof Date ? p.x.getTime() : Date.parse(p.x);
                    var px = xp(x);
                    var pyv = yp(p.y);
                    root.appendChild(svg("rect", {
                        x: px - barW / 2,
                        y: Math.min(pyv, py0),
                        width: barW,
                        height: Math.max(1, Math.abs(py0 - pyv)),
                        fill: s.color || "#ff6746",
                    }));
                });
            } else {
                var coords = "";
                s.points.forEach(function (p) {
                    if (p.y == null) return;
                    var x = p.x instanceof Date ? p.x.getTime() : Date.parse(p.x);
                    coords += xp(x) + "," + yp(p.y) + " ";
                });
                root.appendChild(svg("polyline", {
                    points: coords,
                    fill: "none",
                    stroke: s.color || "#ff6746",
                    "stroke-width": "2",
                    "stroke-linejoin": "round",
                    "stroke-linecap": "round",
                }));
            }
        });

        // Legend (only when more than one named series).
        var named = series.filter(function (s) { return s.name; });
        if (named.length > 1) {
            var lx = padL;
            var ly = 16;
            named.forEach(function (s) {
                root.appendChild(svg("rect", {
                    x: lx, y: ly - 8, width: 10, height: 10, fill: s.color,
                }));
                var t = svg("text", {
                    x: lx + 14, y: ly + 1, fill: "#e6e6e6", "font-size": "11",
                });
                t.textContent = s.name;
                root.appendChild(t);
                lx += 24 + s.name.length * 7;
            });
        }

        // Crosshair + tooltip on pointer-move / touch.
        var crosshair = svg("line", {
            x1: 0, x2: 0, y1: padT, y2: H - padB,
            stroke: "#e6e6e6", "stroke-opacity": "0.4",
            "pointer-events": "none", visibility: "hidden",
        });
        root.appendChild(crosshair);

        var tipBox = document.createElement("div");
        tipBox.style.cssText =
            "position:absolute;pointer-events:none;background:#1b2435;" +
            "color:#e6e6e6;padding:4px 8px;border:1px solid #4dabf7;" +
            "border-radius:3px;font-size:12px;font-variant-numeric:tabular-nums;" +
            "white-space:nowrap;display:none;z-index:5;line-height:1.3";
        if (getComputedStyle(c).position === "static") c.style.position = "relative";
        c.appendChild(tipBox);

        var unit = o.tooltipUnit || "";

        function nearest(tx) {
            // For the first series, find the data point whose x is closest to tx.
            var s = series[0];
            if (!s) return null;
            var best = null, bestDist = Infinity;
            s.points.forEach(function (p, i) {
                if (p.y == null) return;
                var x = p.x instanceof Date ? p.x.getTime() : Date.parse(p.x);
                var d = Math.abs(x - tx);
                if (d < bestDist) { bestDist = d; best = {i: i, x: x}; }
            });
            return best;
        }

        function moveTo(clientX, clientY) {
            var rect = c.getBoundingClientRect();
            var x = clientX - rect.left;
            if (x < padL || x > W - padR) { hide(); return; }
            var tx = xMin + (xMax - xMin) * (x - padL) / plotW;
            var hit = nearest(tx);
            if (!hit) { hide(); return; }
            var snapX = xp(hit.x);
            crosshair.setAttribute("x1", snapX);
            crosshair.setAttribute("x2", snapX);
            crosshair.setAttribute("visibility", "visible");

            var lines = ['<div>' + fmtTooltipDate(new Date(hit.x)) + '</div><b>'];
            series.forEach(function (s, idx) {
                var p = s.points[hit.i];
                if (!p || p.y == null) return;
                var v = p.y.toFixed(1) + unit;
                if (idx > 0) lines.push(' / ');
                lines.push(v);
            });
            lines.push('</b>');
            tipBox.innerHTML = lines.join("");
            tipBox.style.display = "block";
            // Position relative to the container.
            var tipX = snapX + 8;
            if (tipX + tipBox.offsetWidth > W) tipX = snapX - tipBox.offsetWidth - 8;
            tipBox.style.left = tipX + "px";
            tipBox.style.top  = (padT + 4) + "px";
        }

        function hide() {
            crosshair.setAttribute("visibility", "hidden");
            tipBox.style.display = "none";
        }

        root.addEventListener("mousemove", function (e) { moveTo(e.clientX, e.clientY); });
        root.addEventListener("mouseleave", hide);
        root.addEventListener("touchstart", function (e) {
            var t = e.touches[0]; if (t) moveTo(t.clientX, t.clientY);
        }, {passive: true});
        root.addEventListener("touchmove", function (e) {
            var t = e.touches[0]; if (t) moveTo(t.clientX, t.clientY);
        }, {passive: true});
        root.addEventListener("touchend", hide);
    };

    global.SimpleChart = SimpleChart;
})(window);
