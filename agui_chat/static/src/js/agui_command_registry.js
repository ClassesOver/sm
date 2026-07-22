odoo.define("agui_chat.command_registry", function (require) {
    "use strict";

    var Adapter = require("agui_chat.model_adapter");
    var pyUtils = require("web.py_utils");

    var MENU_TARGET = {
        type: "object",
        additionalProperties: false,
        required: ["snapshotId", "hostRevision", "catalogId", "catalogRevision"],
        properties: {
            snapshotId: {type: "string"},
            hostRevision: {type: "integer"},
            catalogId: {type: "string"},
            catalogRevision: {type: "integer"},
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

    function menuSchema(properties, required) {
        return {
            type: "object",
            additionalProperties: false,
            required: ["target"].concat(required || []),
            properties: _.extend({target: MENU_TARGET}, properties || {}),
        };
    }

    var CATALOG = [
        {
            name: "odoo.navigate_menu",
            description: "导航到当前用户可见且自身配置 action 的末级 HRP 菜单。目标名称明确时只传 query：唯一匹配会直接打开，多候选会返回供用户选择；已有明确选择时只传候选原样返回的 menuId 和 actionId。target 始终使用当前 menuTarget。",
            parameters: _.extend(menuSchema({
                query: {type: "string", minLength: 1, maxLength: 400},
                menuId: {type: "integer", minimum: 1},
                actionId: {type: "integer", minimum: 1},
            }), {
                oneOf: [
                    {
                        required: ["query"],
                        not: {anyOf: [{required: ["menuId"]}, {required: ["actionId"]}]},
                    },
                    {
                        required: ["menuId", "actionId"],
                        not: {required: ["query"]},
                    },
                ],
            }),
        },
        {
            name: "odoo.apply_filter",
            description: "仅当当前宿主快照的 viewType 为 list 或 kanban 时调用；Odoo tree 视图按 list 兼容。在对应 SearchView 中添加一个可见原生筛选并返回匹配记录候选，其他视图类型禁止调用。",
            parameters: schema({
                domain: {type: "array", description: "已验证的 JSON domain 条件列表；单个条件也写成 [[字段, 运算符, 值]]，禁止字符串和字段点号路径。"},
                label: {type: "string", minLength: 1, maxLength: 120},
            }, ["domain", "label"]),
        },
        {
            name: "odoo.apply_group",
            description: "仅当当前宿主快照的 viewType 为 list 或 kanban 时调用；Odoo tree 视图按 list 兼容。设置对应 SearchView 的完整原生分组状态，其他视图类型禁止调用。",
            parameters: schema({
                groupBy: {
                    type: "array", maxItems: 3,
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
            }, ["groupBy"]),
        },
        {
            name: "odoo.export_current_view",
            description: "仅在当前 List 视图按业务导出规则把当前勾选记录或当前筛选结果导出为 XLSX 到 thread 工作区；必须使用当前 viewTarget。",
            parameters: schema({
                format: {type: "string", enum: ["xlsx"]},
            }, ["format"]),
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
            name: "odoo.switch_view",
            description: "仅当当前宿主快照的 viewType 为 list 或 kanban 时调用；Odoo tree 视图按 list 兼容。切换到当前 action 声明的原生 Kanban、List 或 Form 视图，从多记录视图切到 Form 会进入未保存的新建表单，Form 当前视图禁止调用。",
            parameters: schema({
                viewType: {type: "string", enum: ["kanban", "list", "form"]},
            }, ["viewType"]),
        },
        {
            name: "odoo.open_x2many_record",
            description: "使用当前快照的 One2many 行 token 打开原生明细表单。",
            parameters: schema({
                rowToken: {type: "string", minLength: 1, maxLength: 160},
                mode: {type: "string", enum: ["readonly", "edit"]},
            }, ["rowToken", "mode"]),
        },
        {
            name: "odoo.open_x2many_create",
            description: "使用当前快照的 One2many 字段 token 打开原生明细新建表单。",
            parameters: schema({
                fieldToken: {type: "string", minLength: 1, maxLength: 160},
            }, ["fieldToken"]),
        },
        {
            name: "odoo.reload_current_form",
            description: "在当前父表单没有未保存更改时调用原生 reload 获取导入结果。",
            parameters: schema(),
        },
        {
            name: "odoo.enter_edit_mode",
            description: "让当前原生表单进入编辑模式；不修改字段，也不保存。",
            parameters: schema(),
        },
        {
            name: "odoo.activate_view_control",
            description: "激活当前 Form、List 或 Kanban 快照中的可见控件 token；对象、删除和状态按钮始终需要用户确认。",
            parameters: schema({
                controlToken: {type: "string", minLength: 1, maxLength: 160},
            }, ["controlToken"]),
        },
        {
            name: "odoo.search_relation",
            description: "仅当当前宿主快照的 viewType 为 form 时调用；使用当前表单或当前快照 One2many 行 token 的实时域和上下文搜索可写关系字段，其他视图类型禁止调用。",
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
            description: "仅当当前宿主快照的 viewType 为 form 时调用；暂存字段并执行 onchange，但不保存，修改 One2many 行时必须使用当前编辑态快照中的 rowToken，其他视图类型禁止调用。",
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
            description: "仅当当前宿主快照的 viewType 为 form 时调用；应用并保存当前表单变更，其他视图类型禁止调用。只读模式会自动进入编辑模式并等待宿主状态同步，无需用户手动点击编辑。",
            parameters: schema({
                patch: {
                    type: "object",
                    description: "字段名到新值的映射；直接传 JSON 对象，不要传序列化后的 JSON 字符串。",
                },
            }, ["patch"]),
        },
        {
            name: "odoo.validate_current_form",
            description: "仅当当前宿主快照的 viewType 为 form 时调用；执行当前原生表单渲染器校验，其他视图类型禁止调用。",
            parameters: schema(),
        },
        {
            name: "odoo.save_current_form",
            description: "仅当当前宿主快照的 viewType 为 form 时调用；通过当前原生 FormController 保存表单，其他视图类型禁止调用。",
            parameters: schema(),
        },
        {
            name: "odoo.discard_current_form",
            description: "仅当当前宿主快照的 viewType 为 form 时调用；确认后放弃当前原生表单的更改，其他视图类型禁止调用。",
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
    function commandError(code, message) {
        var error = new Error(message || code);
        error.code = code;
        return error;
    }

    function recoverPatchError(context, controller, error) {
        var refreshed = error && error.aguiModelRestored ?
            context.refresh(controller, true) : $.when();
        return refreshed.then(function () {
            if (error && error.code) {
                throw error;
            }
            throw commandError(
                "onchange_failed", error && error.message || "表单 onchange 执行失败。"
            );
        });
    }

    function validationError(invalidFields) {
        return _.extend(commandError("validation_failed", "表单原生校验未通过。"), {
            invalidFields: invalidFields,
        });
    }

    function saveRecord(context, controller) {
        var saving = _.isFunction(context.saveForm) ?
            context.saveForm(controller) : $.when(controller.saveRecord()).then(function (fields) {
                return {changedFields: fields || [], persistence: "database"};
            });
        return $.when(saving).then(null, function () {
            return context.refresh(controller, true).then(function () {
                throw commandError("save_failed", "表单保存失败，请修正后重试或放弃更改。");
            });
        });
    }

    function requireForm(context) {
        var snapshot = context.getSnapshot();
        var controller = context.getController();
        if (!snapshot.interactive || snapshot.controller.viewType !== "form" || !controller) {
            throw commandError("no_current_form", "当前没有可用的 HRP 原生表单。")
        }
        return controller;
    }

    function requireView(context, allowedTypes) {
        var snapshot = context.getSnapshot();
        var controller = context.getController();
        if (!snapshot.interactive || !controller ||
                allowedTypes.indexOf(snapshot.controller.viewType) === -1) {
            throw commandError("no_current_view", "当前没有可用的 HRP 原生视图。");
        }
        return controller;
    }

    function rejectUnsavedChanges(context) {
        if (context.hasUnsavedChanges()) {
            throw commandError("unsaved_changes", "当前表单有未保存修改，请先保存或放弃后再继续。");
        }
    }

    function exportError(code, message) {
        throw commandError(code, message);
    }

    function exportColumns(controller, snapshot) {
        var columns = controller.renderer && controller.renderer.columns || [];
        return _.chain(columns).map(function (column) {
            var attrs = column && column.attrs || {};
            var name = attrs.name || column && column.name;
            var field = name && snapshot.fields && snapshot.fields[name];
            var invisible = column && column.invisible || attrs.invisible === "1" ||
                attrs.invisible === 1 || attrs.invisible === true;
            if (!name || column && column.tag === "button" || invisible || !field ||
                    field.type === "binary" || field.invisible || field.redacted) {
                return false;
            }
            return {name: name, label: String(attrs.string || field.string || name).slice(0, 160)};
        }).compact().value();
    }

    function exportModel(snapshot) {
        return snapshot.record && snapshot.record.model ||
            snapshot.selection && snapshot.selection.model || false;
    }

    function directExportFields(controller, record, columns) {
        var fields = record && record.fields || {};
        var fieldsInfo = record && record.fieldsInfo && record.fieldsInfo.list || {};
        var precisionMap = {};
        if (_.isFunction(controller.call)) {
            precisionMap = controller.call(
                "session_storage", "getItem", "decimal_precision"
            ) || {};
        }
        return _.map(columns, function (column) {
            var field = fields[column.name] || {};
            var fieldInfo = fieldsInfo[column.name] || {};
            var options = fieldInfo.options || {};
            var precisionName = options.decimal_precision;
            var decimalPrecision = precisionName && precisionMap[precisionName];
            return {
                name: column.name,
                label: column.label,
                fieldInfo: _.extend({}, fieldInfo, {
                    type: field.type,
                    decimal_precision: ["float", "integer"].indexOf(field.type) !== -1 ?
                        (decimalPrecision === undefined ? 2 : decimalPrecision) : undefined,
                }),
            };
        });
    }

    function flattenDirectExportData(items, selectedIds, num) {
        var parentNum = 0;
        return _.reduce(items || [], function (result, item) {
            if (selectedIds.length && _.isArray(item && item.data)) {
                parentNum = _.intersection(selectedIds, item.res_ids || []).length;
            } else {
                parentNum = item && item.data && item.data.length;
            }
            if (_.isArray(item && item.data) && item.data.length) {
                return result.concat(flattenDirectExportData(item.data, selectedIds, parentNum));
            }
            return result.concat({
                count: item && item.count || 1,
                isOpen: item && item.isOpen,
                isSelect: item && item.isSelect,
                num: num || 0,
            });
        }, []);
    }

    function directExportData(record, selectedIds) {
        var recordData = $.extend(true, {}, record || {});
        function trimSelectedData(dataPoint) {
            if (!dataPoint || !_.isArray(dataPoint.data)) {
                return;
            }
            $.each(dataPoint.data, function (_index, item) {
                if (!item) {
                    return;
                }
                if (item.count !== 0) {
                    trimSelectedData(item);
                } else if (selectedIds.length) {
                    var count = _.intersection(selectedIds, dataPoint.res_ids || []).length;
                    dataPoint.data = dataPoint.data.slice(0, count);
                    return false;
                }
            });
        }
        trimSelectedData(recordData);
        return flattenDirectExportData(recordData.data, selectedIds);
    }

    function directExportOrder(orderedBy) {
        return _.map(orderedBy || [], function (order) {
            return order.name + (order.asc !== false ? " ASC" : " DESC");
        }).join(", ");
    }

    function directExportDetailOrder(controller, record) {
        var orderedBy = directExportOrder(record && record.orderedBy);
        var defaultOrder = controller.renderer && controller.renderer.arch &&
            controller.renderer.arch.attrs.default_order;
        if (orderedBy || !defaultOrder) {
            return orderedBy;
        }
        return _.map(defaultOrder.split(","), function (order) {
            var parts = order.trim().split(/\s+/);
            return parts[0] + (String(parts[1] || "").toLowerCase() === "desc" ?
                " DESC" : " ASC");
        }).join(", ");
    }

    function directExportGroupOrder(record) {
        var groupedBy = record && record.groupedBy || [];
        if (!groupedBy.length) {
            return undefined;
        }
        var rawGroupBy = groupedBy[0].split(":")[0];
        var fields = record.fields || {};
        return directExportOrder(_.filter(record.orderedBy || [], function (order) {
            return order.name === rawGroupBy || fields[order.name] &&
                fields[order.name].group_operator !== undefined;
        }));
    }

    function exportPath(snapshot, callId, format) {
        var captured = new Date(snapshot.capturedAt);
        var timestamp = isNaN(captured.getTime()) ? "invalid" : captured.toISOString()
            .replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
        var model = String(exportModel(snapshot) || "export")
            .replace(/[^a-zA-Z0-9_.-]/g, "_");
        var shortId = String(callId || "export").replace(/[^a-zA-Z0-9]/g, "").slice(0, 12) || "export";
        return "exports/" + model + "-" + timestamp + "-" + shortId + "." + format;
    }

    function buildExportBinding(context, args, call) {
        var snapshot = context.getSnapshot();
        var controller = context.getController();
        var format = String(args.format || "");
        var columns;
        var ids;
        var domainReady;
        var record;
        if (!snapshot.interactive || snapshot.controller.viewType !== "list" || !controller) {
            exportError("no_current_list", "当前没有可用的 HRP 原生列表。");
        }
        if (format !== "xlsx") {
            exportError("invalid_arguments", "导出格式必须是 xlsx。");
        }
        if (controller.model && _.isFunction(controller.model.isDirty) &&
                controller.model.isDirty(controller.handle)) {
            exportError("unsaved_changes", "当前列表有未保存修改，请先保存或放弃后再导出。");
        }
        columns = exportColumns(controller, snapshot);
        if (!columns.length) {
            exportError("export_no_fields", "当前列表没有可安全导出的列。");
        }
        record = controller.model.get(controller.handle);
        domainReady = $.when(
            _.isFunction(controller.getActiveDomain) ? controller.getActiveDomain() : undefined
        );
        return domainReady.then(function (activeDomain) {
            var domain;
            if (activeDomain === undefined) {
                ids = _.isFunction(controller.getSelectedIds) ? controller.getSelectedIds() || [] : [];
                domain = record && record.domain || [];
            } else {
                ids = false;
                domain = activeDomain || [];
            }
            var recordCount = ids && ids.length || snapshot.capabilities &&
                snapshot.capabilities.totalCount || 0;
            var selectedIds = ids || [];
            var directContext = record && _.isFunction(record.getContext) ?
                pyUtils.eval("contexts", [record.getContext(), {
                    export_way: "direct",
                    expWay: controller.expWay,
                }]) : {export_way: "direct", expWay: controller.expWay};
            return {
                publicArguments: {
                    target: Adapter.clone(args.target),
                    format: format,
                    field_names: _.pluck(columns, "name"),
                    __export: {
                        workspacePath: exportPath(snapshot, call && call.id, format),
                        format: format,
                        scope: ids && ids.length ? "selection" : "filter",
                        recordCount: recordCount,
                        fieldCount: columns.length,
                        columns: _.pluck(columns, "label"),
                    },
                },
                privateSpec: {
                    model: exportModel(snapshot),
                    fields: directExportFields(controller, record, columns),
                    data: directExportData(record, selectedIds),
                    ids: ids || false,
                    domain: domain,
                    groupby: (record && record.groupedBy || []).slice(0),
                    context: directContext,
                    action: snapshot.action && snapshot.action.id || false,
                    orderby: directExportGroupOrder(record),
                    detail_orderby: directExportDetailOrder(controller, record),
                },
            };
        });
    }

    function sameExportBinding(left, right) {
        return _.isEqual(left || {}, right || {});
    }

    COMMANDS["odoo.export_current_view"] = function (context, args, call) {
        return buildExportBinding(context, args, call).then(function (binding) {
            if (!sameExportBinding(binding.publicArguments.__export, args.__export) ||
                    !sameExportBinding(binding.publicArguments.field_names, args.field_names)) {
                exportError("stale_snapshot", "当前导出范围或列已变化，请重新确认。");
            }
            return context.exportCurrentView(call, binding.privateSpec, args.__export);
        });
    };

    function navigationResult(context, before, result) {
        return context.waitForInteractiveSnapshotChange(before.snapshotId).then(function (snapshot) {
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

    COMMANDS["odoo.navigate_menu"] = function (context, args) {
        var snapshot = context.getSnapshot();
        var hasQuery = _.isString(args.query) && !!args.query.trim();
        var hasMenuId = _.isNumber(args.menuId) && args.menuId > 0;
        var hasActionId = _.isNumber(args.actionId) && args.actionId > 0;
        var result;
        var selected;
        if (hasQuery === (hasMenuId || hasActionId) || hasMenuId !== hasActionId) {
            throw commandError(
                "invalid_menu_navigation",
                "菜单导航必须只提供 query，或同时提供 menuId 和 actionId。"
            );
        }
        if (!hasQuery) {
            rejectUnsavedChanges(context);
            return $.when(context.openMenu(args.menuId, args.actionId)).then(function (menu) {
                return navigationResult(context, snapshot, {menu: menu});
            });
        }
        result = context.searchMenus(args.query);
        result = _.extend({}, result, {
            snapshotId: snapshot.snapshotId,
            hostRevision: snapshot.hostRevision,
        });
        if (result.truncated || result.matchCount !== 1 || result.candidates.length !== 1) {
            return _.extend({}, result, {navigated: false});
        }
        selected = result.candidates[0];
        rejectUnsavedChanges(context);
        return $.when(context.openMenu(selected.menuId, selected.actionId)).then(function (menu) {
            return navigationResult(context, snapshot, _.extend({}, result, {menu: menu}));
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

    COMMANDS["odoo.apply_group"] = function (context, args) {
        var snapshot = context.getSnapshot();
        var controller = context.getController();
        var groupBy;
        if (!snapshot.interactive || !controller ||
                ["list", "kanban"].indexOf(snapshot.controller.viewType) === -1 ||
                !snapshot.capabilities || !snapshot.capabilities.group) {
            throw commandError("group_unavailable", "当前视图不支持原生分组。");
        }
        try {
            groupBy = Adapter.validateGroupBy(snapshot, args.groupBy);
            Adapter.applyGroupBy(controller, groupBy);
        } catch (error) {
            throw commandError(error.code || "invalid_group_by", error.message || "分组参数未通过校验。");
        }
        return $.when(_.isFunction(controller.reload) ? controller.reload() : undefined).then(function () {
            return context.refresh(controller, true);
        }).then(function (nextSnapshot) {
            return {
                applied: true,
                groupBy: nextSnapshot.capabilities && _.isArray(nextSnapshot.capabilities.groupBy) ?
                    nextSnapshot.capabilities.groupBy : groupBy,
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

    COMMANDS["odoo.switch_view"] = function (context, args) {
        var before = context.getSnapshot();
        var controller = requireView(context, ["list", "kanban"]);
        var viewTypes = before.capabilities && before.capabilities.viewTypes || [];
        rejectUnsavedChanges(context);
        if (before.controller.viewType === args.viewType) {
            throw commandError("view_already_active", "目标视图已是当前视图。");
        }
        if (viewTypes.indexOf(args.viewType) === -1) {
            throw commandError("view_unavailable", "当前 action 不提供目标视图。");
        }
        if (args.viewType === "form" && !(before.capabilities && before.capabilities.create)) {
            throw commandError("create_not_allowed", "当前 action 不允许通过 Form 视图新建记录。");
        }
        return $.when(context.switchView(controller, args.viewType)).then(function () {
            return navigationResult(context, before, {viewType: args.viewType});
        }).then(function (result) {
            var snapshot = context.getSnapshot();
            if (!result.navigated || !snapshot.controller ||
                    snapshot.controller.viewType !== args.viewType) {
                throw commandError("switch_view_failed", "客户端未进入目标视图。");
            }
            return result;
        });
    };

    COMMANDS["odoo.open_x2many_record"] = function (context, args) {
        var before = context.getSnapshot();
        var row = context.resolveToken(args.rowToken, "x2many_row");
        if (!row || !context.validateToken(row, "x2many_row")) {
            throw commandError("stale_x2many_row_token", "明细行令牌已过期，请刷新后重试。");
        }
        var capability = _.findWhere(
            before.capabilities && before.capabilities.x2many || [], {field: row.fieldName}
        );
        if (args.mode === "edit" && !(capability && capability.operations.update)) {
            throw commandError("one2many_operation_not_allowed", "当前明细不允许编辑。");
        }
        return $.when(context.openX2Many(row, false, args.mode)).then(function () {
            return context.waitForSnapshotChange(before.snapshotId);
        }).then(function (snapshot) {
            if (!snapshot.record || snapshot.record.model !== row.model) {
                throw commandError("x2many_form_open_failed", "客户端未进入明细表单。");
            }
            return {opened: true, mode: args.mode, persistence: "parent_pending"};
        });
    };

    COMMANDS["odoo.open_x2many_create"] = function (context, args) {
        var before = context.getSnapshot();
        var fieldBinding = context.resolveToken(args.fieldToken, "x2many_field");
        if (!fieldBinding || !context.validateToken(fieldBinding, "x2many_field")) {
            throw commandError("stale_x2many_field_token", "明细字段令牌已过期，请刷新后重试。");
        }
        var capability = _.findWhere(
            before.capabilities && before.capabilities.x2many || [],
            {field: fieldBinding.fieldName}
        );
        if (!(capability && capability.operations.create)) {
            throw commandError("one2many_operation_not_allowed", "当前明细不允许新建。");
        }
        return $.when(context.openX2Many(fieldBinding, true, "edit")).then(function () {
            return context.waitForSnapshotChange(before.snapshotId);
        }).then(function (snapshot) {
            if (!snapshot.record || snapshot.record.model !== fieldBinding.model) {
                throw commandError("x2many_form_open_failed", "客户端未进入明细新建表单。");
            }
            return {opened: true, mode: "create", persistence: "parent_pending"};
        });
    };

    COMMANDS["odoo.reload_current_form"] = function (context) {
        var controller = requireForm(context);
        if (context.hasUnsavedChanges()) {
            throw commandError("parent_form_dirty", "当前表单存在未保存更改，不能重新载入。");
        }
        return context.reloadForm(controller).then(function (snapshot) {
            return {
                reloaded: true,
                snapshotId: snapshot.snapshotId,
                hostRevision: snapshot.hostRevision,
            };
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
                return recoverPatchError(context, controller, error);
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
                return recoverPatchError(context, controller, error);
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
            }).then(function (saved) {
                prepared.persistence = saved.persistence;
                return context.refresh(controller, true);
            }).then(function () {
                var completedSnapshot = context.getSnapshot();
                var undoPayload = prepared.persistence === "parent_pending" ? false :
                    Adapter.buildUndoPayload(controller, completedSnapshot, prepared);
                return {
                    applied: prepared.applied,
                    rejected: [],
                    saved: true,
                    persistence: prepared.persistence,
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
            return saveRecord(context, controller).then(function (saved) {
                return context.refresh(controller, true).then(function () {
                    return {
                        saved: true,
                        applied: saved.changedFields || [],
                        persistence: saved.persistence,
                        enteredEditMode: editable.enteredEditMode,
                    };
                });
            });
        });
    };

    COMMANDS["odoo.discard_current_form"] = function (context) {
        var controller = requireForm(context);
        var ready;
        if (_.isFunction(context.discardForm) && context.isModalForm()) {
            return context.discardForm(controller).then(function () {
                return {discarded: true, persistence: "parent_pending"};
            });
        }
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

    function prepare(context, call) {
        if (!call || call.tool !== "odoo.export_current_view") {
            return $.when({call: call, preview: false});
        }
        return buildExportBinding(context, call.arguments || {}, call).then(function (binding) {
            call.arguments = binding.publicArguments;
            call.preview = {export: Adapter.clone(binding.publicArguments.__export)};
            return {call: call, preview: call.preview};
        });
    }

    function execute(context, call) {
        var tool = call && call.tool;
        var args = call && call.arguments || {};
        var control = tool === "odoo.activate_view_control" &&
            context.resolveToken(args.controlToken, "control");
        if (!COMMANDS[tool]) {
            return $.Deferred().reject(commandError("unsupported_command", "不支持此页面命令。")).promise();
        }
        if ((WRITE_COMMANDS[tool] || control &&
                ["object", "create", "delete", "state"].indexOf(control.type) !== -1) &&
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
        prepare: prepare,
        execute: execute,
    };
});
