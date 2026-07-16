odoo.define("agui_chat.model_adapter", function (require) {
    "use strict";

    var fieldUtils = require("web.field_utils");

    var MAX_FIELDS = 120;
    var MAX_TEXT_CHARS = 4096;
    var MAX_RELATION_IDS = 200;
    var MAX_RELATION_SEARCH_LIMIT = 20;
    var DEFAULT_RELATION_SEARCH_LIMIT = 8;
    var MAX_RELATION_QUERY_CHARS = 120;
    var MAX_VIEW_RECORDS = 40;
    var MAX_VIEW_CONTROLS = 80;
    var MAX_FILTER_CONDITIONS = 20;
    var MAX_FILTER_LOGIC_DEPTH = 4;
    var MAX_FILTER_TEXT_CHARS = 240;
    var MAX_SNAPSHOT_BYTES = 256 * 1024;
    var SECRET_FIELD = /(password|passwd|secret|token|api[_-]?key)/i;
    var FILTER_OPERATORS = {
        boolean: ["=", "!="],
        char: ["ilike", "not ilike", "=", "!="],
        text: ["ilike", "not ilike", "=", "!="],
        html: ["ilike", "not ilike", "=", "!="],
        date: ["=", "!=", ">", "<", ">=", "<="],
        datetime: ["=", "!=", ">", "<", ">=", "<="],
        integer: ["=", "!=", ">", "<", ">=", "<=", "in", "not in"],
        id: ["="],
        float: ["=", "!=", ">", "<", ">=", "<="],
        monetary: ["=", "!=", ">", "<", ">=", "<="],
        selection: ["=", "!=", "in", "not in"],
        many2one: ["=", "!=", "ilike", "not ilike", "child_of"],
    };

    function clone(value) {
        if (value === undefined || value === null) {
            return value;
        }
        return JSON.parse(JSON.stringify(value));
    }

    function utf8ByteLength(value) {
        var code;
        var index = 0;
        var length = 0;
        while (index < value.length) {
            code = value.charCodeAt(index++);
            if (code < 0x80) {
                length += 1;
            } else if (code < 0x800) {
                length += 2;
            } else if (code >= 0xd800 && code <= 0xdbff && index < value.length &&
                    value.charCodeAt(index) >= 0xdc00 && value.charCodeAt(index) <= 0xdfff) {
                index += 1;
                length += 4;
            } else {
                length += 3;
            }
        }
        return length;
    }

    function bounded(value, depth) {
        var result;
        depth = depth || 0;
        if (depth > 5) {
            return "[truncated]";
        }
        if (_.isString(value)) {
            return value.slice(0, MAX_TEXT_CHARS);
        }
        if (_.isNumber(value) || _.isBoolean(value) || value === false || value === null) {
            return value;
        }
        if (value && value._isAMomentObject) {
            return value.toJSON ? value.toJSON() : value.format();
        }
        if (_.isArray(value)) {
            return _.map(value.slice(0, MAX_RELATION_IDS), function (item) {
                return bounded(item, depth + 1);
            });
        }
        if (_.isObject(value)) {
            result = {};
            _.each(_.keys(value).slice(0, MAX_FIELDS), function (key) {
                result[key] = bounded(value[key], depth + 1);
            });
            return result;
        }
        return value === undefined ? false : String(value).slice(0, MAX_TEXT_CHARS);
    }

    function getRecord(controller, raw) {
        if (!controller || !controller.model || !controller.handle) {
            return null;
        }
        return controller.model.get(controller.handle, raw ? {raw: true} : undefined);
    }

    function relationIds(value) {
        var ids = [];
        if (!value) {
            return ids;
        }
        if (_.isArray(value)) {
            ids = _.map(value, function (item) {
                if (_.isNumber(item)) {
                    return item;
                }
                if (_.isObject(item)) {
                    return item.res_id || item.id || item.data && item.data.id;
                }
                return false;
            });
        } else if (_.isObject(value)) {
            ids = value.res_ids || value.ids || value.data && relationIds(value.data) || [];
        }
        return _.chain(ids).map(function (id) {
            id = parseInt(id, 10);
            return isNaN(id) ? false : id;
        }).compact().uniq().value().slice(0, MAX_RELATION_IDS);
    }

    function serializeValue(value, field) {
        if (field && field.type === "binary") {
            return undefined;
        }
        if (field && field.type === "many2one") {
            if (!value) {
                return false;
            }
            if (_.isArray(value)) {
                return {id: value[0] || false, displayName: value[1] || false};
            }
            if (_.isObject(value)) {
                return {
                    id: value.res_id || value.id || value.data && value.data.id || false,
                    displayName: value.display_name || value.name || value.data && value.data.display_name || false,
                };
            }
            return false;
        }
        if (field && (field.type === "many2many" || field.type === "one2many")) {
            var ids = relationIds(value);
            return {
                ids: ids,
                count: _.isObject(value) && _.isNumber(value.count) ? value.count : ids.length,
            };
        }
        return bounded(value);
    }

    function fieldInfo(record, viewType) {
        var infos = record && record.fieldsInfo || {};
        return infos[viewType] || {};
    }

    function evaluateModifiers(record, info) {
        if (!info || !info.modifiers || !record || !_.isFunction(record.evalModifiers)) {
            return {};
        }
        return record.evalModifiers(info.modifiers) || {};
    }

    function buildFields(record, rawRecord, viewType, sensitiveFields) {
        var result = {};
        var infos = fieldInfo(rawRecord, viewType);
        _.each(_.keys(infos).slice(0, MAX_FIELDS), function (name) {
            var field = rawRecord.fields && rawRecord.fields[name];
            var info = infos[name] || {};
            var modifiers;
            if (!field || field.type === "binary") {
                return;
            }
            modifiers = evaluateModifiers(record, info);
            result[name] = {
                name: name,
                string: info.string || field.string || name,
                type: field.type,
                relation: field.relation || false,
                selection: bounded(field.selection || false),
                readonly: !!modifiers.readonly,
                required: !!modifiers.required,
                invisible: !!modifiers.invisible,
                redacted: SECRET_FIELD.test(name) || sensitiveFields.indexOf(name) !== -1,
            };
        });
        return result;
    }

    function serializeFormRecord(controller, record, rawRecord, fields) {
        var values = {};
        var dirty = {};
        var changes = rawRecord._changes || {};
        var dirtyFields = _.uniq(_.keys(changes).concat(controller.__aguiHostDirtyFields || []));
        _.each(fields, function (meta, name) {
            var field = rawRecord.fields && rawRecord.fields[name];
            var value;
            if (meta.redacted) {
                values[name] = "[redacted]";
                if (_.has(changes, name)) {
                    dirty[name] = "[redacted]";
                }
                return;
            }
            value = serializeValue(record.data && record.data[name], field);
            if (value !== undefined) {
                values[name] = value;
            }
            if (dirtyFields.indexOf(name) !== -1) {
                value = serializeValue(record.data && record.data[name], field);
                if (value !== undefined) {
                    dirty[name] = value;
                }
            }
        });
        return {
            model: record.model || rawRecord.model || false,
            resId: record.res_id || false,
            values: values,
            dirty: dirty,
            dirtyFields: _.keys(dirty),
        };
    }

    function recordDisplayName(record) {
        var data = record && record.data || {};
        var value = data.display_name || data.name || data.title || record && record.res_id;
        if (_.isObject(value)) {
            value = value.display_name || value.name || value.value || value.res_id;
        }
        return String(value || "").slice(0, 160);
    }

    function collectRecordStates(state, result) {
        result = result || [];
        _.each(state && state.data || [], function (item) {
            if (result.length >= MAX_VIEW_RECORDS) {
                return;
            }
            if (item && item.type === "record" && item.res_id) {
                result.push(item);
            } else if (item && item.data) {
                collectRecordStates(item, result);
            }
        });
        return result;
    }

    function uniqueClosedGroup(state) {
        if (!state || state.type !== "list" || state.count !== 1) {
            return false;
        }
        var children = _.filter(state.data || [], function (item) {
            return item && item.count > 0;
        });
        if (children.length !== 1 || children[0].type !== "list" || children[0].count !== 1) {
            return false;
        }
        return children[0].isOpen ? uniqueClosedGroup(children[0]) : children[0];
    }

    function expandUniqueRecordCandidate(controller) {
        var model = controller && controller.model;
        var expanded = false;
        var visited = {};
        if (!model || !_.isFunction(model.toggleGroup)) {
            return $.when(false);
        }
        function expandNext() {
            var state = getRecord(controller, false);
            var group;
            if (collectRecordStates(state).length === 1) {
                return $.when(true);
            }
            group = uniqueClosedGroup(state);
            if (!group || visited[group.id]) {
                return $.when(false);
            }
            visited[group.id] = true;
            return $.when(model.toggleGroup(group.id)).then(function () {
                expanded = true;
                return expandNext();
            });
        }
        return expandNext().then(function (found) {
            if (!found || !expanded || !_.isFunction(controller.update)) {
                return found;
            }
            return $.when(controller.update({}, {keepSelection: true, reload: false})).then(function () {
                return true;
            });
        });
    }

    function kanbanRecordWidgets(renderer) {
        var records = [];
        _.each(renderer && renderer.widgets || [], function (widget) {
            if (widget && _.isArray(widget.records)) {
                records = records.concat(widget.records);
            } else if (widget && widget.state && widget.db_id) {
                records.push(widget);
            }
        });
        return records;
    }

    function visibleElement($element) {
        var element = $element && $element[0];
        if (!element || element.hidden || element.getAttribute && element.getAttribute("aria-hidden") === "true") {
            return false;
        }
        return !$element.hasClass("o_hidden") && $element.css("display") !== "none" &&
            $element.css("visibility") !== "hidden";
    }

    function searchFilterFields(controller, sensitiveFields) {
        var searchView = controller && controller.searchView;
        var fields = searchView && searchView.filters_menu && searchView.filters_menu.fields ||
            searchView && searchView.fields || {};
        var result = {};
        _.each(fields, function (field, name) {
            var type = field && field.type || (name === "id" ? "id" : false);
            if (!type || !FILTER_OPERATORS[type] || field.searchable === false ||
                    field.selectable === false || field.deprecated || SECRET_FIELD.test(name) ||
                    sensitiveFields.indexOf(name) !== -1) {
                return;
            }
            result[name] = {
                name: name,
                string: field.string || name,
                type: type,
                relation: field.relation || false,
                selection: bounded(field.selection || false),
                operators: FILTER_OPERATORS[type].slice(0),
            };
        });
        return result;
    }

    function buildViewCapabilities(controller, snapshot, registerToken, sensitiveFields) {
        var state = getRecord(controller, false);
        var viewType = snapshot.controller.viewType;
        var active = controller.activeActions || {};
        var records = [];
        var controls = [];
        var widgets;
        if (viewType === "kanban") {
            widgets = kanbanRecordWidgets(controller.renderer);
            _.each(widgets.slice(0, MAX_VIEW_RECORDS), function (widget) {
                var record = widget.state;
                var label;
                var recordToken;
                if (!record || !record.res_id || !visibleElement(widget.$el)) {
                    return;
                }
                label = recordDisplayName(record);
                recordToken = registerToken("record", {
                    localId: record.id || widget.db_id,
                    resId: record.res_id,
                    model: record.model,
                    widget: widget,
                    displayName: label,
                });
                records.push({token: recordToken, displayName: label});
                if (widget.$el.hasClass("oe_kanban_global_click") ||
                        widget.$el.hasClass("oe_kanban_global_click_edit")) {
                    controls.push({
                        token: registerToken("control", {
                            type: widget.$el.hasClass("oe_kanban_global_click_edit") ? "edit" : "open",
                            widget: widget,
                            $element: widget.$el,
                            localId: record.id || widget.db_id,
                            resId: record.res_id,
                            recordLabel: label,
                            label: label,
                            global: true,
                        }),
                        type: widget.$el.hasClass("oe_kanban_global_click_edit") ? "edit" : "open",
                        label: label,
                        recordLabel: label,
                    });
                }
                widget.$el.find(".oe_kanban_action").each(function () {
                    var $element = $(this);
                    var type = String($element.data("type") || "button");
                    var controlLabel;
                    if (controls.length >= MAX_VIEW_CONTROLS ||
                            ["open", "edit", "action", "object"].indexOf(type) === -1 ||
                            !visibleElement($element)) {
                        return;
                    }
                    controlLabel = String($element.attr("title") || $element.attr("aria-label") ||
                        $element.text() || $element.data("name") || type).trim().slice(0, 160);
                    controls.push({
                        token: registerToken("control", {
                            type: type,
                            widget: widget,
                            $element: $element,
                            localId: record.id || widget.db_id,
                            resId: record.res_id,
                            recordLabel: label,
                            label: controlLabel,
                        }),
                        type: type,
                        label: controlLabel,
                        recordLabel: label,
                    });
                });
            });
        } else if (viewType === "list") {
            _.each(collectRecordStates(state), function (record) {
                var label = recordDisplayName(record);
                records.push({
                    token: registerToken("record", {
                        localId: record.id,
                        resId: record.res_id,
                        model: record.model,
                        displayName: label,
                    }),
                    displayName: label,
                });
            });
        }
        return {
            create: !!active.create,
            open: viewType === "list" || viewType === "kanban",
            edit: !!active.edit,
            filter: !!(controller.searchView && _.isFunction(controller.searchView.updateFilters)),
            totalCount: state && (_.isNumber(state.count) ? state.count : state.data && state.data.length) || 0,
            filterFields: searchFilterFields(controller, sensitiveFields || []),
            records: records,
            controls: controls.slice(0, MAX_VIEW_CONTROLS),
        };
    }

    function filterValueValid(meta, operator, value) {
        var type = meta.type;
        var values = (operator === "in" || operator === "not in") ? value : [value];
        if ((operator === "in" || operator === "not in") &&
                (!_.isArray(value) || !value.length || value.length > 50)) {
            return false;
        }
        return _.every(values, function (item) {
            if (item === false && (operator === "=" || operator === "!=")) {
                return true;
            }
            if (type === "boolean") {
                return _.isBoolean(item);
            }
            if (["integer", "id"].indexOf(type) !== -1) {
                return _.isNumber(item) && isFinite(item) && Math.floor(item) === item;
            }
            if (["float", "monetary"].indexOf(type) !== -1) {
                return _.isNumber(item) && isFinite(item);
            }
            if (type === "selection") {
                return _.pluck(meta.selection || [], 0).indexOf(item) !== -1;
            }
            if (type === "many2one" && ["=", "!=", "child_of"].indexOf(operator) !== -1) {
                return _.isNumber(item) && isFinite(item) && Math.floor(item) === item && item > 0;
            }
            if (type === "date") {
                return _.isString(item) && /^\d{4}-\d{2}-\d{2}$/.test(item);
            }
            if (type === "datetime") {
                return _.isString(item) && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$/.test(item);
            }
            return _.isString(item) && item.length <= MAX_FILTER_TEXT_CHARS;
        });
    }

    function validateFilterDomain(snapshot, domain) {
        var fields = snapshot.capabilities && snapshot.capabilities.filterFields || {};
        var conditionCount = 0;
        var error;
        var index = 0;
        function invalid(code, message) {
            var failure = new Error(message || "筛选 domain 未通过校验。");
            failure.code = code;
            throw failure;
        }
        function validateCondition(item) {
            var name = item && item[0];
            var operator = item && item[1];
            var meta = fields[name];
            conditionCount += 1;
            if (!_.isArray(item) || item.length !== 3 || !_.isString(name) ||
                    name.indexOf(".") !== -1 || !meta ||
                    meta.operators.indexOf(operator) === -1 ||
                    !filterValueValid(meta, operator, item[2])) {
                invalid("invalid_filter_condition");
            }
        }
        function parseTerm(position, depth) {
            var item;
            var arity;
            var child;
            if (position >= domain.length) {
                invalid("invalid_filter_logic", "筛选逻辑运算符缺少条件。");
            }
            item = domain[position];
            if (!_.isString(item)) {
                validateCondition(item);
                return position + 1;
            }
            if (["&", "|", "!"].indexOf(item) === -1) {
                invalid("invalid_filter_domain");
            }
            if (depth >= MAX_FILTER_LOGIC_DEPTH) {
                invalid("filter_logic_too_deep", "筛选逻辑嵌套过深。");
            }
            arity = item === "!" ? 1 : 2;
            position += 1;
            for (child = 0; child < arity; child += 1) {
                position = parseTerm(position, depth + 1);
            }
            return position;
        }
        if (!_.isArray(domain) || domain.length > MAX_FILTER_CONDITIONS * 2) {
            error = new Error("筛选 domain 必须是有限长度的 JSON 数组。");
            error.code = "invalid_filter_domain";
            throw error;
        }
        while (index < domain.length) {
            index = parseTerm(index, 0);
        }
        if (!conditionCount || conditionCount > MAX_FILTER_CONDITIONS) {
            error = new Error("筛选条件数量无效。");
            error.code = "invalid_filter_domain";
            throw error;
        }
        return clone(domain);
    }

    function compactActionViews(views) {
        return _.chain(views || []).map(function (view) {
            var viewId;
            var viewType;
            if (_.isArray(view)) {
                viewId = view[0] || false;
                viewType = view[1] || false;
            } else if (_.isObject(view)) {
                viewId = view.viewID || view.view_id || false;
                viewType = view.type || false;
            }
            if (viewType === "tree") {
                viewType = "list";
            }
            return viewType ? [viewId, viewType] : false;
        }).compact().first(20).value();
    }

    function compactAction(action) {
        if (!action) {
            return false;
        }
        if (_.isNumber(action) || _.isString(action)) {
            return {id: action};
        }
        return bounded({
            id: action.id || false,
            xmlId: action.xml_id || false,
            name: action.name || false,
            type: action.type || false,
            resModel: action.res_model || false,
            resId: action.res_id || false,
            views: compactActionViews(action.views),
            viewMode: action.view_mode || false,
            domain: action.domain || [],
            context: action.context || {},
            target: action.target || false,
        });
    }

    function compactMenu(menu) {
        if (!menu) {
            return false;
        }
        if (_.isNumber(menu) || _.isString(menu)) {
            return {id: menu};
        }
        return bounded({
            id: menu.id || menu.menu_id || false,
            xmlId: menu.xml_id || false,
            name: menu.name || menu.menu_name || false,
        });
    }

    function buildSnapshot(options) {
        var controller = options.controller;
        var record = getRecord(controller, false);
        var rawRecord = getRecord(controller, true);
        var fields;
        var snapshot;
        var viewType = options.viewType;
        if (!record || !rawRecord || ["form", "list", "kanban"].indexOf(viewType) === -1) {
            throw new Error("当前 BasicModel 数据点不可用。")
        }
        fields = buildFields(record, rawRecord, viewType, options.sensitiveFields || []);
        snapshot = {
            protocol: "agui.odoo.v2",
            snapshotId: options.snapshotId,
            hostRevision: options.hostRevision,
            capturedAt: new Date().toISOString(),
            interactive: true,
            surface: options.surface,
            controller: {
                actionId: options.action && options.action.id || false,
                controllerId: options.controllerId,
                dataPointId: record.id || controller.handle || false,
                viewType: viewType,
                mode: controller.mode || false,
            },
            action: compactAction(options.action),
            menu: compactMenu(options.menu),
            record: viewType === "form" ? serializeFormRecord(controller, record, rawRecord, fields) : false,
            selection: viewType === "list" || viewType === "kanban" ? {
                model: record.model || rawRecord.model || false,
                ids: controller.getSelectedIds ? bounded(controller.getSelectedIds()) : [],
                domain: bounded(record.domain || []),
                context: bounded(record.context || {}),
            } : false,
            fields: fields,
        };
        snapshot.capabilities = buildViewCapabilities(
            controller, snapshot, options.registerToken || function () { return false; },
            options.sensitiveFields || []
        );
        if (utf8ByteLength(JSON.stringify(snapshot)) > MAX_SNAPSHOT_BYTES) {
            throw new Error("当前 Odoo 页面快照超过大小限制。")
        }
        return snapshot;
    }

    function parseIds(value) {
        var ids = _.isArray(value) ? value : [value];
        var error;
        if (ids.length > MAX_RELATION_IDS) {
            error = new Error("输入的关系记录 ID 数量超过限制。")
            error.code = "relation_limit_exceeded";
            throw error;
        }
        ids = _.map(ids, function (id) {
            id = parseInt(_.isObject(id) ? id.id || id.resId : id, 10);
            if (isNaN(id) || id <= 0) {
                throw new Error("关系记录 ID 必须是正整数。")
            }
            return id;
        });
        return _.uniq(ids);
    }

    function parseScalar(field, value) {
        var parser;
        if (value === null || value === false || value === "") {
            return false;
        }
        if (field.type === "boolean") {
            if (!_.isBoolean(value)) {
                throw new Error("布尔字段必须使用布尔值。")
            }
            return value;
        }
        if (value === false) {
            return false;
        }
        if (field.type === "selection") {
            if (_.pluck(field.selection || [], 0).indexOf(value) === -1) {
                throw new Error("该选项值未在字段中声明。")
            }
            return value;
        }
        if (field.type === "many2one") {
            var idValue = value;
            if (_.isArray(value)) {
                if (value.length !== 2 || !_.isString(value[1])) {
                    throw new Error("Many2one 字段必须提供整数 ID、[ID, 显示名称] 二元数组或 {id, displayName} 对象。")
                }
                idValue = value[0];
            } else if (_.isObject(value)) {
                if (!_.has(value, "id") || !_.isString(value.displayName)) {
                    throw new Error("Many2one 字段必须提供整数 ID、[ID, 显示名称] 二元数组或 {id, displayName} 对象。")
                }
                idValue = value.id;
            }
            var id = parseInt(idValue, 10);
            if (_.isObject(idValue) || isNaN(id) || id <= 0 || String(id) !== String(idValue)) {
                throw new Error("Many2one 字段必须提供整数 ID、[ID, 显示名称] 二元数组或 {id, displayName} 对象。")
            }
            return {id: id};
        }
        if (field.type === "one2many") {
            throw new Error("通用表单变更不支持修改 One2many 字段。")
        }
        if (field.type === "integer" && _.isNumber(value)) {
            if (!isFinite(value) || Math.floor(value) !== value) {
                throw new Error("整数字段必须使用整数值。")
            }
            return value;
        }
        if ((field.type === "float" || field.type === "monetary") && _.isNumber(value)) {
            if (!isFinite(value)) {
                throw new Error("数值字段必须使用有限数值。")
            }
            return value;
        }
        parser = fieldUtils.parse[field.type];
        if (_.isFunction(parser) && ["integer", "float", "monetary", "date", "datetime"].indexOf(field.type) !== -1) {
            return parser(value, field, {isUTC: true});
        }
        if (["char", "text", "html"].indexOf(field.type) !== -1 && !_.isString(value)) {
            throw new Error("文本字段必须使用字符串值。")
        }
        return value;
    }

    function many2manyCommand(currentValue, value) {
        var operation = String(value && (value.operation || value.op) || "").toLowerCase();
        var current;
        var ids;
        if (["link", "unlink", "replace"].indexOf(operation) === -1) {
            throw new Error("Many2many 字段只支持 link、unlink 或 replace 操作。")
        }
        ids = parseIds(value.ids || value.id || []);
        if (operation !== "replace") {
            current = resolveRelation(currentValue);
            if (!current.complete) {
                var error = new Error("当前 Many2many 值尚未完整解析。")
                error.code = "relation_unresolved";
                throw error;
            }
            if (operation === "link") {
                ids = _.uniq(current.ids.concat(ids));
            } else {
                ids = _.difference(current.ids, ids);
            }
        }
        if (ids.length > MAX_RELATION_IDS) {
            var limitError = new Error("关系记录 ID 结果数量超过限制。")
            limitError.code = "relation_limit_exceeded";
            throw limitError;
        }
        return {operation: "REPLACE_WITH", ids: ids};
    }

    function resolveRelation(value) {
        var count;
        var nested;
        var resolved = [];
        var unresolved = false;
        if (!value) {
            return {ids: [], complete: true};
        }
        if (_.isArray(value)) {
            if (value.length > MAX_RELATION_IDS) {
                return {ids: [], complete: false};
            }
            _.each(value, function (item) {
                var id;
                if (_.isNumber(item)) {
                    id = item;
                } else if (_.isObject(item)) {
                    id = item.res_id || item.id || item.data && (item.data.res_id || item.data.id);
                } else {
                    unresolved = true;
                    return;
                }
                id = parseInt(id, 10);
                if (isNaN(id) || id <= 0) {
                    unresolved = true;
                } else {
                    resolved.push(id);
                }
            });
            resolved = _.uniq(resolved);
            return {ids: resolved, complete: !unresolved && resolved.length === value.length};
        }
        if (!_.isObject(value)) {
            return {ids: [], complete: false};
        }
        count = _.isNumber(value.count) ? value.count : false;
        if (_.isArray(value.res_ids)) {
            nested = resolveRelation(value.res_ids);
        } else if (_.isArray(value.ids)) {
            nested = resolveRelation(value.ids);
        } else if (value.data !== undefined) {
            nested = resolveRelation(value.data);
        } else {
            return {ids: [], complete: false};
        }
        if (count !== false && count > nested.ids.length) {
            nested.complete = false;
        }
        return nested;
    }

    function relationField(controller, snapshot, name) {
        var rawRecord = getRecord(controller, true);
        var meta = snapshot.fields[name];
        var field = rawRecord && rawRecord.fields && rawRecord.fields[name];
        var error;
        if (!name || !meta || !field) {
            error = new Error("当前视图中不存在该关系字段。")
            error.code = "field_not_in_view";
            throw error;
        }
        if (meta.redacted || meta.readonly || meta.invisible) {
            error = new Error("该关系字段当前不可编辑。")
            error.code = meta.redacted ? "field_sensitive" : meta.readonly ? "field_readonly" : "field_invisible";
            throw error;
        }
        if (field.type !== "many2one" && field.type !== "many2many") {
            error = new Error("只有 Many2one 和 Many2many 字段支持关系搜索。")
            error.code = "unsupported_relation_field";
            throw error;
        }
        return {rawRecord: rawRecord, meta: meta, field: field};
    }

    function relationEnvironment(controller, name) {
        var record = getRecord(controller, false);
        var error;
        if (!record || !_.isFunction(record.getDomain) || !_.isFunction(record.getContext)) {
            error = new Error("当前关系字段的域不可用。")
            error.code = "relation_domain_unavailable";
            throw error;
        }
        return {
            record: record,
            domain: clone(record.getDomain({fieldName: name}) || []),
            context: clone(record.getContext({fieldName: name}) || {}),
        };
    }

    function selectedRelationIds(value, fieldType) {
        var id;
        if (fieldType !== "many2one") {
            return relationIds(value);
        }
        if (_.isArray(value)) {
            id = value[0];
        } else if (_.isObject(value)) {
            id = value.res_id || value.id || value.data && (value.data.res_id || value.data.id);
        }
        id = parseInt(id, 10);
        return isNaN(id) || id <= 0 ? [] : [id];
    }

    function normalizedName(value) {
        return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
    }

    function searchRelation(controller, snapshot, args) {
        args = args || {};
        var name = String(args.field || "");
        var relation = relationField(controller, snapshot, name);
        var environment = relationEnvironment(controller, name);
        var query = String(args.query || "").trim();
        var operation = String(args.operation || "");
        var limit = parseInt(args.limit || DEFAULT_RELATION_SEARCH_LIMIT, 10);
        var selected = selectedRelationIds(
            environment.record.data && environment.record.data[name], relation.field.type
        );
        var error;
        var domain;
        if (!query || query.length > MAX_RELATION_QUERY_CHARS) {
            error = new Error("关系搜索词长度必须在 1 到 120 个字符之间。")
            error.code = "invalid_relation_query";
            throw error;
        }
        if (relation.field.type === "many2one" && operation !== "set" ||
                relation.field.type === "many2many" && ["link", "unlink"].indexOf(operation) === -1) {
            error = new Error("关系操作与字段类型不匹配。")
            error.code = "invalid_relation_operation";
            throw error;
        }
        if (isNaN(limit)) {
            limit = DEFAULT_RELATION_SEARCH_LIMIT;
        }
        limit = Math.min(Math.max(limit, 1), MAX_RELATION_SEARCH_LIMIT);
        if (!controller || !_.isFunction(controller._rpc)) {
            error = new Error("当前控制器无法搜索关系记录。")
            error.code = "relation_search_unavailable";
            throw error;
        }
        domain = operation === "unlink" ? [["id", "in", selected]] : environment.domain;
        return controller._rpc({
            model: relation.field.relation,
            method: "name_search",
            kwargs: {
                name: query,
                args: domain,
                operator: "ilike",
                limit: limit,
                context: environment.context,
            },
        }, {shadow: true}).then(function (rows) {
            var candidates = _.map((rows || []).slice(0, limit), function (row) {
                var id = parseInt(row[0], 10);
                return {
                    id: id,
                    displayName: String(row[1] || ""),
                    selected: selected.indexOf(id) !== -1,
                };
            });
            var exact = candidates.length === 1 &&
                normalizedName(candidates[0].displayName) === normalizedName(query);
            return {
                field: name,
                fieldLabel: relation.meta.string || name,
                fieldType: relation.field.type,
                relation: relation.field.relation,
                query: query,
                relationOperation: operation,
                resolution: !candidates.length ? "none" : exact ? "unique_exact" : "ambiguous",
                candidates: candidates,
                snapshotId: snapshot.snapshotId,
                hostRevision: snapshot.hostRevision,
            };
        });
    }

    function validateRelationChecks(controller, checks, prepared) {
        var promises = [];
        _.each(checks, function (check) {
            if (check.operation === "unlink") {
                if (_.difference(check.ids, check.currentIds).length) {
                    prepared.rejected.push({field: check.name, code: "relation_not_selected"});
                }
                return;
            }
            if (!check.ids.length) {
                return;
            }
            var environment;
            try {
                environment = relationEnvironment(controller, check.name);
            } catch (error) {
                prepared.rejected.push({
                    field: check.name,
                    code: error.code || "relation_domain_unavailable",
                });
                return;
            }
            if (!controller || !_.isFunction(controller._rpc)) {
                prepared.rejected.push({field: check.name, code: "relation_domain_unavailable"});
                return;
            }
            promises.push(controller._rpc({
                model: check.relation,
                method: "search_read",
                domain: [["id", "in", check.ids]].concat(environment.domain),
                fields: ["id"],
                limit: check.ids.length,
                context: environment.context,
            }, {shadow: true}).then(function (records) {
                var allowed = _.map(records || [], function (record) { return record.id; });
                if (_.difference(check.ids, allowed).length) {
                    prepared.rejected.push({field: check.name, code: "relation_domain_mismatch"});
                }
            }));
        });
        return $.when.apply($, promises).then(function () {
            if (prepared.rejected.length) {
                prepared.changes = {};
                prepared.applied = [];
            }
            return prepared;
        });
    }

    function normalizePatch(patch) {
        if (_.isString(patch)) {
            try {
                patch = JSON.parse(patch);
            } catch (error) {
                return [];
            }
        }
        if (_.isArray(patch)) {
            return patch;
        }
        if (_.isObject(patch)) {
            return _.map(patch, function (value, field) {
                return {field: field, value: value};
            });
        }
        return [];
    }

    function targetFromSnapshot(snapshot) {
        var record = snapshot && snapshot.record || {};
        var selection = snapshot && snapshot.selection || {};
        var controller = snapshot && snapshot.controller || {};
        return {
            snapshotId: snapshot && snapshot.snapshotId,
            hostRevision: snapshot && snapshot.hostRevision,
            controllerId: controller.controllerId,
            dataPointId: controller.dataPointId,
            model: record.model || selection.model || false,
            resId: record.resId || false,
        };
    }

    function comparableValue(value, field) {
        var relation;
        var ids;
        if (field.type === "many2one") {
            ids = selectedRelationIds(value, field.type);
            return ids.length ? ids[0] : false;
        }
        if (field.type === "many2many") {
            relation = resolveRelation(value);
            return relation.complete ? relation.ids.slice(0).sort(function (left, right) {
                return left - right;
            }) : null;
        }
        return serializeValue(value, field);
    }

    function undoValue(value, field) {
        var comparable = comparableValue(value, field);
        if (field.type === "many2many") {
            return comparable === null ? undefined : {operation: "replace", ids: comparable};
        }
        return comparable;
    }

    function proposedValue(change, field) {
        if (field.type === "many2one") {
            return change ? {id: change.id, displayName: "#" + change.id} : false;
        }
        if (field.type === "many2many") {
            return {ids: (change.ids || []).slice(0), count: (change.ids || []).length};
        }
        return serializeValue(change, field);
    }

    function previewValue(value, field) {
        var serialized = serializeValue(value, field);
        if (field.type === "many2one" && serialized && serialized.id) {
            return {
                id: serialized.id,
                displayName: serialized.displayName || "#" + serialized.id,
            };
        }
        return serialized;
    }

    function preparePatch(controller, snapshot, args) {
        var rawRecord = getRecord(controller, true);
        var record = getRecord(controller, false);
        var patch = normalizePatch(args.patch);
        var changes = {};
        var rejected = [];
        var applied = [];
        var relationChecks = [];
        var beforeValues = {};
        var undoPatch = {};
        var undoSupported = true;
        var dirtyFields = _.uniq(
            snapshot.record && snapshot.record.dirtyFields || []
        ).concat(_.keys(rawRecord && rawRecord._changes || {}));
        dirtyFields = _.uniq(dirtyFields.concat(controller.__aguiHostDirtyFields || []));
        if (!patch.length) {
            return {
                changes: changes, applied: applied, rejected: [{code: "empty_patch"}],
                relationChecks: [], beforeValues: {}, undoPatch: {}, undoSupported: false,
            };
        }
        if (dirtyFields.length) {
            return {
                changes: changes,
                applied: applied,
                rejected: [{code: "dirty_conflict", fields: dirtyFields}],
                relationChecks: [],
                beforeValues: {},
                undoPatch: {},
                undoSupported: false,
            };
        }
        _.each(patch, function (item) {
            var name = item && item.field;
            var meta = snapshot.fields[name];
            var field = rawRecord.fields && rawRecord.fields[name];
            try {
                if (!name || !meta || !field) {
                    throw {code: "field_not_in_view"};
                }
                if (meta.redacted) {
                    throw {code: "field_sensitive"};
                }
                if (meta.readonly) {
                    throw {code: "field_readonly"};
                }
                if (meta.invisible) {
                    throw {code: "field_invisible"};
                }
                beforeValues[name] = comparableValue(record.data && record.data[name], field);
                undoPatch[name] = undoValue(record.data && record.data[name], field);
                if (undoPatch[name] === undefined || field.type === "binary" || field.type === "one2many") {
                    undoSupported = false;
                }
                if (field.type === "many2many") {
                    var operation = String(item.value && (item.value.operation || item.value.op) || "").toLowerCase();
                    var inputIds = parseIds(item.value && (item.value.ids || item.value.id) || []);
                    var current = resolveRelation(record.data && record.data[name]);
                    changes[name] = many2manyCommand(record.data && record.data[name], item.value);
                    relationChecks.push({
                        name: name,
                        relation: field.relation,
                        operation: operation,
                        ids: operation === "replace" ? changes[name].ids : inputIds,
                        currentIds: current.ids,
                    });
                } else {
                    changes[name] = parseScalar(field, item.value);
                    if (field.type === "many2one" && changes[name] && changes[name].id) {
                        relationChecks.push({
                            name: name,
                            relation: field.relation,
                            operation: "set",
                            ids: [changes[name].id],
                            currentIds: [],
                        });
                    }
                }
                applied.push(name);
            } catch (error) {
                rejected.push({
                    field: name || false,
                    code: error.code || "invalid_value",
                    message: error.message || false,
                });
            }
        });
        if (rejected.length) {
            changes = {};
            applied = [];
            relationChecks = [];
        }
        return {
            changes: changes,
            applied: applied,
            rejected: rejected,
            relationChecks: relationChecks,
            beforeValues: beforeValues,
            undoPatch: undoPatch,
            undoSupported: undoSupported,
        };
    }

    function buildPatchPreview(controller, snapshot, args) {
        args = args || {};
        var rawRecord = getRecord(controller, true);
        var record = getRecord(controller, false);
        var prepared = preparePatch(controller, snapshot, args);
        var rejectedByField = {};
        _.each(prepared.rejected, function (item) {
            _.each(item.fields || [item.field], function (name) {
                if (name) {
                    rejectedByField[name] = item;
                }
            });
        });
        var changes = _.map(normalizePatch(args.patch), function (item) {
            var name = item && item.field;
            var meta = snapshot.fields && snapshot.fields[name] || {};
            var field = rawRecord && rawRecord.fields && rawRecord.fields[name] || {};
            var sensitive = !!meta.redacted;
            var oldValue = sensitive ? "[redacted]" : previewValue(
                record && record.data && record.data[name], field
            );
            var newValue = "[invalid]";
            if (sensitive) {
                newValue = "[redacted]";
            } else if (_.has(prepared.changes, name)) {
                newValue = proposedValue(prepared.changes[name], field);
            } else if (!rejectedByField[name]) {
                newValue = bounded(item && item.value);
            }
            return {
                field: name || false,
                label: meta.string || field.string || name || "",
                fieldType: field.type || meta.type || false,
                oldValue: oldValue,
                newValue: newValue,
                sensitive: sensitive,
                rejected: rejectedByField[name] && rejectedByField[name].code || false,
            };
        });
        return {
            target: clone(args.target || targetFromSnapshot(snapshot)),
            changes: changes,
            rejected: clone(prepared.rejected),
        };
    }

    function captureComparableValues(controller, names) {
        var record = getRecord(controller, false);
        var rawRecord = getRecord(controller, true);
        var result = {};
        _.each(names || [], function (name) {
            var field = rawRecord && rawRecord.fields && rawRecord.fields[name];
            if (field) {
                result[name] = comparableValue(record.data && record.data[name], field);
            }
        });
        return result;
    }

    function buildUndoPayload(controller, snapshot, prepared) {
        if (!prepared.undoSupported || !prepared.applied.length) {
            return false;
        }
        return {
            target: targetFromSnapshot(snapshot),
            patch: clone(prepared.undoPatch),
            expected: captureComparableValues(controller, prepared.applied),
        };
    }

    function validateUndo(controller, snapshot, args) {
        var patch = normalizePatch(args && args.patch);
        var expected = args && args.expected;
        var rawRecord = getRecord(controller, true);
        var record = getRecord(controller, false);
        var dirtyFields = snapshot.record && snapshot.record.dirtyFields || [];
        if (!_.isObject(expected) || dirtyFields.length || _.keys(rawRecord._changes || {}).length ||
                (controller.__aguiHostDirtyFields || []).length) {
            return {ok: false, code: "undo_conflict"};
        }
        var fieldNames = _.pluck(patch, "field");
        if (!fieldNames.length || _.difference(fieldNames, _.keys(expected)).length ||
                _.difference(_.keys(expected), fieldNames).length) {
            return {ok: false, code: "undo_conflict"};
        }
        var conflict = _.some(fieldNames, function (name) {
            var field = rawRecord.fields && rawRecord.fields[name];
            return !field || JSON.stringify(comparableValue(record.data && record.data[name], field)) !==
                JSON.stringify(expected[name]);
        });
        return {ok: !conflict, code: conflict ? "undo_conflict" : "ok"};
    }

    function applyPatch(controller, snapshot, args) {
        var prepared = preparePatch(controller, snapshot, args || {});
        var record = getRecord(controller, false);
        if (prepared.rejected.length) {
            return $.when(prepared);
        }
        if (!controller || !_.isFunction(controller._applyChanges)) {
            return $.Deferred().reject(new Error("当前 FormController 无法应用表单变更。")).promise();
        }
        return validateRelationChecks(controller, prepared.relationChecks, prepared).then(function () {
            if (prepared.rejected.length) {
                return prepared;
            }
            return $.when(controller._applyChanges(record.id || controller.handle, prepared.changes, {
                target: {name: "__agui_host__"},
                data: {
                    context: record.context || {},
                    notifyChange: true,
                    viewType: "form",
                    allowWarning: true,
                },
                stopPropagation: function () {},
            })).then(function () {
                return prepared;
            });
        });
    }

    function validateForm(controller) {
        var result;
        if (!controller || !controller.renderer || !_.isFunction(controller.renderer.canBeSaved)) {
            throw new Error("表单渲染器校验不可用。")
        }
        result = controller.renderer.canBeSaved(controller.handle);
        if (result === true || result === undefined) {
            return [];
        }
        if (_.isArray(result)) {
            return result;
        }
        if (_.isObject(result)) {
            return _.keys(result);
        }
        return ["form_validation_failed"];
    }

    return {
        buildSnapshot: buildSnapshot,
        buildPatchPreview: buildPatchPreview,
        buildUndoPayload: buildUndoPayload,
        captureComparableValues: captureComparableValues,
        validateUndo: validateUndo,
        targetFromSnapshot: targetFromSnapshot,
        searchRelation: searchRelation,
        applyPatch: applyPatch,
        validateForm: validateForm,
        validateFilterDomain: validateFilterDomain,
        expandUniqueRecordCandidate: expandUniqueRecordCandidate,
        clone: clone,
    };
});
