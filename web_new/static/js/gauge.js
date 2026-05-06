(function(global, factory) {
    var Gauge = factory(global);
    if (typeof define === "function" && define.amd) {
        define(function() {
            return Gauge;
        });
    } else {
        if (typeof module === "object" && module.exports) {
            module.exports = Gauge;
        } else {
            global.Gauge = Gauge;
        }
    }
})(typeof window === "undefined" ? this : window, function(window, canCreateDiscussions) {
    /**
     * @param {!Object} params
     * @return {undefined}
     */
    function Animation(params) {
        /**
         * @return {undefined}
         */
        function tick() {
            /** @type {number} */
            var percent = value / length;
            var p = i * parseFloat(percent) + start;
            step(p, value);
            value = value + 1;
            if (percent < 1) {
                requestAnimationFrame(tick);
            }
        }
        var duration = params.duration;
        /** @type {number} */
        var value = 1;
        /** @type {number} */
        var length = 60 * duration;
        var start = params.start || 0;
        var l = params.end;
        /** @type {number} */
        var i = l - start;
        var step = params.step;
        var parseFloat = params.easing || function ease(t) {
            if ((t = t / 0.5) < 1) {
                return 0.5 * Math.pow(t, 3);
            }
            return 0.5 * (Math.pow(t - 2, 3) + 2);
        };
        requestAnimationFrame(tick);
    }
    var document = window.document;
    var requestAnimationFrame = window.requestAnimationFrame || window.mozRequestAnimationFrame || window.webkitRequestAnimationFrame || window.msRequestAnimationFrame || function(callback) {
        return setTimeout(callback, 1000 / 60);
    };
    var Gauge = function() {

        function svg(type, attrs, options) {
            var node = document.createElementNS(svgNs, type);
            var attr;
            for (attr in attrs) {
                node.setAttribute(attr, attrs[attr]);
            }
            if (options) {
                options.forEach(function(c) {
                    node.appendChild(c);
                });
            }
            return node;
        }

        function getAngle(value, percent) {
            return value * percent / 100;
        }
        /**
         * @param {?} obj
         * @param {number} limit
         * @param {number} count
         * @return {?}
         */
        function normalize(obj, limit, count) {
            /** @type {number} */
            var date = Number(obj);
            if (date > count) {
                return count;
            }
            if (date < limit) {
                return limit;
            }
            return date;
        }

        function f(value, min, max) {
            /** @type {number} */
            var total = max - min;
            /** @type {number} */
            var diff = value - min;
            return 100 * diff / total;
        }

        function getCartesian(cx, cy, radius, angle) {
            /** @type {number} */
            var endAngleRad = angle * Math.PI / 180;
            return {
                x: Math.round((cx + radius * Math.cos(endAngleRad)) * 1000) / 1000,
                y: Math.round((cy + radius * Math.sin(endAngleRad)) * 1000) / 1000
            };
        }

        function getDialCoords(radius, startAngle, endAngle) {
            /** @type {number} */
            var cx = textProp.centerX;
            /** @type {number} */
            var cy = textProp.centerY;
            return {
                end: getCartesian(cx, cy, radius, endAngle),
                start: getCartesian(cx, cy, radius, startAngle)
            };
        }

        /** @type {string} */
        var svgNs = "http://www.w3.org/2000/svg";
        var textProp = {
            centerX: 50,
            centerY: 50
        };
        var obj = {
            dialRadius: 40,
            dialStartAngle: 135,
            dialEndAngle: 45,
            value: 0,
            value1: 0,
            value2: 0,
            title: "",
            max: 100,
            min: 0,
            min1: 0,
            min2: 0,
            strokeWidth: 8,
            valueDialClass: "value",
            valueClass: "value-text",
            dialClass: "dial",
            gaugeClass: "gauge",
            showValue: true,
            gaugeColor: null,
            dual: false, // Enable dual gauge mode
            label: function(val) {
                return Math.round(val);
            },
            label1: function(val) {
                return Math.round(val);
            },
            label2: function(val) {
                return Math.round(val);
            },
            // Secondary gauge labels (for dual mode)
            labelSecondary: function(val) {
                return Math.round(val);
            },
            label1Secondary: function(val) {
                return Math.round(val);
            },
            label2Secondary: function(val) {
                return Math.round(val);
            }
        };

        return function Gauge(elem, opts) {

            function pathString(radius, startAngle, endAngle, largeArc) {
                var coords = getDialCoords(radius, startAngle, endAngle);
                //console.log("COORDS:" + coords.start);
                var start = coords.start;
                var end = coords.end;
                var largeArcFlag = typeof largeArc === "undefined" ? 1 : largeArc;
                return ["M", start.x, start.y, "A", radius, radius, 0, largeArcFlag, 1, end.x, end.y].join(" ");
                //console.log("RAD" + radius);
            }

            function render(elem) {
                // Shared text attributes
                var textAttrs = {
                    fill: "#e6e6e6",
                    "font-family": "sans-serif",
                    "font-weight": "normal",
                    "text-anchor": "middle",
                    "alignment-baseline": "middle",
                    "dominant-baseline": "central"
                };

                var isDual = opts.dual;
                var innerRadius = radius - 5;

                gaugeTextTitle = svg("text", Object.assign({}, textAttrs, {
                    x: 49, y: isDual ? 28 : 26, "class": "gauge-title", "font-size": "9px"
                }));
                gaugeTextTitle.textContent = title;

                if (isDual) {
                    // Dual mode layout - MPPT1 values on top, MPPT2 values below
                    gaugeTextElem1 = svg("text", Object.assign({}, textAttrs, {
                        x: 34, y: 40, "class": "gauge-text-elem1", "font-size": "6px"
                    }));
                    gaugeTextElem2 = svg("text", Object.assign({}, textAttrs, {
                        x: 66, y: 40, "class": "gauge-text-elem2", "font-size": "6px"
                    }));
                    gaugeTextElem = svg("text", Object.assign({}, textAttrs, {
                        x: 50, y: 50, "class": "gauge-text-elem", "font-size": "9px"
                    }));
                    // Secondary gauge text elements
                    gaugeTextElem1Sec = svg("text", Object.assign({}, textAttrs, {
                        x: 34, y: 62, "class": "gauge-text-elem1-sec", "font-size": "6px"
                    }));
                    gaugeTextElem2Sec = svg("text", Object.assign({}, textAttrs, {
                        x: 66, y: 62, "class": "gauge-text-elem2-sec", "font-size": "6px"
                    }));
                    gaugeTextElemSec = svg("text", Object.assign({}, textAttrs, {
                        x: 50, y: 72, "class": "gauge-text-elem-sec", "font-size": "9px"
                    }));
                    // Separators for dual mode
                    gaugeHSeparator = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 24, "y1": 57, "x2": 76, "y2": 57
                    });
                    gaugeHSeparator1 = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 24, "y1": 34, "x2": 76, "y2": 34
                    });
                    gaugeVSeparator = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 50, "y1": 36, "x2": 50, "y2": 44
                    });
                    gaugeVSeparator2 = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 50, "y1": 58, "x2": 50, "y2": 66
                    });
                } else {
                    gaugeTextElem = svg("text", Object.assign({}, textAttrs, {
                        x: 50, y: 70, "class": "gauge-text-elem", "font-size": "11px"
                    }));
                    gaugeTextElem1 = svg("text", Object.assign({}, textAttrs, {
                        x: 34, y: 48, "class": "gauge-text-elem1", "font-size": "8px"
                    }));
                    gaugeTextElem2 = svg("text", Object.assign({}, textAttrs, {
                        x: 65, y: 48, "class": "gauge-text-elem2", "font-size": "8px"
                    }));
                    gaugeHSeparator = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 20, "y1": 60, "x2": 80, "y2": 60
                    });
                    gaugeHSeparator1 = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 20, "y1": 35, "x2": 80, "y2": 35
                    });
                    gaugeVSeparator = svg("line", {
                        fill: "none", stroke: "#808080", "stroke-width": 1,
                        "x1": 50, "y1": 38, "x2": 50, "y2": 58
                    });
                    gaugeVSeparator2 = svg();
                    gaugeTextElem1Sec = svg();
                    gaugeTextElem2Sec = svg();
                    gaugeTextElemSec = svg();
                }

                // Outer arc (primary gauge)
                gaugeValuePath = svg("path", {
                    fill: "none",
                    stroke: "blue",
                    "stroke-width": isDual ? 4 : 8,
                    d: pathString(radius, startAngle, startAngle)
                });

                // Inner arc (secondary gauge for dual mode)
                if (isDual) {
                    gaugeValuePathSec = svg("path", {
                        fill: "none",
                        stroke: "#00cc00",
                        "stroke-width": 4,
                        d: pathString(innerRadius, startAngle, startAngle)
                    });
                } else {
                    gaugeValuePathSec = svg();
                }

                var blob1AngleRight = getAngle(100, 300 - Math.abs(startAngle - endAngle));
                var flag = blob1AngleRight <= 180 ? 0 : 1;

                var children = [
                    // Background arcs
                    svg("path", {
                        "class": simplifyClassNode,
                        fill: "none",
                        stroke: "#808080",
                        "stroke-width": isDual ? 4 : 8,
                        d: pathString(radius, startAngle, endAngle, flag)
                    })
                ];

                if (isDual) {
                    children.push(svg("path", {
                        fill: "none",
                        stroke: "#606060",
                        "stroke-width": 4,
                        d: pathString(innerRadius, startAngle, endAngle, flag)
                    }));
                }

                children.push(
                    gaugeTextTitle, gaugeTextElem, gaugeTextElem1, gaugeTextElem2,
                    gaugeTextElemSec, gaugeTextElem1Sec, gaugeTextElem2Sec,
                    gaugeHSeparator, gaugeHSeparator1, gaugeVSeparator, gaugeVSeparator2,
                    gaugeValuePath, gaugeValuePathSec
                );

                var gaugeElement = svg("svg", {
                    "viewBox": viewBox || "0 0 100 100",
                    "class": lastGlobalUpdate
                }, children);
                elem.appendChild(gaugeElement);
            }

            function updateGauge(name, item) {
                if (item == 0) {
                    var percent = f(name, min, max);
                    var angle = getAngle(percent, 360 - Math.abs(startAngle - endAngle));
                    var flag = angle <= 180 ? 0 : 1;
                    if (toastBox) {
                        gaugeTextElem.textContent = config.call(opts, name);
                    }
                    gaugeValuePath.setAttribute("d", pathString(radius, startAngle, angle + startAngle, flag));
                } else if (item == 1) {
                    if (toastBox) {
                        gaugeTextElem1.textContent = config1.call(opts, name);
                    }
                } else {
                    if (toastBox) {
                        gaugeTextElem2.textContent = config2.call(opts, name);
                    }
                }
            }

            // Update secondary gauge (for dual mode)
            function updateGaugeSec(name, item) {
                if (!isDual) return;
                if (item == 0) {
                    var percent = f(name, min, max);
                    var angle = getAngle(percent, 360 - Math.abs(startAngle - endAngle));
                    var flag = angle <= 180 ? 0 : 1;
                    if (toastBox) {
                        gaugeTextElemSec.textContent = configSec.call(opts, name);
                    }
                    gaugeValuePathSec.setAttribute("d", pathString(innerRadius, startAngle, angle + startAngle, flag));
                } else if (item == 1) {
                    if (toastBox) {
                        gaugeTextElem1Sec.textContent = config1Sec.call(opts, name);
                    }
                } else {
                    if (toastBox) {
                        gaugeTextElem2Sec.textContent = config2Sec.call(opts, name);
                    }
                }
            }


            function setPathColor(value, duration) {
                var strokeColor = color(value);
                var durationMs = duration * 1000;
                var transition = "stroke " + durationMs + "ms ease";
                gaugeValuePath.style = "stroke: " + strokeColor + "; -webkit-transition: " + transition;
            }
            opts = Object.assign({}, obj, opts);
            var title = opts.title;
            var max = opts.max;
            var max1 = opts.max1;
            var max2 = opts.max2;
            var min = opts.min;
            var min1 = opts.min1;
            var min2 = opts.min2;
            var value = normalize(opts.value, min, max);
            var value1 = normalize(opts.value1, min1, max1);
            var value2 = normalize(opts.value2, min2, max2);
            var valueSec = 0;
            var value1Sec = 0;
            var value2Sec = 0;
            var radius = opts.dialRadius;
            var toastBox = opts.showValue;
            var startAngle = opts.dialStartAngle;
            var endAngle = opts.dialEndAngle;
            //var detailedEvents = opts.valueDialClass;
            //var _featureClick = opts.valueClass;
            //var MAX_RECONNECT_TRIES = opts.valueLabelClass;
            var simplifyClassNode = opts.dialClass;
            var lastGlobalUpdate = opts.gaugeClass;
            var color = opts.color;
            //var unit = opts.unit;
            var gaugeTextElem;
            var gaugeTextElem1;
            var gaugeTextElem2;
            var gaugeTextElemSec;
            var gaugeTextElem1Sec;
            var gaugeTextElem2Sec;
            var gaugeValuePath;
            var gaugeValuePathSec;
            var gaugeVSeparator2;
            var config = opts.label;
            var config1 = opts.label1;
            var config2 = opts.label2;
            var configSec = opts.labelSecondary;
            var config1Sec = opts.label1Secondary;
            var config2Sec = opts.label2Secondary;
            var isDual = opts.dual;
            var innerRadius = radius - 5;
            var viewBox = opts.viewBox;
            var instance;
            if (startAngle < endAngle) {
                console.log("WARN! startAngle < endAngle, Swapping");
                var temp = startAngle;
                startAngle = endAngle;
                endAngle = temp;
            }

            instance = {


                setValueAnimated: function(val, val1,  duration) {

                    var oldVal = value;
                    value = normalize(val, min, max);
                    if (oldVal === value) {
                        return;
                    }
                    if (color) {
                        setPathColor(value, duration);
                    }


                    //console.log(value);
                    Animation({
                        start: oldVal || 0,
                        end: value,
                        duration: duration || 1,
                        step: function(val) {
                            updateGauge(val, 0);
                        }
                    });


                },

                setValueAnimated1: function(val, duration) {

                    var oldVal1 = value1;
                    value1 = normalize(val, min1, max1);

                    if (oldVal1 === value1) {
                        return;
                    }

                    Animation({
                        start: oldVal1 || 0,
                        end: value1,
                        duration: duration || 1,
                        step: function(val) {
                            updateGauge(val, 1);
                        }
                    });
                },

                setValueAnimated2: function(val, duration) {
                    var oldVal2 = value2;
                    value2 = normalize(val, min2, max2);
                    if (oldVal2 === value2) {
                        return;
                    }
                    Animation({
                        start: oldVal2 || 0,
                        end: value2,
                        duration: duration || 1,
                        step: function(val) {
                            updateGauge(val, 2);
                        }
                    });
                },

                // Secondary gauge methods (for dual mode)
                setValueAnimatedSec: function(val, duration) {
                    if (!isDual) return;
                    var oldVal = valueSec;
                    valueSec = normalize(val, min, max);
                    if (oldVal === valueSec) {
                        return;
                    }
                    if (color) {
                        var strokeColor = color(valueSec);
                        gaugeValuePathSec.style = "stroke: " + strokeColor;
                    }
                    Animation({
                        start: oldVal || 0,
                        end: valueSec,
                        duration: duration || 1,
                        step: function(val) {
                            updateGaugeSec(val, 0);
                        }
                    });
                },

                setValueAnimated1Sec: function(val, duration) {
                    if (!isDual) return;
                    var oldVal = value1Sec;
                    value1Sec = normalize(val, min1, max1);
                    if (oldVal === value1Sec) {
                        return;
                    }
                    Animation({
                        start: oldVal || 0,
                        end: value1Sec,
                        duration: duration || 1,
                        step: function(val) {
                            updateGaugeSec(val, 1);
                        }
                    });
                },

                setValueAnimated2Sec: function(val, duration) {
                    if (!isDual) return;
                    var oldVal = value2Sec;
                    value2Sec = normalize(val, min2, max2);
                    if (oldVal === value2Sec) {
                        return;
                    }
                    Animation({
                        start: oldVal || 0,
                        end: value2Sec,
                        duration: duration || 1,
                        step: function(val) {
                            updateGaugeSec(val, 2);
                        }
                    });
                }
            };
            //console.log(text);
            render(elem);
            //instance.setValue(value);
            return instance;
        };
    }();
    return Gauge;
});
