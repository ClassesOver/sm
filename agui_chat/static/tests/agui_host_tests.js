odoo.define("agui_chat.tests.host", function (require) {
    "use strict";

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

    QUnit.test("menu options refresh when WebClient menu data arrives late", function (assert) {
        var webClient = {menu_data: null};
        var service = Object.create(HostService.prototype);
        service._webClient = null;
        service._menuData = null;
        service._menuOptions = [];

        service.configureNavigation(webClient, null);
        assert.deepEqual(service.getMenuOptions(), []);

        webClient.menu_data = {
            children: [{
                id: 90,
                name: "员工",
                action: "ir.actions.act_window,115",
                children: [],
            }],
        };
        assert.deepEqual(service.getMenuOptions(), [{
            menuId: 90,
            actionId: 115,
            name: "员工",
            path: ["员工"],
            fullPath: "员工",
        }]);
    });

    QUnit.test("snapshot is bounded to view fields and redacts secrets", function (assert) {
        assert.expect(11);
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
        assert.notOk(state.fields.image, "binary fields are omitted");
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
            var requiredTarget = tool.name === "odoo.open_menu" ?
                ["snapshotId", "hostRevision"] :
                ["snapshotId", "hostRevision", "controllerId", "dataPointId", "model", "resId"];
            assert.ok(tool.parameters.required.indexOf("target") !== -1, tool.name);
            assert.deepEqual(tool.parameters.properties.target.required, requiredTarget);
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

    QUnit.test("snapshot limit counts UTF-8 bytes", function (assert) {
        assert.expect(1);
        var controller = fakeController();
        var record = controller.model.get("data-1");
        var raw = controller.model.get("data-1", {raw: true});
        _.each(_.range(22), function (index) {
            var name = "text_" + index;
            record.data[name] = Array(4097).join("\u4e2d");
            raw.fields[name] = {type: "text", string: name};
            raw.fieldsInfo.form[name] = {modifiers: {}};
        });
        assert.throws(function () { snapshot(controller); }, /大小限制/);
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
                tool: "odoo.open_menu", arguments: {menuId: 8},
            });
        }).then(function () {
            assert.ok(false, "dirty form navigation must not execute");
        }, function (error) {
            assert.strictEqual(error.code, "unsaved_changes");
            done();
        });
    });
});
