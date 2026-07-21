odoo.define("agui_chat.tests.host", function (require) {
    "use strict";

    var core = require("web.core");
    var Adapter = require("agui_chat.model_adapter");
    var ChatBridge = require("agui_chat.host_bridge");
    var Commands = require("agui_chat.command_registry");
    var HostService = require("agui_chat.host_service");

    function fakeController(options) {
        options = options || {};
        var record = {
            id: "data-1",
            model: "res.partner",
            res_id: 7,
            data: {
                name: "Acme",
                partner_id: {id: 5, display_name: "Current Partner"},
                secret_token: "hidden",
                tag_ids: options.tagIds === undefined ? [{id: 2}, {id: 3}] : options.tagIds,
            },
            context: {},
            domain: [],
            evalModifiers: function (modifiers) { return modifiers || {}; },
            getDomain: function () { return [["company_id", "=", 1]]; },
            getContext: function () { return {company_id: 1}; },
        };
        var raw = _.extend({}, record, {
            fields: {
                name: {type: "char", string: "Name", readonly: true, required: true},
                partner_id: {type: "many2one", string: "Partner", relation: "res.partner"},
                secret_token: {type: "char", string: "Secret"},
                tag_ids: {type: "many2many", relation: "res.partner.category"},
                line_ids: {type: "one2many", relation: "res.partner"},
                image: {type: "binary"},
            },
            fieldsInfo: {
                form: {
                    name: {
                        readonly: "0", required: "0", invisible: "0", modifiers: {},
                    },
                    partner_id: {
                        string: "Current View Partner",
                        modifiers: {},
                        domain: "[(\'company_id\', \'=\', company_id)]",
                    },
                    secret_token: {modifiers: {}},
                    tag_ids: {modifiers: {}},
                    line_ids: {
                        modifiers: {readonly: true, required: true, invisible: true},
                    },
                    image: {modifiers: {}},
                },
            },
            _changes: options.changes || {},
        });
        var controller = {
            handle: "data-1",
            mode: options.mode || "edit",
            model: {
                get: function (handle, getOptions) {
                    if (handle !== "data-1") {
                        throw new Error("unexpected handle");
                    }
                    return getOptions && getOptions.raw ? raw : record;
                },
            },
            _applyChanges: options.applyChanges || function () { return $.when(); },
            _rpc: options.rpc || function () { return $.when([]); },
            renderer: {
                canBeSaved: options.canBeSaved || function () { return true; },
            },
        };
        controller.is_action_enabled = function (action) {
            return action === "edit" && options.editEnabled !== false;
        };
        controller._setMode = options.setMode || function (mode) {
            controller.mode = mode;
            return $.when();
        };
        controller.saveRecord = options.saveRecord || function () { return $.when([]); };
        return controller;
    }

    function snapshot(controller) {
        return Adapter.buildSnapshot({
            controller: controller,
            controllerId: "controller-1",
            viewType: "form",
            action: {id: 1},
            menu: false,
            hostRevision: 1,
            snapshotId: "snapshot-1",
            surface: "dock",
            sensitiveFields: [],
        });
    }

    QUnit.module("agui_chat v2 host adapter");

    QUnit.test("host bridge forwards the Odoo session CSRF token", function (assert) {
        var bridge = new ChatBridge.HostBridge({
            call: function (_service, method) {
                if (method === "getMenuCatalog") {
                    return {
                        catalogId: "catalog", catalogRevision: 1, capturedAt: "now",
                        ready: true, totalCount: 0, entries: [],
                    };
                }
                throw new Error("Unexpected host call: " + method);
            },
        });
        bridge.config = {limits: {}, agent: {}};

        var props = bridge.mountProps({protocol: "agui.odoo.v2"}, "dock");

        assert.strictEqual(props.csrfToken, core.csrf_token);
    });

    QUnit.test("host bridge sends bounded One2many preview requests", function (assert) {
        assert.expect(2);
        var bridge = new ChatBridge.HostBridge({call: function () { return $.when(); }});
        bridge._rpc = function (route, values) {
            assert.strictEqual(route, "/agui_chat_import/preview");
            assert.deepEqual(values, {
                jobToken: "job-1",
                expectedRevision: 3,
                parseOptions: {encoding: "utf-8", separator: ",", quoting: '"'},
                mapping: {"产品": "name"},
                finalize: true,
            });
            return $.when({ok: true});
        };

        bridge.publicApi().previewX2ManyImport({
            jobToken: "job-1",
            expectedRevision: 3,
            parseOptions: {encoding: "utf-8", separator: ",", quoting: '"'},
            mapping: {"产品": "name"},
            finalize: true,
        });
    });

    QUnit.test("chat dock stays interactive above modal backdrops", function (assert) {
        assert.expect(2);
        var $manager = $(
            "<div class='o_agui_chat_surface_manager o_agui_chat_enabled " +
            "o_agui_chat_dock_open o_agui_chat_dock_right'>" +
            "<button class='o_agui_chat_dock_toggle'></button>" +
            "<div class='o_agui_chat_dock'></div></div>"
        ).appendTo(document.body);
        var $backdrop = $("<div class='modal-backdrop show'></div>").appendTo(document.body);
        var backdropLevel = parseInt(window.getComputedStyle($backdrop[0]).zIndex, 10);
        var dockLevel = parseInt(window.getComputedStyle($manager.find(".o_agui_chat_dock")[0]).zIndex, 10);
        var toggleLevel = parseInt(window.getComputedStyle($manager.find(".o_agui_chat_dock_toggle")[0]).zIndex, 10);

        assert.ok(dockLevel > backdropLevel, "打开的聊天面板位于 modal backdrop 之上");
        assert.ok(toggleLevel > backdropLevel, "聊天入口位于 modal backdrop 之上");
        $backdrop.remove();
        $manager.remove();
    });

    QUnit.test("menu catalog refreshes when WebClient menu data arrives late", function (assert) {
        assert.expect(4);
        var webClient = {menu_data: null};
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = null;
        service._menuOptions = [];

        service.configureNavigation(webClient, null);
        var pending = service.getMenuCatalog();
        assert.notOk(pending.ready);
        assert.deepEqual(pending.entries, []);

        webClient.menu_data = {
            children: [{
                id: 90,
                name: "员工",
                action: "ir.actions.act_window,115",
                children: [],
            }],
        };
        var ready = service.getMenuCatalog();
        assert.ok(ready.ready);
        assert.deepEqual(ready.entries, [{
            menuId: 90,
            actionId: 115,
            name: "员工",
            path: ["员工"],
            fullPath: "员工",
        }]);
    });

    QUnit.test("menu catalog keeps native action leaves with their full paths", function (assert) {
        assert.expect(4);
        var menuData = {
            children: [{
                id: 90, name: "员工", action: false, children: [{
                    id: 91, name: "员工", action: "ir.actions.act_window,115",
                    children: [],
                }],
            }, {
                id: 100, name: "费用报销", action: false,
                children: [{
                    id: 101, name: "费用报销", action: false, children: [{
                        id: 1444, name: "报销单查询",
                        action: "ir.actions.act_window,404", children: [],
                    }],
                }, {
                    id: 102, name: "单据查询", action: false, children: [{
                        id: 1265, name: "报销单查询",
                        action: "ir.actions.act_window,404", children: [],
                    }],
                }],
            }],
        };
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = null;
        service._menuOptions = [];
        service._menuSubscribers = [];

        var catalog = service.configureNavigation({menu_data: menuData}, menuData);

        assert.strictEqual(catalog.entries.length, 3);
        assert.strictEqual(catalog.entries[0].fullPath, "员工 / 员工");
        assert.deepEqual(_.pluck(catalog.entries, "menuId"), [91, 1444, 1265]);
        assert.deepEqual(_.pluck(catalog.entries, "fullPath"), [
            "员工 / 员工",
            "费用报销 / 费用报销 / 报销单查询",
            "费用报销 / 单据查询 / 报销单查询",
        ]);
    });

    QUnit.test("menu catalog opens only safe native action types", function (assert) {
        assert.expect(5);
        var done = assert.async();
        var opened;
        var menuData = {
            children: [
                {id: 1, name: "窗口", action: "ir.actions.act_window,42", children: []},
                {id: 2, name: "客户端", action: "ir.actions.client,43", children: []},
                {id: 3, name: "服务端", action: "ir.actions.server,44", children: []},
                {id: 4, name: "报表", action: "ir.actions.report,45", children: []},
                {id: 5, name: "网址", action: "ir.actions.act_url,46", children: []},
                {id: 6, name: "畸形", action: "ir.actions.client,47extra", children: []},
            ],
        };
        var webClient = {
            menu_data: menuData,
            do_action: function (actionId, options) {
                opened = {actionId: actionId, options: options};
                return $.when();
            },
        };
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = null;
        service._menuOptions = [];
        service._menuSubscribers = [];

        var catalog = service.configureNavigation(webClient, menuData);

        assert.deepEqual(_.pluck(catalog.entries, "menuId"), [1, 2]);
        assert.deepEqual(_.pluck(catalog.entries, "actionId"), [42, 43]);
        service._openMenu(2, 43).then(function (menu) {
            assert.strictEqual(opened.actionId, 43);
            assert.deepEqual(opened.options, {clear_breadcrumbs: true, action_menu_id: 2});
            assert.strictEqual(menu.menuId, 2);
            done();
        });
    });

    QUnit.test("menu catalog version is stable and in-place changes do not publish a page snapshot", function (assert) {
        assert.expect(8);
        var menuData = {
            children: [{
                id: 90, name: "员工", action: "ir.actions.act_window,115",
                children: [],
            }],
        };
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = null;
        service._menuOptions = [];
        service._menuSubscribers = [];
        service._menuSearch = {menuId: 90};
        service._snapshot = {snapshotId: "page", hostRevision: 7};
        service.configureNavigation({menu_data: menuData}, menuData);
        var first = service.getMenuCatalog();
        var stable = service.getMenuCatalog();

        assert.strictEqual(stable.catalogId, first.catalogId);
        assert.strictEqual(stable.catalogRevision, first.catalogRevision);
        assert.strictEqual(service._snapshot.snapshotId, "page");
        assert.strictEqual(service._snapshot.hostRevision, 7);

        var published;
        service.subscribeMenuCatalog({}, function (catalog) { published = catalog; });
        menuData.children[0].name = "员工档案";
        var changed = service.getMenuCatalog();

        assert.notEqual(changed.catalogId, first.catalogId);
        assert.strictEqual(changed.catalogRevision, first.catalogRevision + 1);
        assert.strictEqual(published.entries[0].fullPath, "员工档案");
        assert.notOk(service._menuSearch, "catalog changes invalidate search evidence");
    });

    QUnit.test("menu search prefers exact matches and falls back to contains matches", function (assert) {
        assert.expect(11);
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = {
            children: [{
                id: 8,
                name: "费用报销",
                action: "",
                children: [{
                    id: 9,
                    name: "报销单查询",
                    action: "ir.actions.act_window,42",
                    children: [],
                }, {
                    id: 10,
                    name: "报销单查询归档",
                    action: "ir.actions.act_window,43",
                    children: [],
                }],
            }],
        };
        service._menuOptions = [];
        service._menuSubscribers = [];
        service._snapshot = {snapshotId: "page", hostRevision: 1};

        var exact = service.searchMenus("打开报销单查询", {threadId: "thread", runId: "run"});
        assert.strictEqual(exact.matchType, "exact");
        assert.strictEqual(exact.matchCount, 1);
        assert.notOk(exact.truncated);
        assert.strictEqual(exact.candidates.length, 1);
        assert.strictEqual(exact.candidates[0].menuId, 9);
        assert.strictEqual(exact.candidates[0].actionId, 42);

        var contains = service.searchMenus("报销", {threadId: "thread", runId: "run"});
        assert.strictEqual(contains.matchType, "contains");
        assert.strictEqual(contains.matchCount, 2);
        assert.notOk(contains.truncated);
        assert.deepEqual(_.pluck(contains.candidates, "menuId"), [9, 10]);
        assert.notOk(service._menuSearch, "ambiguous results cannot authorize navigation");
    });

    QUnit.test("duplicate menu leaves remain ambiguous", function (assert) {
        assert.expect(3);
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = {
            children: [{
                id: 1, name: "费用", action: "", children: [{
                    id: 2, name: "查询", action: "ir.actions.act_window,42",
                    children: [],
                }],
            }, {
                id: 3, name: "采购", action: "", children: [{
                    id: 4, name: "查询", action: "ir.actions.act_window,43",
                    children: [],
                }],
            }],
        };
        service._menuOptions = [];
        service._menuSubscribers = [];
        service._snapshot = {snapshotId: "page", hostRevision: 1};

        var result = service.searchMenus("查询", {threadId: "thread", runId: "run"});

        assert.strictEqual(result.matchType, "exact");
        assert.strictEqual(result.matchCount, 2);
        assert.notOk(service._menuSearch);
    });

    QUnit.test("opening a menu rejects a stale action id", function (assert) {
        assert.expect(2);
        var opened = false;
        var service = Object.create(HostService.prototype);
        service._webClient = {
            menu_data: {
                children: [{
                    id: 9,
                    name: "报销单查询",
                    action: "ir.actions.act_window,42",
                    children: [],
                }],
            },
            do_action: function () { opened = true; },
        };
        service._menuData = service._webClient.menu_data;
        service._menuOptions = [];
        service._menuSubscribers = [];

        try {
            service._openMenu(9, 43);
            assert.ok(false, "stale action id must be rejected");
        } catch (error) {
            assert.strictEqual(error.code, "menu_action_conflict");
            assert.notOk(opened);
        }
    });

    QUnit.test("menu opening requires a unique search in the same run", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var service = Object.create(HostService.prototype);
        service._snapshot = {
            snapshotId: "page", hostRevision: 1, interactive: true,
        };
        service._webClient = null;
        service._menuData = {
            children: [{
                id: 9,
                name: "报销单查询",
                action: "ir.actions.act_window,42",
                children: [],
            }],
        };
        service._menuOptions = [];
        service._menuSubscribers = [];
        service._menuSearch = false;
        var catalog = service.getMenuCatalog();
        var call = {
            id: "open-menu",
            tool: "odoo.open_menu",
            arguments: {
                target: {
                    snapshotId: "page", hostRevision: 1,
                    catalogId: catalog.catalogId, catalogRevision: catalog.catalogRevision,
                },
                menuId: 9,
                actionId: 42,
            },
            context: {threadId: "thread-1", runId: "run-1"},
        };

        service.prepareHostCommand(call).then(function (result) {
            assert.strictEqual(result.code, "menu_search_required");
            service.searchMenus("报销单查询", {threadId: "thread-1", runId: "run-1"});
            return service.prepareHostCommand(_.extend({}, call, {
                context: {threadId: "thread-1", runId: "run-2"},
            }));
        }).then(function (result) {
            assert.strictEqual(result.code, "menu_search_required");
            return service.prepareHostCommand(call);
        }).then(function (result) {
            assert.ok(result.ok);
            done();
        });
    });

    QUnit.test("stale menu targets and changed actions fail closed", function (assert) {
        assert.expect(2);
        var done = assert.async();
        var menuData = {
            children: [{
                id: 9, name: "报销单查询", action: "ir.actions.act_window,42",
                children: [],
            }],
        };
        var service = Object.create(HostService.prototype);
        service._snapshot = {snapshotId: "page", hostRevision: 1, interactive: true};
        service._webClient = {menu_data: menuData};
        service._menuData = menuData;
        service._menuOptions = [];
        service._menuSubscribers = [];
        service._menuSearch = false;
        var catalog = service.getMenuCatalog();
        var call = {
            id: "stale-menu", tool: "odoo.open_menu",
            arguments: {
                target: {
                    snapshotId: "page", hostRevision: 1,
                    catalogId: catalog.catalogId, catalogRevision: catalog.catalogRevision,
                },
                menuId: 9, actionId: 42,
            },
            context: {threadId: "thread", runId: "run"},
        };

        menuData.children[0].name = "报销查询";
        service.prepareHostCommand(call).then(function (result) {
            assert.strictEqual(result.code, "stale_menu_catalog");
            var latest = service.getMenuCatalog();
            call.arguments.target.catalogId = latest.catalogId;
            call.arguments.target.catalogRevision = latest.catalogRevision;
            menuData.children[0].action = "ir.actions.act_window,43";
            return service.prepareHostCommand(call);
        }).then(function (result) {
            assert.strictEqual(result.code, "menu_action_conflict");
            done();
        });
    });

    QUnit.test("snapshot is bounded to view fields and redacts secrets", function (assert) {
        assert.expect(12);
        var state = snapshot(fakeController());
        assert.strictEqual(state.protocol, "agui.odoo.v2");
        assert.strictEqual(state.fields.partner_id.string, "Current View Partner");
        assert.notOk(state.fields.name.readonly, "evaluated modifiers override model readonly");
        assert.notOk(state.fields.name.required, "evaluated modifiers override model required");
        assert.notOk(state.fields.name.invisible, "XML string zero is false");
        assert.ok(state.fields.line_ids.readonly, "evaluated readonly is exported");
        assert.ok(state.fields.line_ids.required, "evaluated required is exported");
        assert.ok(state.fields.line_ids.invisible, "evaluated invisible is exported");
        assert.strictEqual(state.record.values.secret_token, "[redacted]");
        assert.deepEqual(state.record.values.tag_ids, {ids: [2, 3], count: 2});
        assert.strictEqual(state.fields.image.type, "binary", "binary field metadata is preserved");
        assert.notOk(_.has(state.record.values, "image"), "binary field values are omitted");
    });

    QUnit.test("form fields and one2many capabilities have no field count limit", function (assert) {
        assert.expect(10);
        var controller = fakeController();
        var record = controller.model.get("data-1");
        var raw = controller.model.get("data-1", {raw: true});
        _.each(_.range(135), function (index) {
            var name = "extra_field_" + index;
            record.data[name] = "value-" + index;
            raw.fields[name] = {type: "char", string: "扩展字段 " + index};
            raw.fieldsInfo.form[name] = {modifiers: {}};
        });
        _.each(["expense_report_lines", "summary_line_ids"], function (name) {
            record.data[name] = false;
            raw.fields[name] = {
                type: "one2many", string: name, relation: "res.partner",
                relation_field: "parent_id",
            };
            raw.fieldsInfo.form[name] = {modifiers: {}};
        });

        var state = snapshot(controller);
        var expense = _.findWhere(state.capabilities.x2many, {field: "expense_report_lines"});
        var summary = _.findWhere(state.capabilities.x2many, {field: "summary_line_ids"});
        assert.strictEqual(_.keys(state.fields).length, 143);
        assert.ok(state.fields.extra_field_134, "原上限后的普通字段仍可发现");
        assert.ok(state.fields.expense_report_lines, "原上限后的 One2many 元信息仍可发现");
        assert.ok(expense, "expense_report_lines 进入统一 One2many 能力");
        assert.ok(summary, "summary_line_ids 进入统一 One2many 能力");
        assert.strictEqual(expense.relationField, "parent_id");
        assert.strictEqual(expense.childFieldCount, 0);
        assert.strictEqual(expense.fieldToken, false);
        assert.strictEqual(expense.unsupportedReason, "child_schema_unavailable");
        assert.notOk(state.capabilities.x2manyFields, "不新增 x2manyFields 能力");
    });

    QUnit.test("one2many child schema metadata has no field count limit", function (assert) {
        assert.expect(6);
        var controller = fakeController();
        var record = controller.model.get("data-1");
        var raw = controller.model.get("data-1", {raw: true});
        var childFields = {};
        var formInfos = {};
        var listInfos = {};
        _.each(_.range(135), function (index) {
            var name = "child_field_" + index;
            childFields[name] = {type: "char", string: "子字段 " + index};
            formInfos[name] = {modifiers: {}};
            listInfos[name] = {modifiers: {}};
        });
        var formView = {
            type: "form", arch: {attrs: {}}, fields: childFields,
            fieldsInfo: {form: formInfos},
        };
        var listView = {
            type: "list", arch: {attrs: {}}, fields: childFields,
            fieldsInfo: {list: listInfos},
        };
        record.data.expense_report_lines = {
            id: "expense-list", type: "list", model: "res.partner.line",
            data: [], res_ids: [], count: 0,
        };
        raw.fields.expense_report_lines = {
            type: "one2many", string: "报销明细", relation: "res.partner.line",
            relation_field: "parent_id",
        };
        raw.fieldsInfo.form.expense_report_lines = {
            modifiers: {}, views: {form: formView, list: listView},
        };
        controller.renderer.allFieldWidgets = {"data-1": [{
            name: "expense_report_lines",
            field: raw.fields.expense_report_lines,
        }]};

        var state = snapshot(controller);
        var capability = _.findWhere(state.capabilities.x2many, {
            field: "expense_report_lines",
        });
        assert.strictEqual(state.fields.expense_report_lines.childFieldCount, 135);
        assert.strictEqual(capability.childFieldCount, 135);
        assert.ok(/^[a-f0-9]{64}$/.test(capability.schemaHash));
        assert.notOk(state.fields.expense_report_lines.childFields,
            "父快照不重复发送完整子字段映射");
        assert.strictEqual(capability.unsupportedReason, "unsupported_widget");
        assert.deepEqual(capability.operations, {create: false, update: false, delete: false});
    });

    QUnit.test("one2many import uses the unified capability schema hash", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var binding = {fieldName: "expense_report_lines"};
        var state = {
            interactive: true,
            controller: {viewType: "form"},
            record: {model: "expense.report", resId: 9},
            capabilities: {x2many: [{
                field: "expense_report_lines",
                schemaHash: "schema-hash-135",
                operations: {create: true, update: true, delete: true},
            }]},
        };
        var context = {
            getSnapshot: function () { return state; },
            getController: function () { return {}; },
            hasUnsavedChanges: function () { return false; },
            resolveToken: function (token, kind) {
                assert.strictEqual(token + ":" + kind, "field-token:x2many_field");
                return binding;
            },
            validateToken: function (candidate) { return candidate === binding; },
            prepareX2ManyImport: function (payload) {
                assert.deepEqual(payload, {
                    parent_model: "expense.report",
                    parent_id: 9,
                    field_name: "expense_report_lines",
                    attachment_id: "attachment-7",
                    schema_hash: "schema-hash-135",
                });
                return $.when({ok: true, jobToken: "job-token"});
            },
        };
        Commands.execute(context, {
            tool: "odoo.prepare_x2many_import",
            authorizationId: "import-authorization",
            arguments: {fieldToken: "field-token", attachmentId: "attachment-7"},
        }).then(function (result) {
            assert.strictEqual(result.jobToken, "job-token");
            done();
        });
    });

    QUnit.test("one field modifier failure does not invalidate the snapshot", function (assert) {
        assert.expect(4);
        var controller = fakeController();
        var record = controller.model.get("data-1");
        var raw = controller.model.get("data-1", {raw: true});
        record.data.broken_field = "仍需可见";
        raw.fields.broken_field = {type: "char", string: "异常字段"};
        raw.fieldsInfo.form.broken_field = {modifiers: {explode: true}};
        record.evalModifiers = function (modifiers) {
            if (modifiers && modifiers.explode) {
                throw new Error("modifier parse failed");
            }
            return modifiers || {};
        };

        var state = snapshot(controller);
        assert.strictEqual(state.fields.broken_field.string, "异常字段");
        assert.strictEqual(state.fields.broken_field.type, "char");
        assert.strictEqual(
            state.fields.broken_field.unsupportedReason, "modifier_evaluation_failed"
        );
        assert.strictEqual(state.record.values.broken_field, "仍需可见");
    });

    QUnit.test("patch preview uses live labels, relation display values, and redaction", function (assert) {
        assert.expect(8);
        var controller = fakeController();
        var state = snapshot(controller);
        var target = Adapter.targetFromSnapshot(state);
        var scalar = Adapter.buildPatchPreview(controller, state, {
            target: target, patch: {name: "New Acme"},
        });
        var relation = Adapter.buildPatchPreview(controller, state, {
            target: target, patch: {partner_id: 9},
        });
        var sensitive = Adapter.buildPatchPreview(controller, state, {
            target: target, patch: {secret_token: "new secret"},
        });
        assert.strictEqual(scalar.changes[0].label, "Name");
        assert.strictEqual(scalar.changes[0].oldValue, "Acme");
        assert.strictEqual(scalar.changes[0].newValue, "New Acme");
        assert.strictEqual(relation.changes[0].oldValue.displayName, "Current Partner");
        assert.strictEqual(relation.changes[0].newValue.displayName, "#9");
        assert.strictEqual(sensitive.changes[0].oldValue, "[redacted]");
        assert.strictEqual(sensitive.changes[0].newValue, "[redacted]");
        assert.strictEqual(sensitive.rejected[0].code, "field_sensitive");
    });

    QUnit.test("JSON string patch is normalized before preview and apply", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var controller = fakeController({
            applyChanges: function (_handle, changes) {
                assert.strictEqual(changes.name, "String patch");
                return $.when();
            },
        });
        var state = snapshot(controller);
        var args = {patch: JSON.stringify([{field: "name", value: "String patch"}])};
        var preview = Adapter.buildPatchPreview(controller, state, args);
        assert.strictEqual(preview.changes[0].newValue, "String patch");
        Adapter.applyPatch(controller, state, args).then(function (result) {
            assert.deepEqual(result.applied, ["name"]);
            done();
        });
    });

    QUnit.test("undo validation refuses changed values and dirty forms", function (assert) {
        assert.expect(3);
        var controller = fakeController();
        var state = snapshot(controller);
        assert.ok(Adapter.validateUndo(controller, state, {
            patch: {name: "Before"}, expected: {name: "Acme"},
        }).ok);
        assert.strictEqual(Adapter.validateUndo(controller, state, {
            patch: {name: "Before"}, expected: {name: "Changed elsewhere"},
        }).code, "undo_conflict");
        controller = fakeController({changes: {name: "Local edit"}});
        assert.strictEqual(Adapter.validateUndo(controller, snapshot(controller), {
            patch: {name: "Before"}, expected: {name: "Acme"},
        }).code, "undo_conflict");
    });

    QUnit.test("business tools use the explicit write gate and server-bound execution", function (assert) {
        assert.expect(20);
        var done = assert.async();
        var command = "odoo.business.test_document.confirm";
        var call = {
            id: "business-call",
            tool: command,
            arguments: {
                model: "agui.chat.test.document",
                document_id: 7,
                expected_state: "draft",
            },
            context: {
                requestId: "request-business",
                runId: "run-business",
                threadId: "thread-business",
            },
        };
        var businessTool = {
            name: command,
            description: "确认测试单据",
            parameters: {type: "object"},
            accessLevel: "write",
        };
        var readBusinessTool = {
            name: "odoo.business.test_document.read",
            description: "读取测试单据",
            parameters: {type: "object"},
            accessLevel: "read",
        };
        var stageTool = {
            name: "odoo.stage_current_form",
            description: "暂存",
            parameters: {type: "object"},
        };
        var bridge = new ChatBridge.HostBridge({
            call: function () {
                assert.ok(false, "business tools must not execute through the page host service");
            },
        });
        bridge.config = {
            host_tools_enabled: true,
            write_tools_enabled: false,
            enabled_commands: ["odoo.stage_current_form"],
            business_tools: [businessTool, readBusinessTool],
        };
        assert.deepEqual(
            _.pluck(bridge.setCatalog([stageTool]), "name"),
            [readBusinessTool.name]
        );
        assert.notOk(bridge.allowedTools[command]);
        assert.strictEqual(bridge.allowedTools[readBusinessTool.name], "business");
        assert.notOk(bridge.allowedTools["odoo.stage_current_form"]);

        bridge.config.write_tools_enabled = true;
        assert.deepEqual(
            _.pluck(bridge.setCatalog([stageTool]), "name"),
            ["odoo.stage_current_form", command, readBusinessTool.name]
        );
        assert.strictEqual(bridge.allowedTools[command], "business");
        assert.strictEqual(bridge.allowedTools["odoo.stage_current_form"], "host");

        var routes = [];
        bridge._rpc = function (route, values) {
            routes.push(route);
            if (route === "/agui_chat/business/prepare") {
                assert.deepEqual(values.call.arguments, call.arguments);
                return $.when({
                    ok: false,
                    needs_confirmation: true,
                    authorization_id: "business-authorization",
                    code: "confirmation_required",
                });
            }
            if (route === "/agui_chat/host_command") {
                assert.strictEqual(values.phase, "confirm");
                assert.ok(values.approved);
                return $.when({
                    ok: true,
                    authorization_id: "business-authorization",
                    bound_call: {
                        id: call.id,
                        tool: command,
                        arguments: call.arguments,
                        context: call.context,
                    },
                });
            }
            assert.strictEqual(values.command_name, command);
            assert.deepEqual(values.payload, call.arguments);
            assert.strictEqual(values.authorization_token, "business-authorization");
            assert.strictEqual(values.idempotency_key, "business-authorization");
            return $.when({ok: true, result: {state: "confirmed"}});
        };

        bridge.executeTool(call).then(function (decision) {
            assert.ok(decision.needs_confirmation);
            assert.strictEqual(decision.authorization_id, "business-authorization");
            return bridge.confirmTool(call, decision.authorization_id, true);
        }).then(function (result) {
            assert.ok(result.ok);
            assert.strictEqual(result.operation, command);
            assert.strictEqual(result.result.state, "confirmed");
            assert.deepEqual(routes, [
                "/agui_chat/business/prepare",
                "/agui_chat/host_command",
                "/agui_chat/business/execute",
            ]);
            done();
        });
    });

    QUnit.test("current list reports bind full BasicModel state before server preparation", function (assert) {
        assert.expect(10);
        var done = assert.async();
        var command = "odoo.business.report.filters";
        var target = {
            snapshotId: "snapshot-list", hostRevision: 3,
            controllerId: "controller-list", dataPointId: "data-list",
            model: "res.partner", resId: false,
        };
        var sourceState = {
            target: target, viewType: "list", menuId: 7, actionId: 11,
            domain: [["name", "ilike", "仅绑定接口可见"]],
            context: {search_default_customer: 1}, groupBy: [], sort: ["-name"],
            selectedIds: [5, 8], scope: "selected", selectedCount: 2,
        };
        var bridge = new ChatBridge.HostBridge({
            call: function (service, method, value) {
                assert.strictEqual(service + ":" + method, "agui_host:getReportSourceState");
                assert.deepEqual(value, target);
                return sourceState;
            },
        });
        bridge.config = {
            host_tools_enabled: true,
            write_tools_enabled: false,
            enabled_commands: [],
            business_tools: [{
                name: command, parameters: {type: "object"}, accessLevel: "read",
            }],
        };
        bridge.setCatalog([]);
        var routes = [];
        bridge._rpc = function (route, values) {
            routes.push(route);
            if (route === "/agui_chat/report/source/bind") {
                assert.deepEqual(values.source.selectedIds, [5, 8]);
                assert.deepEqual(values.source.domain, sourceState.domain);
                assert.strictEqual(values.source.threadId, "thread-list");
                return $.when({ok: true, sourceHandle: "source-bound"});
            }
            if (route === "/agui_chat/business/prepare") {
                assert.deepEqual(values.call.arguments.source, {
                    kind: "current_view", sourceHandle: "source-bound",
                });
                assert.notOk(values.call.arguments.domain);
                return $.when({
                    ok: true,
                    authorization_id: "authorization-report",
                    bound_call: values.call,
                });
            }
            assert.strictEqual(values.payload.source.sourceHandle, "source-bound");
            return $.when({ok: true, result: {mode: "describe"}});
        };
        bridge.executeTool({
            id: "report-list", tool: command,
            arguments: {source: {kind: "current_view"}, target: target,
                mode: "describe", requests: [{}]},
            context: {requestId: "request-list", runId: "run-list", threadId: "thread-list"},
        }).then(function (result) {
            assert.ok(result.ok);
            assert.deepEqual(routes, [
                "/agui_chat/report/source/bind",
                "/agui_chat/business/prepare",
                "/agui_chat/business/execute",
            ]);
            done();
        });
    });

    QUnit.test("current list report source falls back to the matching snapshot query", function (assert) {
        assert.expect(4);
        var service = Object.create(HostService.prototype);
        var snapshot = {
            snapshotId: "snapshot-list", hostRevision: 3, interactive: true,
            controller: {
                controllerId: "controller-list", dataPointId: "data-list",
                actionId: 11, viewType: "list",
            },
            menu: {id: 7},
            selection: {
                model: "res.partner", ids: [],
                domain: [["name", "ilike", "快照筛选"]],
                context: {active_test: false},
            },
        };
        var controller = {
            handle: "data-list",
            model: {get: function () { return {orderedBy: [], groupedBy: []}; }},
            getSelectedIds: function () { return []; },
        };
        service.getSnapshot = function () { return snapshot; };
        service._resolveCurrentController = function () { return controller; };

        var result = service.getReportSourceState({
            snapshotId: "snapshot-list", hostRevision: 3,
            controllerId: "controller-list", dataPointId: "data-list",
            model: "res.partner", resId: false,
        });

        assert.deepEqual(result.domain, snapshot.selection.domain);
        assert.deepEqual(result.context, snapshot.selection.context);
        assert.strictEqual(result.scope, "domain");
        assert.strictEqual(result.selectedCount, 0);
    });

    QUnit.test("host bridge completes rejected undo conflicts", function (assert) {
        assert.expect(4);
        var done = assert.async();
        var completed;
        var bridge = new ChatBridge.HostBridge({
            call: function () {
                return $.Deferred().reject({
                    ok: false, code: "undo_conflict", error: "changed",
                }).promise();
            },
        });
        bridge._complete = function (authorizationId, result) {
            completed = {authorizationId: authorizationId, result: result};
            return $.when({ok: true});
        };

        bridge._executeBound({
            authorization_id: "undo-token",
            bound_call: {tool: "odoo.undo_current_form", arguments: {}},
        }, 0).then(function (result) {
            assert.strictEqual(completed.authorizationId, "undo-token");
            assert.strictEqual(completed.result.code, "undo_conflict");
            assert.strictEqual(result.code, "undo_conflict");
            assert.notOk(result.retryable);
            done();
        });
    });

    QUnit.test("host bridge retries result persistence once", function (assert) {
        assert.expect(4);
        var done = assert.async();
        var completions = 0;
        var bridge = new ChatBridge.HostBridge({
            call: function () { return $.when({ok: true, saved: true}); },
        });
        bridge._rpc = function (_route, values) {
            assert.strictEqual(values.phase, "complete");
            completions += 1;
            return $.when(completions === 1 ?
                {ok: false, code: "host_command_failed"} : {ok: true});
        };

        bridge._executeBound({
            authorization_id: "completion-retry",
            bound_call: {tool: "odoo.save_current_form", arguments: {}},
        }, 0).then(function (result) {
            assert.strictEqual(completions, 2);
            assert.ok(result.ok);
            done();
        });
    });

    QUnit.test("host bridge reports result persistence failure after two attempts", function (assert) {
        assert.expect(5);
        var done = assert.async();
        var completions = 0;
        var bridge = new ChatBridge.HostBridge({
            call: function () { return $.when({ok: true, saved: true}); },
        });
        bridge._rpc = function () {
            completions += 1;
            if (completions === 1) {
                return $.Deferred().reject({code: "network_error"}).promise();
            }
            return $.when({ok: false, code: "result_too_large"});
        };

        bridge._executeBound({
            authorization_id: "completion-failure",
            bound_call: {tool: "odoo.patch_current_form", arguments: {}},
        }, 0).then(function (result) {
            assert.strictEqual(completions, 2);
            assert.notOk(result.ok);
            assert.strictEqual(result.code, "result_persistence_failed");
            assert.strictEqual(result.persistence_code, "result_too_large");
            assert.notOk(result.retryable);
            done();
        });
    });

    QUnit.test("replayed patch restores its undo authorization", function (assert) {
        assert.expect(5);
        var done = assert.async();
        var phases = [];
        var bridge = new ChatBridge.HostBridge({call: function () { return $.when(); }});
        bridge._rpc = function (_route, values) {
            phases.push(values.phase);
            if (values.phase === "prepare") {
                return $.when({
                    ok: true,
                    authorization_id: "source-authorization",
                    replay_result: {
                        ok: true,
                        receipt: {undo: {available: true}},
                        undo_payload: {target: {}, patch: {name: "Before"}, expected: {name: "After"}},
                    },
                });
            }
            assert.strictEqual(values.authorization_id, "source-authorization");
            return $.when({
                ok: true,
                undo_authorization_id: "undo-authorization",
                expires_at: "2030-01-01 00:00:00",
            });
        };

        bridge._serverPrepare({tool: "odoo.patch_current_form"}, 0).then(function (result) {
            assert.deepEqual(phases, ["prepare", "undo_prepare"]);
            assert.notOk(result.undo_payload, "internal undo payload is not exposed");
            assert.ok(result.receipt.undo.available);
            assert.strictEqual(result.receipt.undo.authorization_id, "undo-authorization");
            done();
        });
    });

    QUnit.test("replayed patch keeps a consumed undo unavailable", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var bridge = new ChatBridge.HostBridge({call: function () { return $.when(); }});
        bridge._rpc = function () {
            return $.when({ok: true, replay_result: {ok: true, undone: true}});
        };

        bridge._withUndoReceipt({
            ok: true,
            receipt: {undo: {available: true}},
            undo_payload: {target: {}, patch: {name: "Before"}, expected: {name: "After"}},
        }, "source-authorization").then(function (result) {
            assert.notOk(result.undo_payload);
            assert.notOk(result.receipt.undo.available);
            assert.strictEqual(result.receipt.undo.status, "undone");
            done();
        });
    });

    QUnit.test("stale confirmation does not replace an executing authorization", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var prepareCalls = 0;
        var bridge = new ChatBridge.HostBridge({call: function () { return $.when(); }});
        bridge.allowedTools["odoo.patch_current_form"] = true;
        bridge._browserPrepare = function () {
            return $.when({
                ok: true,
                retried: true,
                call: {tool: "odoo.patch_current_form"},
            });
        };
        bridge._retireAuthorization = function (_operation, authorizationId) {
            assert.strictEqual(authorizationId, "old-authorization");
            return $.when({ok: false, code: "command_in_progress"});
        };
        bridge._serverPrepare = function () {
            prepareCalls += 1;
            return $.when({ok: true});
        };

        bridge.confirmTool({tool: "odoo.patch_current_form"}, "old-authorization", true).then(
            function (result) {
                assert.strictEqual(result.code, "command_in_progress");
                assert.strictEqual(prepareCalls, 0);
                done();
            }
        );
    });

    QUnit.test("snapshot compacts expanded ActionManager views", function (assert) {
        assert.expect(2);
        var controller = fakeController();
        var state = Adapter.buildSnapshot({
            controller: controller,
            controllerId: "controller-1",
            viewType: "form",
            action: {
                views: [
                    {viewID: 11, type: "list", fieldsView: {arch: Array(200001).join("x")}},
                    {viewID: 12, type: "form", Widget: {prototype: {large: Array(200001).join("y")}}},
                ],
            },
            menu: false,
            hostRevision: 1,
            snapshotId: "snapshot-compact-action",
            surface: "dock",
            sensitiveFields: [],
        });
        assert.deepEqual(state.action.views, [[11, "list"], [12, "form"]]);
        assert.ok(JSON.stringify(state).length < 10000, "expanded view definitions are not exported");
    });

    QUnit.test("any dirty field rejects the complete patch before _applyChanges", function (assert) {
        assert.expect(2);
        var done = assert.async();
        var applyCalled = false;
        var applyChanges = function () { applyCalled = true; return $.when(); };
        var controller = fakeController({changes: {name: "User edit"}, applyChanges: applyChanges});
        Adapter.applyPatch(controller, snapshot(controller), {
            patch: [
                {field: "name", value: "Agent edit"},
                {field: "line_ids", value: {operation: "create", values: {name: "Line"}}},
            ],
        }).then(function (result) {
            assert.deepEqual(_.pluck(result.rejected, "code"), ["dirty_conflict"]);
            assert.notOk(applyCalled, "no partial patch is applied");
            done();
        });
    });

    QUnit.test("a dirty field outside the patch still rejects the complete patch", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var applyCalled = false;
        var controller = fakeController({
            changes: {partner_id: {id: 9}},
            applyChanges: function () { applyCalled = true; return $.when(); },
        });
        Adapter.applyPatch(controller, snapshot(controller), {
            patch: {name: "Agent edit"},
        }).then(function (result) {
            assert.strictEqual(result.rejected[0].code, "dirty_conflict");
            assert.deepEqual(result.rejected[0].fields, ["partner_id"]);
            assert.notOk(applyCalled, "unrelated user changes are not saved by the patch");
            done();
        });
    });

    QUnit.test("relation search uses the live domain and context", function (assert) {
        assert.expect(6);
        var done = assert.async();
        var request;
        var requestOptions;
        var controller = fakeController({
            rpc: function (params, options) {
                request = params;
                requestOptions = options;
                return $.when([[9, "Shanghai Partner"]]);
            },
        });
        Adapter.searchRelation(controller, snapshot(controller), {
            field: "partner_id", query: "Shanghai Partner", operation: "set", limit: 8,
        }).then(function (result) {
            assert.deepEqual(request.kwargs.args, [["company_id", "=", 1]]);
            assert.deepEqual(request.kwargs.context, {company_id: 1});
            assert.deepEqual(requestOptions, {shadow: true});
            assert.strictEqual(result.fieldLabel, "Current View Partner");
            assert.strictEqual(result.resolution, "unique_exact");
            assert.strictEqual(result.candidates[0].id, 9);
            done();
        });
    });

    QUnit.test("many2one patch rejects ids outside the latest domain", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var applyCalled = false;
        var controller = fakeController({
            applyChanges: function () { applyCalled = true; return $.when(); },
            rpc: function (params) {
                assert.strictEqual(params.method, "search_read");
                return $.when([]);
            },
        });
        Adapter.applyPatch(controller, snapshot(controller), {
            patch: {partner_id: 9},
        }).then(function (result) {
            assert.deepEqual(_.pluck(result.rejected, "code"), ["relation_domain_mismatch"]);
            assert.notOk(applyCalled, "an invalid relation is not applied");
            done();
        });
    });

    QUnit.test("relation validation reports unavailable domains and skips empty replacements", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var rpcCalled = false;
        var applyCalled = false;
        var unavailable = fakeController({
            applyChanges: function () { applyCalled = true; return $.when(); },
        });
        unavailable.model.get("data-1").getDomain = false;
        Adapter.applyPatch(unavailable, snapshot(unavailable), {
            patch: {partner_id: 9},
        }).then(function (result) {
            assert.deepEqual(_.pluck(result.rejected, "code"), ["relation_domain_unavailable"]);
            assert.notOk(applyCalled, "a relation without a live domain is not applied");
            var empty = fakeController({
                tagIds: [],
                rpc: function () { rpcCalled = true; return $.when([]); },
            });
            return Adapter.applyPatch(empty, snapshot(empty), {
                patch: {tag_ids: {operation: "replace", ids: []}},
            });
        }).then(function () {
            assert.notOk(rpcCalled, "an empty replacement does not issue a relation RPC");
            done();
        });
    });

    QUnit.test("client catalog requires the appropriate host target", function (assert) {
        assert.expect(Commands.getCatalog().length * 2);
        _.each(Commands.getCatalog(), function (tool) {
            var menuTools = ["odoo.search_menu", "odoo.open_menu"];
            var pageTools = [
                "odoo.read_mentioned_records",
                "odoo.open_mentioned_menu", "odoo.open_mentioned_record",
                "odoo.apply_mentioned_filter",
            ];
            var requiredTarget = menuTools.indexOf(tool.name) !== -1 ?
                ["snapshotId", "hostRevision", "catalogId", "catalogRevision"] :
                pageTools.indexOf(tool.name) !== -1 ?
                ["snapshotId", "hostRevision"] :
                ["snapshotId", "hostRevision", "controllerId", "dataPointId", "model", "resId"];
            assert.ok(tool.parameters.required.indexOf("target") !== -1, tool.name);
            assert.deepEqual(tool.parameters.properties.target.required, requiredTarget);
        });
    });

    QUnit.test("group command catalog exposes the complete bounded schema", function (assert) {
        assert.expect(1);
        var command = _.findWhere(Commands.getCatalog(), {name: "odoo.apply_group"});
        assert.deepEqual(command.parameters, {
            type: "object",
            additionalProperties: false,
            required: ["target", "groupBy"],
            properties: {
                target: {
                    type: "object",
                    additionalProperties: false,
                    required: [
                        "snapshotId", "hostRevision", "controllerId", "dataPointId", "model", "resId",
                    ],
                    properties: {
                        snapshotId: {type: "string"},
                        hostRevision: {type: "integer"},
                        controllerId: {type: "string"},
                        dataPointId: {type: ["string", "boolean"]},
                        model: {type: ["string", "boolean"]},
                        resId: {type: ["integer", "boolean"]},
                    },
                },
                groupBy: {
                    type: "array",
                    maxItems: 3,
                    items: {
                        type: "object",
                        additionalProperties: false,
                        required: ["field"],
                        properties: {
                            field: {type: "string", minLength: 1, maxLength: 128},
                            interval: {
                                type: "string",
                                enum: ["day", "week", "month", "quarter", "year"],
                            },
                        },
                    },
                },
            },
        });
    });

    QUnit.test("patch enters edit mode before applying changes", function (assert) {
        assert.expect(6);
        var done = assert.async();
        var controller = fakeController({
            mode: "readonly",
            setMode: function (mode) {
                assert.strictEqual(mode, "edit");
                controller.mode = mode;
                return $.when();
            },
            applyChanges: function (_handle, changes) {
                assert.strictEqual(changes.name, "Agent edit");
                return $.when();
            },
            saveRecord: function () {
                assert.strictEqual(controller.mode, "edit");
                return $.when(["name"]);
            },
        });
        var currentSnapshot = snapshot(controller);
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return currentSnapshot; },
            refresh: function () {
                currentSnapshot = snapshot(controller);
                return $.when(currentSnapshot);
            },
        }, {
            tool: "odoo.patch_current_form",
            authorizationId: "authorization-1",
            arguments: {patch: {name: "Agent edit"}},
        }).then(function (result) {
            assert.ok(result.enteredEditMode);
            assert.deepEqual(result.applied, ["name"]);
            assert.ok(result.saved, "patch is persisted through FormController.saveRecord");
            done();
        });
    });

    QUnit.test("enter edit mode changes mode without saving", function (assert) {
        assert.expect(5);
        var done = assert.async();
        var saveCalled = false;
        var controller = fakeController({
            mode: "readonly",
            setMode: function (mode) {
                assert.strictEqual(mode, "edit");
                controller.mode = mode;
                return $.when();
            },
            saveRecord: function () {
                saveCalled = true;
                return $.when([]);
            },
        });
        var currentSnapshot = snapshot(controller);
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return currentSnapshot; },
            refresh: function () {
                currentSnapshot = snapshot(controller);
                return $.when(currentSnapshot);
            },
        }, {
            tool: "odoo.enter_edit_mode",
            arguments: {},
        }).then(function (result) {
            assert.ok(result.editing);
            assert.ok(result.enteredEditMode);
            assert.strictEqual(currentSnapshot.controller.mode, "edit");
            assert.notOk(saveCalled, "entering edit mode does not save the form");
            done();
        });
    });

    QUnit.test("patch refreshes a stale readonly snapshot when the controller is already editing", function (assert) {
        assert.expect(5);
        var done = assert.async();
        var refreshed = false;
        var setModeCalled = false;
        var controller = fakeController({
            mode: "readonly",
            editEnabled: false,
            setMode: function () {
                setModeCalled = true;
                return $.when();
            },
            applyChanges: function (_handle, changes) {
                assert.strictEqual(changes.name, "Synced edit");
                return $.when();
            },
            saveRecord: function () {
                return $.when(["name"]);
            },
        });
        var currentSnapshot = snapshot(controller);
        controller.mode = "edit";
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return currentSnapshot; },
            refresh: function () {
                refreshed = true;
                currentSnapshot = snapshot(controller);
                return $.when(currentSnapshot);
            },
        }, {
            tool: "odoo.patch_current_form",
            authorizationId: "authorization-stale-mode",
            arguments: {patch: {name: "Synced edit"}},
        }).then(function (result) {
            assert.notOk(setModeCalled, "the active edit mode is not entered twice");
            assert.ok(refreshed, "the stale host snapshot is refreshed");
            assert.strictEqual(currentSnapshot.controller.mode, "edit");
            assert.notOk(result.enteredEditMode, "the controller was already editing");
            done();
        });
    });

    QUnit.test("patch rejects forms that do not allow editing", function (assert) {
        assert.expect(2);
        var done = assert.async();
        var setModeCalled = false;
        var controller = fakeController({
            mode: "readonly",
            editEnabled: false,
            setMode: function () {
                setModeCalled = true;
                return $.when();
            },
        });
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return snapshot(controller); },
            refresh: function () { return $.when(snapshot(controller)); },
        }, {
            tool: "odoo.patch_current_form",
            authorizationId: "authorization-2",
            arguments: {patch: {name: "Agent edit"}},
        }).then(function () {
            assert.ok(false, "patch must be rejected");
            done();
        }, function (error) {
            assert.strictEqual(error.code, "form_edit_not_allowed");
            assert.notOk(setModeCalled);
            done();
        });
    });

    QUnit.test("save enters edit mode before using the native save flow", function (assert) {
        assert.expect(4);
        var done = assert.async();
        var controller = fakeController({
            mode: "readonly",
            setMode: function (mode) {
                assert.strictEqual(mode, "edit");
                controller.mode = mode;
                return $.when();
            },
            saveRecord: function () {
                assert.strictEqual(controller.mode, "edit");
                return $.when(["name"]);
            },
        });
        var currentSnapshot = snapshot(controller);
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return currentSnapshot; },
            refresh: function () {
                currentSnapshot = snapshot(controller);
                return $.when(currentSnapshot);
            },
        }, {
            tool: "odoo.save_current_form",
            authorizationId: "authorization-save",
            arguments: {},
        }).then(function (result) {
            assert.ok(result.enteredEditMode);
            assert.deepEqual(result.applied, ["name"]);
            done();
        });
    });

    QUnit.test("many2many link rejects unresolved current relations and oversized input", function (assert) {
        assert.expect(2);
        var done = assert.async();
        var unresolved = fakeController({tagIds: {data: [{res_id: 2}], count: 2}});
        var tooMany = _.range(1, 202);
        Adapter.applyPatch(unresolved, snapshot(unresolved), {
            patch: [{field: "tag_ids", value: {operation: "link", ids: [3]}}],
        }).then(function (result) {
            var controller = fakeController();
            assert.strictEqual(result.rejected[0].code, "relation_unresolved");
            return Adapter.applyPatch(controller, snapshot(controller), {
                patch: [{field: "tag_ids", value: {operation: "replace", ids: tooMany}}],
            });
        }).then(function (result) {
            assert.strictEqual(result.rejected[0].code, "relation_limit_exceeded");
            done();
        });
    });

    QUnit.test("snapshot compression removes values but preserves complete field metadata", function (assert) {
        assert.expect(4);
        var controller = fakeController({changes: {name: "Changed"}});
        var record = controller.model.get("data-1");
        var raw = controller.model.get("data-1", {raw: true});
        _.each(_.range(22), function (index) {
            var name = "text_" + index;
            record.data[name] = Array(4097).join("\u4e2d");
            raw.fields[name] = {type: "text", string: name};
            raw.fieldsInfo.form[name] = {modifiers: {}};
        });
        var state = snapshot(controller);
        assert.strictEqual(_.keys(state.fields).length, 28);
        assert.ok(state.fields.text_21, "字段元信息没有随 values 压缩删除");
        assert.notOk(_.has(state.record.values, "text_21"), "非脏普通值被压缩");
        assert.strictEqual(state.record.values.name, "Acme", "脏字段值始终保留");
    });

    QUnit.test("oversized field metadata returns an explicit snapshot error", function (assert) {
        assert.expect(1);
        var controller = fakeController();
        var record = controller.model.get("data-1");
        var raw = controller.model.get("data-1", {raw: true});
        _.each(_.range(70), function (index) {
            var name = "wide_meta_" + index;
            record.data[name] = false;
            raw.fields[name] = {type: "char", string: Array(4097).join("中")};
            raw.fieldsInfo.form[name] = {modifiers: {}};
        });
        assert.throws(function () {
            snapshot(controller);
        }, function (error) {
            return error.code === "snapshot_too_large" && /字段元信息/.test(error.message);
        });
    });

    QUnit.test("filter domain validates field types, logic arity, and nesting", function (assert) {
        assert.expect(5);
        var state = {
            capabilities: {
                filterFields: {
                    name: {type: "char", operators: ["=", "ilike"]},
                    quantity: {type: "integer", operators: ["=", ">"]},
                },
            },
        };
        assert.deepEqual(Adapter.validateFilterDomain(state, [
            "|", ["name", "ilike", "Acme"], ["quantity", ">", 2],
        ]), ["|", ["name", "ilike", "Acme"], ["quantity", ">", 2]]);
        assert.throws(function () {
            Adapter.validateFilterDomain(state, ["|", ["name", "=", "Acme"]]);
        }, function (error) { return error.code === "invalid_filter_logic"; });
        assert.throws(function () {
            Adapter.validateFilterDomain(state, ["!", "!", "!", "!", "!", ["name", "=", "Acme"]]);
        }, function (error) { return error.code === "filter_logic_too_deep"; });
        assert.throws(function () {
            Adapter.validateFilterDomain(state, [["partner.name", "=", "Acme"]]);
        }, function (error) { return error.code === "invalid_filter_condition"; });
        assert.throws(function () {
            Adapter.validateFilterDomain(state, [["quantity", "=", "2"]]);
        }, function (error) { return error.code === "invalid_filter_condition"; });
    });

    QUnit.test("list group capabilities expose only native sortable safe fields", function (assert) {
        assert.expect(12);
        var fields = {
            partner_id: {type: "many2one", string: "合作伙伴", sortable: true},
            name: {type: "char", string: "名称", sortable: true},
            active: {type: "boolean", string: "有效", sortable: true},
            state: {type: "selection", string: "状态", sortable: true},
            document_date: {type: "date", string: "单据日期", sortable: true},
            write_date: {type: "datetime", string: "更新时间", sortable: true},
            amount: {type: "float", string: "金额", sortable: true},
            unsorted: {type: "char", string: "不可排序", sortable: false},
            hidden: {type: "char", string: "隐藏字段", sortable: true, invisible: true},
            secret_token: {type: "char", string: "密钥", sortable: true},
        };
        var state = {
            id: "root", model: "res.partner", data: [], count: 0,
            domain: [], context: {}, groupedBy: ["document_date:week", "state"],
        };
        var raw = _.extend({}, state, {fields: fields, fieldsInfo: {list: {}}});
        var groupableFields = _.map(fields, function (field, name) {
            return _.extend({name: name}, field);
        });
        var controller = {
            handle: "root",
            activeActions: {},
            renderer: {},
            searchView: {
                query: {},
                groupby_menu: {groupableFields: groupableFields},
                fields: fields,
            },
            model: {get: function (_handle, options) { return options && options.raw ? raw : state; }},
            getSelectedIds: function () { return []; },
        };

        var view = Adapter.buildSnapshot({
            controller: controller, controllerId: "list-controller", viewType: "list",
            action: {id: 1}, menu: false, hostRevision: 1, snapshotId: "list-snapshot",
            surface: "dock", sensitiveFields: [],
        });
        var groupFields = view.capabilities.groupFields;

        assert.ok(view.capabilities.group);
        assert.deepEqual(_.keys(groupFields).sort(), [
            "active", "document_date", "name", "partner_id", "state", "write_date",
        ]);
        assert.strictEqual(groupFields.partner_id.type, "many2one");
        assert.strictEqual(groupFields.name.type, "char");
        assert.strictEqual(groupFields.active.type, "boolean");
        assert.strictEqual(groupFields.state.type, "selection");
        assert.deepEqual(groupFields.document_date.intervals, [
            "day", "week", "month", "quarter", "year",
        ]);
        assert.deepEqual(groupFields.write_date.intervals, [
            "day", "week", "month", "quarter", "year",
        ]);
        assert.deepEqual(view.capabilities.groupBy, [
            {field: "document_date", interval: "week"}, {field: "state"},
        ]);

        controller.searchView.groupby_menu.groupableFields = [
            _.extend({name: "secret_token"}, fields.secret_token),
        ];
        raw.groupedBy = ["secret_token"];
        view = Adapter.buildSnapshot({
            controller: controller, controllerId: "list-controller", viewType: "list",
            action: {id: 1}, menu: false, hostRevision: 2, snapshotId: "safe-empty-snapshot",
            surface: "dock", sensitiveFields: [],
        });
        assert.ok(view.capabilities.group, "原生菜单可用性不依赖可暴露字段数量");
        assert.deepEqual(view.capabilities.groupFields, {});
        assert.deepEqual(view.capabilities.groupBy, []);
    });

    QUnit.test("form snapshots do not expose native grouping", function (assert) {
        assert.expect(3);
        var state = snapshot(fakeController());
        assert.notOk(state.capabilities.group);
        assert.deepEqual(state.capabilities.groupFields, {});
        assert.deepEqual(state.capabilities.groupBy, []);
    });

    QUnit.test("group validation normalizes dates and rejects invalid target states", function (assert) {
        assert.expect(9);
        var state = {
            capabilities: {
                groupFields: {
                    name: {type: "char", intervals: []},
                    document_date: {
                        type: "date", intervals: ["day", "week", "month", "quarter", "year"],
                    },
                    state: {type: "selection", intervals: []},
                    active: {type: "boolean", intervals: []},
                },
            },
        };
        assert.deepEqual(Adapter.validateGroupBy(state, [
            {field: "name"}, {field: "document_date"},
        ]), [{field: "name"}, {field: "document_date", interval: "month"}]);
        assert.deepEqual(Adapter.validateGroupBy(state, []), []);
        assert.throws(function () { Adapter.validateGroupBy(state, "name"); }, function (error) {
            return error.code === "invalid_group_by";
        });
        assert.throws(function () {
            Adapter.validateGroupBy(state, [
                {field: "name"}, {field: "state"}, {field: "active"}, {field: "document_date"},
            ]);
        }, function (error) { return error.code === "invalid_group_by"; });
        assert.throws(function () { Adapter.validateGroupBy(state, [{field: ""}]); }, function (error) {
            return error.code === "invalid_group_field";
        });
        assert.throws(function () { Adapter.validateGroupBy(state, [{field: "unknown"}]); }, function (error) {
            return error.code === "invalid_group_field";
        });
        assert.throws(function () {
            Adapter.validateGroupBy(state, [{field: "name"}, {field: "name"}]);
        }, function (error) { return error.code === "invalid_group_field"; });
        assert.throws(function () {
            Adapter.validateGroupBy(state, [{field: "name", interval: "month"}]);
        }, function (error) { return error.code === "invalid_group_interval"; });
        assert.throws(function () {
            Adapter.validateGroupBy(state, [{field: "document_date", interval: "hour"}]);
        }, function (error) { return error.code === "invalid_group_interval"; });
    });

    QUnit.test("native grouping replaces only group facets and strips favorite group_by", function (assert) {
        assert.expect(25);
        var resets = 0;
        var added = [];
        var favoriteContext = {group_by: ["legacy"], orderedBy: [{name: "name", asc: false}]};
        var favoriteField = {
            get_context: function () { return favoriteContext; },
            get_groupby: function () { return [{group_by: ["legacy"]}]; },
            get_domain: function () { return [["active", "=", true]]; },
        };
        var favoriteFacet = {
            attributes: {is_custom_filter: true, field: favoriteField},
            get: function (name) { return this.attributes[name]; },
        };
        var filterFacet = {
            attributes: {cat: "filterCategory"},
            get: function (name) { return this.attributes[name]; },
        };
        var oldGroupFacet = {
            attributes: {cat: "groupByCategory"},
            get: function (name) { return this.attributes[name]; },
        };
        var facets = [favoriteFacet, filterFacet, oldGroupFacet];
        var query = {
            models: facets,
            on: function () {},
            each: function (callback) { facets.slice(0).forEach(callback); },
            remove: function (facet, options) {
                assert.ok(options.silent, "旧分组 facet 被静默移除");
                facets.splice(facets.indexOf(facet), 1);
            },
            add: function (values, options) {
                assert.ok(options.silent, "新分组 facet 被静默加入");
                added.push(values[0]);
            },
            trigger: function (eventName) {
                assert.strictEqual(eventName, "reset");
                resets += 1;
            },
        };
        var menu = {
            fields: {
                state: {type: "selection", string: "状态", sortable: true},
                document_date: {type: "date", string: "单据日期", sortable: true},
            },
            groupableFields: [
                {name: "state", type: "selection", string: "状态", sortable: true},
                {name: "document_date", type: "date", string: "单据日期", sortable: true},
            ],
            intervalOptions: [
                {description: "日", optionId: "day", groupId: 1},
                {description: "月", optionId: "month", groupId: 1},
            ],
            items: [],
            presentedFields: [],
            _prepareItem: function (item) {
                item.hasOptions = item.isDate;
                item.defaultOptionId = "month";
            },
        };
        var searchView = {
            query: query,
            groupby_menu: menu,
            fields: menu.fields,
            intervalMapping: [], periodMapping: [], groupbysMapping: [], groupsMapping: [],
        };
        var controller = {searchView: searchView};
        var result = Adapter.applyGroupBy(controller, [
            {field: "state"}, {field: "document_date", interval: "day"},
        ]);

        assert.deepEqual(result, [
            {field: "state"}, {field: "document_date", interval: "day"},
        ]);
        assert.strictEqual(resets, 1);
        assert.strictEqual(facets.indexOf(filterFacet), 1, "普通筛选 facet 保留");
        assert.strictEqual(facets.indexOf(favoriteFacet), 0, "收藏 facet 保留");
        assert.deepEqual(favoriteField.get_domain(), [["active", "=", true]]);
        assert.strictEqual(favoriteField.get_context().group_by, undefined);
        assert.deepEqual(favoriteField.get_context().orderedBy, favoriteContext.orderedBy);
        assert.deepEqual(favoriteField.get_groupby(), []);
        assert.strictEqual(added.length, 2);
        assert.deepEqual(_.map(added, function (facet) {
            return facet.values[0].value.attrs.fieldName;
        }), ["state", "document_date"]);
        assert.deepEqual(_.pluck(menu.items, "fieldName"), ["state", "document_date"]);
        assert.strictEqual(searchView.groupbysMapping.length, 2);
        assert.strictEqual(_.findWhere(menu.items, {fieldName: "document_date"}).currentOptionId, "day");

        added = [];
        Adapter.applyGroupBy(controller, [
            {field: "state"}, {field: "document_date", interval: "month"},
        ]);
        assert.strictEqual(menu.items.length, 2, "重复应用不会新增菜单项");
        assert.strictEqual(searchView.groupbysMapping.length, 2, "重复应用会复用原生映射");

        added = [];
        Adapter.applyGroupBy(controller, []);
        assert.strictEqual(searchView.groupbysMapping.length, 2, "清除后保留原生菜单映射且不重复创建");
        assert.deepEqual(added, []);
    });

    QUnit.test("kanban group command reloads and returns refreshed normalized state", function (assert) {
        assert.expect(8);
        var done = assert.async();
        var resetCount = 0;
        var reloaded = false;
        var current = {
            interactive: true,
            controller: {viewType: "kanban"},
            capabilities: {
                group: true,
                groupFields: {
                    document_date: {
                        type: "date", intervals: ["day", "week", "month", "quarter", "year"],
                    },
                },
                groupBy: [],
            },
        };
        var next = _.extend({}, current, {
            snapshotId: "grouped", hostRevision: 4,
            capabilities: _.extend({}, current.capabilities, {
                groupBy: [{field: "document_date", interval: "month"}],
            }),
        });
        var searchView = {
            fields: {document_date: {type: "date", string: "单据日期", sortable: true}},
            groupby_menu: {
                fields: {document_date: {type: "date", string: "单据日期", sortable: true}},
                groupableFields: [{
                    name: "document_date", type: "date", string: "单据日期", sortable: true,
                }],
                intervalOptions: [], items: [], presentedFields: [],
                _prepareItem: function () {},
            },
            intervalMapping: [], periodMapping: [], groupbysMapping: [], groupsMapping: [],
            query: {
                on: function () {}, each: function () {}, remove: function () {},
                add: function (_facets, options) { assert.ok(options.silent); },
                trigger: function (name) {
                    assert.strictEqual(name, "reset");
                    resetCount += 1;
                },
            },
        };
        var controller = {
            searchView: searchView,
            reload: function () { reloaded = true; return $.when(); },
        };
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return current; },
            refresh: function () { return $.when(next); },
        }, {
            tool: "odoo.apply_group",
            arguments: {groupBy: [{field: "document_date"}]},
        }).then(function (result) {
            assert.strictEqual(resetCount, 1);
            assert.ok(reloaded);
            assert.ok(result.applied);
            assert.deepEqual(result.groupBy, [{field: "document_date", interval: "month"}]);
            assert.strictEqual(result.snapshotId, "grouped");
            assert.strictEqual(result.hostRevision, 4);
            done();
        });
    });

    QUnit.test("group command uses stable unavailable code outside list and kanban", function (assert) {
        assert.expect(1);
        var done = assert.async();
        Commands.execute({
            getController: function () { return {}; },
            getSnapshot: function () {
                return {
                    interactive: true, controller: {viewType: "form"},
                    capabilities: {group: false, groupFields: {}, groupBy: []},
                };
            },
        }, {
            tool: "odoo.apply_group", arguments: {groupBy: []},
        }).then(function () {
            assert.ok(false, "Form 视图不应执行分组");
            done();
        }, function (error) {
            assert.strictEqual(error.code, "group_unavailable");
            done();
        });
    });

    QUnit.test("kanban snapshot exposes only visible record and control tokens", function (assert) {
        assert.expect(7);
        var bindings = [];
        var card = $('<div class="oe_kanban_global_click">' +
            '<button class="oe_kanban_action" data-type="object" title="确认">确认</button>' +
            '<button class="oe_kanban_action" data-type="action" style="display:none">隐藏</button>' +
        '</div>').appendTo("#qunit-fixture");
        var item = {
            id: "record-7", model: "res.partner", res_id: 7,
            data: {display_name: "Acme"},
        };
        var root = {id: "root", model: "res.partner", data: [item], context: {}, domain: []};
        var raw = _.extend({}, root, {
            fields: {display_name: {type: "char", string: "Name"}},
            fieldsInfo: {kanban: {display_name: {modifiers: {}}}},
        });
        var widget = {state: item, db_id: "record-7", $el: card};
        var controller = {
            handle: "root",
            activeActions: {create: true, edit: true},
            renderer: {widgets: [widget]},
            model: {get: function (_handle, options) { return options && options.raw ? raw : root; }},
            getSelectedIds: function () { return []; },
        };
        var state = Adapter.buildSnapshot({
            controller: controller, controllerId: "kanban-controller", viewType: "kanban",
            action: {id: 9}, menu: false, hostRevision: 1, snapshotId: "kanban-snapshot",
            surface: "dock", sensitiveFields: [],
            registerToken: function (kind, binding) {
                bindings.push({kind: kind, binding: binding});
                return kind + "-" + bindings.length;
            },
        });
        assert.strictEqual(state.controller.viewType, "kanban");
        assert.deepEqual(state.capabilities.records, [{token: "record-1", displayName: "Acme"}]);
        assert.deepEqual(_.pluck(state.capabilities.controls, "type"), ["open", "object"]);
        assert.strictEqual(bindings[0].binding.resId, 7);
        assert.strictEqual(bindings[1].binding.widget, widget);
        assert.strictEqual(bindings[2].binding.label, "确认");
        assert.ok(state.capabilities.create);
    });

    QUnit.test("native filter replaces only the previous assistant facet", function (assert) {
        assert.expect(6);
        var done = assert.async();
        var removed;
        var reloaded = false;
        var previous = [{id: "assistant-old"}];
        var controller = {
            __aguiAssistantFilters: previous,
            searchView: {
                updateFilters: function (filters, filtersToRemove) {
                    assert.deepEqual(filters, [{domain: [["name", "ilike", "Acme"]], help: "Acme 客户"}]);
                    removed = filtersToRemove;
                    return [{id: "assistant-new"}];
                },
            },
            reload: function () { reloaded = true; return $.when(); },
        };
        var current = {
            interactive: true,
            controller: {viewType: "list"},
            capabilities: {
                filter: true,
                filterFields: {name: {type: "char", operators: ["ilike"]}},
            },
        };
        var next = _.extend({}, current, {
            snapshotId: "filtered", hostRevision: 2,
            capabilities: _.extend({}, current.capabilities, {
                totalCount: 2,
                records: [{token: "record-1", displayName: "Acme"}],
            }),
        });
        Commands.execute({
            resolveToken: function () { return false; },
            getController: function () { return controller; },
            getSnapshot: function () { return current; },
            refresh: function () { return $.when(next); },
        }, {
            tool: "odoo.apply_filter",
            arguments: {domain: [["name", "ilike", "Acme"]], label: "Acme 客户"},
        }).then(function (result) {
            assert.strictEqual(removed, previous);
            assert.ok(reloaded);
            assert.deepEqual(controller.__aguiAssistantFilters, [{id: "assistant-new"}]);
            assert.strictEqual(result.count, 2);
            assert.deepEqual(result.candidates, next.capabilities.records);
            done();
        });
    });

    QUnit.test("unique grouped filter expands collapsed groups before returning candidate", function (assert) {
        assert.expect(8);
        var done = assert.async();
        var record = {
            id: "record-7", type: "record", count: 1, model: "res.partner", res_id: 7,
            data: {display_name: "Acme"},
        };
        var group = {
            id: "group-1", type: "list", count: 1, isOpen: false, data: [],
        };
        var root = {
            id: "root", type: "list", count: 1, data: [group], groupedBy: ["company_id"],
        };
        var controller = {
            handle: "root",
            searchView: {
                updateFilters: function () { return [{id: "assistant-filter"}]; },
            },
            reload: function () { return $.when(); },
            update: function (params, options) {
                assert.deepEqual(params, {});
                assert.deepEqual(options, {keepSelection: true, reload: false});
                return $.when();
            },
            model: {
                get: function () { return root; },
                toggleGroup: function (groupId) {
                    assert.strictEqual(groupId, "group-1");
                    group.isOpen = true;
                    group.data = [record];
                    return $.when(groupId);
                },
            },
        };
        var current = {
            interactive: true,
            controller: {viewType: "list"},
            capabilities: {
                filter: true,
                filterFields: {name: {type: "char", operators: ["ilike"]}},
            },
        };
        var filtered = _.extend({}, current, {
            snapshotId: "filtered", hostRevision: 2,
            capabilities: _.extend({}, current.capabilities, {totalCount: 1, records: []}),
        });
        var expanded = _.extend({}, filtered, {
            snapshotId: "expanded", hostRevision: 3,
            capabilities: _.extend({}, filtered.capabilities, {
                records: [{token: "record-1", displayName: "Acme"}],
            }),
        });
        var refreshes = 0;
        Commands.execute({
            getController: function () { return controller; },
            getSnapshot: function () { return current; },
            refresh: function () {
                refreshes += 1;
                return $.when(refreshes === 1 ? filtered : expanded);
            },
        }, {
            tool: "odoo.apply_filter",
            arguments: {domain: [["name", "ilike", "Acme"]], label: "Acme 客户"},
        }).then(function (result) {
            assert.strictEqual(refreshes, 2);
            assert.strictEqual(result.count, 1);
            assert.deepEqual(result.candidates, expanded.capabilities.records);
            assert.strictEqual(result.snapshotId, "expanded");
            assert.strictEqual(result.hostRevision, 3);
            done();
        });
    });

    QUnit.test("open record rejects when the host does not navigate", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var opened = false;
        var current = {
            snapshotId: "list-snapshot",
            capabilities: {edit: true},
        };
        Commands.execute({
            resolveToken: function () {
                return {localId: "record-7", resId: 7, displayName: "Acme"};
            },
            validateToken: function () { return true; },
            hasUnsavedChanges: function () { return false; },
            getSnapshot: function () { return current; },
            openRecord: function () { opened = true; return $.when(); },
            waitForSnapshotChange: function () { return $.when(current); },
        }, {
            tool: "odoo.open_record",
            arguments: {recordToken: "record-1", mode: "readonly"},
        }).then(function () {
            assert.ok(false, "unchanged host snapshot must not report a successful open");
            done();
        }, function (error) {
            assert.ok(opened, "the native open event was attempted");
            assert.strictEqual(error.code, "record_open_failed");
            assert.strictEqual(error.message, "客户端未进入记录表单。");
            done();
        });
    });

    QUnit.test("object controls require authorization and dirty forms block menu navigation", function (assert) {
        assert.expect(2);
        var done = assert.async();
        Commands.execute({
            resolveToken: function () { return {type: "object"}; },
        }, {
            tool: "odoo.activate_view_control", arguments: {controlToken: "control-1"},
        }).then(function () {
            assert.ok(false, "object control must not execute");
        }, function (error) {
            assert.strictEqual(error.code, "authorization_required");
            return Commands.execute({
                resolveToken: function () { return false; },
                getSnapshot: function () { return {snapshotId: "page", hostRevision: 1}; },
                hasUnsavedChanges: function () { return true; },
            }, {
                tool: "odoo.open_menu", arguments: {menuId: 8, actionId: 42},
            });
        }).then(function () {
            assert.ok(false, "dirty form navigation must not execute");
        }, function (error) {
            assert.strictEqual(error.code, "unsaved_changes");
            done();
        });
    });

    QUnit.test("menu search is read-only and opening verifies the searched action", function (assert) {
        assert.expect(6);
        var done = assert.async();
        var snapshot = {snapshotId: "page", hostRevision: 1};
        var context = {
            getSnapshot: function () { return snapshot; },
            hasUnsavedChanges: function () { return false; },
            searchMenus: function (query) {
                assert.strictEqual(query, "报销单查询");
                return {
                    query: query,
                    matchType: "exact",
                    candidates: [{menuId: 9, actionId: 42, fullPath: "费用报销 / 报销单查询"}],
                };
            },
            openMenu: function (menuId, actionId) {
                assert.strictEqual(menuId, 9);
                assert.strictEqual(actionId, 42);
                snapshot = {snapshotId: "opened", hostRevision: 2};
                return $.when({menuId: menuId, actionId: actionId});
            },
            waitForSnapshotChange: function () { return $.when(snapshot); },
        };

        Commands.execute(context, {
            tool: "odoo.search_menu", arguments: {query: "报销单查询"},
        }).then(function (result) {
            assert.strictEqual(result.matchType, "exact");
            assert.strictEqual(result.snapshotId, "page");
            return Commands.execute(context, {
                tool: "odoo.open_menu", arguments: {menuId: 9, actionId: 42},
            });
        }).then(function (result) {
            assert.strictEqual(result.menu.actionId, 42);
            done();
        });
    });

    QUnit.test("mentioned menu create checks the opened action snapshot", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var created = false;
        var waits = 0;
        Commands.execute({
            getSnapshot: function () { return {snapshotId: "before"}; },
            hasUnsavedChanges: function () { return false; },
            openMenu: function () { return $.when(); },
            waitForSnapshotChange: function () {
                waits += 1;
                return $.when(waits === 1 ? {snapshotId: "menu", capabilities: {create: true}} : {snapshotId: "create"});
            },
            getController: function () { return {}; },
            openCreate: function () { created = true; return $.when(); },
        }, {
            tool: "odoo.open_mentioned_menu", authorizationId: "authorization-1",
            arguments: {token: "menu", __mention: [{kind: "menu", action: "create", menu_id: 8, action_id: 42, label: "客户"}]},
        }).then(function (result) {
            assert.ok(created, "create executes after opening the menu");
            assert.strictEqual(waits, 2);
            assert.strictEqual(result.mode, "create");
            done();
        }, function (error) {
            assert.ok(false, error && error.message);
            done();
        });
    });

    QUnit.test("mentioned menu create stops when the opened action rejects create", function (assert) {
        assert.expect(4);
        var done = assert.async();
        var opened = false;
        var created = false;
        Commands.execute({
            getSnapshot: function () { return {snapshotId: "before"}; },
            hasUnsavedChanges: function () { return false; },
            openMenu: function () { opened = true; return $.when(); },
            waitForSnapshotChange: function () { return $.when({snapshotId: "menu", capabilities: {create: false}}); },
            getController: function () { return {}; },
            openCreate: function () { created = true; return $.when(); },
        }, {
            tool: "odoo.open_mentioned_menu", authorizationId: "authorization-1",
            arguments: {token: "menu", __mention: [{kind: "menu", action: "create", menu_id: 8, action_id: 42, label: "客户"}]},
        }).then(function () {
            assert.ok(false, "unsupported create must fail");
            done();
        }, function (error) {
            assert.ok(opened, "the menu remains opened");
            assert.notOk(created, "openCreate is not called");
            assert.strictEqual(error.code, "create_not_allowed");
            assert.strictEqual(error.message, "当前 action 不支持新建");
            done();
        });
    });

    QUnit.test("mentioned record keeps the bound view mode across menu navigation", function (assert) {
        assert.expect(4);
        var done = assert.async();
        var opened = false;
        var waits = 0;
        var listSnapshot = {
            snapshotId: "mentioned-list",
            selection: {model: "res.partner"},
            record: false,
        };
        var formSnapshot = {
            snapshotId: "mentioned-form",
            controller: {mode: "readonly"},
            record: {model: "res.partner", resId: 17},
        };
        Commands.execute({
            getSnapshot: function () { return {snapshotId: "before"}; },
            hasUnsavedChanges: function () { return false; },
            openMenu: function (menuId) {
                assert.strictEqual(menuId, 8);
                return $.when();
            },
            waitForSnapshotChange: function () {
                waits += 1;
                return $.when(waits === 1 ? listSnapshot : formSnapshot);
            },
            openMentionedRecord: function (recordId, mode) {
                opened = true;
                assert.strictEqual(recordId, 17);
                assert.strictEqual(mode, "readonly");
                return $.when();
            },
        }, {
            tool: "odoo.open_mentioned_record",
            authorizationId: "authorization-1",
            arguments: {
                token: "bound-record", __mention: [{
                    token: "bound-record", kind: "record", action: "view",
                    model: "res.partner", record_id: 17, menu_id: 8, action_id: 42,
                    label: "Acme",
                }],
            },
        }).then(function (result) {
            assert.ok(opened && result.opened);
            done();
        }, function (error) {
            assert.ok(false, error && error.message);
            done();
        });
    });

    QUnit.test("mentioned filters replace the query through the native host adapter", function (assert) {
        assert.expect(3);
        var done = assert.async();
        var waits = 0;
        var applied;
        var binding = {
            token: "bound-filter", kind: "current_filter", action: "apply",
            model: "res.partner", menu_id: 8, action_id: 42, label: "当前筛选",
            domain: [["name", "ilike", "Acme"]], context: {}, group_by: ["company_id"],
            sort: ["-name"],
        };
        Commands.execute({
            getSnapshot: function () { return {snapshotId: "before"}; },
            hasUnsavedChanges: function () { return false; },
            openMenu: function () { return $.when(); },
            waitForSnapshotChange: function () {
                waits += 1;
                return $.when({snapshotId: "filter-" + waits, hostRevision: waits});
            },
            applyMentionFilter: function (value) { applied = value; return $.when(); },
        }, {
            tool: "odoo.apply_mentioned_filter",
            authorizationId: "authorization-filter",
            arguments: {token: binding.token, __mention: [binding]},
        }).then(function (result) {
            assert.strictEqual(applied, binding);
            assert.ok(result.applied);
            assert.strictEqual(result.snapshotId, "filter-2");
            done();
        }, function (error) {
            assert.ok(false, error && error.message);
            done();
        });
    });
});
