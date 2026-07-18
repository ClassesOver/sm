odoo.define("agui_chat_test.form_complex_tests", function (require) {
    "use strict";

    var Adapter = require("agui_chat.model_adapter");
    var Commands = require("agui_chat.command_registry");
    var HostService = require("agui_chat.host_service");
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
                    detail_item_ids: {
                        string: "通用明细", type: "one2many", relation: "agui.chat.test.line",
                        relation_field: "document_id",
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
                    phone_number: {string: "手机号", type: "char"},
                },
                records: [{
                    id: 1,
                    name: "原单据",
                    required_code: "DOC-1",
                    document_type: "standard",
                    domain_key: "standard",
                    candidate_id: 10,
                    tag_ids: [10],
                    detail_item_ids: [100, 101],
                    line_ids: [100],
                    show_extra: false,
                    dynamic_note: false,
                    locked_note: "可修改",
                    quantity: 1,
                    state: "draft",
                    secret_token: "never-export-this",
                    phone_number: "13800138000",
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
                    name: {string: "明细名称", type: "char", required: true},
                    quantity: {string: "数量", type: "integer"},
                    domain_key: {
                        string: "关系域键", type: "selection",
                        selection: [["standard", "标准"], ["special", "特殊"]],
                    },
                    candidate_id: {
                        string: "明细候选", type: "many2one", relation: "agui.chat.test.option",
                    },
                    tag_ids: {
                        string: "明细标签", type: "many2many", relation: "agui.chat.test.option",
                    },
                    secret_token: {string: "明细敏感令牌", type: "char"},
                    form_note: {string: "表单专用备注", type: "char"},
                    tree_note: {string: "列表专用备注", type: "char"},
                    document_id: {
                        string: "单据", type: "many2one", relation: "agui.chat.test.document",
                    },
                },
                records: [
                    {id: 100, name: "原明细 A", quantity: 1, domain_key: "standard", candidate_id: 10, tag_ids: [10], secret_token: "child-secret", form_note: "表单值", tree_note: "列表值", document_id: 1},
                    {id: 101, name: "原明细 B", quantity: 2, domain_key: "special", candidate_id: 20, tag_ids: [20], secret_token: "child-secret", form_note: "表单值", tree_note: "列表值", document_id: 1},
                ],
            },
        };
    }

    function formArch() {
        return '<form string="通用单据">' +
            '<header><button name="action_confirm" type="object" string="确认"/></header>' +
            '<field name="domain_key" invisible="1"/>' +
            '<field name="secret_token" invisible="1"/>' +
            '<field name="phone_number"/>' +
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
            '<field name="detail_item_ids"><tree editable="bottom">' +
                '<field name="name"/><field name="quantity"/>' +
                '<field name="domain_key"/>' +
                '<field name="candidate_id" domain="[(\'domain_key\', \'=\', domain_key)]"/>' +
                '<field name="tag_ids"/><field name="secret_token" invisible="1"/>' +
                '<field name="tree_note"/>' +
            '</tree><form string="明细表单">' +
                '<field name="name"/><field name="quantity"/>' +
                '<field name="domain_key"/><field name="candidate_id"/>' +
                '<field name="tag_ids"/><field name="secret_token" invisible="1"/>' +
                '<field name="form_note"/>' +
            '</form></field>' +
        '</form>';
    }

    function snapshot(controller, tokenStore) {
        var sequence = 0;
        _.each(_.keys(tokenStore || {}), function (token) { delete tokenStore[token]; });
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
            registerToken: tokenStore ? function (kind, binding) {
                sequence += 1;
                var token = kind + "-" + sequence;
                tokenStore[token] = {kind: kind, binding: binding};
                return token;
            } : undefined,
        });
    }

    function commandContext(controller, tokenStore) {
        tokenStore = tokenStore || {};
        var current = snapshot(controller, tokenStore);
        var context = {
            getController: function () { return controller; },
            getSnapshot: function () { return current; },
            hasUnsavedChanges: function () { return controller.model.isDirty(controller.handle); },
            resolveToken: function (token, kind) {
                var entry = tokenStore[token];
                return entry && entry.kind === kind ? entry.binding : false;
            },
            validateToken: function (binding, kind) {
                return _.some(tokenStore, function (entry) {
                    return entry.kind === kind && entry.binding === binding;
                });
            },
            activateControl: function (binding) {
                binding.$element.trigger("click");
                return $.when();
            },
            refresh: function () {
                current = snapshot(controller, tokenStore);
                return $.when(current);
            },
        };
        context.waitForSnapshotChange = function () {
            var ready = controller.mutex && controller.mutex.getUnlockedDef ?
                controller.mutex.getUnlockedDef() : $.when();
            return $.when(ready).then(context.refresh);
        };
        return context;
    }

    function executePatch(controller, context, patch) {
        return Commands.execute(context, {
            tool: "odoo.patch_current_form",
            authorizationId: "qunit-authorization",
            arguments: {patch: patch},
        });
    }

    function executeStage(context, patch, rowToken) {
        return Commands.execute(context, {
            tool: "odoo.stage_current_form",
            authorizationId: "qunit-stage-authorization",
            arguments: _.extend({patch: patch}, rowToken ? {rowToken: rowToken} : {}),
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

    QUnit.test("staged onchange updates relation domain and saves only once", async function (assert) {
        assert.expect(8);
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
        var context = commandContext(form);
        var first = await executeStage(context, {document_type: "special"});

        assert.ok(first.staged);
        assert.notOk(first.saved);
        assert.strictEqual(writes, 0);
        assert.strictEqual(context.getSnapshot().record.values.domain_key, "special");
        assert.deepEqual(form.model.get(form.handle).getDomain({fieldName: "candidate_id"}), [
            ["domain_key", "=", "special"],
        ]);

        var second = await executeStage(context, {candidate_id: 20});
        assert.ok(second.staged);
        assert.strictEqual(writes, 0, "sequential stages never persist the form");

        var saved = await Commands.execute(context, {
            tool: "odoo.save_current_form",
            authorizationId: "qunit-save-authorization",
            arguments: {},
        });
        assert.ok(saved.saved && writes === 1, "the explicit save persists all staged changes once");
        form.destroy();
    });

    QUnit.test("failed one2many batch restores rows and existing staged state", async function (assert) {
        assert.expect(7);
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
        var context = commandContext(form);
        await executeStage(context, {name: "已有暂存值"});
        var originalApply = form._applyChanges.bind(form);
        var relationCalls = 0;
        form._applyChanges = function (localId, changes, event) {
            if (changes.detail_item_ids) {
                relationCalls += 1;
                if (relationCalls === 2) {
                    return $.Deferred().reject(new Error("第二条明细操作失败")).promise();
                }
            }
            return originalApply(localId, changes, event);
        };

        var error = await rejected(executeStage(context, {detail_item_ids: {
            operations: [
                {operation: "update", id: 100, values: {quantity: 9}},
                {operation: "create", values: {name: "不应残留", quantity: 3}},
            ],
        }}));
        var state = context.getSnapshot();
        var rows = state.record.values.detail_item_ids.records;

        assert.strictEqual(error.code, "onchange_failed");
        assert.strictEqual(writes, 0, "失败批次没有数据库写入");
        assert.strictEqual(state.record.values.name, "已有暂存值", "已有 staged 值保留");
        assert.ok(state.record.dirtyFields.indexOf("name") !== -1, "已有 staged 标记保留");
        assert.strictEqual(state.record.values.detail_item_ids.count, 2, "没有新增行残留");
        assert.strictEqual(_.findWhere(rows, {id: 100}).values.quantity, 1, "已修改行恢复原值");
        assert.notOk(_.find(rows, function (row) {
            return row.values.name === "不应残留";
        }), "失败创建没有残留");
        form.destroy();
    });

    QUnit.test("visible One2many tokens create and stage a native child row", async function (assert) {
        assert.expect(10);
        var writes = 0;
        var tokens = {};
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
        var context = commandContext(form, tokens);
        var state = context.getSnapshot();
        var x2many = state.capabilities.x2many[0];
        var formButton = _.findWhere(state.capabilities.controls, {
            name: "action_confirm", type: "object",
        });

        assert.strictEqual(x2many.field, "line_ids");
        assert.strictEqual(x2many.relation, "agui.chat.test.line");
        assert.ok(x2many.token && x2many.rows[0].token);
        assert.ok(x2many.rows[0].fields.name && x2many.rows[0].fields.quantity);
        assert.ok(formButton && formButton.token, "visible Form object button has a token");
        assert.strictEqual(state.record.values.phone_number, "[redacted]");

        var create = _.findWhere(x2many.controls, {type: "create"});
        assert.ok(create && create.token, "native create control has a token");
        await Commands.execute(context, {
            tool: "odoo.activate_view_control",
            authorizationId: "qunit-create-authorization",
            arguments: {controlToken: create.token},
        });
        state = context.getSnapshot();
        x2many = state.capabilities.x2many[0];
        assert.strictEqual(x2many.rows.length, 2, "native One2many added a local row");

        var newRow = x2many.rows[x2many.rows.length - 1];
        var staged = await executeStage(context, {name: "差旅明细", quantity: 3}, newRow.token);
        assert.ok(staged.staged && !staged.saved);
        assert.strictEqual(writes, 0, "child row remains local until the parent save");
        form.destroy();
    });

    QUnit.test("many2one patch accepts serialized relation values", async function (assert) {
        assert.expect(7);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var pairResult = await executePatch(form, commandContext(form), {
            candidate_id: [11, "标准候选二"],
        });
        var state = snapshot(form);

        assert.ok(pairResult.saved);
        assert.strictEqual(state.record.values.candidate_id.id, 11);
        var objectResult = await executePatch(form, commandContext(form), {
            candidate_id: {id: 10, displayName: "标准唯一候选"},
        });
        state = snapshot(form);
        assert.ok(objectResult.saved);
        assert.strictEqual(state.record.values.candidate_id.id, 10);
        var invalidPair = await Adapter.applyPatch(form, state, {patch: {candidate_id: [11]}});
        var invalidObject = await Adapter.applyPatch(form, state, {patch: {candidate_id: {id: 11}}});
        assert.strictEqual(invalidPair.rejected[0].code, "invalid_value");
        assert.strictEqual(invalidObject.rejected[0].code, "invalid_value");
        assert.strictEqual(snapshot(form).record.values.candidate_id.id, 10, "invalid values are not applied");
        form.destroy();
    });

    QUnit.test("one2many generic operations and stale relation ids are rejected", async function (assert) {
        assert.expect(5);
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
        var unsafeCreate = await Adapter.applyPatch(form, state, {
            patch: {detail_item_ids: {operations: [{operation: "create", values: {
                name: "禁止猜测关系", candidate_id: {id: 10, displayName: "标准唯一候选"},
            }}]}},
        });
        assert.strictEqual(line.rejected[0].code, "invalid_one2many_patch");
        assert.strictEqual(unsafeCreate.rejected[0].code, "batch_requires_interactive");
        assert.strictEqual(snapshot(form).record.values.line_ids.count, 1, "no child row is created");
        form.destroy();
    });

    QUnit.test("generic one2many snapshot is metadata driven and bounded", async function (assert) {
        assert.expect(16);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var state = snapshot(form);
        var meta = state.fields.detail_item_ids;
        var value = state.record.values.detail_item_ids;

        assert.strictEqual(meta.type, "one2many");
        assert.strictEqual(meta.schemaSource, "form");
        assert.ok(/^[a-f0-9]{64}$/.test(meta.schemaHash));
        assert.deepEqual(meta.operations, {create: true, update: true, delete: true});
        assert.strictEqual(meta.childFields.candidate_id.relation, "agui.chat.test.option");
        assert.ok(meta.childFields.secret_token.redacted);
        assert.ok(meta.childFields.form_note);
        assert.notOk(meta.childFields.tree_note, "Form schema 不与 Tree schema 合并");
        assert.notOk(meta.childFields.form_note.loaded, "Form-only 字段未隐式装载");
        assert.deepEqual(value.ids, [100, 101]);
        assert.strictEqual(value.count, 2);
        assert.strictEqual(value.loadedCount, 2);
        assert.notOk(value.hasMore);
        assert.strictEqual(value.records.length, 2);
        assert.strictEqual(value.records[0].values.secret_token, "[redacted]");
        assert.strictEqual(value.records[0].modifiers.name.required, true);
        form.destroy();
    });

    QUnit.test("form-only one2many fields require native form activation", async function (assert) {
        assert.expect(3);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var state = snapshot(form);
        var result = await Adapter.applyPatch(form, state, {patch: {
            detail_item_ids: {operations: [{
                operation: "update", id: 100, values: {form_note: "禁止隐式装载"},
            }]},
        }});
        assert.strictEqual(state.fields.line_ids.schemaSource, "tree");
        assert.strictEqual(result.rejected[0].code, "requires_form_activation");
        assert.strictEqual(result.rejected[0].childField, "form_note");
        form.destroy();
    });

    QUnit.test("one patch saves parent create update and delete once", async function (assert) {
        assert.expect(11);
        var writes = 0;
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            res_id: 1,
            viewOptions: {mode: "edit"},
            mockRPC: function (route, args) {
                if (args.method === "write" && args.model === "agui.chat.test.document") {
                    writes += 1;
                }
                return this._super.apply(this, arguments);
            },
        });
        var context = commandContext(form);
        var patch = {
            name: "批量后单据",
            detail_item_ids: {
                operations: [
                    {operation: "create", values: {
                        name: "新增明细", quantity: 5, domain_key: "standard",
                    }},
                    {operation: "update", id: 100, values: {quantity: 4}},
                    {operation: "delete", id: 101},
                ],
            },
        };
        var preview = Adapter.buildPatchPreview(form, context.getSnapshot(), {patch: patch});
        assert.deepEqual(preview.rejected, [], "mixed One2many patch passes preview validation");
        var result = await executePatch(form, context, patch);
        var state = snapshot(form);
        var rows = state.record.values.detail_item_ids.records;
        var updated = _.findWhere(rows, {id: 100});
        var created = _.find(rows, function (row) { return row.values.name === "新增明细"; });

        assert.ok(result.saved);
        assert.strictEqual(writes, 1, "the parent form is written exactly once");
        assert.deepEqual(result.applied, ["name", "detail_item_ids"]);
        assert.strictEqual(state.record.values.name, "批量后单据");
        assert.strictEqual(state.record.values.detail_item_ids.count, 2);
        assert.ok(updated);
        assert.strictEqual(updated.values.quantity, 4);
        assert.ok(created && created.id, "the created row is persisted by the parent save");
        assert.notOk(_.findWhere(rows, {id: 101}));
        assert.strictEqual(result.undo_payload, false, "one2many patches never authorize undo");
        form.destroy();
    });

    QUnit.test("one2many relation search uses current native row tokens", async function (assert) {
        assert.expect(10);
        var writes = 0;
        var tokens = {};
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
        var context = commandContext(form, tokens);
        var state = context.getSnapshot();
        var x2many = _.findWhere(state.capabilities.x2many, {field: "detail_item_ids"});
        var existingRow = x2many.rows[0];
        var existing = await Commands.execute(context, {
            tool: "odoo.search_relation",
            arguments: {field: "candidate_id", rowToken: existingRow.token,
                query: "标准唯一候选", operation: "set"},
        });

        assert.deepEqual(_.pluck(existing.candidates, "id"), [10]);
        assert.strictEqual(existing.rowToken, existingRow.token);

        var create = _.findWhere(x2many.controls, {type: "create"});
        assert.ok(create && create.token);
        await Commands.execute(context, {
            tool: "odoo.activate_view_control",
            authorizationId: "qunit-create-detail-authorization",
            arguments: {controlToken: create.token},
        });
        state = context.getSnapshot();
        x2many = _.findWhere(state.capabilities.x2many, {field: "detail_item_ids"});
        var newRow = x2many.rows[x2many.rows.length - 1];
        assert.strictEqual(x2many.rows.length, 3);

        var stagedDomain = await executeStage(context, {domain_key: "special"}, newRow.token);
        assert.ok(stagedDomain.staged);
        state = context.getSnapshot();
        x2many = _.findWhere(state.capabilities.x2many, {field: "detail_item_ids"});
        newRow = x2many.rows[x2many.rows.length - 1];
        var special = await Commands.execute(context, {
            tool: "odoo.search_relation",
            arguments: {field: "candidate_id", rowToken: newRow.token,
                query: "特殊唯一候选", operation: "set"},
        });
        assert.deepEqual(_.pluck(special.candidates, "id"), [20]);
        assert.strictEqual(special.rowToken, newRow.token);

        var stagedCandidate = await executeStage(
            context, {candidate_id: {id: 20, displayName: "特殊唯一候选"}}, special.rowToken
        );
        assert.ok(stagedCandidate.staged);
        assert.strictEqual(writes, 0);
        var saved = await Commands.execute(context, {
            tool: "odoo.save_current_form",
            authorizationId: "qunit-save-detail-authorization",
            arguments: {},
        });
        assert.ok(saved.saved && writes === 1);
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

    QUnit.test("host switches to One2many modal and saves back to parent", async function (assert) {
        assert.expect(10);
        var form = await testUtils.createAsyncView({
            View: FormView,
            model: "agui.chat.test.document",
            data: testData(),
            arch: formArch(),
            archs: {
                "agui.chat.test.option,false,list":
                    '<tree><field name="name"/><field name="domain_key"/></tree>',
                "agui.chat.test.option,false,form":
                    '<form><field name="name"/><field name="domain_key"/></form>',
            },
            res_id: 1,
            viewOptions: {mode: "edit"},
        });
        var service = new HostService();
        service._enabled = true;
        service._actionManager = {
            getCurrentController: function () { return {widget: form}; },
        };
        service.start();
        await service._activateCurrentController();
        var parent = service.getSnapshot();
        var detail = _.findWhere(parent.capabilities.x2many, {field: "detail_item_ids"});
        assert.ok(parent.interactive, "root snapshot is interactive");
        assert.ok(detail, "root snapshot exposes detail_item_ids");
        if (!detail) {
            service.destroy();
            form.destroy();
            return;
        }
        var row = detail.rows[0];
        assert.ok(row && row.token, "root snapshot exposes a row token");

        var opened;
        try {
            opened = await service.executeHostCommand({
                tool: "odoo.open_x2many_record",
                arguments: {
                    target: Adapter.targetFromSnapshot(parent),
                    rowToken: row.token,
                    mode: "edit",
                },
            });
        } catch (error) {
            assert.ok(false, "open rejected: " + JSON.stringify({
                code: error && error.code,
                message: error && error.message,
                error: error && error.error,
                rejected: error && error.rejected,
                snapshot: error && error.snapshot,
                stack: error && error.stack,
            }));
            service.destroy();
            form.destroy();
            return;
        }
        var modal = service.getSnapshot();
        assert.ok(opened.ok);
        assert.strictEqual(modal.record.model, "agui.chat.test.line");
        assert.notStrictEqual(modal.controller.controllerId, parent.controller.controllerId);

        var patched = await service.executeHostCommand({
            tool: "odoo.patch_current_form",
            authorizationId: "qunit-modal-patch",
            arguments: {
                target: Adapter.targetFromSnapshot(modal),
                patch: {quantity: 9},
            },
        });
        var restored = service.getSnapshot();
        var restoredRows = restored.record.values.detail_item_ids.records;
        assert.ok(patched.ok && patched.saved);
        assert.strictEqual(patched.persistence, "parent_pending");
        assert.strictEqual(restored.controller.controllerId !== modal.controller.controllerId, true);
        assert.strictEqual(_.findWhere(restoredRows, {id: 100}).values.quantity, 9);

        service.destroy();
        form.destroy();
    });
});
