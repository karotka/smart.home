/* global WebSocket, document, window */
"use strict";

/**
 * Settings UI for the heat pump. Reads parameter_group_1..7 once on load
 * via heatpump_settingsLoad, then drives every control through the
 * matching backend setter. Each click is auto-saved — the backend does
 * read-modify-write, so there's no separate "save" step.
 *
 * Layout is tab-based: each tab corresponds to a logical group of
 * settings. Within a tab, every config row renders as either:
 *   - a "step" row with [↓] [value] [↑] buttons for ranged numbers
 *   - an "enum" row with one button per discrete value
 *
 * Adding a new parameter = appending one entry to TABS[*].rows. No
 * HTML or CSS edits required.
 */

// ---- Configuration: the entire UI is generated from this. ------------

const TABS = [
    {
        id: "setpoints",
        label: "Setpoints",
        rows: [
            { kind: "step", method: "heatpump_setTemp",
              source: ["parameter_group_1", 4],
              label: "Heating target temp", unit: "°C" },
            { kind: "step", method: "heatpump_setCoolingTemp",
              source: ["parameter_group_1", 3],
              label: "Cooling target temp", unit: "°C" },
            { kind: "step", method: "heatpump_setDHWTemp",
              source: ["parameter_group_1", 2],
              label: "DHW (hot water) target temp", unit: "°C" },
            { kind: "step", method: "heatpump_setCoolingReturnDifference",
              source: ["parameter_group_1", 0],
              label: "Heating & Cooling return diff", unit: "°C" },
            { kind: "step", method: "heatpump_setDHWReturnDifference",
              source: ["parameter_group_1", 1],
              label: "DHW return diff", unit: "°C" },
            { kind: "step", method: "heatpump_setWaterTempComp",
              source: ["parameter_group_1", 5],
              label: "Water temp compensation", unit: "°C" },
        ],
    },
    {
        id: "compensation",
        label: "Compensation",
        rows: [
            { kind: "enum", method: "heatpump_setHeatingAutoAdjust",
              source: ["parameter_group_1", 11],
              label: "Heating target auto adjust",
              options: [{ v: 0, l: "Disabled" }, { v: 1, l: "Enabled" }] },
            { kind: "step", method: "heatpump_setHeatingCompAmbTemp",
              source: ["parameter_group_1", 12],
              label: "Heating comp ambient point", unit: "°C" },
            { kind: "step", method: "heatpump_setTargetTempCompCoef",
              source: ["parameter_group_1", 13],
              label: "Target temp comp coefficient", unit: "×0.1" },
            { kind: "enum", method: "heatpump_setFreqAfterConstTemp",
              source: ["parameter_group_1", 14],
              label: "Compressor freq after const temp",
              options: [{ v: 0, l: "Decrease" }, { v: 1, l: "Non-decrease" }] },
        ],
    },
    {
        id: "disinfect",
        label: "Disinfect",
        rows: [
            { kind: "step", method: "heatpump_setDisinfectCycleDays",
              source: ["parameter_group_1", 6],
              label: "Cycle (0 = disabled)", unit: "days" },
            { kind: "step", method: "heatpump_setDisinfectStartHour",
              source: ["parameter_group_1", 7],
              label: "Start hour", unit: "h" },
            { kind: "step", method: "heatpump_setDisinfectSustainMin",
              source: ["parameter_group_1", 8],
              label: "Sustain time", unit: "min" },
            { kind: "step", method: "heatpump_setDisinfectTargetTemp",
              source: ["parameter_group_1", 9],
              label: "Target temp", unit: "°C" },
            { kind: "step", method: "heatpump_setDisinfectHpTemp",
              source: ["parameter_group_1", 10],
              label: "Heat pump temp during disinfect", unit: "°C" },
        ],
    },
    {
        id: "defrost",
        label: "Defrost",
        rows: [
            { kind: "step", method: "heatpump_setDefrostFreq",
              source: ["parameter_group_2", 2],
              label: "Compressor frequency", unit: "Hz" },
            { kind: "step", method: "heatpump_setDefrostPeriod",
              source: ["parameter_group_2", 3],
              label: "Period", unit: "min" },
            { kind: "step", method: "heatpump_setDefrostEnterTemp",
              source: ["parameter_group_2", 4],
              label: "Enter temp", unit: "°C" },
            { kind: "step", method: "heatpump_setDefrostTime",
              source: ["parameter_group_2", 5],
              label: "Max duration", unit: "min" },
            { kind: "step", method: "heatpump_setDefrostExitTemp",
              source: ["parameter_group_2", 6],
              label: "Exit temp", unit: "°C" },
            { kind: "step", method: "heatpump_setDefrostEvapDiff1",
              source: ["parameter_group_2", 7],
              label: "Env vs evap diff 1", unit: "°C" },
            { kind: "step", method: "heatpump_setDefrostEvapDiff2",
              source: ["parameter_group_2", 8],
              label: "Env vs evap diff 2", unit: "°C" },
            { kind: "step", method: "heatpump_setDefrostAmbTemp",
              source: ["parameter_group_2", 9],
              label: "Ambient temp threshold", unit: "°C" },
        ],
    },
    {
        id: "pump",
        label: "Pump",
        rows: [
            { kind: "enum", method: "heatpump_setDcPumpMode",
              source: ["parameter_group_2", 0],
              label: "DC pump mode",
              options: [
                  { v: 0, l: "No start" },
                  { v: 1, l: "Auto" },
                  { v: 2, l: "Manual" },
              ] },
            { kind: "step", method: "heatpump_setDcPumpManualSpeed",
              source: ["parameter_group_2", 1],
              label: "DC pump manual speed", unit: "%" },
            { kind: "enum", method: "heatpump_setPumpAfterTarget",
              source: ["parameter_group_1", 18],
              label: "Pump after target reached",
              options: [
                  { v: 0, l: "Intermittent" },
                  { v: 1, l: "All time" },
                  { v: 2, l: "Stop at const" },
              ] },
            { kind: "step", method: "heatpump_setPumpCycleMin",
              source: ["parameter_group_1", 19],
              label: "Pump on/off cycle", unit: "min" },
        ],
    },
    {
        id: "heater",
        label: "Heater",
        rows: [
            { kind: "step", method: "heatpump_setPipeHeaterAmbTemp",
              source: ["parameter_group_1", 15],
              label: "Pipe heater enable amb temp", unit: "°C" },
            { kind: "step", method: "heatpump_setDhwHeaterStartTime",
              source: ["parameter_group_1", 16],
              label: "DHW backup heater entry time", unit: "min" },
            { kind: "enum", method: "heatpump_setEHeaterMode",
              source: ["parameter_group_7", 14],
              label: "E-heater mode",
              options: [
                  { v: 0, l: "Off" },
                  { v: 1, l: "Heating only" },
                  { v: 2, l: "DHW only" },
                  { v: 3, l: "Both" },
              ] },
        ],
    },
    {
        id: "function",
        label: "Function",
        rows: [
            { kind: "enum", method: "heatpump_setFunction",
              source: ["parameter_group_1", 17],
              label: "Heat pump function",
              options: [
                  { v: 1, l: "Heating only" },
                  { v: 2, l: "Heating + Cooling" },
                  { v: 3, l: "Heating + DHW" },
                  { v: 4, l: "Heating + Cooling + DHW" },
              ] },
            { kind: "enum", method: "heatpump_setSmartGrid",
              source: ["parameter_group_7", 12],
              label: "Smart Grid",
              options: [
                  { v: 0, l: "Disabled" },
                  { v: 1, l: "Passive" },
                  { v: 2, l: "Active" },
              ] },
            { kind: "step", method: "heatpump_setSmartGridOpTime",
              source: ["parameter_group_7", 13],
              label: "Smart Grid operating time", unit: "min" },
        ],
    },
];


// ---- Runtime state ---------------------------------------------------

const hpSettings = {
    queue: {},
    snapshot: {},        // { parameter_group_1: [...], parameter_group_2: [...], ... }
    activeTab: TABS[0].id,

    connect(port) {
        const url = "wss://" + window.location.hostname + (port ? ":" + port : "") + "/websocket";
        this.socket = new WebSocket(url);
        this.socket.onopen = () => {
            console.log("hp settings: connected");
            this.call("heatpump_settingsLoad", {}, "settings_load");
        };
        this.socket.onmessage = (ev) => this.handleMessage(JSON.parse(ev.data));
        this.socket.onerror = (err) => console.error("hp settings socket error:", err);
        this.socket.onclose = () => {
            console.log("hp settings: socket closed, reconnect in 1 s");
            setTimeout(() => this.connect(port), 1000);
        };
    },

    call(method, params, router) {
        this.socket.send(JSON.stringify({
            method, params, router: router || method, id: "",
        }));
    },

    handleMessage(rpc) {
        if (rpc.error) {
            this.toast("Error: " + rpc.result, true);
            return;
        }
        if (rpc.router === "settings_load") {
            this.snapshot = rpc.result || {};
            this.render();
            return;
        }
        // Setter response — find the matching row and update its display.
        const row = this.findRowByMethod(rpc.router);
        if (!row || !rpc.result) return;
        const newVal = rpc.result.temperature ?? rpc.result.value;
        if (newVal === undefined || newVal === null) return;

        const [groupCode, idx] = row.source;
        if (this.snapshot[groupCode]) this.snapshot[groupCode][idx] = newVal;
        this.updateRow(row);
        if (rpc.result.unchanged) {
            this.toast(row.label + " unchanged", false);
        } else {
            this.toast(row.label + " → " + newVal + (row.unit ? " " + row.unit : ""), false);
        }
    },

    findRowByMethod(method) {
        for (const tab of TABS) {
            for (const row of tab.rows) {
                if (row.method === method) return row;
            }
        }
        return null;
    },

    valueOf(row) {
        const [code, idx] = row.source;
        const arr = this.snapshot[code];
        if (!arr || idx >= arr.length) return null;
        return arr[idx];
    },

    // ---- DOM rendering -----------------------------------------------

    render() {
        this.renderTabs();
        this.renderBody();
    },

    renderTabs() {
        const root = document.getElementById("hpSettingsTabs");
        root.innerHTML = "";
        for (const tab of TABS) {
            const el = document.createElement("div");
            el.className = "hpsTab" + (tab.id === this.activeTab ? " active" : "");
            el.textContent = tab.label;
            el.onclick = () => {
                this.activeTab = tab.id;
                this.render();
            };
            root.appendChild(el);
        }
    },

    renderBody() {
        const root = document.getElementById("hpSettingsBody");
        root.innerHTML = "";
        const tab = TABS.find((t) => t.id === this.activeTab);
        if (!tab) return;
        for (const row of tab.rows) {
            root.appendChild(this.renderRow(row));
        }
    },

    renderRow(row) {
        const wrap = document.createElement("div");
        wrap.className = "hpsRow";
        wrap.dataset.method = row.method;

        const label = document.createElement("div");
        label.className = "hpsLabel";
        label.textContent = row.label;
        wrap.appendChild(label);

        const ctrl = document.createElement("div");
        ctrl.className = "hpsCtrl";
        if (row.kind === "step") {
            this.renderStep(ctrl, row);
        } else if (row.kind === "enum") {
            this.renderEnum(ctrl, row);
        }
        wrap.appendChild(ctrl);

        return wrap;
    },

    renderStep(ctrl, row) {
        const down = document.createElement("button");
        down.className = "hpsBtn step";
        down.textContent = "−";
        down.onclick = () => this.call(row.method, { direction: "down" }, row.method);

        const val = document.createElement("span");
        val.className = "hpsValue";
        val.dataset.bind = row.method;
        const v = this.valueOf(row);
        val.textContent = (v === null ? "—" : v) + (row.unit ? " " + row.unit : "");

        const up = document.createElement("button");
        up.className = "hpsBtn step";
        up.textContent = "+";
        up.onclick = () => this.call(row.method, { direction: "up" }, row.method);

        ctrl.append(down, val, up);
    },

    renderEnum(ctrl, row) {
        const cur = this.valueOf(row);
        for (const opt of row.options) {
            const btn = document.createElement("button");
            btn.className = "hpsBtn enum" + (opt.v === cur ? " active" : "");
            btn.textContent = opt.l;
            btn.dataset.bind = row.method;
            btn.dataset.value = String(opt.v);
            btn.onclick = () => this.call(row.method, { value: opt.v }, row.method);
            ctrl.appendChild(btn);
        }
    },

    updateRow(row) {
        // re-render the active tab so values + active-button states refresh
        if (TABS.find((t) => t.id === this.activeTab).rows.includes(row)) {
            this.renderBody();
        }
    },

    toast(msg, isError) {
        const el = document.getElementById("hpSettingsToast");
        el.textContent = msg;
        el.className = "hpsToast show" + (isError ? " err" : "");
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => { el.className = "hpsToast"; }, 2200);
    },
};

window.hpSettings = hpSettings;
