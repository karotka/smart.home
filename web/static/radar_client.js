// Radar page: OSM basemap + toggleable ČHMÚ precipitation overlay +
// live adsb.fi aircraft markers. Backend proxies all upstream calls
// (see server_fastapi.py) so this file only talks to same-origin JSON.

(function () {
    'use strict';

    // Leaflet's default marker icons are baked with paths like
    // "images/marker-icon.png". We host the sprite under /static/images/,
    // so pointing imagePath there keeps the popup pins usable if we ever
    // add L.marker() calls without custom icons.
    if (window.L && L.Icon && L.Icon.Default) {
        L.Icon.Default.imagePath = '/static/images/';
    }

    var CHMI_REFRESH_MS   = 60 * 1000;    // frame list re-fetch
    var CHMI_FRAME_MS     = 500;          // per-frame during loop
    var CHMI_HOLD_LAST_MS = 1500;         // linger on newest frame
    var CHMI_OPACITY      = 0.55;
    var ADSB_REFRESH_MS   = 8 * 1000;
    var ADSB_DIST_MAX_NM  = 250;          // adsb.fi hard ceiling
    var ADSB_DIST_MIN_NM  = 30;
    var ADSB_MOVE_DEBOUNCE_MS = 700;
    var DEFAULT_ZOOM      = 9;
    var LABEL_MIN_ZOOM    = 10;
    // RainViewer past-frame animation. Each frame = ~10 min interval.
    var RV_REFRESH_MS     = 60 * 1000;
    var RV_FRAME_MS       = 500;
    var RV_HOLD_LAST_MS   = 1500;
    var RV_PAST_FRAMES    = 8;            // ~80 min back
    var RV_OPACITY        = 0.75;
    var RV_COLOR          = 2;            // 2 = Universal Blue (default)
    // Rough Europe bounds for the auto-fit when the user turns on the
    // Europe-wide RainViewer overlay. Not the raw MSG footprint — just
    // "what looks like Europe" on a Web Mercator map.
    var EU_BOUNDS         = [[35, -12], [65, 42]];
    var ALERTS_REFRESH_MS = 5 * 60 * 1000;

    function fmtLocalTime(iso) {
        try {
            var d = new Date(iso);
            return d.toLocaleTimeString(undefined,
                { hour: '2-digit', minute: '2-digit' });
        } catch (e) { return '—'; }
    }

    function setText(sel, txt) {
        var el = document.querySelector(sel);
        if (el) el.textContent = txt;
    }

    // ---- Aircraft layer -------------------------------------------------

    function AircraftLayer(map) {
        this.map    = map;
        this.layer  = L.layerGroup().addTo(map);
        this.byHex  = {};        // hex -> {marker, lastSeen}
        this.lastTs = 0;
        this._timer = null;
        this._moveTimer = null;
    }

    // Kept only for compatibility with callers that used to hardcode home.
    // The real query center is now derived from map.getCenter() on every
    // refresh, so wherever the user pans, planes follow.
    AircraftLayer.prototype.setCenter = function () {};

    AircraftLayer.prototype.start = function () {
        if (this._timer) return;
        var self = this;
        this.refresh();
        this._timer = setInterval(this.refresh.bind(this), ADSB_REFRESH_MS);
        // Refresh on pan/zoom too, debounced so a drag doesn't spam
        // adsb.fi. moveend fires once at the end of a pan or a zoom.
        this.map.on('moveend', function () {
            clearTimeout(self._moveTimer);
            self._moveTimer = setTimeout(function () { self.refresh(); },
                                         ADSB_MOVE_DEBOUNCE_MS);
        });
    };

    // Half-diagonal of the map viewport in nautical miles. That's the
    // smallest circular radius around the center that fully covers what
    // the user actually sees. adsb.fi caps at 250 NM, so beyond a
    // continent-wide zoom the corners of the map just aren't populated.
    AircraftLayer.prototype._radiusNM = function () {
        var b = this.map.getBounds();
        var meters = b.getNorthEast().distanceTo(b.getSouthWest()) / 2.0;
        var nm = meters / 1852.0;
        // Add a small margin so planes right at the edge stay on screen
        // between refreshes even if they fly outward at 500 kt.
        return Math.max(ADSB_DIST_MIN_NM,
                        Math.min(ADSB_DIST_MAX_NM, Math.ceil(nm * 1.15)));
    };

    AircraftLayer.prototype.refresh = function () {
        var self  = this;
        var c     = this.map.getCenter();
        var dist  = this._radiusNM();
        var url   = '/api/radar/aircraft?lat=' + c.lat.toFixed(3)
                  + '&lon=' + c.lng.toFixed(3)
                  + '&dist_nm=' + dist;
        fetch(url).then(function (r) { return r.json(); }).then(function (j) {
            if (j.error) return;
            self.apply(j);
        }).catch(function (e) { console.warn('adsb fetch failed', e); });
    };

    AircraftLayer.prototype.apply = function (j) {
        var now  = Date.now();
        var seen = {};
        for (var i = 0; i < j.aircraft.length; i++) {
            var a = j.aircraft[i];
            if (!a.hex) continue;
            seen[a.hex] = true;
            var rec = this.byHex[a.hex];
            var latLng = [a.lat, a.lon];
            if (rec) {
                rec.marker.setLatLng(latLng);
                rec.marker.setIcon(this._icon(a));
                rec.marker.setPopupContent(this._popup(a));
                rec.lastSeen = now;
            } else {
                var m = L.marker(latLng, { icon: this._icon(a) })
                    .bindPopup(this._popup(a))
                    .addTo(this.layer);
                this.byHex[a.hex] = { marker: m, lastSeen: now };
            }
        }
        // Purge everything absent from this response — adsb.fi always
        // returns every plane in-range, so anything missing landed or
        // flew out of the polling radius.
        for (var hex in this.byHex) {
            if (!seen[hex]) {
                this.layer.removeLayer(this.byHex[hex].marker);
                delete this.byHex[hex];
            }
        }
        this.lastTs = now;
        setText('[data-adsb-count]', String(j.aircraft.length));
        setText('[data-adsb-age]', fmtLocalTime(j.ts));
    };

    AircraftLayer.prototype._icon = function (a) {
        // Top-down black silhouette with prominent wings. Nose at y=-10,
        // main wings from x=±11, tail wings from x=±3.5. White stroke so
        // dark planes stay readable over dark map tiles too.
        var rot = (a.track == null ? 0 : a.track);
        var cls = 'planeIcon' + (a.alt_ft && a.alt_ft < 500 ? ' on-ground' : '');
        var svg =
            '<svg viewBox="-12 -12 24 24" width="26" height="26" ' +
                'style="transform:rotate(' + rot + 'deg)">' +
              '<path fill="#0a0a0a" stroke="#ffffff" stroke-width="0.7" ' +
                'stroke-linejoin="round" d="' +
                'M 0 -10 L 1.5 -3 L 11 0 L 11 2 L 1.5 0.5 ' +
                'L 1.5 5 L 3.5 7 L 3.5 8 L 0 6.5 L -3.5 8 ' +
                'L -3.5 7 L -1.5 5 L -1.5 0.5 L -11 2 L -11 0 ' +
                'L -1.5 -3 Z" />' +
            '</svg>';
        var label = a.flight || a.reg;
        var labelHtml = label
            ? '<span class="cs">' + label + '</span>'
            : '';
        return L.divIcon({
            html: '<div class="' + cls + '">' + svg + labelHtml + '</div>',
            className: '',
            iconSize:   [26, 26],
            iconAnchor: [13, 13],
        });
    };

    AircraftLayer.prototype._popup = function (a) {
        var lines = [];
        lines.push('<b>' + (a.flight || a.reg || a.hex) + '</b>');
        if (a.type) lines.push(a.type);
        if (a.alt_ft != null) lines.push(a.alt_ft + ' ft');
        if (a.spd_kt != null) lines.push(Math.round(a.spd_kt) + ' kt');
        if (a.sqk) lines.push('sq ' + a.sqk);
        return lines.join(' · ');
    };

    // ---- Radar (precipitation) layer -----------------------------------

    function RadarLayer(map) {
        this.map = map;
        this.overlays = [];    // L.imageOverlay[] in chronological order
        this.frameIx = 0;
        this._tick = null;
        this._reload = null;
        this._active = true;   // hide overlays entirely when layer off
    }

    RadarLayer.prototype.setActive = function (on) {
        this._active = on;
        if (!on) {
            for (var i = 0; i < this.overlays.length; i++) {
                this.overlays[i].setOpacity(0);
            }
        }
    };

    RadarLayer.prototype.start = function () {
        var self = this;
        this.reload();
        this._reload = setInterval(this.reload.bind(this), CHMI_REFRESH_MS);
        this._scheduleNext();
    };

    RadarLayer.prototype._scheduleNext = function () {
        var self = this;
        var wait = (this.frameIx === this.overlays.length - 1)
                 ? CHMI_HOLD_LAST_MS : CHMI_FRAME_MS;
        this._tick = setTimeout(function () {
            if (self.overlays.length === 0) {
                self._scheduleNext();
                return;
            }
            self.frameIx = (self.frameIx + 1) % self.overlays.length;
            self._render();
            self._scheduleNext();
        }, wait);
    };

    RadarLayer.prototype._render = function () {
        if (!this._active) return;
        for (var i = 0; i < this.overlays.length; i++) {
            this.overlays[i].setOpacity(i === this.frameIx ? CHMI_OPACITY : 0);
        }
        var meta = this.overlays[this.frameIx]._radarMeta;
        setText('[data-radar-ts]', fmtLocalTime(meta.ts));
    };

    RadarLayer.prototype.reload = function () {
        var self = this;
        fetch('/api/radar/chmi/frames?count=6').then(function (r) {
            return r.json();
        }).then(function (j) {
            if (j.error) return;
            self._install(j);
        }).catch(function (e) { console.warn('CHMI fetch failed', e); });
    };

    RadarLayer.prototype._install = function (j) {
        // Only rebuild when the newest frame timestamp actually changed.
        var newestUrl = j.frames.length ? j.frames[j.frames.length - 1].url : null;
        var currentNewest = this.overlays.length
            ? this.overlays[this.overlays.length - 1]._radarMeta.url
            : null;
        if (newestUrl === currentNewest) return;

        for (var i = 0; i < this.overlays.length; i++) {
            this.map.removeLayer(this.overlays[i]);
        }
        this.overlays = [];
        var bounds = [
            [j.bbox.south, j.bbox.west],
            [j.bbox.north, j.bbox.east],
        ];
        for (var k = 0; k < j.frames.length; k++) {
            var f = j.frames[k];
            var ov = L.imageOverlay(f.url, bounds, {
                opacity: 0, interactive: false,
            }).addTo(this.map);
            ov._radarMeta = f;
            this.overlays.push(ov);
        }
        // Jump straight to the newest so the first visible frame is "now",
        // rather than 30 min ago while we wait for the loop to catch up.
        this.frameIx = Math.max(0, this.overlays.length - 1);
        this._render();
    };

    // ---- RainViewer layer (Europe-wide precipitation) ------------------
    //
    // One TileLayer whose URL is repointed each animation tick via
    // setUrl(). Cheaper than keeping N stacked TileLayers alive with
    // opacity swapping — and Leaflet's tile cache means switching back
    // to a recent frame is instant.

    function RainViewerLayer(map) {
        this.map    = map;
        this.tile   = null;
        this.frames = [];         // [{time, path}]
        this.frameIx = 0;
        this._tick    = null;
        this._reload  = null;
        this._active  = false;
    }

    RainViewerLayer.prototype.attach = function () {
        if (this.tile) return;
        // Blank template — reload() fills it in on the first fetch.
        this.tile = L.tileLayer('', {
            opacity: RV_OPACITY, tileSize: 256, minZoom: 3, maxZoom: 12,
            attribution: '© RainViewer', crossOrigin: true,
        }).addTo(this.map);
    };

    RainViewerLayer.prototype.detach = function () {
        if (this.tile) {
            this.map.removeLayer(this.tile);
            this.tile = null;
        }
    };

    RainViewerLayer.prototype.setActive = function (on) {
        this._active = on;
        if (on) {
            this.attach();
            if (!this._reload) {
                this.reload();
                this._reload = setInterval(this.reload.bind(this),
                                           RV_REFRESH_MS);
                this._scheduleNext();
            }
        } else {
            this.detach();
        }
    };

    RainViewerLayer.prototype._scheduleNext = function () {
        var self = this;
        var wait = (this.frameIx === this.frames.length - 1)
                 ? RV_HOLD_LAST_MS : RV_FRAME_MS;
        this._tick = setTimeout(function () {
            if (!self._active) { self._tick = null; return; }
            if (self.frames.length) {
                self.frameIx = (self.frameIx + 1) % self.frames.length;
                self._render();
            }
            self._scheduleNext();
        }, wait);
    };

    RainViewerLayer.prototype._render = function () {
        if (!this.tile || !this.frames.length) return;
        var host = this._host;
        var path = this.frames[this.frameIx].path;
        this.tile.setUrl(host + path + '/256/{z}/{x}/{y}/'
                                     + RV_COLOR + '/1_1.png');
    };

    RainViewerLayer.prototype.reload = function () {
        var self = this;
        fetch('/api/radar/rainviewer').then(function (r) { return r.json(); })
            .then(function (j) {
                if (j.error || !j.radar) return;
                self._host   = j.host;
                var past     = j.radar.past || [];
                self.frames  = past.slice(-RV_PAST_FRAMES);
                // Newest first-render so the user immediately sees "now".
                self.frameIx = Math.max(0, self.frames.length - 1);
                self._render();
            })
            .catch(function (e) { console.warn('RainViewer fetch failed', e); });
    };

    // ---- CHMU CAP alerts banner ----------------------------------------

    function AlertsBanner(map) {
        this.map = map;
        this.el  = document.getElementById('radarAlerts');
        if (!this.el) return;
        this.summary = this.el.querySelector('.alHead');
        this.details = this.el.querySelector('.alDetails');
        this.expanded = false;
        var self = this;
        this.summary.addEventListener('click', function () {
            self.expanded = !self.expanded;
            self.el.classList.toggle('open', self.expanded);
        });
    }

    AlertsBanner.prototype.start = function () {
        if (!this.el) return;
        this.refresh();
        setInterval(this.refresh.bind(this), ALERTS_REFRESH_MS);
    };

    AlertsBanner.prototype.refresh = function () {
        if (!this.el) return;
        var self = this;
        fetch('/api/radar/alerts').then(function (r) { return r.json(); })
            .then(function (j) {
                if (j.error) return;
                self._render(j.alerts || []);
            })
            .catch(function () {});
    };

    AlertsBanner.prototype._render = function (alerts) {
        if (!alerts.length) {
            this.el.classList.remove('show', 'open', 'sev-Extreme',
                                     'sev-Severe', 'sev-Moderate', 'sev-Minor');
            this.expanded = false;
            return;
        }
        var top = alerts[0].severity || 'Minor';
        this.el.classList.remove('sev-Extreme', 'sev-Severe',
                                 'sev-Moderate', 'sev-Minor');
        this.el.classList.add('show', 'sev-' + top);

        var count = alerts.length;
        var lead  = alerts[0].event || 'Výstraha';
        var suffix = count > 1 ? ' (+ ' + (count - 1) + ' další)' : '';
        this.summary.textContent = '⚠️ ' + lead + suffix + ' — klikni pro detail';

        var html = '';
        for (var i = 0; i < alerts.length; i++) {
            var a = alerts[i];
            html += '<div class="al sev-' + (a.severity || 'Minor') + '">';
            html +=   '<div class="alTitle">' + (a.event || '') +
                      ' <span class="alSev">' + (a.severity || '') + '</span></div>';
            if (a.expires) {
                var d = new Date(a.expires);
                html += '<div class="alWhen">do ' +
                        d.toLocaleString(undefined, {
                          day: '2-digit', month: '2-digit',
                          hour: '2-digit', minute: '2-digit',
                        }) + '</div>';
            }
            if (a.description) {
                html += '<div class="alDesc">' + a.description + '</div>';
            }
            if (a.areas && a.areas.length) {
                html += '<div class="alAreas">' + a.areas.slice(0, 6).join(', ');
                if (a.areas.length > 6) html += '…';
                html += '</div>';
            }
            html += '</div>';
        }
        this.details.innerHTML = html;
    };

    // ---- Boot -----------------------------------------------------------

    function boot() {
        var mapEl = document.getElementById('radarMap');
        if (!mapEl || !window.L) return;

        var map = L.map(mapEl, {
            zoomControl: true,
            attributionControl: false,
            worldCopyJump: true,
        }).setView([49.8, 15.5], DEFAULT_ZOOM);

        var osm = L.tileLayer(
            'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            { maxZoom: 18, attribution: '© OSM' }
        ).addTo(map);

        var radar      = new RadarLayer(map);
        var aircraft   = new AircraftLayer(map);
        var rainviewer = new RainViewerLayer(map);
        var alerts     = new AlertsBanner(map);

        // Layer control exposes overlay layers so the user can turn each
        // off independently. RadarLayer / RainViewerLayer keep their own
        // "active" flag because we manage tiles/imagery manually rather
        // than through Leaflet's add/remove path (would drop timing).
        var radarProxy = L.layerGroup().addTo(map);
        var rvProxy    = L.layerGroup();
        var overlays = {
            'Radar CZ (ČHMÚ)':   radarProxy,
            'Srážky Evropa (RainViewer)': rvProxy,
            'Letadla':           aircraft.layer,
        };
        L.control.layers({ 'OpenStreetMap': osm }, overlays,
            { position: 'topright', collapsed: false }).addTo(map);

        // Remember the "home" view so we can restore it when the user
        // turns off the wide Europe layer.
        var homeView = { center: map.getCenter(), zoom: map.getZoom() };

        map.on('overlayadd', function (e) {
            if (e.name === 'Radar CZ (ČHMÚ)') radar.setActive(true);
            if (e.name.indexOf('RainViewer') !== -1) {
                rainviewer.setActive(true);
                map.fitBounds(EU_BOUNDS, { animate: true });
            }
        });
        map.on('overlayremove', function (e) {
            if (e.name === 'Radar CZ (ČHMÚ)') radar.setActive(false);
            if (e.name.indexOf('RainViewer') !== -1) {
                rainviewer.setActive(false);
                map.setView(homeView.center, homeView.zoom, { animate: true });
            }
        });

        // Show plane callsign labels only when zoomed in enough — CSS
        // in radar.html hides .planeIcon .cs unless the map container
        // carries .showLabels.
        function syncLabels() {
            mapEl.classList.toggle('showLabels',
                map.getZoom() >= LABEL_MIN_ZOOM);
        }
        map.on('zoomend', syncLabels);
        syncLabels();

        fetch('/api/radar/location').then(function (r) { return r.json(); })
            .then(function (loc) {
                map.setView([loc.lat, loc.lon], DEFAULT_ZOOM);
                homeView = { center: map.getCenter(), zoom: map.getZoom() };
                L.circleMarker([loc.lat, loc.lon], {
                    radius: 10, color: '#ffffff', weight: 3,
                    fillColor: '#8b0000', fillOpacity: 1,
                }).bindPopup('Domů' + (loc.city ? ' (' + loc.city + ')' : ''))
                  .addTo(map);
                aircraft.setCenter(loc.lat, loc.lon);
                aircraft.start();
            })
            .catch(function () {
                aircraft.setCenter(49.8, 15.5);
                aircraft.start();
            });

        radar.start();
        alerts.start();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
