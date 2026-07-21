"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function main() {
    const source = fs.readFileSync(
        path.join(__dirname, "../static/src/js/agui_chat_surfaces.js"), "utf8"
    );
    const modules = {};
    const includes = [];
    const mounts = [];
    const updates = [];
    const unmounts = [];
    const slots = {};
    const listeners = {};
    const storage = {};
    let renderedHtml = "";
    const service = {
        surface: "dock",
        snapshot: {
            protocol: "agui.odoo.v2", surface: "dock", interactive: true,
        },
        subscribers: [],
        menuSubscribers: [],
        menuCatalog: {
            catalogId: "catalog", catalogRevision: 1, capturedAt: "now",
            ready: true, totalCount: 0, entries: [],
        },
    };

    function jqueryNode(name) {
        const classes = new Set();
        const styles = {};
        const node = {
            name,
            classes,
            appendChild(child) {
                child.parentNode = node;
                node.child = child;
            },
            style: {
                values: styles,
                setProperty(key, value) { styles[key] = value; },
                removeProperty(key) { delete styles[key]; },
            },
        };
        const result = {
            0: node,
            length: 1,
            html(value) { renderedHtml = value; return this; },
            toggle() { return this; },
            toggleClass(className, enabled) {
                if (enabled) classes.add(className);
                else classes.delete(className);
                return this;
            },
            show() { return this; },
            text() { return this; },
            attr() { return this; },
            each() { return this; },
        };
        slots[name] = result;
        return result;
    }

    function Base(parent) {
        this.parent = parent;
        this.$el = jqueryNode("root");
    }
    Base.prototype._super = function () { return Promise.resolve(); };
    Base.prototype.$ = function (selector) {
        return slots[selector] || jqueryNode(selector);
    };
    Base.prototype.call = function (_serviceName, method) {
        const args = Array.prototype.slice.call(arguments, 2);
        if (method === "getSnapshot") return service.snapshot;
        if (method === "getToolCatalog") return [];
        if (method === "getMenuCatalog") return service.menuCatalog;
        if (method === "configureNavigation") return service.menuCatalog;
        if (method === "setCurrentController") return service.snapshot;
        if (method === "subscribe") {
            service.subscribers.push({owner: args[0], callback: args[1]});
            return true;
        }
        if (method === "unsubscribe") {
            service.subscribers = service.subscribers.filter((entry) => entry.owner !== args[0]);
            return true;
        }
        if (method === "subscribeMenuCatalog") {
            service.menuSubscribers.push({owner: args[0], callback: args[1]});
            return true;
        }
        if (method === "unsubscribeMenuCatalog") {
            service.menuSubscribers = service.menuSubscribers.filter(
                (entry) => entry.owner !== args[0]
            );
            return true;
        }
        if (method === "setSurface") {
            service.surface = args[0];
            service.snapshot = Object.assign({}, service.snapshot, {surface: args[0]});
            service.subscribers.forEach((entry) => entry.callback.call(entry.owner, service.snapshot));
            return true;
        }
        throw new Error("Unexpected service method: " + method);
    };
    Base.prototype.appendTo = function () { return Promise.resolve(); };
    Base.extend = function (prototype) {
        function Extended(parent) {
            Base.call(this, parent);
            if (prototype.init) prototype.init.call(this, parent);
        }
        Extended.prototype = Object.assign(Object.create(Base.prototype), prototype);
        Extended.prototype.constructor = Extended;
        Extended.extend = Base.extend;
        Extended.include = Base.include;
        return Extended;
    };
    Base.include = function (prototype) {
        includes.push(prototype);
        Object.assign(Base.prototype, prototype);
    };

    function HostBridge(owner) {
        this.owner = owner;
    }
    HostBridge.prototype.loadConfig = function () {
        return Promise.resolve({chat_enabled: true, database: "test_db", user_id: 7});
    };
    HostBridge.prototype.setCatalog = function () { return []; };
    HostBridge.prototype.mountProps = function (hostState, surface) {
        return {hostState, surface};
    };

    function fakeRequire(name) {
        if (name === "web.Widget" || name === "web.WebClient") return Base;
        if (name === "agui_chat.host_bridge") return {HostBridge};
        if (name === "web.core") return {bus: {trigger() {}}};
        throw new Error("Unexpected require: " + name);
    }

    const sandbox = {
        Promise,
        Object,
        Array,
        console,
        document: {
            documentElement: {clientWidth: 1440, clientHeight: 900},
            createElement(tagName) {
                const node = {
                    className: "",
                    href: "",
                    parentNode: null,
                    rel: "",
                    style: {},
                    tagName,
                };
                node.attachShadow = function () {
                    const shadowRoot = {
                        host: node,
                        appendChild(child) {
                            child.parentNode = shadowRoot;
                            if (child.tagName === "link" && child.onload) child.onload();
                        },
                    };
                    return shadowRoot;
                };
                return node;
            },
        },
        window: {
            console,
            innerWidth: 1440,
            innerHeight: 900,
            addEventListener(name, callback) { listeners[name] = callback; },
            removeEventListener(name, callback) {
                if (listeners[name] === callback) delete listeners[name];
            },
            localStorage: {
                getItem(key) { return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null; },
                setItem(key, value) { storage[key] = value; },
            },
            AguiChat: {
                mount(element, props) {
                    mounts.push({element, props});
                    return {
                        update(nextProps) { updates.push(nextProps); },
                        unmount() { unmounts.push(true); },
                    };
                },
            },
        },
        odoo: {
            define(name, factory) {
                modules[name] = factory(fakeRequire);
            },
        },
        _: {
            isFunction(value) { return typeof value === "function"; },
        },
        $: {
            when(value) { return Promise.resolve(value); },
        },
    };
    sandbox.global = sandbox;
    vm.runInNewContext(source, sandbox, {filename: "agui_chat_surfaces.js"});

    const SurfaceManager = modules["agui_chat.surfaces"];
    const fileTypeMixin = includes.find((item) => item._getFileType)._getFileType;
    const fileType = {name: "pdf"};
    assert.strictEqual(fileTypeMixin.call({
        _super() { return fileType; },
    }), fileType);
    const fileTypeFallback = fileTypeMixin.call({
        _super() { throw new Error("third-party file type patch failed"); },
    });
    const manager = new SurfaceManager(new Base());
    return Promise.resolve(fileTypeFallback).then(() => manager.start())
        .then(() => Promise.resolve()).then(() => {
        assert.strictEqual(mounts.length, 1);
        assert.strictEqual((renderedHtml.match(/class='o_agui_chat_action o_agui_chat_direction'/g) || []).length, 4);
        assert(renderedHtml.includes("o_agui_chat_float"));
        assert(renderedHtml.includes("fa-angle-left"));
        assert(renderedHtml.includes("fa-angle-right"));
        assert(renderedHtml.includes("fa-angle-up"));
        assert(renderedHtml.includes("fa-angle-down"));
        assert(renderedHtml.includes("aria-pressed='false'"));
        assert(renderedHtml.includes("title='关闭' aria-label='关闭'"));
        assert(renderedHtml.includes("role='presentation'"));
        assert(renderedHtml.includes("class='o_agui_chat_dock_toggle'"));
        assert(!renderedHtml.includes("btn btn-primary o_agui_chat_dock_toggle"));
        assert(renderedHtml.includes("fa fa-commenting-o o_agui_chat_toggle_icon' role='presentation"));
        const runtimeHost = mounts[0].element.parentNode.host;
        assert.strictEqual(runtimeHost.ariaHidden, undefined);
        const webClientRoot = manager.webClient.$el[0];
        assert.strictEqual(manager.surface, "standalone");
        assert.strictEqual(manager.dockOpen, false);
        assert(!WEBCLIENT_HAS_DOCK_CLASS(webClientRoot));
        assert.strictEqual(webClientRoot.style.values["--agui-chat-dock-size"], undefined);
        let focusPropagationStopped = false;
        assert.strictEqual(manager.events.focusin, "_onSurfaceFocusIn");
        manager._onSurfaceFocusIn({
            stopPropagation() { focusPropagationStopped = true; },
        });
        assert.strictEqual(focusPropagationStopped, true);

        manager._onHostState({surface: "dock"});
        assert.strictEqual(manager.surface, "standalone");
        assert.strictEqual(manager.dockOpen, false);

        manager._onToggleDock();
        assert.strictEqual(manager.dockOpen, true);
        assert.strictEqual(runtimeHost.parentNode.name, ".o_agui_chat_standalone_slot");
        assert(!WEBCLIENT_HAS_DOCK_CLASS(webClientRoot));
        assert.strictEqual(webClientRoot.style.values["--agui-chat-dock-size"], undefined);

        [
            {direction: "left", dx: 100, dy: 0, expected: 820},
            {direction: "right", dx: 100, dy: 0, expected: 620},
            {direction: "top", dx: 0, dy: 50, expected: 470},
            {direction: "bottom", dx: 0, dy: 50, expected: 370},
        ].forEach((testCase) => {
            manager.dockDirection = testCase.direction;
            manager.dockSizes[testCase.direction] = testCase.direction === "top" || testCase.direction === "bottom" ? 420 : 720;
            manager._beginInteraction({clientX: 0, clientY: 0, button: 0, preventDefault() {}}, "dock", null);
            manager._onWindowPointerMove({clientX: testCase.dx, clientY: testCase.dy});
            assert.strictEqual(manager.dockSizes[testCase.direction], testCase.expected);
            manager._onWindowPointerUp();
        });

        manager.openSurface("standalone");
        assert.strictEqual(mounts.length, 1);
        assert.strictEqual(runtimeHost.parentNode.name, ".o_agui_chat_standalone_slot");
        assert(!WEBCLIENT_HAS_DOCK_CLASS(webClientRoot));
        manager.floatRect = {width: 720, height: 600, left: 100, top: 100};
        manager._beginInteraction({clientX: 100, clientY: 100, button: 0, preventDefault() {}}, "move", null);
        manager._onWindowPointerMove({clientX: 5000, clientY: 5000});
        assert.strictEqual(manager.floatRect.left, 704);
        assert.strictEqual(manager.floatRect.top, 284);
        manager._onWindowPointerUp();
        manager.floatRect = {width: 720, height: 600, left: 16, top: 16};
        manager._beginInteraction({clientX: 0, clientY: 0, button: 0, preventDefault() {}}, "resize", "bottom-right");
        manager._onWindowPointerMove({clientX: 5000, clientY: 5000});
        assert.strictEqual(manager.floatRect.width, 1408);
        assert.strictEqual(manager.floatRect.height, 868);
        manager._onWindowPointerUp();
        manager.floatRect = {width: 700, height: 500, left: 200, top: 100};
        manager._beginInteraction({clientX: 200, clientY: 100, button: 0, preventDefault() {}}, "resize", "top-left");
        manager._onWindowPointerMove({clientX: 1000, clientY: 1000});
        assert.strictEqual(manager.floatRect.left + manager.floatRect.width, 900);
        assert.strictEqual(manager.floatRect.top + manager.floatRect.height, 600);
        manager._onWindowPointerUp();

        manager.openSurface("dock");
        assert.strictEqual(runtimeHost.parentNode.name, ".o_agui_chat_dock_slot");
        assert(updates.some((props) => props.surface === "standalone"));
        manager._onClose();
        assert(!WEBCLIENT_HAS_DOCK_CLASS(webClientRoot));
        assert.strictEqual(JSON.parse(storage["agui_chat.layout.v1.test_db.7"]).surface, "dock");

        manager.dockSizes[manager.dockDirection] = 500;
        manager.floatRect = {width: 700, height: 500, left: 200, top: 100};
        sandbox.window.innerWidth = 390;
        sandbox.document.documentElement.clientWidth = 390;
        manager.dockOpen = true;
        manager._applySurface("dock");
        assert(!WEBCLIENT_HAS_DOCK_CLASS(webClientRoot));
        assert.strictEqual(manager.dockSizes[manager.dockDirection], 500);
        assert.deepStrictEqual(manager.floatRect, {width: 700, height: 500, left: 200, top: 100});
        const mobileSize = manager.dockSizes[manager.dockDirection];
        manager._onResizePointerDown({button: 0});
        assert.strictEqual(manager.interaction, null);
        assert.strictEqual(manager.dockSizes[manager.dockDirection], mobileSize);

        const storageKey = "agui_chat.layout.v1.test_db.7";
        const savedLayout = storage[storageKey];
        const originalGetItem = sandbox.window.localStorage.getItem;
        storage[storageKey] = "{broken";
        assert.strictEqual(manager._readStorage(), null);
        sandbox.window.localStorage.getItem = function () { throw new Error("denied"); };
        assert.strictEqual(manager._readStorage(), null);
        sandbox.window.localStorage.getItem = originalGetItem;
        storage[storageKey] = savedLayout;
        manager.destroy();
        assert.strictEqual(unmounts.length, 1);
        assert(!WEBCLIENT_HAS_DOCK_CLASS(webClientRoot));
        assert.strictEqual(listeners.resize, undefined);

        const webClientStart = includes.find((item) => item.start).start.toString();
        assert(webClientStart.includes("return result"));
        assert(!webClientStart.includes("return self.aguiChatSurfaceManager.appendTo"));
        sandbox.window.innerWidth = 1440;
        sandbox.document.documentElement.clientWidth = 1440;
        const restored = new SurfaceManager(new Base());
        return Promise.resolve(restored.start()).then(() => Promise.resolve()).then(() => {
            assert.strictEqual(restored.surface, "dock");
            assert.strictEqual(restored.dockOpen, false);
            assert(!WEBCLIENT_HAS_DOCK_CLASS(restored.webClient.$el[0]));
            assert.strictEqual(restored.dockDirection, "bottom");
            assert.strictEqual(restored.dockSizes.bottom, 500);
            assert.strictEqual(restored.floatRect.width, 700);
            assert.strictEqual(restored.floatRect.height, 500);
            assert.strictEqual(restored.floatRect.left, 200);
            assert.strictEqual(restored.floatRect.top, 100);
            restored.destroy();

            delete storage[storageKey];
            service.snapshot = Object.assign({}, service.snapshot, {surface: "standalone"});
            const legacy = new SurfaceManager(new Base());
            return Promise.resolve(legacy.start()).then(() => Promise.resolve()).then(() => {
                assert.strictEqual(legacy.surface, "standalone");
                assert.strictEqual(legacy.dockOpen, false);
                const legacyHost = mounts[mounts.length - 1].element.parentNode.host;
                assert.strictEqual(legacyHost.parentNode.name, ".o_agui_chat_dock_slot");
                legacy._onToggleDock();
                assert.strictEqual(legacy.dockOpen, true);
                assert.strictEqual(legacyHost.parentNode.name, ".o_agui_chat_standalone_slot");
                legacy.destroy();
                assert.strictEqual(unmounts.length, 3);
                console.log("action_registry_test: ok");
            });
        });
    });
}

function WEBCLIENT_HAS_DOCK_CLASS(node) {
    return ["left", "right", "top", "bottom"].some((direction) =>
        node.classes.has("o_agui_chat_webclient_dock_" + direction)
    );
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
