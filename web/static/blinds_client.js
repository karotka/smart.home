/* global WebSocket, document, window */
"use strict";

/**
 * Client for /windows.html.
 *
 * Loads all blinds + their state via blinds_load, wires up open / stop /
 * close buttons and a position slider on each card. Each click sends a
 * blinds_command and the server's response refreshes the card.
 */

const blindsClient = {
    queue: {},
    snap: {},   // id -> {state, position, online}

    connect(port) {
        const url = "wss://" + window.location.hostname +
            (port ? ":" + port : "") + "/websocket";
        this.socket = new WebSocket(url);

        this.socket.onopen = () => {
            this.bindCards();
            this.call("blinds_load", {}, "blinds_load");
        };

        this.socket.onmessage = (ev) => this.handle(JSON.parse(ev.data));
        this.socket.onerror = (err) => console.error("blinds ws error:", err);
        this.socket.onclose = () => setTimeout(() => this.connect(port), 1000);
    },

    call(method, params, router) {
        this.socket.send(JSON.stringify({
            method, params, router: router || method, id: "",
        }));
    },

    handle(rpc) {
        if (rpc.error) {
            this.toast("Error: " + rpc.result, true);
            return;
        }
        if (rpc.router === "blinds_load") {
            const list = (rpc.result && rpc.result.blinds) || [];
            for (const b of list) {
                this.snap[b.id] = b;
                this.renderCard(b);
            }
            return;
        }
        if (rpc.router === "blinds_command") {
            const r = rpc.result;
            if (!r || !r.ok) {
                this.toast(r && r.msg ? r.msg : "command failed", true);
                return;
            }
            const cur = this.snap[r.id] || {};
            cur.state = r.state;
            cur.position = r.position;
            cur.online = true;
            this.snap[r.id] = cur;
            this.renderCard(cur, r.id);
            this.toast(r.id + " → " + (r.state || (r.position + " %")));
        }
    },

    bindCards() {
        document.querySelectorAll(".blCard").forEach((card) => {
            const id = card.dataset.id;

            card.querySelectorAll(".blBtn").forEach((b) => {
                b.onclick = () => {
                    this.call("blinds_command",
                        { id, direction: b.dataset.act },
                        "blinds_command");
                };
            });

            const slider = card.querySelector(".blSlider");
            slider.addEventListener("change", () => {
                this.call("blinds_command",
                    { id, position: parseInt(slider.value, 10) },
                    "blinds_command");
            });
        });
    },

    renderCard(b, idOverride) {
        const id = idOverride || b.id;
        const card = document.querySelector('.blCard[data-id="' + id + '"]');
        if (!card) return;

        const pos = (typeof b.position === "number") ? b.position : null;
        const txt = card.querySelector(".blPosTxt");
        const fill = card.querySelector(".blPosFill");
        const slider = card.querySelector(".blSlider");

        if (pos !== null) {
            txt.textContent = pos + " %";
            fill.style.width = pos + "%";
            slider.value = pos;
        } else {
            txt.textContent = "—";
            fill.style.width = "0%";
        }

        card.classList.toggle("offline", !b.online);
        // Highlight the active state button
        card.querySelectorAll(".blBtn").forEach((bn) => {
            bn.classList.toggle("active", bn.dataset.act === b.state);
        });
    },

    toast(msg, isError) {
        const el = document.getElementById("blindsToast");
        if (!el) return;
        el.textContent = msg;
        el.className = "hpsToast show" + (isError ? " err" : "");
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => { el.className = "hpsToast"; }, 2200);
    },
};

window.blindsClient = blindsClient;
