"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function extend(Base, prototype) {
    function Extended() {
        this._super = function () {};
        if (prototype.init) prototype.init.apply(this, arguments);
    }
    Extended.prototype = Object.assign(Object.create(Base.prototype), prototype);
    Extended.prototype.constructor = Extended;
    return Extended;
}

function Controller() {
    this.model = {};
    this.handle = "record-1";
    this.renderer = {trigger_up() {}};
}
Controller.include = function (prototype) {
    Object.assign(Controller.prototype, prototype);
};

async function main() {
    const source = fs.readFileSync(
        path.join(__dirname, "../static/src/js/agui_host_service.js"), "utf8"
    );
    let Service;
    const bus = {on() {}, off() {}, trigger() {}};
    const AbstractService = function () {};
    AbstractService.extend = function (prototype) {
        return extend(AbstractService, prototype);
    };
    const WebClient = function () {};
    WebClient.include = function () {};
    const FormViewDialog = function () {};
    FormViewDialog.include = function (prototype) {
        Object.assign(FormViewDialog.prototype, prototype);
    };
    const Adapter = {
        clone(value) {
            return JSON.parse(JSON.stringify(value));
        },
        buildSnapshot(options) {
            return {
                protocol: "agui.odoo.v2",
                snapshotId: options.snapshotId,
                hostRevision: options.hostRevision,
                interactive: true,
                surface: options.surface,
                controller: {
                    controllerId: options.controllerId,
                    dataPointId: options.controller.handle,
                    viewType: options.viewType,
                },
                record: {model: "res.partner", resId: 1},
            };
        },
    };
    function jquery(value) { return value; }
    jquery.when = function (value) { return Promise.resolve(value); };
    jquery.Deferred = function () {
        let resolve;
        const promise = new Promise(function (done) { resolve = done; });
        return {
            resolve,
            promise() { return promise; },
        };
    };
    const sandbox = {
        console,
        Date,
        Math,
        setTimeout,
        clearTimeout,
        odoo: {
            define(_name, factory) {
                factory(function (name) {
                    if (name === "web.AbstractService") return AbstractService;
                    if (name === "web.core") {
                        return {
                            bus,
                            serviceRegistry: {add(_serviceName, Constructor) { Service = Constructor; }},
                        };
                    }
                    if (name === "web.FormController" || name === "web.ListController" ||
                            name === "web.KanbanController") return Controller;
                    if (name === "web.WebClient") return WebClient;
                    if (name === "web.view_dialogs") return {FormViewDialog};
                    if (name === "agui_chat.model_adapter") return Adapter;
                    if (name === "agui_chat.command_registry") return {getCatalog() { return []; }};
                    throw new Error("Unexpected module: " + name);
                });
            },
        },
        _: {
            each(values, callback, owner) {
                (values || []).forEach(function (value) { callback.call(owner, value); });
            },
            map(values, callback) { return (values || []).map(callback); },
            isFunction(value) { return typeof value === "function"; },
            filter(values, callback) { return values.filter(callback); },
            without(values, removed) { return values.filter((value) => value !== removed); },
        },
        $: jquery,
    };
    vm.runInNewContext(source, sandbox, {filename: "agui_host_service.js"});

    const first = new Controller();
    let current = {widget: first};
    const service = new Service();
    service._enabled = true;
    service._actionManager = {getCurrentController() { return current; }};
    service._activateCurrentController();
    const firstId = service.getSnapshot().controller.controllerId;

    const second = new Controller();
    second.handle = "record-2";
    second.actionViews = [{type: "list", multiRecord: true}, {type: "form", multiRecord: false}];
    current = {widget: second};
    const recovered = service.getSnapshot();

    assert.strictEqual(recovered.interactive, true);
    assert.strictEqual(recovered.controller.dataPointId, "record-2");
    assert.notStrictEqual(recovered.controller.controllerId, firstId);
    assert.strictEqual(service._controller, second);

    const navigationSnapshotId = service._snapshot.snapshotId;
    const navigationReady = service._waitForInteractiveSnapshotChange(navigationSnapshotId);
    service._snapshot = Object.assign({}, service._snapshot, {
        snapshotId: "navigation-transition",
        interactive: false,
    });
    service._publish();
    let navigationResolved = false;
    navigationReady.then(function () { navigationResolved = true; });
    await Promise.resolve();
    assert.strictEqual(navigationResolved, false);
    service._snapshot = Object.assign({}, service._snapshot, {
        snapshotId: "navigation-ready",
        interactive: true,
    });
    service._publish();
    const navigationSnapshot = await navigationReady;
    assert.strictEqual(navigationSnapshot.snapshotId, "navigation-ready");
    assert.strictEqual(navigationSnapshot.interactive, true);

    let listEvent;
    second.trigger_up = function (name, data) { listEvent = {name, data}; };
    service._openRecord({localId: "list-record-7", resId: 7}, "readonly");
    assert.strictEqual(listEvent.name, "switch_view");
    assert.strictEqual(listEvent.data.view_type, "form");
    assert.strictEqual(listEvent.data.res_id, 7);
    assert.strictEqual(listEvent.data.mode, "readonly");

    let clicked = false;
    const row = {
        length: 1,
        data(name) { return name === "id" ? "list-record-8" : undefined; },
        trigger(name) { clicked = name === "click"; },
    };
    second.actionViews = [{type: "list", multiRecord: true}];
    second.renderer.$ = function (selector) {
        assert.strictEqual(selector, ".o_data_row");
        return {
            filter(callback) {
                return {first() { return callback.call(row) ? row : {length: 0}; }};
            },
        };
    };
    listEvent = undefined;
    service._openRecord({localId: "list-record-8", resId: 8}, "readonly");
    assert.strictEqual(clicked, true);
    assert.strictEqual(listEvent, undefined);

    clicked = false;
    service._openRecord({localId: "list-record-9", resId: 9}, "readonly");
    assert.strictEqual(clicked, false);
    assert.strictEqual(listEvent.name, "switch_view");
    assert.strictEqual(listEvent.data.res_id, 9);

    let kanbanEvent;
    const widget = {
        trigger_up(name, data) { kanbanEvent = {name, data}; },
    };
    service._openRecord({widget, localId: "kanban-record-8", resId: 8}, "edit");
    assert.strictEqual(kanbanEvent.name, "open_record");
    assert.strictEqual(kanbanEvent.data.id, "kanban-record-8");
    assert.strictEqual(kanbanEvent.data.mode, "edit");
    console.log("host_service_test: ok");
}

main().catch(function (error) {
    console.error(error);
    process.exitCode = 1;
});
