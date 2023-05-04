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
    /** @type {function(this:(IArrayLike<T>|string), *=, *=): !Array<T>} */
    var slice = Array.prototype.slice;
    var requestAnimationFrame = window.requestAnimationFrame || window.mozRequestAnimationFrame || window.webkitRequestAnimationFrame || window.msRequestAnimationFrame || function(callback) {
        return setTimeout(callback, 1000 / 60);
    };
    var Gauge = function() {
        /**
         * @return {?}
         */
        function defaults() {
            var obj = arguments[0];
            /** @type {!Array<?>} */
            var excludeElements = slice.call(arguments, 1);
            excludeElements.forEach(function(sup) {
                for (k in sup) {
                    if (sup.hasOwnProperty(k)) {
                        obj[k] = sup[k];
                    }
                }
            });
            //console.log(obj);
            return obj;
        }

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
            label: function(val) {
                return Math.round(val);
            },
            label1: function(val) {
                return Math.round(val);
            },
            label2: function(val) {
                return Math.round(val);
            }
        };

        return function Gauge(elem, opts) {

            function pathString(radius, startAngle, endAngle, largeArc) {
                var coords = getDialCoords(radius, startAngle, endAngle);
                var start = coords.start;
                var end = coords.end;
                var largeArcFlag = typeof largeArc === "undefined" ? 1 : largeArc;
                return ["M", start.x, start.y, "A", radius, radius, 0, largeArcFlag, 1, end.x, end.y].join(" ");
            }

            function render(elem) {

                gaugeTextTitle = svg("text", {

                    x: 49,
                    y: 26,
                    fill: "#e6e6e6",
                    "class": "gauge-title",
                    "font-size": "9px",
                    "font-family": "sans-serif",
                    "font-weight": "normal",
                    "text-anchor": "middle",
                    "alignment-baseline": "middle",
                    "dominant-baseline": "central",
                });
                gaugeTextTitle.textContent = title;

                gaugeTextElem = svg("text", {
                    x: 50,
                    y: 70,
                    fill: "#e6e6e6",
                    "class": "gauge-text-elem",
                    "font-size": "11px",
                    "font-family": "sans-serif",
                    "font-weight": "normal",
                    "text-anchor": "middle",
                    "alignment-baseline": "middle",
                    "dominant-baseline": "central"
                });

                gaugeTextElem1 = svg("text", {
                    x: 34,
                    y: 48,
                    fill: "#e6e6e6",
                    "class": "gauge-text-elem1",
                    "font-size": "8px",
                    "font-family": "sans-serif",
                    "font-weight": "normal",
                    "text-anchor": "middle",
                    "alignment-baseline": "middle",
                    "dominant-baseline": "central"
                });

                gaugeTextElem2 = svg("text", {
                    x: 65,
                    y: 48,
                    fill: "#e6e6e6",
                    "class": "gauge-text-elem2",
                    "font-size": "8px",
                    "font-family": "sans-serif",
                    "font-weight": "normal",
                    "text-anchor": "middle",
                    "alignment-baseline": "middle",
                    "dominant-baseline": "central"
                });

                gaugeHSeparator = svg("line", {
                    fill: "none",
                    stroke: "#808080",
                    "stroke-width": 1,
                    "x1": 20,
                    "y1": 60,
                    "x2": 80,
                    "y2": 60,
                });

                gaugeHSeparator1 = svg("line", {
                    fill: "none",
                    stroke: "#808080",
                    "stroke-width": 1,
                    "x1": 20,
                    "y1": 35,
                    "x2": 80,
                    "y2": 35,
                });

                gaugeVSeparator = svg("line", {
                    fill: "none",
                    stroke: "#808080",
                    "stroke-width": 1,
                    "x1": 50,
                    "y1": 38,
                    "x2": 50,
                    "y2": 58,
                });

                gaugeValuePath = svg("path", {
                    fill: "none",
                    stroke: "#666",
                    "stroke-width": 8,
                    d: pathString(radius, startAngle, startAngle)
                });

                var blob1AngleRight = getAngle(100, 300 - Math.abs(startAngle - endAngle));
                /** @type {number} */
                var flag = blob1AngleRight <= 180 ? 0 : 1;
                var gaugeElement = svg("svg", {
                    "viewBox": viewBox || "0 0 100 100",
                    "class": lastGlobalUpdate
                }, [svg("path", {
                    "class": simplifyClassNode,
                    fill: "none",
                    stroke: "#808080",
                    "stroke-width": 8,
                    d: pathString(radius, startAngle, endAngle, flag)
                }), gaugeTextTitle, gaugeTextElem, gaugeTextElem1, gaugeTextElem2, gaugeHSeparator, gaugeHSeparator1, gaugeVSeparator, gaugeValuePath]);
                elem.appendChild(gaugeElement);
            }

            function updateGauge(name, item, value) {
                if (item == 0) {
                    var value = f(name, min, max);
                    //console.log(" I:" + i);
                    var angle = getAngle(value, 360 - Math.abs(startAngle - endAngle));
                    /** @type {number} */
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

            function fn(value, total) {
                var green = color(value);
                /** @type {number} */
                var random = total * 1000;
                /** @type {string} */
                var pathTransition = "stroke " + random + "ms ease";
                /** @type {string} */
                gaugeValuePath.style = ["stroke: " + green, "-webkit-transition: " + pathTransition, "-moz-transition: " + pathTransition, "transition: " + pathTransition].join(";");
            }
            opts = defaults({}, obj, opts);
            var title = opts.title;
            var elem = elem;
            var max = opts.max;
            var min = opts.min;
            var min1 = opts.min1;
            var min2 = opts.min2;
            var value = normalize(opts.value, min, max);
            var value1 = normalize(opts.value1, min1, max);
            var value2 = normalize(opts.value2, min2, max);
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
            var gaugeValuePath;
            var config = opts.label;
            var config1 = opts.label1;
            var config2 = opts.label2;
            var viewBox = opts.viewBox;
            var instance;
            if (startAngle < endAngle) {
                console.log("WARN! startAngle < endAngle, Swapping");
                var temp = startAngle;
                startAngle = endAngle;
                endAngle = temp;
            }

            instance = {

                /*
        setMaxValue : function(dt) {
          max = dt;
        },


          setValue : function(params) {
              value = normalize(params, y, max);
              if (color) {
                  fn(value, 0);
              }
              updateGauge(value, 0);
          },

          */

                setValueAnimated: function(val, duration) {

                    var oldVal = value;

                    value = normalize(val, min, max);
                    if (oldVal === value) {
                        return;
                    }
                    if (color) {
                        fn(value, duration);
                    }

                    //console.log(value);
                    Animation({
                        start: oldVal || 0,
                        end: value,
                        duration: duration || 1,
                        step: function(value, delta) {
                            updateGauge(value, 0, delta);
                        }
                    });
                },

                setValueAnimated1: function(val, duration) {

                    var oldVal1 = value1;
                    value1 = normalize(val, min1, max);

                    if (oldVal1 === value1) {
                        return;
                    }

                    Animation({
                        start: oldVal1 || 0,
                        end: value1,
                        duration: duration || 1,
                        step: function(value1, delta) {
                            updateGauge(value1, 1, delta);
                        }
                    });
                },

                setValueAnimated2: function(val, duration) {

                    var oldVal2 = value2;
                    value2 = normalize(val, min2, max);

                    if (oldVal2 === value2) {
                        return;
                    }

                    Animation({
                        start: oldVal2 || 0,
                        end: value2,
                        duration: duration || 1,
                        step: function(value2, delta) {
                            updateGauge(value2, 2, delta);
                        }
                    });
                },

                //getValue : function() {
                //   return value;
                // }
            };
            //console.log(text);
            render(elem);
            //instance.setValue(value);
            return instance;
        };
    }();
    return Gauge;
});
