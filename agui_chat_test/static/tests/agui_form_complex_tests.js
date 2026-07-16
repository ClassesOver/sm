odoo.define("agui_chat_test.form_complex_tests", function (require) {
    "use strict";

    var Adapter = require("agui_chat.model_adapter");
    var Commands = require("agui_chat.command_registry");
    var FormView = require("web.FormView");
    var concurrency = require("web.concurrency");
    var testUtils = require("web.test_utils");

    function testData() {
        return {
            "agui.chat.test.document": {
                fields: {
                    name: {string: "单据名称", type: "char", required: true},
                    required_code: {string: "必填编码", type: "char", required: true},
                    document_type: {
                        string: "单据类型", type: "selection", required: true,
                        selection: [["standard", "标准"], ["special", "特殊"]],
                    },
                    domain_key: {
                        string: "关系域键", type: "selection", required: true,
                        selection: [["standard", "标准"], ["special", "特殊"]],
                    },
                    candidate_id: {
                        string: "主候选", type: "many2one", relation: "agui.chat.test.option",
                    },
                    tag_ids: {
                        string: "候选标签", type: "many2many", relation: "agui.chat.test.option",
                    },
                    line_ids: {
                        string: "明细", type: "one2many", relation: "agui.chat.test.line",
                        relation_field: "document_id",
                    },
                    show_extra: {string: "显示附加字段", type: "boolean"},
                    dynamic_note: {string: "动态附加字段", type: "char"},
                    locked_note: {string: "状态锁定字段", type: "char"},
                    quantity: {string: "数量", type: "integer"},
                    state: {
                        string: "状态", type: "selection",
                        selection: [["draft", "草稿"], ["confirmed", "已确认"]],
                    },
                    secret_token: {string: "敏感令牌", type: "char"},
                },
                records: [{
                    id: 1,
                    name: "原单据",
                    required_code: "DOC-1",
                    document_type: "standard",
                    domain_key: "standard",
                    candidate_id: 10,
                    tag_ids: [10],
                    line_ids: [100],
                    show_extra: false,
                    dynamic_note: false,
                    locked_note: "可修改",
                    quantity: 1,
                    state: "draft",
                    secret_token: "never-export-this",
                }],
                onchanges: {
                    document_type: function (record) {
                        record.domain_key = record.document_type;
                    },
                },
            },
            "agui.chat.test.option": {
                fields: {
                    name: {string: "候选名称", type: "char"},
                    domain_key: {string: "域键", type: "char"},
                },
                records: [
                    {id: 10, name: "标准唯一候选", domain_key: "standard"},
                    {id: 11, name: "标准候选二", domain_key: "standard"},
                    {id: 20, name: "特殊唯一候选", domain_key: "special"},
                ],
            },
            "agui.chat.test.line": {
                fields: {
                    name: {string: "明细名称", type: "char"},
                    quantity: {string: "数量", type: "integer"},
                    document_id: {
                        string: "单据", type: "many2one", relation: "agui.chat.test.document",
                    },
                },
                records: [{id: 100, name: "原明细", quantity: 1, document_id: 1}],
            },
        };
    }

    function formArch() {
        return '<form string="通用单据">' +
            '<field name="domain_key" invisible="1"/>' +
            '<field name="secret_token" invisible="1"/>' +
            '<field name="name"/>' +
            '<field name="required_code"/>' +
            '<field name="document_type"/>' +
            '<field name="candidate_id" domain="[(\'domain_key\', \'=\', domain_key)]"/>' +
            '<field name="tag_ids" widget="many2many_tags" domain="[(\'domain_key\', \'=\', domain_key)]"/>' +
            '<field name="show_extra"/>' +
            '<field name="dynamic_note" attrs="{\'invisible\': [(\'show_extra\', \'=\', False)]}"/>' +
            '<field name="locked_note" attrs="{\'readonly\': [(\'state\', \'=\', \'confirmed\')]}"/>' +
            '<field name="quantity"/>' +
            '<field name="state"/>' +
            '<field name="line_ids"><tree editable="bottom">' +
                '<field name="name"/><field name="quantity"/>' +
            '</tree></field>' +
        '</form>';
    }

    function snapshot(controller) {
        return Adapter.buildSnapshot({
            controller: controller,
            controllerId: "complex-controller",
            viewType: "form",
            action: {id: 1},
            menu: false,
            hostRevision: 1,
            snapshotId: "complex-snapshot",
            surface: "dock",
            sensitiveFields: [],
        });
    }

    function commandContext(controller) {
        var current = snapshot(controller);
        return {
            getController: function () { return controller; },
            getSnapshot: function () { return current; },
            refresh: function () {
                current = snapshot(controller);
                return $.when(current);
            },
        };
    }

    function executePatch(controller, context, patch) {
        return Commands.execute(context, {
            tool: "odoo.patch_current_form",
            authorizationId: "qunit-authorization",
            arguments: {patch: patch},
        });
    }

    function rejected(promise) {
        return new Promise(function (resolve, reject) {
            promise.then(function () {
                reject(new Error("expected command rejection"));
            }, resolve);
        });
    }

    QUnit.module("agui_chat_test real form integration");

    QUnit.test("hidden snapshot values and live modifiers remain fail closed", async function (assert) {
        assert.expect(10);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var state = snapshot(form);
        var context = commandContext(form);

        assert.strictEqual(state.record.values.domain_key, "standard", "hidden domain value is exported");
        assert.ok(state.fields.domain_key.invisible, "hidden field metadata is preserved");
        assert.strictEqual(state.record.values.secret_token, "[redacted]", "secret stays redacted");
        assert.ok(state.fields.dynamic_note.invisible, "dynamic field starts hidden");

        var hidden = await Adapter.applyPatch(form, state, {patch: {dynamic_note: "blocked"}});
        assert.strictEqual(hidden.rejected[0].code, "field_invisible");

        var shown = await executePatch(form, context, {show_extra: true});
        assert.ok(shown.saved);
        state = snapshot(form);
        assert.notOk(state.fields.dynamic_note.invisible, "modifier is recalculated after save");
        assert.ok((await executePatch(form, context, {dynamic_note: "visible value"})).saved);

        assert.ok((await executePatch(form, context, {state: "confirmed"})).saved);
        state = snapshot(form);
        assert.ok(state.fields.locked_note.readonly, "confirmed state locks the field");
        form.destroy();
    });

    QUnit.test("an unrelated BasicModel dirty field rejects an atomic patch", async function (assert) {
        assert.expect(4);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        await form._applyChanges(form.handle, {name: "用户未保存值"}, {
            data: {notifyChange: true, viewType: "form"},
            stopPropagation: function () {},
        });
        var state = snapshot(form);
        var result = await Adapter.applyPatch(form, state, {patch: {quantity: 9}});

        assert.ok(state.record.dirtyFields.indexOf("name") !== -1);
        assert.strictEqual(result.rejected[0].code, "dirty_conflict");
        assert.strictEqual(state.record.values.name, "用户未保存值");
        assert.strictEqual(state.record.values.quantity, 1, "agent value is not partially applied");
        form.destroy();
    });

    QUnit.test("native validation blocks save and preserves dirty values", async function (assert) {
        assert.expect(5);
        var writes = 0;
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
            mockRPC: function (route, args) {
                if (args.method === "write") {
                    writes += 1;
                }
                return this._super.apply(this, arguments);
            },
        });
        var error = await rejected(executePatch(form, commandContext(form), {required_code: false}));
        var state = snapshot(form);

        assert.strictEqual(error.code, "validation_failed");
        assert.deepEqual(error.invalidFields, ["required_code"]);
        assert.strictEqual(writes, 0, "invalid form is never sent to write");
        assert.ok(form.model.isDirty(form.handle), "invalid value stays dirty for correction");
        assert.strictEqual(state.record.values.required_code, false);
        form.destroy();
    });

    QUnit.test("save RPC failures use save_failed and retain BasicModel changes", async function (assert) {
        assert.expect(4);
        var data = testData();
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: data,
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
            mockRPC: function (route, args) {
                if (args.method === "write") {
                    return $.Deferred().reject({message: "constraint failed"});
                }
                return this._super.apply(this, arguments);
            },
        });
        var error = await rejected(executePatch(form, commandContext(form), {quantity: 7}));
        var state = snapshot(form);

        assert.strictEqual(error.code, "save_failed");
        assert.ok(form.model.isDirty(form.handle));
        assert.strictEqual(state.record.values.quantity, 7, "failed value remains in the form");
        assert.strictEqual(data["agui.chat.test.document"].records[0].quantity, 1, "fixture database is unchanged");
        form.destroy();
    });

    QUnit.test("delayed onchange completes before domain refresh and save", async function (assert) {
        assert.expect(4);
        var onchangeDef = $.Deferred();
        var writes = 0;
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
            mockRPC: function (route, args) {
                var result = this._super.apply(this, arguments);
                if (args.method === "onchange") {
                    return onchangeDef.then(function () { return result; });
                }
                if (args.method === "write") {
                    writes += 1;
                }
                return result;
            },
        });
        var pending = executePatch(form, commandContext(form), {document_type: "special"});
        await concurrency.delay(0);
        assert.strictEqual(writes, 0, "save waits for onchange");
        onchangeDef.resolve();
        var result = await pending;
        var state = snapshot(form);

        assert.ok(result.saved);
        assert.strictEqual(state.record.values.domain_key, "special");
        assert.deepEqual(form.model.get(form.handle).getDomain({fieldName: "candidate_id"}), [
            ["domain_key", "=", "special"],
        ]);
        form.destroy();
    });

    QUnit.test("many2one patch accepts an Odoo id and display name pair", async function (assert) {
        assert.expect(4);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var result = await executePatch(form, commandContext(form), {
            candidate_id: [11, "标准候选二"],
        });
        var state = snapshot(form);

        assert.ok(result.saved);
        assert.strictEqual(state.record.values.candidate_id.id, 11);
        var invalid = await Adapter.applyPatch(form, state, {patch: {candidate_id: [10]}});
        assert.strictEqual(invalid.rejected[0].code, "invalid_value");
        assert.strictEqual(snapshot(form).record.values.candidate_id.id, 11, "invalid pair is not applied");
        form.destroy();
    });

    QUnit.test("one2many generic operations and stale relation ids are rejected", async function (assert) {
        assert.expect(4);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var context = commandContext(form);
        await executePatch(form, context, {document_type: "special"});
        var state = snapshot(form);
        var oldCandidate = await Adapter.applyPatch(form, state, {patch: {candidate_id: 10}});

        assert.strictEqual(oldCandidate.rejected[0].code, "relation_domain_mismatch");
        assert.ok((await executePatch(form, context, {candidate_id: 20})).saved);
        state = snapshot(form);
        var line = await Adapter.applyPatch(form, state, {
            patch: {line_ids: {operation: "create", values: {name: "禁止创建"}}},
        });
        assert.strictEqual(line.rejected[0].code, "invalid_value");
        assert.strictEqual(snapshot(form).record.values.line_ids.count, 1, "no child row is created");
        form.destroy();
    });

    QUnit.test("ActionManager destroys the previous native controller", async function (assert) {
        assert.expect(2);
        var actionManager = testUtils.createActionManager({
            data: testData(),
            actions: [
                {
                    id: 1, name: "单据一", type: "ir.actions.act_window",
                    res_model: "agui.chat.test.document", res_id: 1, views: [[false, "form"]],
                    flags: {hasSearchView: false},
                },
                {
                    id: 2, name: "单据二", type: "ir.actions.act_window",
                    res_model: "agui.chat.test.document", res_id: 1, views: [[false, "form"]],
                    flags: {hasSearchView: false},
                },
            ],
            archs: {
                "agui.chat.test.document,false,form": formArch(),
            },
        });
        await actionManager.doAction(1);
        var first = actionManager.getCurrentController().widget;
        assert.notOk(first.isDestroyed());
        await actionManager.doAction(2, {clear_breadcrumbs: true});
        assert.ok(first.isDestroyed(), "navigation destroys the stale controller");
        actionManager.destroy();
    });
});
