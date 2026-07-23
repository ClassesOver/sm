odoo.define("agui_chat.host_service", function (require) {
    "use strict";

    var AbstractService = require("web.AbstractService");
    var contentdisposition = require("web.contentdisposition");
    var core = require("web.core");
    var FormController = require("web.FormController");
    var KanbanController = require("web.KanbanController");
    var ListController = require("web.ListController");
    var WebClient = require("web.WebClient");
    var viewDialogs = require("web.view_dialogs");
    var Adapter = require("agui_chat.model_adapter");
    var Commands = require("agui_chat.command_registry");

    var PROTOCOL = "agui.odoo.v2";
    var bus = core.bus;
    var nextControllerId = 0;

    function uuid() {
        return "agui-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
    }

    function exportResponseFilename(disposition, fallback) {
        var header = String(disposition || "").replace(/;$/, "");
        var parsed;
        var filename;
        try {
            parsed = header && contentdisposition.parse(header);
        } catch (_error) {
            return false;
        }
        if (!parsed || parsed.type !== "attachment") {
            return false;
        }
        filename = String(parsed.parameters.filename || fallback || "")
            .replace(/\\/g, "/").split("/").pop()
            .replace(/[\x00-\x1f\x7f]/g, "").trim();
        if (!filename || filename.length > 255 || !/\.xlsx$/i.test(filename)) {
            filename = fallback;
        }
        return filename || false;
    }

    function unavailableSnapshot(revision, surface, snapshotId, error) {
        var snapshot = {
            protocol: PROTOCOL,
            snapshotId: snapshotId || uuid(),
            hostRevision: revision,
            capturedAt: new Date().toISOString(),
            interactive: false,
            surface: surface,
            controller: {
                actionId: false,
                controllerId: "",
                dataPointId: false,
                viewType: false,
                mode: false,
            },
            action: false,
            menu: false,
            record: false,
            selection: false,
            fields: {},
            capabilities: {
                create: false, open: false, edit: false, filter: false,
                group: false, totalCount: 0, filterFields: {}, groupFields: {}, groupBy: [],
                viewTypes: [], records: [], controls: [], x2many: [],
            },
        };
        if (error && error.code) {
            snapshot.error = {
                code: error.code,
                message: error.message || "页面快照不可用。",
            };
        }
        return snapshot;
    }

    function menuAction(node) {
        // 只导航自身配置 action 的末级菜单，不从子菜单推断或继承 action。
        if ((node && node.children || []).length) {
            return false;
        }
        var parts = String(node && node.action || "").split(",");
        if (parts.length !== 2 ||
                ["ir.actions.act_window", "ir.actions.client"].indexOf(parts[0]) === -1 ||
                !/^[1-9]\d*$/.test(parts[1])) {
            return false;
        }
        return parseInt(parts[1], 10);
    }

    function buildMenuOptions(menuData) {
        var options = [];
        function visit(node, path, primaryMenuId) {
            var name = String(node && node.name || "").trim();
            var nextPath = name ? path.concat([name]) : path;
            var actionId = menuAction(node);
            var menuId = parseInt(node && node.id, 10);
            var primary = primaryMenuId || menuId;
            if (actionId && !isNaN(menuId) && menuId > 0) {
                options.push({
                    menuId: menuId,
                    actionId: actionId,
                    name: name,
                    path: nextPath,
                    fullPath: nextPath.join(" / "),
                    primaryMenuId: primary,
                });
            }
            _.each(node && node.children || [], function (child) {
                visit(child, nextPath, primary);
            });
        }
        _.each(menuData && menuData.children || [], function (node) {
            visit(node, [], parseInt(node.id, 10) || false);
        });
        return options;
    }

    function publicMenuEntries(options) {
        return _.map(options || [], function (option) {
            return _.omit(option, "primaryMenuId");
        });
    }

    function menuCatalogFingerprint(ready, options) {
        return JSON.stringify({
            ready: !!ready,
            entries: _.map(options || [], function (option) {
                return [
                    option.menuId, option.actionId, option.name, option.path,
                    option.fullPath, option.primaryMenuId,
                ];
            }),
        });
    }

    function emptyMenuCatalog() {
        return {
            catalogId: uuid(),
            catalogRevision: 0,
            capturedAt: new Date().toISOString(),
            ready: false,
            totalCount: 0,
            entries: [],
        };
    }

    function menuSearchQuery(value) {
        value = String(value || "").trim().slice(0, 400)
            .replace(/[。！？!?]+$/, "").trim();
        value = value.replace(/^(?:请)?(?:打开|进入|导航到|跳转到)\s*/, "");
        return value.replace(/\s*菜单$/, "").trim();
    }

    function normalizeMenuSearch(value) {
        return String(value || "").trim().replace(/\s*(?:\/|>|＞|›|→)\s*/g, " / ")
            .replace(/\s+/g, " ").toLocaleLowerCase();
    }

    function safeTrigger(controller, immediate, generation) {
        try {
            bus.trigger("agui_host:controller_changed", {
                controller: controller,
                immediate: !!immediate,
                generation: generation,
            });
        } catch (error) {
            // Host refresh must never escape into an Odoo controller lifecycle.
        }
    }

    function updateDirtyFields(controller, fields) {
        if (!controller) {
            return;
        }
        try {
            if (!controller.model ||
                    !_.isFunction(controller.model.isDirty) ||
                    !controller.model.isDirty(controller.handle)) {
                controller.__aguiHostDirtyFields = [];
                controller.__aguiHostStagedFields = {};
                return;
            }
            controller.__aguiHostDirtyFields = _.uniq(
                (controller.__aguiHostDirtyFields || []).concat(fields || [])
            );
        } catch (error) {
            controller.__aguiHostDirtyFields = [];
        }
    }

    function clearDirtyFields(controller) {
        if (controller) {
            controller.__aguiHostDirtyFields = [];
            controller.__aguiHostStagedFields = {};
        }
    }

    function sameTargetIdentity(target, snapshot) {
        return target && snapshot && snapshot.interactive && snapshot.record &&
            target.controllerId === snapshot.controller.controllerId &&
            target.dataPointId === snapshot.controller.dataPointId &&
            target.model === snapshot.record.model && target.resId === snapshot.record.resId;
    }

    var AguiHostService = AbstractService.extend({
        init: function () {
            this._super.apply(this, arguments);
            this._action = false;
            this._menu = false;
            this._controller = null;
            this._rootController = null;
            this._modalDialog = null;
            this._modalController = null;
            this._modalOpenDeferred = null;
            this._controllerId = "";
            this._controllerGeneration = 0;
            this._actionManager = null;
            this._hostRevision = 0;
            this._surface = "dock";
            this._snapshot = unavailableSnapshot(0, this._surface);
            this._subscribers = [];
            this._menuSubscribers = [];
            this._refreshTimer = null;
            this._commandBusy = false;
            this._sensitiveFields = [];
            this._enabled = false;
            this._webClient = null;
            this._menuData = null;
            this._menuOptions = [];
            this._menuCatalog = emptyMenuCatalog();
            this._menuFingerprint = menuCatalogFingerprint(false, []);
            this._tokens = {};
            this._snapshotWaiters = [];
        },

        start: function () {
            bus.on("agui_host:controller_changed", this, this._onControllerChanged);
            bus.on("agui_host:controller_destroyed", this, this._onControllerDestroyed);
            bus.on("agui_host:configure", this, this._onConfigure);
            bus.on("agui_host:form_view_transition", this, this._onFormViewTransition);
            return this._super.apply(this, arguments);
        },

        destroy: function () {
            bus.off("agui_host:controller_changed", this, this._onControllerChanged);
            bus.off("agui_host:controller_destroyed", this, this._onControllerDestroyed);
            bus.off("agui_host:configure", this, this._onConfigure);
            bus.off("agui_host:form_view_transition", this, this._onFormViewTransition);
            if (this._refreshTimer) {
                clearTimeout(this._refreshTimer);
                this._refreshTimer = null;
            }
            this._subscribers = [];
            this._menuSubscribers = [];
            _.each(this._snapshotWaiters, function (waiter) { waiter.resolve(this._snapshot); }, this);
            this._snapshotWaiters = [];
            return this._super.apply(this, arguments);
        },

        configureNavigation: function (webClient, menuData) {
            this._webClient = webClient || null;
            this._menuData = menuData || webClient && webClient.menu_data || null;
            this._refreshMenuCatalog();
            return this.getMenuCatalog();
        },

        getMenuCatalog: function () {
            this._refreshMenuCatalog();
            return Adapter.clone(this._menuCatalog);
        },

        _refreshMenuCatalog: function () {
            var menuData = this._webClient && _.has(this._webClient, "menu_data") ?
                this._webClient.menu_data : this._menuData;
            var ready = !!(menuData && _.isArray(menuData.children));
            var options = ready ? buildMenuOptions(menuData) : [];
            var fingerprint = menuCatalogFingerprint(ready, options);
            this._menuData = menuData || null;
            this._menuOptions = options;
            if (fingerprint === this._menuFingerprint) {
                return false;
            }
            this._menuFingerprint = fingerprint;
            this._menuCatalog = {
                catalogId: uuid(),
                catalogRevision: (this._menuCatalog && this._menuCatalog.catalogRevision || 0) + 1,
                capturedAt: new Date().toISOString(),
                ready: ready,
                totalCount: options.length,
                entries: publicMenuEntries(options),
            };
            this._publishMenuCatalog();
            return true;
        },

        searchMenus: function (value) {
            var query = menuSearchQuery(value);
            var needle = normalizeMenuSearch(query);
            var options;
            var exact;
            var matches;
            var catalog = this.getMenuCatalog();
            options = this._menuOptions;
            exact = needle ? _.filter(options, function (option) {
                return normalizeMenuSearch(option.fullPath) === needle ||
                    normalizeMenuSearch(option.name) === needle;
            }) : [];
            matches = exact.length ? exact : needle ? _.filter(options, function (option) {
                return normalizeMenuSearch(option.fullPath).indexOf(needle) !== -1 ||
                    normalizeMenuSearch(option.name).indexOf(needle) !== -1;
            }) : [];
            return {
                query: query,
                matchType: exact.length ? "exact" : matches.length ? "contains" : "none",
                matchCount: matches.length,
                truncated: matches.length > 8,
                catalogId: catalog.catalogId,
                catalogRevision: catalog.catalogRevision,
                catalogReady: catalog.ready,
                catalogTotalCount: catalog.totalCount,
                candidates: Adapter.clone(publicMenuEntries(matches.slice(0, 8))),
            };
        },

        setCurrentController: function (action, descriptor) {
            try {
                descriptor = descriptor || {};
                this._actionManager = descriptor.__actionManager || this._actionManager;
                this._action = action || descriptor.action || false;
                this._menu = descriptor.menu || descriptor.menu_id && {id: descriptor.menu_id} || false;
                if (!this._enabled) {
                    return Adapter.clone(this._snapshot);
                }
                return this._activateCurrentController();
            } catch (error) {
                return this._setUnavailable("host_unavailable");
            }
        },

        clearCurrentController: function (descriptor) {
            try {
                if (descriptor && descriptor.controllerId && descriptor.controllerId !== this._controllerId) {
                    return Adapter.clone(this._snapshot);
                }
                this._controller = null;
                this._controllerId = "";
                this._controllerGeneration += 1;
                this._rootController = null;
                this._modalController = null;
                this._modalDialog = null;
                return this._setUnavailable("host_unavailable");
            } catch (error) {
                return this._setUnavailable("host_unavailable");
            }
        },

        getSnapshot: function () {
            try {
                if (!this._enabled) {
                    return Adapter.clone(this._snapshot);
                }
                if (!this._resolveCurrentController()) {
                    this._activateCurrentController();
                }
                return Adapter.clone(this._snapshot);
            } catch (error) {
                this._setUnavailable("host_unavailable");
                return Adapter.clone(this._snapshot);
            }
        },

        subscribe: function (owner, callback) {
            try {
                if (!owner || !_.isFunction(callback)) {
                    return false;
                }
                this.unsubscribe(owner, callback);
                this._subscribers.push({owner: owner, callback: callback});
                return true;
            } catch (error) {
                return false;
            }
        },

        subscribeMenuCatalog: function (owner, callback) {
            try {
                if (!owner || !_.isFunction(callback)) {
                    return false;
                }
                this.unsubscribeMenuCatalog(owner, callback);
                this._menuSubscribers.push({owner: owner, callback: callback});
                return true;
            } catch (error) {
                return false;
            }
        },

        unsubscribe: function (owner, callback) {
            try {
                this._subscribers = _.filter(this._subscribers, function (entry) {
                    return entry.owner !== owner || callback && entry.callback !== callback;
                });
                return true;
            } catch (error) {
                return false;
            }
        },

        unsubscribeMenuCatalog: function (owner, callback) {
            try {
                this._menuSubscribers = _.filter(this._menuSubscribers, function (entry) {
                    return entry.owner !== owner || callback && entry.callback !== callback;
                });
                return true;
            } catch (error) {
                return false;
            }
        },

        getToolCatalog: function () {
            try {
                return Commands.getCatalog();
            } catch (error) {
                return [];
            }
        },

        prepareHostCommand: function (call, allowStaleRetry) {
            var self = this;
            var cleanCall = Adapter.clone(call || {});
            this._refreshMenuCatalog();
            if (cleanCall.arguments) {
                delete cleanCall.arguments.__control;
                delete cleanCall.arguments.__row;
            }
            var snapshot = this.getSnapshot();
            var validation = this._validateTarget(cleanCall, snapshot);
            var target = cleanCall.arguments && cleanCall.arguments.target;
            var retry = validation === "stale_snapshot" && allowStaleRetry &&
                cleanCall.tool === "odoo.patch_current_form" && sameTargetIdentity(target, snapshot);
            var ready = retry ? this._refreshNow(this._resolveCurrentController()) : $.when(snapshot);
            if (validation && !retry) {
                return $.when(this._commandResult(false, cleanCall, validation, {}, snapshot));
            }
            return ready.then(function (nextSnapshot) {
                var preview;
                if (retry) {
                    cleanCall.arguments.target = Adapter.targetFromSnapshot(nextSnapshot);
                }
                var rowBinding = cleanCall.arguments && cleanCall.arguments.rowToken &&
                    self._resolveToken(cleanCall.arguments.rowToken, "x2many_row");
                if (cleanCall.arguments && cleanCall.arguments.rowToken &&
                        (!rowBinding || !self._validateToken(rowBinding, "x2many_row"))) {
                    return self._commandResult(
                        false, cleanCall, "stale_x2many_row_token", {}, nextSnapshot
                    );
                }
                if (rowBinding) {
                    cleanCall.arguments.__row = {
                        field: rowBinding.fieldName,
                        model: rowBinding.model,
                    };
                }
                if (cleanCall.tool === "odoo.patch_current_form" ||
                        cleanCall.tool === "odoo.stage_current_form") {
                    preview = Adapter.buildPatchPreview(
                        self._resolveCurrentController(), nextSnapshot, cleanCall.arguments || {},
                        cleanCall.tool === "odoo.stage_current_form" ? {
                            allowStaged: true,
                            rowBinding: rowBinding,
                        } : {}
                    );
                    if (preview.rejected.length) {
                        return self._commandResult(
                            false, cleanCall,
                            preview.rejected.length === 1 ? preview.rejected[0].code : "patch_rejected",
                            {preview: preview, rejected: preview.rejected}, nextSnapshot
                        );
                    }
                    cleanCall.preview = preview;
                }
                if (cleanCall.tool === "odoo.activate_view_control") {
                    var control = self._resolveToken(
                        cleanCall.arguments && cleanCall.arguments.controlToken, "control"
                    );
                    if (!control || !self._validateToken(control, "control")) {
                        return self._commandResult(false, cleanCall, "stale_control_token", {}, nextSnapshot);
                    }
                    cleanCall.arguments.__control = {
                        type: control.type,
                        name: control.name,
                        label: control.label,
                        recordLabel: control.recordLabel,
                    };
                }
                if (cleanCall.tool === "odoo.open_x2many_record") {
                    var row = self._resolveToken(
                        cleanCall.arguments && cleanCall.arguments.rowToken, "x2many_row"
                    );
                    if (!row || !self._validateToken(row, "x2many_row")) {
                        return self._commandResult(
                            false, cleanCall, "stale_x2many_row_token", {}, nextSnapshot
                        );
                    }
                }
                if (cleanCall.tool === "odoo.open_x2many_create") {
                    var x2manyField = self._resolveToken(
                        cleanCall.arguments && cleanCall.arguments.fieldToken, "x2many_field"
                    );
                    if (!x2manyField || !self._validateToken(x2manyField, "x2many_field")) {
                        return self._commandResult(
                            false, cleanCall, "stale_x2many_field_token", {}, nextSnapshot
                        );
                    }
                }
                if (cleanCall.tool === "odoo.open_record" && !self._resolveToken(
                    cleanCall.arguments && cleanCall.arguments.recordToken, "record"
                )) {
                    return self._commandResult(false, cleanCall, "stale_record_token", {}, nextSnapshot);
                }
                if (cleanCall.tool === "odoo.navigate_menu") {
                    var menuArgs = cleanCall.arguments || {};
                    var hasQuery = _.isString(menuArgs.query) && !!menuArgs.query.trim();
                    var hasMenuId = _.isNumber(menuArgs.menuId) && isFinite(menuArgs.menuId) &&
                        Math.floor(menuArgs.menuId) === menuArgs.menuId && menuArgs.menuId > 0;
                    var hasActionId = _.isNumber(menuArgs.actionId) && isFinite(menuArgs.actionId) &&
                        Math.floor(menuArgs.actionId) === menuArgs.actionId && menuArgs.actionId > 0;
                    if (hasQuery === (hasMenuId || hasActionId) || hasMenuId !== hasActionId) {
                        return self._commandResult(
                            false, cleanCall, "invalid_menu_navigation", {}, nextSnapshot
                        );
                    }
                    if (hasQuery) {
                        return {
                            ok: true,
                            call: cleanCall,
                            preview: preview || false,
                            retried: !!retry,
                        };
                    }
                    var selectedMenu = self._menuOption(
                        menuArgs.menuId
                    );
                    if (!selectedMenu) {
                        return self._commandResult(
                            false, cleanCall, "menu_unavailable", {}, nextSnapshot
                        );
                    }
                    if (selectedMenu.actionId !== parseInt(
                            menuArgs.actionId, 10)) {
                        return self._commandResult(
                            false, cleanCall, "menu_action_conflict", {}, nextSnapshot
                        );
                    }
                }
                return Commands.prepare(self._commandContext(), cleanCall).then(function (prepared) {
                    return {
                        ok: true,
                        call: prepared.call,
                        preview: prepared.preview || preview || false,
                        retried: !!retry,
                    };
                }, function (error) {
                    return self._commandResult(false, cleanCall, error && error.code || "command_failed", {
                        error: error && error.message || "页面命令准备失败。",
                    }, nextSnapshot);
                });
            });
        },

        executeHostCommand: function (call) {
            var self = this;
            var snapshot;
            var validation;
            try {
                this._refreshMenuCatalog();
                snapshot = this.getSnapshot();
                if (this._commandBusy) {
                    return $.when(this._commandResult(false, call, "command_busy", {}, snapshot));
                }
                validation = call && call.tool === "odoo.undo_current_form" ?
                    this._validateUndoTarget(call, snapshot) : this._validateTarget(call, snapshot);
                if (validation) {
                    return $.when(this._commandResult(false, call, validation, {}, snapshot));
                }
                this._commandBusy = true;
                return Commands.execute(this._commandContext(), call).then(function (payload) {
                    var nextSnapshot = self.getSnapshot();
                    self._commandBusy = false;
                    if (call.tool === "odoo.export_current_view") {
                        return _.extend({
                            ok: true, operation: call.tool, code: "ok",
                        }, payload || {});
                    }
                    return self._commandResult(true, call, "ok", payload, nextSnapshot);
                }, function (error) {
                    var nextSnapshot = self.getSnapshot();
                    self._commandBusy = false;
                    return self._commandResult(false, call, error && error.code || "command_failed", {
                        error: error && error.message || "页面命令执行失败。",
                        rejected: error && error.rejected || [],
                        invalidFields: error && error.invalidFields || [],
                    }, nextSnapshot);
                });
            } catch (error) {
                this._commandBusy = false;
                snapshot = this._setUnavailable("host_unavailable");
                return $.when(this._commandResult(false, call, "host_unavailable", {}, snapshot));
            }
        },

        setSurface: function (surface) {
            try {
                if (surface !== "dock" && surface !== "standalone") {
                    return false;
                }
                if (this._surface !== surface) {
                    this._surface = surface;
                    this._refreshNow(this._controller);
                    bus.trigger("agui_chat:surface_changed", surface);
                }
                return true;
            } catch (error) {
                return false;
            }
        },

        _currentControllerFromManager: function () {
            var current;
            if (!this._actionManager || !_.isFunction(this._actionManager.getCurrentController)) {
                return null;
            }
            current = this._actionManager.getCurrentController();
            return current && (current.widget || current.controller || current) || null;
        },

        _resolveCurrentController: function () {
            if (this._modalDialog && this._controller === this._modalController) {
                if (!(this._controller instanceof FormController) || !this._controller.model ||
                        !this._controller.handle || this._controller.isDestroyed &&
                        this._controller.isDestroyed() ||
                        this._controller.__aguiHostGeneration !== this._controllerGeneration) {
                    return null;
                }
                return this._controller;
            }
            var current = this._currentControllerFromManager();
            if (!current || current !== this._controller || current.__aguiHostGeneration !== this._controllerGeneration) {
                return null;
            }
            if (!(current instanceof FormController) && !(current instanceof ListController) &&
                    !(current instanceof KanbanController)) {
                return null;
            }
            if (!current.model || !current.handle || current.isDestroyed && current.isDestroyed()) {
                return null;
            }
            return current;
        },

        _activateCurrentController: function () {
            var controller = this._currentControllerFromManager();
            var viewType;
            if (controller instanceof FormController) {
                viewType = "form";
            } else if (controller instanceof ListController) {
                viewType = "list";
            } else if (controller instanceof KanbanController) {
                viewType = "kanban";
            } else {
                return this._setUnavailable("host_unavailable");
            }
            if (!controller.model || !controller.handle) {
                return this._setUnavailable("host_unavailable");
            }
            this._rootController = controller;
            this._modalDialog = null;
            this._modalController = null;
            return this._activateController(controller, viewType);
        },

        _activateController: function (controller, viewType) {
            nextControllerId += 1;
            this._controllerGeneration += 1;
            this._controller = controller;
            this._controllerId = "controller-" + nextControllerId;
            controller.__aguiHostGeneration = this._controllerGeneration;
            controller.__aguiHostControllerId = this._controllerId;
            controller.__aguiHostViewType = viewType;
            controller.__aguiHostDirtyFields = controller.__aguiHostDirtyFields || [];
            controller.__aguiHostStagedFields = controller.__aguiHostStagedFields || {};
            return this._refreshNow(controller);
        },

        _refreshNow: function (controller) {
            var current = this._resolveCurrentController();
            if (!controller || controller !== current) {
                return $.when(this._setUnavailable("host_unavailable"));
            }
            if (this._refreshTimer) {
                clearTimeout(this._refreshTimer);
                this._refreshTimer = null;
            }
            try {
                this._hostRevision += 1;
                var snapshotId = uuid();
                var tokens = {};
                this._snapshot = Adapter.buildSnapshot({
                    controller: controller,
                    controllerId: this._controllerId,
                    viewType: controller.__aguiHostViewType,
                    action: this._action,
                    menu: this._menu,
                    hostRevision: this._hostRevision,
                    snapshotId: snapshotId,
                    surface: this._surface,
                    sensitiveFields: this._sensitiveFields,
                    registerToken: function (kind, binding) {
                        var token = kind + "-" + uuid();
                        tokens[token] = {kind: kind, binding: binding, snapshotId: snapshotId};
                        return token;
                    },
                });
                this._tokens = tokens;
                this._publish();
                return $.when(Adapter.clone(this._snapshot));
            } catch (error) {
                return $.when(this._setUnavailable(
                    error && error.code === "snapshot_too_large" ? error : false
                ));
            }
        },

        _requestRefresh: function (controller, immediate, generation) {
            var self = this;
            if (!controller || controller !== this._controller || generation !== this._controllerGeneration || !this._resolveCurrentController()) {
                return $.when(Adapter.clone(this._snapshot));
            }
            if (immediate) {
                return this._refreshNow(controller);
            }
            if (this._refreshTimer) {
                clearTimeout(this._refreshTimer);
            }
            this._refreshTimer = setTimeout(function () {
                self._refreshTimer = null;
                self._refreshNow(controller);
            }, 50);
            return $.when(Adapter.clone(this._snapshot));
        },

        _onControllerChanged: function (event) {
            try {
                if (!this._enabled) {
                    return;
                }
                this._requestRefresh(event.controller, event.immediate, event.generation);
            } catch (error) {
                this._setUnavailable("host_unavailable");
            }
        },

        _onConfigure: function (config) {
            try {
                config = config || {};
                this._enabled = !!config.enabled;
                this._sensitiveFields = config.sensitiveFields || [];
                if (this._enabled) {
                    this._activateCurrentController();
                } else {
                    this._setUnavailable("host_unavailable");
                }
            } catch (error) {
                this._enabled = false;
                this._setUnavailable("host_unavailable");
            }
        },

        _onControllerDestroyed: function (event) {
            try {
                if (event.controller === this._modalController) {
                    return;
                }
                if (event.controller === this._rootController) {
                    this._rootController = null;
                }
                if (event.controller === this._controller && event.generation === this._controllerGeneration) {
                    this.clearCurrentController({controllerId: this._controllerId});
                }
            } catch (error) {
                this._setUnavailable("host_unavailable");
            }
        },

        _onFormViewTransition: function (event) {
            try {
                if (!this._enabled || !event || !event.dialog) {
                    return;
                }
                if (event.phase === "begin") {
                    if (this._modalDialog && this._modalDialog !== event.dialog) {
                        return;
                    }
                    this._rootController = this._currentControllerFromManager() ||
                        this._rootController;
                    this._modalDialog = event.dialog;
                    this._tokens = {};
                    this._setUnavailable("form_view_transition");
                    return;
                }
                if (event.phase === "ready" && this._modalDialog === event.dialog &&
                        event.controller instanceof FormController) {
                    this._modalController = event.controller;
                    event.controller.__aguiHostModalDialog = event.dialog;
                    this._activateController(event.controller, "form");
                    if (this._modalOpenDeferred) {
                        clearTimeout(this._modalOpenDeferred.timer);
                        this._modalOpenDeferred.resolve(Adapter.clone(this._snapshot));
                        this._modalOpenDeferred = null;
                    }
                    return;
                }
                if (event.phase === "end" && this._modalDialog === event.dialog) {
                    if (this._modalOpenDeferred) {
                        clearTimeout(this._modalOpenDeferred.timer);
                        this._modalOpenDeferred.reject(new Error("明细表单在就绪前已关闭。"));
                        this._modalOpenDeferred = null;
                    }
                    this._modalDialog = null;
                    this._modalController = null;
                    var root = this._currentControllerFromManager();
                    var viewType = root instanceof FormController ? "form" :
                        root instanceof ListController ? "list" :
                        root instanceof KanbanController ? "kanban" : false;
                    if (root && root === this._rootController && viewType && root.model && root.handle) {
                        this._activateController(root, viewType);
                    } else {
                        this._setUnavailable("host_unavailable");
                    }
                }
            } catch (error) {
                this._setUnavailable("host_unavailable");
            }
        },

        _setUnavailable: function (error) {
            if (!this._snapshot || this._snapshot.interactive || this._snapshot.surface !== this._surface) {
                this._hostRevision += 1;
                this._snapshot = unavailableSnapshot(
                    this._hostRevision, this._surface, false, error
                );
                this._tokens = {};
                this._publish();
            }
            return Adapter.clone(this._snapshot);
        },

        _publish: function () {
            var snapshot = Adapter.clone(this._snapshot);
            var pending = this._snapshotWaiters;
            this._snapshotWaiters = [];
            _.each(pending, function (waiter) {
                if (snapshot.snapshotId !== waiter.snapshotId &&
                        (!waiter.interactive || snapshot.interactive)) {
                    clearTimeout(waiter.timer);
                    waiter.resolve(snapshot);
                } else {
                    this._snapshotWaiters.push(waiter);
                }
            }, this);
            _.each(this._subscribers.slice(0), function (entry) {
                try {
                    entry.callback.call(entry.owner, snapshot);
                } catch (error) {
                    // Subscriber failures are isolated from Odoo.
                }
            });
        },

        _publishMenuCatalog: function () {
            var catalog = Adapter.clone(this._menuCatalog);
            _.each((this._menuSubscribers || []).slice(0), function (entry) {
                try {
                    entry.callback.call(entry.owner, catalog);
                } catch (error) {
                    // Subscriber failures are isolated from Odoo.
                }
            });
        },

        _validateTarget: function (call, snapshot) {
            var args = call && call.arguments;
            var target = args && args.target;
            if (call && call.tool === "odoo.navigate_menu") {
                if (!target || !_.has(target, "snapshotId") ||
                        !_.has(target, "hostRevision") || !_.has(target, "catalogId") ||
                        !_.has(target, "catalogRevision")) {
                    return "invalid_target";
                }
                if (target.snapshotId !== snapshot.snapshotId ||
                        target.hostRevision !== snapshot.hostRevision) {
                    return "stale_snapshot";
                }
                if (target.catalogId !== this._menuCatalog.catalogId ||
                        target.catalogRevision !== this._menuCatalog.catalogRevision) {
                    if (args && _.has(args, "menuId")) {
                        var current = _.findWhere(this._menuOptions, {
                            menuId: parseInt(args && args.menuId, 10),
                        });
                        if (current && current.actionId !== parseInt(args && args.actionId, 10)) {
                            return "menu_action_conflict";
                        }
                    }
                    return "stale_menu_catalog";
                }
                return false;
            }
            var model = snapshot.record && snapshot.record.model || snapshot.selection && snapshot.selection.model || false;
            var resId = snapshot.record && snapshot.record.resId || false;
            var required = ["snapshotId", "hostRevision", "controllerId", "dataPointId", "model", "resId"];
            if (!snapshot.interactive || !target || !_.every(required, function (key) { return _.has(target, key); })) {
                return "invalid_target";
            }
            if (target.snapshotId !== snapshot.snapshotId || target.hostRevision !== snapshot.hostRevision) {
                return "stale_snapshot";
            }
            if (target.controllerId !== snapshot.controller.controllerId || target.dataPointId !== snapshot.controller.dataPointId) {
                return "controller_conflict";
            }
            if (target.model !== model || target.resId !== resId) {
                return "record_conflict";
            }
            return false;
        },

        _validateUndoTarget: function (call, snapshot) {
            var args = call && call.arguments;
            var target = args && args.target;
            var required = ["controllerId", "dataPointId", "model", "resId"];
            if (!snapshot.interactive || !target ||
                    !_.every(required, function (key) { return _.has(target, key); })) {
                return "invalid_target";
            }
            return sameTargetIdentity(target, snapshot) ? false : "undo_conflict";
        },

        _commandContext: function () {
            var self = this;
            return {
                getSnapshot: function () { return self.getSnapshot(); },
                getController: function () { return self._resolveCurrentController(); },
                refresh: function (controller, immediate) {
                    return self._requestRefresh(controller, immediate, controller && controller.__aguiHostGeneration);
                },
                hasUnsavedChanges: function () { return self._hasUnsavedChanges(); },
                waitForSnapshotChange: function (snapshotId) { return self._waitForSnapshotChange(snapshotId); },
                waitForInteractiveSnapshotChange: function (snapshotId) {
                    return self._waitForInteractiveSnapshotChange(snapshotId);
                },
                resolveToken: function (token, kind) { return self._resolveToken(token, kind); },
                validateToken: function (binding, kind) { return self._validateToken(binding, kind); },
                searchMenus: function (query) {
                    return self.searchMenus(query);
                },
                openMenu: function (menuId, actionId) {
                    return self._openMenu(menuId, actionId);
                },
                openRecord: function (binding, mode) { return self._openRecord(binding, mode); },
                openCreate: function (controller) { return self._openCreate(controller); },
                switchView: function (controller, viewType) {
                    return self._switchView(controller, viewType);
                },
                activateControl: function (binding) { return self._activateControl(binding); },
                openX2Many: function (binding, create, mode) {
                    return self._openX2Many(binding, create, mode);
                },
                isModalForm: function () {
                    return !!self._modalDialog && self._modalController === self._controller;
                },
                saveForm: function (controller) { return self._saveForm(controller); },
                discardForm: function (controller) { return self._discardForm(controller); },
                reloadForm: function (controller) { return self._reloadForm(controller); },
                exportCurrentView: function (call, spec, metadata) {
                    return self._exportCurrentView(call, spec, metadata);
                },
            };
        },

        _exportCurrentView: function (call, spec, metadata) {
            var workspace = call && call.__workspace;
            var format = metadata && metadata.format;
            var exportData = {
                import_compat: false,
                model: spec.model,
                fields: _.map(spec.fields || [], function (field) {
                    return {
                        name: field.name,
                        label: field.label,
                        fieldInfo: field.fieldInfo,
                    };
                }),
                data: spec.data || [],
                ids: spec.ids || false,
                domain: spec.domain || [],
                groupby: spec.groupby || [],
                context: spec.context || {},
                action: spec.action || false,
                orderby: spec.orderby,
                detail_orderby: spec.detail_orderby || "",
            };
            if (!workspace || !workspace.capability || !workspace.threadId ||
                    workspace.threadId !== workspace.expectedThreadId) {
                return $.Deferred().reject(_.extend(
                    new Error("工作区能力令牌无效。"), {code: "workspace_capability_rejected"}
                )).promise();
            }
            var exportBody = new FormData();
            exportBody.append("data", JSON.stringify(exportData));
            exportBody.append("token", "agui-export");
            if (core.csrf_token) {
                exportBody.append("csrf_token", core.csrf_token);
            }
            return window.fetch("/web/export/" + format, {
                method: "POST", credentials: "same-origin", body: exportBody,
            }).then(function (response) {
                var disposition = response.headers.get("Content-Disposition") || "";
                var filename = exportResponseFilename(
                    disposition, metadata.workspacePath.split("/").pop()
                );
                if (!response.ok || !filename) {
                    throw _.extend(new Error("Odoo 原生导出失败。"), {code: "odoo_export_failed"});
                }
                return response.blob().then(function (blob) {
                    return {blob: blob, filename: filename};
                }, function () {
                    throw _.extend(new Error("Odoo 原生导出失败。"), {
                        code: "odoo_export_failed",
                    });
                });
            }, function () {
                throw _.extend(new Error("Odoo 原生导出失败。"), {code: "odoo_export_failed"});
            }).then(function (exportFile) {
                var blob = exportFile.blob;
                if (blob.size > 200 * 1024 * 1024) {
                    throw _.extend(new Error("导出文件超过 200 MiB。"), {code: "export_file_too_large"});
                }
                var uploadBody = new FormData();
                uploadBody.append("threadId", workspace.threadId);
                uploadBody.append("path", metadata.workspacePath);
                uploadBody.append("file", blob, exportFile.filename);
                return window.fetch(workspace.filesUrl, {
                    method: "POST",
                    credentials: workspace.credentials,
                    headers: {
                        "X-AGUI-Thread": workspace.threadId,
                        "X-AGUI-Capability": workspace.capability,
                    },
                    body: uploadBody,
                }).then(function (response) {
                    return response.json().catch(function () { return {}; }).then(function (payload) {
                        var entry = payload && payload.entry;
                        if (!response.ok || response.status !== 201 || payload.ok !== true ||
                                !entry || entry.path !== metadata.workspacePath) {
                            throw _.extend(new Error(payload.error || "工作区上传失败。"), {
                                code: payload.error || "workspace_upload_failed",
                            });
                        }
                        return {
                            path: metadata.workspacePath,
                            filename: exportFile.filename,
                            format: format,
                            size: blob.size,
                            recordCount: metadata.recordCount,
                            fieldCount: metadata.fieldCount,
                        };
                    });
                }, function () {
                    throw _.extend(new Error("工作区上传失败。"), {
                        code: "workspace_upload_failed",
                    });
                });
            });
        },

        _menuOption: function (menuId) {
            menuId = parseInt(menuId, 10);
            this._refreshMenuCatalog();
            return _.findWhere(this._menuOptions, {menuId: menuId}) || false;
        },

        _openMenu: function (menuId, actionId) {
            var option = this._menuOption(menuId);
            var self = this;
            if (!option || !this._webClient || !_.isFunction(this._webClient.do_action)) {
                var unavailable = new Error("所选菜单已删除或当前用户无权访问。");
                unavailable.code = "menu_unavailable";
                throw unavailable;
            }
            actionId = parseInt(actionId, 10);
            if (isNaN(actionId) || actionId <= 0 || option.actionId !== actionId) {
                var conflict = new Error("菜单对应动作已变化，请重新搜索后再打开。");
                conflict.code = "menu_action_conflict";
                throw conflict;
            }
            this._menu = {id: option.menuId, name: option.name};
            return $.when(this._webClient.do_action(option.actionId, {
                clear_breadcrumbs: true,
                action_menu_id: option.menuId,
            })).then(function (result) {
                if (self._webClient.menu && _.isFunction(self._webClient.menu.change_menu_section)) {
                    self._webClient.menu.change_menu_section(option.primaryMenuId);
                }
                return _.omit(option, "primaryMenuId");
            });
        },

        _hasUnsavedChanges: function () {
            var controller = this._resolveCurrentController();
            var raw;
            if (!(controller instanceof FormController)) {
                return false;
            }
            try {
                raw = controller.model.get(controller.handle, {raw: true});
                return !!(controller.model.isDirty && controller.model.isDirty(controller.handle)) ||
                    !!_.keys(raw && raw._changes || {}).length ||
                    !!(controller.__aguiHostDirtyFields || []).length;
            } catch (error) {
                return true;
            }
        },

        _resolveToken: function (token, kind) {
            var entry = this._tokens[String(token || "")];
            return entry && entry.kind === kind && entry.snapshotId === this._snapshot.snapshotId ?
                entry.binding : false;
        },

        _validateToken: function (binding, kind) {
            var controller = this._resolveCurrentController();
            var state;
            var $element;
            if (!binding || !controller) {
                return false;
            }
            if (kind === "x2many_row" || kind === "x2many_field") {
                var parent = controller.model.get(controller.handle);
                var list = parent && parent.data && parent.data[binding.fieldName];
                if (!list || list.model !== binding.model ||
                        kind === "x2many_field" && list.id !== binding.localId) {
                    return false;
                }
                if (kind === "x2many_row") {
                    state = controller.model.get(binding.localId, {raw: true});
                    if (!state || state.model !== binding.model ||
                            (state.res_id || false) !== binding.resId) {
                        return false;
                    }
                    return _.some(list.data || [], function (item) {
                        return item && item.id === binding.localId;
                    });
                }
                return true;
            }
            if (binding.widget && binding.x2manyAction) {
                if (!binding.widget.$el || !binding.widget.$el.length ||
                        binding.widget.isDestroyed && binding.widget.isDestroyed() ||
                        binding.widget.name !== binding.fieldName ||
                        binding.widget.field.relation !== binding.model) {
                    return false;
                }
                state = binding.x2manyAction === "open" &&
                    controller.model.get(binding.localId, {raw: true});
                if (binding.x2manyAction === "open" && (!state ||
                        state.model !== binding.model ||
                        (state.res_id || false) !== binding.resId)) {
                    return false;
                }
                $element = binding.$element || binding.widget.$el;
                if (!$element.length || $element[0].hidden ||
                        $element.attr("aria-hidden") === "true" ||
                        $element.hasClass("o_hidden") || $element.css("display") === "none" ||
                        $element.css("visibility") === "hidden" ||
                        !$.contains(binding.widget.$el[0], $element[0]) &&
                        binding.widget.$el[0] !== $element[0]) {
                    return false;
                }
            } else if (binding.widget) {
                state = binding.widget.state;
                if (!state || state.res_id !== binding.resId || !binding.widget.$el ||
                        !binding.widget.$el.length || binding.widget.isDestroyed && binding.widget.isDestroyed()) {
                    return false;
                }
                $element = binding.$element || binding.widget.$el;
                if (!$element.length || $element[0].hidden ||
                        $element.attr("aria-hidden") === "true" ||
                        $element.hasClass("o_hidden") || $element.css("display") === "none" ||
                        $element.css("visibility") === "hidden") {
                    return false;
                }
            } else {
                state = controller.model.get(binding.localId, {raw: true});
                if (!state || state.res_id !== binding.resId) {
                    return false;
                }
            }
            if (kind === "control" && binding.$element) {
                var $root = binding.widget && binding.widget.$el ||
                    controller.renderer && controller.renderer.$el;
                if (!$root || !$root.length || !binding.$element.length ||
                        (!$.contains($root[0], binding.$element[0]) &&
                            $root[0] !== binding.$element[0])) {
                    return false;
                }
            }
            return true;
        },

        _openRecord: function (binding, mode) {
            var controller = this._resolveCurrentController();
            var actionViews;
            var hasFormView;
            var $row;
            if (binding.widget) {
                binding.widget.trigger_up("open_record", {
                    id: binding.localId,
                    mode: mode || "readonly",
                });
                return $.when();
            }
            actionViews = controller.actionViews || [];
            hasFormView = _.filter(actionViews, function (view) {
                return view && (view.type === "form" || view[1] === "form");
            }).length > 0;
            if (actionViews.length && !hasFormView && controller.renderer &&
                    _.isFunction(controller.renderer.$)) {
                $row = controller.renderer.$(".o_data_row").filter(function () {
                    return $(this).data("id") === binding.localId;
                }).first();
                if ($row.length) {
                    $row.trigger("click");
                    return $.when();
                }
            }
            controller.trigger_up("switch_view", {
                view_type: "form",
                res_id: binding.resId,
                mode: mode || "readonly",
            });
            return $.when();
        },

        _openCreate: function (controller) {
            if (controller instanceof FormController && _.isFunction(controller.createRecord)) {
                return controller.createRecord();
            }
            controller.trigger_up("switch_view", {view_type: "form", res_id: undefined});
            return $.when();
        },

        _switchView: function (controller, viewType) {
            controller.trigger_up("switch_view", {view_type: viewType});
            return $.when();
        },

        _openX2Many: function (binding, create, mode) {
            var self = this;
            var widget = binding && binding.widget;
            if (this._modalDialog) {
                var busy = new Error("当前已有明细弹窗，请先保存或放弃。");
                busy.code = "x2many_dialog_busy";
                throw busy;
            }
            if (!widget || !_.isFunction(widget._openFormDialog) ||
                    widget.isDestroyed && widget.isDestroyed()) {
                var unavailable = new Error("当前明细字段尚未激活，无法打开原生表单。");
                unavailable.code = "requires_form_activation";
                throw unavailable;
            }
            var ready = $.Deferred();
            this._modalOpenDeferred = ready;
            ready.timer = setTimeout(function () {
                if (self._modalOpenDeferred === ready) {
                    self._modalOpenDeferred = null;
                    ready.reject(new Error("明细表单装载超时。"));
                }
            }, 5000);
            if (create) {
                widget._openFormDialog({
                    on_saved: function (record) {
                        return widget._setValue({operation: "ADD", id: record.id});
                    },
                });
                return ready.promise();
            }
            var id = binding.localId;
            widget._openFormDialog({
                id: id,
                on_saved: function (record) {
                    var exists = _.some(widget.value && widget.value.data || [], {id: record.id});
                    return widget._setValue({operation: exists ? "UPDATE" : "ADD", id: record.id});
                },
                on_remove: function () {
                    return widget._setValue({operation: "DELETE", ids: [id]});
                },
                deletable: widget.activeActions && widget.activeActions.delete,
                readonly: mode === "readonly",
            });
            return ready.promise();
        },

        _saveForm: function (controller) {
            var dialog = this._modalDialog;
            if (dialog && controller === this._modalController && _.isFunction(dialog._save)) {
                return $.when(dialog._save()).then(function () {
                    return dialog.__aguiHostOnSaved || $.when();
                }).then(function () {
                    dialog.close();
                    return {changedFields: [], persistence: "parent_pending"};
                });
            }
            return $.when(controller.saveRecord()).then(function (fields) {
                return {changedFields: fields || [], persistence: "database"};
            });
        },

        _discardForm: function (controller) {
            var dialog = this._modalDialog;
            if (!dialog || controller !== this._modalController ||
                    !controller.model || !_.isFunction(controller.model.discardChanges)) {
                return $.Deferred().reject(new Error("原生明细放弃流程不可用。")).promise();
            }
            controller.model.discardChanges(controller.handle, {rollback: true});
            dialog.close();
            return $.when();
        },

        _reloadForm: function (controller) {
            if (!controller || !_.isFunction(controller.reload)) {
                return $.Deferred().reject(new Error("当前表单不支持重新载入。")).promise();
            }
            var self = this;
            return $.when(controller.reload()).then(function () {
                return self._refreshNow(controller);
            });
        },

        _activateControl: function (binding) {
            if (binding.global) {
                binding.widget.trigger_up("open_record", {
                    id: binding.localId,
                    mode: binding.type === "edit" ? "edit" : "readonly",
                });
            } else {
                binding.$element.trigger("click");
            }
            return $.when();
        },

        _waitForSnapshotChange: function (snapshotId) {
            return this._waitForChangedSnapshot(snapshotId, false);
        },

        _waitForInteractiveSnapshotChange: function (snapshotId) {
            return this._waitForChangedSnapshot(snapshotId, true);
        },

        _waitForChangedSnapshot: function (snapshotId, interactive) {
            var deferred = $.Deferred();
            var self = this;
            if (this._snapshot.snapshotId !== snapshotId &&
                    (!interactive || this._snapshot.interactive)) {
                return $.when(Adapter.clone(this._snapshot));
            }
            var waiter = {
                snapshotId: snapshotId,
                interactive: interactive,
                resolve: deferred.resolve.bind(deferred),
            };
            waiter.timer = setTimeout(function () {
                self._snapshotWaiters = _.without(self._snapshotWaiters, waiter);
                deferred.resolve(Adapter.clone(self._snapshot));
            }, 2500);
            this._snapshotWaiters.push(waiter);
            return deferred.promise();
        },

        _commandResult: function (ok, call, code, payload, snapshot) {
            return _.extend({
                ok: !!ok,
                operation: call && call.tool || "odoo.unknown",
                code: code,
                snapshotId: snapshot.snapshotId,
                hostRevision: snapshot.hostRevision,
                retryable: code === "stale_snapshot",
                snapshot: Adapter.clone(snapshot),
            }, payload || {});
        },
    });

    core.serviceRegistry.add("agui_host", AguiHostService);

    function afterControllerChange(controller, result, immediate, generation, onSuccess) {
        return $.when(result).then(function (value) {
            if (_.isFunction(onSuccess)) {
                onSuccess();
            }
            safeTrigger(controller, immediate, generation);
            return value;
        }, function () {
            var rejected = $.Deferred();
            var rejectionArgs = arguments;
            safeTrigger(controller, immediate, generation);
            rejected.reject.apply(rejected, rejectionArgs);
            return rejected.promise();
        });
    }

    viewDialogs.FormViewDialog.include({
        init: function (parent, options) {
            var self = this;
            options = _.extend({}, options || {});
            var onSaved = options.on_saved;
            if (options.shouldSaveLocally && _.isFunction(onSaved)) {
                options.on_saved = function () {
                    self.__aguiHostOnSaved = $.when(onSaved.apply(this, arguments));
                    return self.__aguiHostOnSaved;
                };
            }
            return this._super(parent, options);
        },
        open: function () {
            var self = this;
            var localX2Many = !!(this.shouldSaveLocally && this.model && this.parentID);
            if (localX2Many) {
                this.__aguiHostX2ManyDialog = true;
                bus.trigger("agui_host:form_view_transition", {
                    phase: "begin", dialog: this,
                });
            }
            var result = this._super.apply(this, arguments);
            if (localX2Many) {
                this.opened().then(function () {
                    if (!self.isDestroyed() && self.form_view) {
                        bus.trigger("agui_host:form_view_transition", {
                            phase: "ready", dialog: self, controller: self.form_view,
                        });
                    }
                });
            }
            return result;
        },
        destroy: function () {
            if (this.__aguiHostX2ManyDialog && !this.__aguiHostEndPublished) {
                this.__aguiHostEndPublished = true;
                bus.trigger("agui_host:form_view_transition", {
                    phase: "end", dialog: this,
                });
            }
            return this._super.apply(this, arguments);
        },
    });

    FormController.include({
        _confirmChange: function () {
            var generation = this.__aguiHostGeneration;
            var fields = arguments[1] || [];
            return afterControllerChange(
                this, this._super.apply(this, arguments), false, generation,
                updateDirtyFields.bind(null, this, fields)
            );
        },
        saveRecord: function () {
            var generation = this.__aguiHostGeneration;
            return afterControllerChange(
                this, this._super.apply(this, arguments), true, generation,
                clearDirtyFields.bind(null, this)
            );
        },
        discardChanges: function () {
            var generation = this.__aguiHostGeneration;
            return afterControllerChange(
                this, this._super.apply(this, arguments), true, generation,
                clearDirtyFields.bind(null, this)
            );
        },
        update: function () {
            var generation = this.__aguiHostGeneration;
            return afterControllerChange(this, this._super.apply(this, arguments), true, generation);
        },
        destroy: function () {
            safeTrigger(this, true, this.__aguiHostGeneration);
            bus.trigger("agui_host:controller_destroyed", {
                controller: this,
                generation: this.__aguiHostGeneration,
            });
            return this._super.apply(this, arguments);
        },
    });

    ListController.include({
        update: function () {
            var generation = this.__aguiHostGeneration;
            return afterControllerChange(this, this._super.apply(this, arguments), true, generation);
        },
        _onSelectionChanged: function () {
            var result = this._super.apply(this, arguments);
            safeTrigger(this, false, this.__aguiHostGeneration);
            return result;
        },
        destroy: function () {
            bus.trigger("agui_host:controller_destroyed", {
                controller: this,
                generation: this.__aguiHostGeneration,
            });
            return this._super.apply(this, arguments);
        },
    });

    KanbanController.include({
        update: function () {
            var generation = this.__aguiHostGeneration;
            return afterControllerChange(this, this._super.apply(this, arguments), true, generation);
        },
        destroy: function () {
            bus.trigger("agui_host:controller_destroyed", {
                controller: this,
                generation: this.__aguiHostGeneration,
            });
            return this._super.apply(this, arguments);
        },
    });

    WebClient.include({
        instanciate_menu_widgets: function () {
            var self = this;
            return $.when(this._super.apply(this, arguments)).then(function (value) {
                try {
                    self.call("agui_host", "configureNavigation", self, self.menu_data);
                } catch (error) {
                    if (typeof console !== "undefined" && console.warn) {
                        console.warn("AG-UI menu catalog sync failed", error);
                    }
                }
                return value;
            });
        },
        current_action_updated: function (action, descriptor) {
            var result = this._super.apply(this, arguments);
            var serviceDescriptor = _.extend({}, descriptor || {}, {
                __actionManager: this.action_manager,
            });
            try {
                this.call("agui_host", "setCurrentController", action, serviceDescriptor);
            } catch (error) {
                // Chat integration cannot break the WebClient action lifecycle.
            }
            return result;
        },
    });

    return AguiHostService;
});
