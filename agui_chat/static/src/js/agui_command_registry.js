odoo.define("agui_chat.command_registry", function (require) {
    "use strict";

    var Adapter = require("agui_chat.model_adapter");

    var PAGE_TARGET = {
        type: "object",
        additionalProperties: false,
        required: ["snapshotId", "hostRevision"],
        properties: {
            snapshotId: {type: "string"},
            hostRevision: {type: "integer"},
        },
    };

    var VIEW_TARGET = {
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
    };

    function schema(properties, required) {
        return {
            type: "object",
            additionalProperties: false,
            required: ["target"].concat(required || []),
            properties: _.extend({target: VIEW_TARGET}, properties || {}),
        };
    }

    function pageSchema(properties, required) {
        return {
            type: "object",
            additionalProperties: false,
            required: ["target"].concat(required || []),
            properties: _.extend({target: PAGE_TARGET}, properties || {}),
        };
    }

    var CATALOG = [
        {
            name: "odoo.read_mentioned_records",
            description: "批量读取用户明确选择且绑定为引用数据动作的 1 至 5 条记录。",
            parameters: pageSchema({
                tokens: {
                    type: "array", minItems: 1, maxItems: 5, uniqueItems: true,
                    items: {type: "string", minLength: 1, maxLength: 160},
                },
            }, ["tokens"]),
        },
        {
            name: "odoo.open_mentioned_menu",
            description: "执行用户明确绑定的菜单打开或新建动作。",
            parameters: pageSchema({
                token: {type: "string", minLength: 1, maxLength: 160},
            }, ["token"]),
        },
        {
            name: "odoo.open_mentioned_record",
            description: "执行用户明确绑定的记录查看或编辑动作。",
            parameters: pageSchema({
                token: {type: "string", minLength: 1, maxLength: 160},
            }, ["token"]),
        },
        {
            name: "odoo.apply_mentioned_filter",
            description: "应用用户明确绑定的收藏筛选或当前临时筛选，并替换当前查询。",
            parameters: pageSchema({
                token: {type: "string", minLength: 1, maxLength: 160},
            }, ["token"]),
        },
        {
            name: "odoo.open_menu",
            description: "打开用户已明确选择的 Odoo 窗口菜单；不要猜测 menuId。",
            parameters: pageSchema({
                menuId: {type: "integer", minimum: 1},
            }, ["menuId"]),
        },
        {
            name: "odoo.apply_filter",
            description: "在当前 List 或 Kanban SearchView 中添加一个可见原生筛选，并返回匹配记录候选。",
            parameters: schema({
                domain: {type: "array", description: "已验证的 JSON domain 条件列表；单个条件也写成 [[字段, 运算符, 值]]，禁止字符串和字段点号路径。"},
                label: {type: "string", minLength: 1, maxLength: 120},
            }, ["domain", "label"]),
        },
        {
            name: "odoo.open_record",
            description: "使用当前快照提供的记录 token 打开记录，可进入只读或编辑态。",
            parameters: schema({
                recordToken: {type: "string", minLength: 1, maxLength: 160},
                mode: {type: "string", enum: ["readonly", "edit"]},
            }, ["recordToken", "mode"]),
        },
        {
            name: "odoo.open_create",
            description: "使用当前 action 上下文进入原生完整新建表单；不填写也不保存。",
            parameters: schema(),
        },
        {
            name: "odoo.enter_edit_mode",
            description: "让当前原生表单进入编辑模式；不修改字段，也不保存。",
            parameters: schema(),
        },
        {
            name: "odoo.activate_view_control",
            description: "激活当前 Kanban 快照中的可见控件 token；对象按钮始终需要用户确认。",
            parameters: schema({
                controlToken: {type: "string", minLength: 1, maxLength: 160},
            }, ["controlToken"]),
        },
        {
            name: "odoo.search_relation",
            description: "使用当前表单的域和上下文搜索可写关系字段。",
            parameters: schema({
                field: {type: "string", minLength: 1, maxLength: 128},
                rowToken: {type: "string", minLength: 1, maxLength: 160},
                query: {type: "string", minLength: 1, maxLength: 120},
                operation: {type: "string", enum: ["set", "link", "unlink"]},
                limit: {type: "integer", minimum: 1, maximum: 20},
            }, ["field", "query", "operation"]),
        },
        {
            name: "odoo.stage_current_form",
            description: "在当前原生表单暂存字段并执行 onchange，但不保存；修改 One2many 行时必须使用当前编辑态快照中的 rowToken。",
            parameters: schema({
                rowToken: {type: "string", minLength: 1, maxLength: 160},
                patch: {
                    type: "object",
                    description: "当前表单或当前快照签发子表行的字段名到新值映射。",
                },
            }, ["patch"]),
        },
        {
            name: "odoo.patch_current_form",
            description: "应用并保存当前表单变更；只读模式会自动进入编辑模式并等待宿主状态同步，无需用户手动点击编辑。",
            parameters: schema({
                patch: {
                    type: "object",
                    description: "字段名到新值的映射；直接传 JSON 对象，不要传序列化后的 JSON 字符串。",
                },
            }, ["patch"]),
        },
        {
            name: "odoo.validate_current_form",
            description: "执行当前原生表单渲染器校验。",
            parameters: schema(),
        },
        {
            name: "odoo.save_current_form",
            description: "通过当前原生 FormController 保存表单。",
            parameters: schema(),
        },
        {
            name: "odoo.discard_current_form",
            description: "确认后放弃当前原生表单的更改。",
            parameters: schema(),
        },
    ];

    var COMMANDS = {};
    var WRITE_COMMANDS = {
        "odoo.stage_current_form": true,
        "odoo.patch_current_form": true,
        "odoo.undo_current_form": true,
        "odoo.save_current_form": true,
        "odoo.discard_current_form": true,
    };
    var BOUND_MENTION_COMMANDS = {
        "odoo.read_mentioned_records": true,
        "odoo.open_mentioned_menu": true,
        "odoo.open_mentioned_record": true,
        "odoo.apply_mentioned_filter": true,
    };
    function commandError(code, message) {
        var error = new Error(message || code);
        error.code = code;
        return error;
    }

    function validationError(invalidFields) {
        return _.extend(commandError("validation_failed", "表单原生校验未通过。"), {
            invalidFields: invalidFields,
        });
    }

    function saveRecord(context, controller) {
        return $.when(controller.saveRecord()).then(null, function () {
            return context.refresh(controller, true).then(function () {
                throw commandError("save_failed", "表单保存失败，请修正后重试或放弃更改。");
            });
        });
    }

    function requireForm(context) {
        var snapshot = context.getSnapshot();
        var controller = context.getController();
        if (!snapshot.interactive || snapshot.controller.viewType !== "form" || !controller) {
            throw commandError("no_current_form", "当前没有可用的 Odoo 原生表单。")
        }
        return controller;
    }

    function requireView(context, allowedTypes) {
        var snapshot = context.getSnapshot();
        var controller = context.getController();
        if (!snapshot.interactive || !controller ||
                allowedTypes.indexOf(snapshot.controller.viewType) === -1) {
            throw commandError("no_current_view", "当前没有可用的 Odoo 原生视图。");
        }
        return controller;
    }

    function rejectUnsavedChanges(context) {
        if (context.hasUnsavedChanges()) {
            throw commandError("unsaved_changes", "当前表单有未保存修改，请先保存或放弃后再继续。");
        }
    }

    function navigationResult(context, before, result) {
        return context.waitForSnapshotChange(before.snapshotId).then(function (snapshot) {
            return _.extend({navigated: snapshot.snapshotId !== before.snapshotId}, result || {});
        });
    }

    function sameFormTarget(before, after) {
        return before && after && before.interactive && after.interactive &&
            before.controller.controllerId === after.controller.controllerId &&
            before.controller.dataPointId === after.controller.dataPointId &&
            before.record && after.record &&
            before.record.model === after.record.model &&
            before.record.resId === after.record.resId;
    }

    function ensureFormEditMode(context, controller) {
        var before = context.getSnapshot();
        var enteredEditMode = false;
        var unlocked;
        if (controller.mode === "edit" && before.controller.mode === "edit") {
            return $.when({controller: controller, snapshot: before, enteredEditMode: false});
        }
        unlocked = controller.mutex && _.isFunction(controller.mutex.getUnlockedDef) ?
            controller.mutex.getUnlockedDef() : $.when();
        return $.when(unlocked).then(function () {
            if (controller.mode === "edit") {
                return;
            }
            if (!_.isFunction(controller.is_action_enabled) ||
                    !controller.is_action_enabled("edit")) {
                throw commandError("form_edit_not_allowed", "当前表单不允许编辑。");
            }
            if (!_.isFunction(controller._setMode)) {
                throw commandError("edit_mode_unavailable", "当前表单无法进入编辑模式。");
            }
            enteredEditMode = true;
            return controller._setMode("edit");
        }).then(function () {
            return context.refresh(controller, true);
        }).then(function () {
            var after = context.getSnapshot();
            if (!sameFormTarget(before, after)) {
                throw commandError("controller_conflict", "进入编辑模式时当前记录已变化。");
            }
            if (controller.mode !== "edit" || after.controller.mode !== "edit") {
                throw commandError("edit_mode_unavailable", "当前表单未进入编辑模式。");
            }
            return {controller: controller, snapshot: after, enteredEditMode: enteredEditMode};
        }, function (error) {
            if (error && error.code) {
                throw error;
            }
            throw commandError("edit_mode_unavailable", "当前表单无法进入编辑模式。");
        });
    }

    function resolveRowBinding(context, args) {
        var row = args && args.rowToken &&
            context.resolveToken(args.rowToken, "x2many_row");
        if (!args || !args.rowToken) {
            return false;
        }
        if (!row || !context.validateToken(row, "x2many_row")) {
            throw commandError("stale_x2many_row_token", "One2many 行令牌已过期，请使用最新快照重试。");
        }
        return row;
    }

    COMMANDS["odoo.search_relation"] = function (context, args) {
        return Adapter.searchRelation(
            requireForm(context), context.getSnapshot(), args, resolveRowBinding(context, args)
        );
    };

    function mentionBinding(args, kind) {
        var bindings = args && args.__mention;
        var binding = _.isArray(bindings) && bindings.length === 1 ? bindings[0] : false;
        if (!binding || binding.kind !== kind) {
            throw commandError("invalid_mention_binding", "对象引用绑定无效。");
        }
        return binding;
    }

    function openMentionMenu(context, binding) {
        var before = context.getSnapshot();
        rejectUnsavedChanges(context);
        return $.when(context.openMenu(binding.menu_id)).then(function () {
            return context.waitForSnapshotChange(before.snapshotId);
        });
    }

    COMMANDS["odoo.read_mentioned_records"] = function (context, args, call) {
        if (!_.isArray(args.__mention) || args.__mention.length !== args.tokens.length) {
            throw commandError("invalid_mention_binding", "记录引用绑定无效。");
        }
        return context.readMentions(args.tokens, call.authorizationId);
    };

    COMMANDS["odoo.open_mentioned_menu"] = function (context, args) {
        var binding = mentionBinding(args, "menu");
        return openMentionMenu(context, binding).then(function (snapshot) {
            if (binding.action !== "create") {
                return {opened: true, mode: "open", label: binding.label};
            }
            var controller = context.getController();
            if (!controller || !(snapshot.capabilities && snapshot.capabilities.create)) {
                throw commandError("create_not_allowed", "当前菜单不允许新建记录。");
            }
            return $.when(context.openCreate(controller)).then(function () {
                return context.waitForSnapshotChange(snapshot.snapshotId);
            }).then(function (next) {
                return {opened: next.snapshotId !== snapshot.snapshotId, mode: "create", label: binding.label};
            });
        });
    };

    COMMANDS["odoo.open_mentioned_record"] = function (context, args) {
        var binding = mentionBinding(args, "record");
        var mode = binding.action === "edit" ? "edit" : "readonly";
        return openMentionMenu(context, binding).then(function (snapshot) {
            var model = snapshot.record && snapshot.record.model ||
                snapshot.selection && snapshot.selection.model;
            if (model !== binding.model) {
                throw commandError("mention_model_mismatch", "菜单与所选记录模型不匹配。");
            }
            return $.when(context.openMentionedRecord(binding.record_id, mode)).then(function () {
                return context.waitForSnapshotChange(snapshot.snapshotId);
            });
        }).then(function (snapshot) {
            if (!snapshot.record || snapshot.record.model !== binding.model ||
                    snapshot.record.resId !== binding.record_id) {
                throw commandError("record_open_failed", "客户端未进入所选记录表单。");
            }
            if (mode === "edit" && snapshot.controller.mode !== "edit") {
                throw commandError("edit_mode_unavailable", "所选记录未进入编辑模式。");
            }
            return {opened: true, mode: mode, displayName: binding.label};
        });
    };

    COMMANDS["odoo.apply_mentioned_filter"] = function (context, args) {
        var bindings = args && args.__mention;
        var binding = _.isArray(bindings) && bindings.length === 1 ? bindings[0] : false;
        if (!binding || ["saved_filter", "current_filter"].indexOf(binding.kind) === -1) {
            throw commandError("invalid_mention_binding", "筛选引用绑定无效。");
        }
        return openMentionMenu(context, binding).then(function (snapshot) {
            return $.when(context.applyMentionFilter(binding)).then(function () {
                return context.waitForSnapshotChange(snapshot.snapshotId);
            });
        }).then(function (snapshot) {
            return {
                applied: true,
                label: binding.label,
                snapshotId: snapshot.snapshotId,
                hostRevision: snapshot.hostRevision,
            };
        });
    };

    COMMANDS["odoo.open_menu"] = function (context, args) {
        var before = context.getSnapshot();
        rejectUnsavedChanges(context);
        return $.when(context.openMenu(args.menuId)).then(function (menu) {
            return navigationResult(context, before, {menu: menu});
        });
    };

    COMMANDS["odoo.apply_filter"] = function (context, args) {
        var controller = requireView(context, ["list", "kanban"]);
        var snapshot = context.getSnapshot();
        var searchView = controller.searchView;
        var label = String(args.label || "").trim();
        var domain;
        var added;
        if (!snapshot.capabilities || !snapshot.capabilities.filter ||
                !searchView || !_.isFunction(searchView.updateFilters)) {
            throw commandError("filter_unavailable", "当前视图不支持原生筛选。");
        }
        if (!label || label.length > 120) {
            throw commandError("invalid_filter_label", "筛选标签长度无效。");
        }
        try {
            domain = Adapter.validateFilterDomain(snapshot, args.domain);
        } catch (error) {
            throw commandError(error.code || "invalid_filter_domain", "筛选 domain 未通过校验。");
        }
        added = searchView.updateFilters(
            [{domain: domain, help: label}], controller.__aguiAssistantFilters || []
        );
        controller.__aguiAssistantFilters = added;
        return $.when(_.isFunction(controller.reload) ? controller.reload() : undefined).then(function () {
            return context.refresh(controller, true);
        }).then(function (nextSnapshot) {
            var capabilities = nextSnapshot.capabilities || {};
            if (capabilities.totalCount !== 1 || (capabilities.records || []).length) {
                return nextSnapshot;
            }
            return Adapter.expandUniqueRecordCandidate(controller).then(function (expanded) {
                return expanded ? context.refresh(controller, true) : nextSnapshot;
            });
        }).then(function (nextSnapshot) {
            var capabilities = nextSnapshot.capabilities || {};
            return {
                label: label,
                domain: domain,
                count: capabilities.totalCount || 0,
                candidates: capabilities.records || [],
                snapshotId: nextSnapshot.snapshotId,
                hostRevision: nextSnapshot.hostRevision,
            };
        });
    };

    COMMANDS["odoo.open_record"] = function (context, args) {
        var before = context.getSnapshot();
        var record = context.resolveToken(args.recordToken, "record");
        rejectUnsavedChanges(context);
        if (!record || !context.validateToken(record, "record")) {
            throw commandError("stale_record_token", "记录候选已过期，请重新筛选。");
        }
        if (args.mode === "edit" && !(before.capabilities && before.capabilities.edit)) {
            throw commandError("record_edit_not_allowed", "当前 action 不允许编辑记录。");
        }
        return $.when(context.openRecord(record, args.mode)).then(function () {
            return navigationResult(context, before, {
                mode: args.mode, displayName: record.displayName,
            });
        }).then(function (result) {
            if (!result.navigated) {
                throw commandError("record_open_failed", "客户端未进入记录表单。");
            }
            result.opened = true;
            return result;
        });
    };

    COMMANDS["odoo.open_create"] = function (context) {
        var before = context.getSnapshot();
        var controller = requireView(context, ["form", "list", "kanban"]);
        rejectUnsavedChanges(context);
        if (!(before.capabilities && before.capabilities.create)) {
            throw commandError("create_not_allowed", "当前 action 不允许新建记录。");
        }
        return $.when(context.openCreate(controller)).then(function () {
            return navigationResult(context, before, {opened: true, mode: "create"});
        });
    };

    COMMANDS["odoo.enter_edit_mode"] = function (context) {
        return ensureFormEditMode(context, requireForm(context)).then(function (editable) {
            return {
                editing: true,
                enteredEditMode: editable.enteredEditMode,
            };
        });
    };

    COMMANDS["odoo.activate_view_control"] = function (context, args) {
        var before = context.getSnapshot();
        var control = context.resolveToken(args.controlToken, "control");
        requireView(context, ["form", "list", "kanban"]);
        if (!control || !context.validateToken(control, "control")) {
            throw commandError("stale_control_token", "页面控件已过期，请刷新页面后重试。");
        }
        if (["open", "edit", "action"].indexOf(control.type) !== -1 &&
                !control.x2manyAction) {
            rejectUnsavedChanges(context);
        }
        return $.when(context.activateControl(control)).then(function () {
            return navigationResult(context, before, {
                activated: true,
                controlType: control.type,
                label: control.label,
                recordLabel: control.recordLabel,
            });
        });
    };

    COMMANDS["odoo.stage_current_form"] = function (context, args) {
        var controller = requireForm(context);
        if (args.rowToken && controller.mode !== "edit") {
            throw commandError(
                "edit_mode_required",
                "修改 One2many 行前必须先进入编辑模式并使用新快照中的行令牌。"
            );
        }
        return ensureFormEditMode(context, controller).then(function (editable) {
            var rowBinding = resolveRowBinding(context, args);
            var options = {allowStaged: true, rowBinding: rowBinding};
            var preview = Adapter.buildPatchPreview(
                controller, editable.snapshot, args, options
            );
            return Adapter.applyPatch(
                controller, editable.snapshot, args, options
            ).then(function (prepared) {
                if (prepared.rejected.length) {
                    var code = prepared.rejected.length === 1 ?
                        prepared.rejected[0].code : "patch_rejected";
                    throw _.extend(commandError(code, "表单暂存变更已被拒绝。"), {
                        rejected: prepared.rejected,
                    });
                }
                Adapter.markStagedPatch(controller, rowBinding, prepared.applied);
                return context.refresh(controller, true).then(function (snapshot) {
                    return {
                        applied: prepared.applied,
                        rejected: [],
                        staged: true,
                        saved: false,
                        enteredEditMode: editable.enteredEditMode,
                        rowToken: rowBinding ? args.rowToken : false,
                        preview: preview,
                        dirtyFields: snapshot.record && snapshot.record.dirtyFields || [],
                    };
                });
            }, function (error) {
                if (error && error.code) {
                    throw error;
                }
                throw commandError(
                    "onchange_failed", error && error.message || "表单 onchange 执行失败。"
                );
            });
        });
    };

    COMMANDS["odoo.patch_current_form"] = function (context, args) {
        var controller = requireForm(context);
        if (!_.isFunction(controller.saveRecord)) {
            throw commandError("save_unavailable", "当前 FormController 无法保存记录。")
        }
        return ensureFormEditMode(context, controller).then(function (editable) {
            var preview = Adapter.buildPatchPreview(controller, editable.snapshot, args);
            return Adapter.applyPatch(controller, editable.snapshot, args).then(function (prepared) {
                prepared.enteredEditMode = editable.enteredEditMode;
                prepared.snapshot = editable.snapshot;
                prepared.preview = preview;
                return prepared;
            }, function (error) {
                if (error && error.code) {
                    throw error;
                }
                throw commandError("onchange_failed", error && error.message || "表单 onchange 执行失败。");
            });
        }).then(function (prepared) {
            if (prepared.rejected.length) {
                var code = prepared.rejected.length === 1 ?
                    prepared.rejected[0].code : "patch_rejected";
                throw _.extend(commandError(code, "表单变更已被拒绝。"), {
                    rejected: prepared.rejected,
                });
            }
            return context.refresh(controller, true).then(function () {
                var invalidFields;
                if (!sameFormTarget(prepared.snapshot, context.getSnapshot())) {
                    throw commandError("controller_conflict", "保存前当前记录已变化。");
                }
                invalidFields = Adapter.validateForm(controller);
                if (invalidFields.length) {
                    throw validationError(invalidFields);
                }
                return saveRecord(context, controller);
            }).then(function () {
                return context.refresh(controller, true);
            }).then(function () {
                var completedSnapshot = context.getSnapshot();
                var undoPayload = Adapter.buildUndoPayload(controller, completedSnapshot, prepared);
                return {
                    applied: prepared.applied,
                    rejected: [],
                    saved: true,
                    enteredEditMode: prepared.enteredEditMode,
                    preview: prepared.preview,
                    receipt: {
                        target: Adapter.targetFromSnapshot(completedSnapshot),
                        changes: prepared.preview.changes,
                        savedAt: new Date().toISOString(),
                        undo: {available: !!undoPayload},
                    },
                    undo_payload: undoPayload || false,
                };
            });
        });
    };

    COMMANDS["odoo.undo_current_form"] = function (context, args) {
        var controller = requireForm(context);
        if (!_.isFunction(controller.saveRecord)) {
            throw commandError("save_unavailable", "当前 FormController 无法保存记录。")
        }
        return ensureFormEditMode(context, controller).then(function (editable) {
            var validation = Adapter.validateUndo(controller, editable.snapshot, args || {});
            if (!validation.ok) {
                throw commandError("undo_conflict", "当前表单已变化，无法撤销。")
            }
            return Adapter.applyPatch(controller, editable.snapshot, {patch: args.patch}).then(function (prepared) {
                if (prepared.rejected.length) {
                    throw _.extend(commandError("undo_conflict", "当前表单已变化，无法撤销。"), {
                        rejected: prepared.rejected,
                    });
                }
                return context.refresh(controller, true).then(function () {
                    if (!sameFormTarget(editable.snapshot, context.getSnapshot())) {
                        throw commandError("undo_conflict", "撤销前当前记录已变化。")
                    }
                    return saveRecord(context, controller);
                }).then(function () {
                    return context.refresh(controller, true);
                }).then(function () {
                    return {
                        undone: true,
                        saved: true,
                        applied: prepared.applied,
                        receipt: {
                            target: Adapter.targetFromSnapshot(context.getSnapshot()),
                            undoneAt: new Date().toISOString(),
                        },
                    };
                });
            });
        });
    };

    COMMANDS["odoo.validate_current_form"] = function (context) {
        var invalidFields = Adapter.validateForm(requireForm(context));
        return $.when({valid: !invalidFields.length, invalidFields: invalidFields});
    };

    COMMANDS["odoo.save_current_form"] = function (context) {
        var controller = requireForm(context);
        if (!_.isFunction(controller.saveRecord)) {
            throw commandError("save_unavailable", "当前 FormController 无法保存记录。")
        }
        return ensureFormEditMode(context, controller).then(function (editable) {
            var invalidFields = Adapter.validateForm(controller);
            if (invalidFields.length) {
                throw validationError(invalidFields);
            }
            return saveRecord(context, controller).then(function (changedFields) {
                return context.refresh(controller, true).then(function () {
                    return {
                        saved: true,
                        applied: changedFields || [],
                        enteredEditMode: editable.enteredEditMode,
                    };
                });
            });
        });
    };

    COMMANDS["odoo.discard_current_form"] = function (context) {
        var controller = requireForm(context);
        var ready;
        if (!controller.model || !_.isFunction(controller.model.discardChanges) ||
                !_.isFunction(controller._confirmSave)) {
            throw commandError("discard_unavailable", "原生放弃更改流程不可用。")
        }
        ready = controller.mutex && _.isFunction(controller.mutex.getUnlockedDef) ?
            $.when(controller.mutex.getUnlockedDef(), controller.savingDef) : $.when();
        return ready.then(function () {
            controller.model.discardChanges(controller.handle);
            if (_.isFunction(controller.model.canBeAbandoned) &&
                    controller.model.canBeAbandoned(controller.handle)) {
                if (!_.isFunction(controller._abandonRecord)) {
                    throw commandError("discard_unavailable", "当前新记录无法放弃。")
                }
                return controller._abandonRecord(controller.handle);
            }
            return controller._confirmSave(controller.handle);
        }).then(function () {
            controller.__aguiHostDirtyFields = [];
            return context.refresh(controller, true).then(function () {
                return {discarded: true};
            });
        });
    };

    function getCatalog() {
        return Adapter.clone(CATALOG);
    }

    function execute(context, call) {
        var tool = call && call.tool;
        var args = call && call.arguments || {};
        var control = tool === "odoo.activate_view_control" &&
            context.resolveToken(args.controlToken, "control");
        if (!COMMANDS[tool]) {
            return $.Deferred().reject(commandError("unsupported_command", "不支持此页面命令。")).promise();
        }
        if ((WRITE_COMMANDS[tool] || BOUND_MENTION_COMMANDS[tool] || control && control.type === "object") &&
                !(call && call.authorizationId)) {
            return $.Deferred().reject(commandError("authorization_required", "此命令需要服务端授权。")).promise();
        }
        try {
            return $.when(COMMANDS[tool](context, args, call));
        } catch (error) {
            return $.Deferred().reject(error).promise();
        }
    }

    return {
        getCatalog: getCatalog,
        execute: execute,
    };
});
