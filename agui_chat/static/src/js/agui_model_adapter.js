odoo.define("agui_chat.model_adapter", function (require) {
    "use strict";

    var fieldUtils = require("web.field_utils");
    var searchInputs = require("web.search_inputs");

    var MAX_TEXT_CHARS = 4096;
    var MAX_VALUE_OBJECT_KEYS = 120;
    var MAX_RELATION_IDS = 200;
    var MAX_RELATION_SEARCH_LIMIT = 20;
    var DEFAULT_RELATION_SEARCH_LIMIT = 8;
    var MAX_RELATION_QUERY_CHARS = 120;
    var MAX_ONE2MANY_OPERATIONS = 40;
    var MAX_VIEW_RECORDS = 40;
    var MAX_VIEW_CONTROLS = 80;
    var MAX_FILTER_CONDITIONS = 20;
    var MAX_FILTER_LOGIC_DEPTH = 4;
    var MAX_FILTER_TEXT_CHARS = 240;
    var MAX_GROUP_LEVELS = 3;
    var MAX_SNAPSHOT_BYTES = 256 * 1024;
    var SECRET_FIELD = /(password|passwd|secret|token|api[_-]?key|phone|mobile|bank|card|vat|tax[_-]?id|identity|id[_-]?card|身份证|银行卡|手机号|税号)/i;
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
    var GROUP_FIELD_TYPES = ["many2one", "char", "boolean", "selection", "date", "datetime"];
    var GROUP_INTERVALS = ["day", "week", "month", "quarter", "year"];

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
            _.each(_.keys(value).slice(0, MAX_VALUE_OBJECT_KEYS), function (key) {
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

    function fieldWidget(info) {
        return info && (info.widget || info.attrs && info.attrs.widget) || false;
    }

    function buildFields(record, rawRecord, viewType, sensitiveFields) {
        var result = {};
        var infos = fieldInfo(rawRecord, viewType);
        _.each(_.keys(infos), function (name) {
            var field = rawRecord.fields && rawRecord.fields[name];
            var info = infos[name] || {};
            var modifiers = {};
            var unsupportedReason = false;
            if (!field) {
                return;
            }
            try {
                modifiers = evaluateModifiers(record, info);
            } catch (error) {
                unsupportedReason = "modifier_evaluation_failed";
            }
            result[name] = {
                name: name,
                string: info.string || field.string || name,
                type: field.type,
                relation: field.relation || false,
                relationField: field.relation_field || false,
                selection: bounded(field.selection || false),
                widget: fieldWidget(info),
                readonly: !!modifiers.readonly,
                required: !!modifiers.required,
                invisible: !!modifiers.invisible,
                redacted: SECRET_FIELD.test(name) || sensitiveFields.indexOf(name) !== -1,
                unsupportedReason: unsupportedReason,
            };
        });
        return result;
    }

    function parsedArchFlag(value, defaultValue) {
        if (value === undefined || value === null || value === "") {
            return defaultValue;
        }
        try {
            return !!JSON.parse(value);
        } catch (error) {
            return false;
        }
    }

    function x2manyWidget(controller, rawRecord, name) {
        var renderer = controller && controller.renderer;
        var widgets = renderer && renderer.allFieldWidgets &&
            renderer.allFieldWidgets[rawRecord && rawRecord.id] || [];
        return _.find(widgets, function (widget) {
            return widget && widget.name === name && widget.field &&
                widget.field.type === "one2many";
        }) || false;
    }

    function one2manySchema(rawRecord, name) {
        var info = fieldInfo(rawRecord, "form")[name];
        var field = rawRecord && rawRecord.fields && rawRecord.fields[name];
        var views = info && info.views || {};
        var schemaView = views.form || views.list || views.tree;
        var operationView = views.list || views.tree;
        var source = views.form ? "form" : schemaView ? "tree" : false;
        var childInfos = schemaView && schemaView.fieldsInfo &&
            schemaView.fieldsInfo[schemaView.type];
        if (!field || field.type !== "one2many" || !info || !schemaView ||
                !schemaView.fields || !childInfos) {
            return false;
        }
        return {
            field: field,
            info: info,
            view: schemaView,
            schemaView: schemaView,
            operationView: operationView,
            schemaSource: source,
            childFields: schemaView.fields,
            childInfos: childInfos,
            viewType: schemaView.type,
        };
    }

    function one2manyStructure(controller, rawRecord, name, list) {
        var schema = one2manySchema(rawRecord, name);
        if (!schema || !list || list.type !== "list" ||
                list.model !== schema.field.relation || !_.isArray(list.data) ||
                !_.isArray(list.res_ids)) {
            return false;
        }
        return _.extend({}, schema, {
            list: list,
            listId: list.id,
            widget: x2manyWidget(controller, rawRecord, name),
        });
    }

    function one2manyCollection(list) {
        var totalCount;
        if (!list || list.type !== "list" || !_.isArray(list.data) ||
                !_.isArray(list.res_ids)) {
            return {
                dataPointId: false,
                loadedCount: 0,
                totalCount: 0,
                hasMore: false,
            };
        }
        totalCount = _.isNumber(list.count) ? list.count : list.res_ids.length;
        return {
            dataPointId: list.id || false,
            loadedCount: list.data.length,
            totalCount: totalCount,
            hasMore: totalCount > list.data.length,
        };
    }

    function hasDynamicModifiers(info) {
        return _.some(info && info.modifiers || {}, function (value) {
            return _.isArray(value) || _.isObject(value);
        });
    }

    function staticModifiers(info) {
        return _.pick(info && info.modifiers || {}, function (value) {
            return _.isBoolean(value) || _.isNumber(value) || _.isString(value);
        });
    }

    function childFieldLoaded(controller, structure, name) {
        var operationInfos = structure.operationView && structure.operationView.fieldsInfo &&
            structure.operationView.fieldsInfo[structure.operationView.type] || {};
        if (operationInfos[name]) {
            return true;
        }
        if (!structure.list.data.length) {
            return false;
        }
        return _.every(structure.list.data, function (item) {
            var record = item && controller.model.get(item.id);
            return record && record.data && _.has(record.data, name);
        });
    }

    function canonicalSchemaHash(schema) {
        var input = JSON.stringify(_.map(_.keys(schema).sort(), function (name) {
            var meta = schema[name];
            return [
                name, meta.type, meta.relation || false, meta.selection || false,
                meta.widget || false, meta.modifiers || {}, meta.redacted,
            ];
        }));
        var seeds = [2166136261, 2246822519, 3266489917, 668265263];
        return _.map(seeds, function (seed) {
            var hash = seed >>> 0;
            var index;
            for (index = 0; index < input.length; index += 1) {
                hash ^= input.charCodeAt(index);
                hash = Math.imul(hash, 16777619) >>> 0;
                hash ^= hash >>> 13;
            }
            var left = (hash >>> 0).toString(16);
            var right = (Math.imul(hash ^ seed, 2246822519) >>> 0).toString(16);
            return ("00000000" + left).slice(-8) + ("00000000" + right).slice(-8);
        }).join("");
    }

    function childFieldMetadata(controller, structure, sensitiveFields) {
        var result = {};
        _.each(_.keys(structure.childInfos), function (name) {
            var field = structure.childFields[name];
            var info = structure.childInfos[name] || {};
            var loaded = false;
            var dynamic = false;
            var redacted;
            var unsupportedReason = false;
            if (!field) {
                return;
            }
            try {
                loaded = childFieldLoaded(controller, structure, name);
                dynamic = hasDynamicModifiers(info);
            } catch (error) {
                unsupportedReason = "child_field_metadata_failed";
            }
            redacted = SECRET_FIELD.test(name) || sensitiveFields.indexOf(name) !== -1;
            result[name] = {
                type: field.type,
                relation: field.relation || false,
                selection: bounded(field.selection || false),
                string: info.string || field.string || name,
                widget: info.widget || info.attrs && info.attrs.widget || false,
                modifiers: bounded(staticModifiers(info)),
                dynamicModifiers: dynamic,
                redacted: redacted,
                loaded: loaded,
                batchWritable: !unsupportedReason && loaded && !dynamic && !redacted &&
                    !fieldWidget(info) &&
                    ["binary", "one2many"].indexOf(field.type) === -1,
                unsupportedReason: unsupportedReason,
            };
        });
        return result;
    }

    function one2manyOperations(meta, structure) {
        var attrs = structure.operationView && structure.operationView.arch &&
            structure.operationView.arch.attrs || {};
        var options = structure.info.options || {};
        var fieldAttrs = structure.info.attrs || {};
        var active = structure.widget && structure.widget.activeActions || {};
        var writable = !meta.readonly && !meta.invisible && !meta.redacted &&
            !meta.unsupportedReason;
        return {
            create: writable && !!structure.operationView && active.create !== false &&
                parsedArchFlag(attrs.create, true) &&
                parsedArchFlag(fieldAttrs.can_create, true) && !options.no_create,
            update: writable && !!structure.operationView && active.write !== false &&
                active.edit !== false && parsedArchFlag(attrs.edit, true) &&
                parsedArchFlag(fieldAttrs.can_write, true),
            delete: writable && !!structure.operationView && active.delete !== false &&
                parsedArchFlag(attrs.delete, true),
        };
    }

    function decorateOne2manyFields(controller, record, rawRecord, fields, sensitiveFields) {
        _.each(fields, function (meta, name) {
            var structure;
            var info;
            var views;
            var childFields;
            var schema;
            var list;
            if (meta.type !== "one2many") {
                return;
            }
            info = fieldInfo(rawRecord, "form")[name] || {};
            views = info.views || {};
            meta.operations = {create: false, update: false, delete: false};
            meta.hasTreeView = !!(views.list || views.tree);
            meta.hasFormView = !!views.form;
            meta.schemaSource = views.form ? "form" : meta.hasTreeView ? "tree" : false;
            meta.childFieldCount = 0;
            meta.schemaHash = false;
            list = record.data && record.data[name];
            meta.collection = one2manyCollection(list);
            schema = one2manySchema(rawRecord, name);
            if (!schema) {
                meta.unsupportedReason = meta.unsupportedReason || "child_schema_unavailable";
                return;
            }
            structure = one2manyStructure(controller, rawRecord, name, list);
            childFields = childFieldMetadata(controller, structure || _.extend({}, schema, {
                list: {data: []},
            }), sensitiveFields);
            meta.schemaSource = schema.schemaSource;
            meta.childFieldCount = _.keys(childFields).length;
            meta.schemaHash = canonicalSchemaHash(childFields);
            if (!structure) {
                meta.unsupportedReason = meta.unsupportedReason || "x2many_collection_unavailable";
                return;
            }
            meta.operations = one2manyOperations(meta, structure);
            if (structure.widget && !_.isFunction(structure.widget._openFormDialog)) {
                meta.unsupportedReason = "unsupported_widget";
                meta.operations = {create: false, update: false, delete: false};
            } else if (!structure.widget) {
                meta.unsupportedReason = meta.unsupportedReason || "requires_form_activation";
            }
        });
    }

    function serializeOne2many(controller, rawRecord, name, meta, value) {
        var collection = one2manyCollection(value);
        return {
            count: collection.totalCount,
            loadedCount: collection.loadedCount,
            hasMore: collection.hasMore,
        };
    }

    function one2manyIsDirty(controller, rawRecord, name) {
        return (controller.__aguiHostDirtyFields || []).indexOf(name) !== -1;
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
            value = field.type === "one2many" ?
                serializeOne2many(controller, rawRecord, name, meta, record.data && record.data[name]) :
                serializeValue(record.data && record.data[name], field);
            if (value !== undefined) {
                values[name] = value;
            }
            if (dirtyFields.indexOf(name) !== -1 ||
                    field.type === "one2many" && one2manyIsDirty(controller, rawRecord, name)) {
                value = field.type === "one2many" ?
                    serializeOne2many(controller, rawRecord, name, meta, record.data && record.data[name]) :
                    serializeValue(record.data && record.data[name], field);
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

    function buttonNodes(arch, result) {
        result = result || [];
        if (!arch) {
            return result;
        }
        if (arch.tag === "button" && arch.attrs &&
                ["action", "object"].indexOf(arch.attrs.type) !== -1) {
            result.push(arch);
        }
        _.each(arch.children || [], function (child) {
            buttonNodes(child, result);
        });
        return result;
    }

    function matchingButtonNode(nodes, name, occurrence) {
        return _.filter(nodes, function (node) {
            return String(node.attrs && node.attrs.name || "") === name;
        })[occurrence] || false;
    }

    function visibleViewButtons(controller, snapshot, registerToken) {
        var renderer = controller && controller.renderer;
        var nodes = buttonNodes(renderer && renderer.arch);
        var occurrences = {};
        var controls = [];
        var state = getRecord(controller, false);
        var viewType = snapshot.controller.viewType;
        var $buttons = renderer && renderer.$ ? renderer.$("button[name]") : $();
        $buttons.each(function () {
            var $element = $(this);
            var name = String($element.attr("name") || "");
            var node;
            var record = state;
            var localId;
            var label;
            if (controls.length >= MAX_VIEW_CONTROLS || !name || $element.prop("disabled") ||
                    !visibleElement($element) || $element.closest(".o_field_x2many").length) {
                return;
            }
            node = matchingButtonNode(
                nodes, name, viewType === "list" ? 0 : occurrences[name] || 0
            );
            occurrences[name] = (occurrences[name] || 0) + 1;
            if (!node) {
                return;
            }
            if (viewType === "list") {
                localId = $element.closest(".o_data_row").data("id");
                record = controller.model && controller.model.get &&
                    controller.model.get(localId, {raw: true});
                if (!record || !record.res_id) {
                    return;
                }
            }
            label = String($element.attr("title") || $element.attr("aria-label") ||
                $element.text() || node.attrs.string || name).trim().slice(0, 160);
            controls.push({
                token: registerToken("control", {
                    type: node.attrs.type,
                    name: name,
                    $element: $element,
                    localId: record && record.id,
                    resId: record && record.res_id || false,
                    model: record && record.model || false,
                    label: label,
                    recordLabel: recordDisplayName(record),
                }),
                type: node.attrs.type,
                name: name,
                label: label,
                recordLabel: recordDisplayName(record),
            });
        });
        return controls;
    }

    function x2ManyCapabilities(controller, snapshot, registerToken, sensitiveFields) {
        var parent = getRecord(controller, false);
        var rawParent = getRecord(controller, true);
        var result = [];
        var infos = fieldInfo(rawParent, "form");
        _.each(_.keys(infos), function (fieldName) {
            var rows = [];
            var controls = [];
            var field = rawParent && rawParent.fields && rawParent.fields[fieldName];
            var fieldMeta = snapshot.fields && snapshot.fields[fieldName] || {};
            var list = parent && parent.data && parent.data[fieldName];
            var schema = one2manySchema(rawParent, fieldName);
            var structure = one2manyStructure(controller, rawParent, fieldName, list);
            var widget = x2manyWidget(controller, rawParent, fieldName);
            var childFields = {};
            var fieldToken = false;
            var unsupportedReason = fieldMeta.unsupportedReason || false;
            var validList;
            var $create;
            if (!field || field.type !== "one2many") {
                return;
            }
            validList = !!(list && list.type === "list" && list.model === field.relation &&
                _.isArray(list.data) && _.isArray(list.res_ids));
            if (schema) {
                try {
                    childFields = childFieldMetadata(controller, structure || _.extend({}, schema, {
                        list: {data: []},
                    }), sensitiveFields);
                } catch (error) {
                    unsupportedReason = unsupportedReason || "child_schema_unavailable";
                }
            }
            if (validList) {
                fieldToken = registerToken("x2many_field", {
                    widget: widget,
                    fieldName: fieldName,
                    localId: list.id,
                    model: field.relation,
                    schemaHash: fieldMeta.schemaHash,
                });
            }
            _.each(validList ? list.data : [], function (item) {
                var record = controller.model.get(item.id);
                var rawRecord = controller.model.get(item.id, {raw: true});
                var rowToken;
                var $row;
                var controlToken;
                if (!record || !rawRecord || record.model !== field.relation) {
                    return;
                }
                rowToken = registerToken("x2many_row", {
                    widget: widget,
                    fieldName: fieldName,
                    localId: record.id,
                    resId: record.res_id || false,
                    model: record.model,
                    fields: childFields,
                    viewType: schema && schema.viewType || false,
                });
                $row = widget && widget.renderer && widget.renderer.$ ?
                    widget.renderer.$(".o_data_row").filter(function () {
                        return $(this).data("id") === record.id;
                    }).first() : $();
                if ($row.length && visibleElement($row)) {
                    controlToken = registerToken("control", {
                        type: widget.isReadonly ? "open" : "edit",
                        name: fieldName,
                        x2manyAction: "open",
                        widget: widget,
                        $element: $row,
                        fieldName: fieldName,
                        localId: record.id,
                        resId: record.res_id || false,
                        model: record.model,
                        label: recordDisplayName(record),
                        recordLabel: recordDisplayName(record),
                    });
                    controls.push({
                        token: controlToken,
                        type: widget.isReadonly ? "open" : "edit",
                        label: recordDisplayName(record),
                        recordLabel: recordDisplayName(record),
                    });
                }
                rows.push({
                    id: _.isNumber(rawRecord.res_id) ? rawRecord.res_id : false,
                    token: rowToken,
                    displayName: recordDisplayName(record),
                    openControlToken: controlToken || false,
                });
            });
            if (widget && !widget.isReadonly && widget.activeActions &&
                    widget.activeActions.create) {
                $create = widget.$(".o_field_x2many_list_row_add a:visible, button.o-kanban-button-new:visible").first();
                if ($create.length && visibleElement($create)) {
                    controls.push({
                        token: registerToken("control", {
                            type: "create",
                            name: fieldName,
                            x2manyAction: "create",
                            widget: widget,
                            $element: $create,
                            fieldName: fieldName,
                            localId: widget.value.id,
                            resId: false,
                            model: widget.field.relation,
                            label: String($create.text() || "新增明细").trim().slice(0, 160),
                            recordLabel: fieldMeta.string,
                        }),
                        type: "create",
                        label: String($create.text() || "新增明细").trim().slice(0, 160),
                        recordLabel: fieldMeta.string,
                    });
                }
            }
            result.push({
                field: fieldName,
                label: fieldMeta.string || field.string || fieldName,
                relation: field.relation || false,
                relationField: field.relation_field || false,
                widget: fieldMeta.widget || false,
                readonly: !!fieldMeta.readonly,
                invisible: !!fieldMeta.invisible,
                hasTreeView: !!fieldMeta.hasTreeView,
                hasFormView: !!fieldMeta.hasFormView,
                schemaSource: fieldMeta.schemaSource || false,
                childFieldCount: fieldMeta.childFieldCount || 0,
                schemaHash: fieldMeta.schemaHash || false,
                collection: clone(fieldMeta.collection || {}),
                operations: clone(fieldMeta.operations || {
                    create: false, update: false, delete: false,
                }),
                fieldToken: fieldToken,
                rows: rows,
                controls: controls,
                unsupportedReason: unsupportedReason,
            });
        });
        return result;
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

    function groupingAvailable(controller, viewType) {
        var searchView = controller && controller.searchView;
        var groupByMenu = searchView && searchView.groupby_menu;
        return ["list", "kanban"].indexOf(viewType) !== -1 && !!(
            searchView && searchView.query && groupByMenu &&
            _.isArray(groupByMenu.groupableFields)
        );
    }

    function searchGroupFields(controller, viewType, sensitiveFields) {
        var searchView = controller && controller.searchView;
        var groupByMenu = searchView && searchView.groupby_menu;
        var result = {};
        if (!groupingAvailable(controller, viewType)) {
            return result;
        }
        _.each(groupByMenu.groupableFields, function (field) {
            var name = field && field.name;
            if (!name || !field.sortable || GROUP_FIELD_TYPES.indexOf(field.type) === -1 ||
                    field.invisible === true || field.modifiers && field.modifiers.invisible ||
                    SECRET_FIELD.test(name) || sensitiveFields.indexOf(name) !== -1) {
                return;
            }
            result[name] = {
                name: name,
                string: field.string || name,
                type: field.type,
                intervals: ["date", "datetime"].indexOf(field.type) !== -1 ?
                    GROUP_INTERVALS.slice(0) : [],
            };
        });
        return result;
    }

    function currentGroupBy(state, fields) {
        var seen = {};
        return _.chain(state && state.groupedBy || []).map(function (value) {
            var parts = String(value || "").split(":");
            var field = parts.shift();
            var meta = fields[field];
            var interval;
            if (!meta || seen[field]) {
                return false;
            }
            seen[field] = true;
            if (["date", "datetime"].indexOf(meta.type) !== -1) {
                interval = parts[0];
                if (GROUP_INTERVALS.indexOf(interval) === -1) {
                    interval = "month";
                }
                return {field: field, interval: interval};
            }
            return {field: field};
        }).compact().first(MAX_GROUP_LEVELS).value();
    }

    function buildViewCapabilities(controller, snapshot, registerToken, sensitiveFields) {
        var state = getRecord(controller, false);
        var viewType = snapshot.controller.viewType;
        var active = controller.activeActions || {};
        var canGroup = groupingAvailable(controller, viewType);
        var groupFields = searchGroupFields(controller, viewType, sensitiveFields || []);
        var records = [];
        var controls = [];
        var viewTypes = _.chain(controller.actionViews || []).map(function (view) {
            return view && (view.type || view[1]);
        }).filter(function (type) {
            return ["kanban", "list", "form"].indexOf(type) !== -1;
        }).uniq().value();
        if (viewTypes.indexOf(viewType) === -1) viewTypes.unshift(viewType);
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
        controls = controls.concat(visibleViewButtons(controller, snapshot, registerToken));
        return {
            create: !!active.create,
            viewTypes: viewTypes,
            open: viewType === "list" || viewType === "kanban",
            edit: !!active.edit,
            filter: !!(controller.searchView && _.isFunction(controller.searchView.updateFilters)),
            group: canGroup,
            totalCount: state && (_.isNumber(state.count) ? state.count : state.data && state.data.length) || 0,
            filterFields: searchFilterFields(controller, sensitiveFields || []),
            groupFields: groupFields,
            groupBy: currentGroupBy(state, groupFields),
            records: records,
            controls: controls.slice(0, MAX_VIEW_CONTROLS),
            x2many: viewType === "form" ? x2ManyCapabilities(
                controller, snapshot, registerToken, sensitiveFields || []
            ) : [],
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

    function groupError(code, message) {
        var error = new Error(message);
        error.code = code;
        return error;
    }

    function validateGroupBy(snapshot, groupBy) {
        var fields = snapshot.capabilities && snapshot.capabilities.groupFields || {};
        var seen = {};
        if (!_.isArray(groupBy) || groupBy.length > MAX_GROUP_LEVELS) {
            throw groupError("invalid_group_by", "分组必须是最多三级的数组。");
        }
        return _.map(groupBy, function (item) {
            var field = item && _.isString(item.field) ? item.field.trim() : "";
            var meta = fields[field];
            var isDate;
            var interval;
            if (!_.isObject(item) || _.isArray(item) ||
                    _.difference(_.keys(item), ["field", "interval"]).length) {
                throw groupError("invalid_group_by", "分组项格式无效。");
            }
            if (!field || field.length > 128 || field.indexOf(".") !== -1 || !meta || seen[field]) {
                throw groupError("invalid_group_field", "分组字段不可用或重复。");
            }
            seen[field] = true;
            isDate = ["date", "datetime"].indexOf(meta.type) !== -1;
            interval = item.interval;
            if (!isDate && interval !== undefined) {
                throw groupError("invalid_group_interval", "非日期字段不能指定日期粒度。");
            }
            if (isDate) {
                interval = interval === undefined ? "month" : interval;
                if (!_.isString(interval) || (meta.intervals || []).indexOf(interval) === -1) {
                    throw groupError("invalid_group_interval", "日期分组粒度无效。");
                }
                return {field: field, interval: interval};
            }
            return {field: field};
        });
    }

    function facetAttribute(facet, name) {
        return facet && _.isFunction(facet.get) ? facet.get(name) :
            facet && facet.attributes && facet.attributes[name];
    }

    function stripFavoriteGroupBy(searchView) {
        searchView.query.each(function (facet) {
            var field;
            var getContext;
            if (!facetAttribute(facet, "is_custom_filter")) {
                return;
            }
            field = facetAttribute(facet, "field");
            if (!field || field.__aguiGroupByWrapped) {
                return;
            }
            getContext = field.get_context;
            field.get_context = function () {
                var context = _.isFunction(getContext) ? getContext.apply(this, arguments) : getContext;
                if (!context || !_.isObject(context) || _.isArray(context)) {
                    return context;
                }
                return _.omit(context, "group_by");
            };
            field.get_groupby = function () { return []; };
            field.__aguiGroupByWrapped = true;
        });
    }

    function groupMapping(searchView, fieldName) {
        return _.find(searchView.groupbysMapping || [], function (mapping) {
            return mapping.groupby && mapping.groupby.attrs &&
                mapping.groupby.attrs.fieldName === fieldName;
        });
    }

    function groupMenuItem(menu, fieldName) {
        return _.find(menu.items || [], function (item) {
            return item.fieldName === fieldName;
        });
    }

    function ensureGroupMapping(searchView, spec) {
        var menu = searchView.groupby_menu;
        var mapping = groupMapping(searchView, spec.field);
        var menuItem = groupMenuItem(menu, spec.field);
        var groupEntry;
        var groupby;
        var group;
        var meta;
        var isDate;
        var groupId;
        var presented;
        meta = searchView.fields && searchView.fields[spec.field] ||
            _.findWhere(menu.groupableFields || [], {name: spec.field}) || {};
        isDate = ["date", "datetime"].indexOf(meta.type) !== -1;
        groupId = mapping && mapping.groupId || menuItem && menuItem.groupId ||
            _.uniqueId("__group__");
        if (!menuItem) {
            menuItem = {
                itemId: mapping && mapping.groupbyId || _.uniqueId("__groupby__"),
                description: meta.string || spec.field,
                fieldName: spec.field,
                groupId: groupId,
                isDate: isDate,
                isActive: false,
            };
            if (_.isFunction(menu._prepareItem)) {
                menu._prepareItem(menuItem);
            }
            menu.items = menu.items || [];
            menu.items.push(menuItem);
            presented = _.findWhere(menu.presentedFields || [], {name: spec.field});
            if (presented) {
                menu.presentedFields.splice(menu.presentedFields.indexOf(presented), 1);
            }
        }
        if (!mapping) {
            groupby = new searchInputs.Filter({attrs: {
                context: "{'group_by':'" + spec.field + "'}",
                name: meta.string || spec.field,
                string: meta.string || spec.field,
                fieldName: spec.field,
                isDate: isDate,
                modifiers: {},
            }}, searchView);
            group = new searchInputs.FilterGroup(
                [groupby], searchView, searchView.intervalMapping, searchView.periodMapping
            );
            mapping = {groupbyId: menuItem.itemId, groupby: groupby, groupId: groupId};
            searchView.groupbysMapping.push(mapping);
            searchView.groupsMapping.push({groupId: groupId, group: group, category: "Group By"});
        }
        groupEntry = _.findWhere(searchView.groupsMapping || [], {groupId: mapping.groupId});
        if (!groupEntry) {
            group = new searchInputs.FilterGroup(
                [mapping.groupby], searchView, searchView.intervalMapping, searchView.periodMapping
            );
            groupEntry = {groupId: mapping.groupId, group: group, category: "Group By"};
            searchView.groupsMapping.push(groupEntry);
        }
        return {mapping: mapping, group: groupEntry.group, menuItem: menuItem};
    }

    function applyGroupBy(controller, groupBy) {
        var searchView = controller && controller.searchView;
        var query = searchView && searchView.query;
        var facets = [];
        if (!searchView || !searchView.groupby_menu || !query ||
                !_.isFunction(query.each) || !_.isFunction(query.remove) ||
                !_.isFunction(query.add) || !_.isFunction(query.trigger)) {
            throw groupError("group_unavailable", "当前视图不支持原生分组。");
        }
        stripFavoriteGroupBy(searchView);
        query.each(function (facet) {
            if (facetAttribute(facet, "cat") === "groupByCategory") {
                facets.push(facet);
            }
        });
        _.each(facets, function (facet) {
            query.remove(facet, {silent: true});
        });
        _.each(groupBy, function (spec) {
            var native = ensureGroupMapping(searchView, spec);
            var couple;
            if (spec.interval) {
                couple = _.findWhere(searchView.intervalMapping, {groupby: native.mapping.groupby});
                if (!couple) {
                    couple = {groupby: native.mapping.groupby, interval: spec.interval};
                    searchView.intervalMapping.push(couple);
                }
                couple.interval = spec.interval;
                native.menuItem.currentOptionId = spec.interval;
            }
            if (_.isFunction(native.group.updateIntervalMapping)) {
                native.group.updateIntervalMapping(searchView.intervalMapping);
            }
            query.add([native.group.make_facet([
                native.group.make_value(native.mapping.groupby),
            ])], {silent: true});
        });
        query.trigger("reset");
        return clone(groupBy);
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

    function snapshotByteLength(snapshot) {
        return utf8ByteLength(JSON.stringify(snapshot));
    }

    function snapshotMetadataByteLength(snapshot) {
        return snapshotByteLength({
            fields: snapshot.fields,
            x2many: _.map(snapshot.capabilities && snapshot.capabilities.x2many || [], function (item) {
                return _.omit(item, "rows", "controls");
            }),
        });
    }

    function compactSnapshot(snapshot) {
        if (snapshotByteLength(snapshot) <= MAX_SNAPSHOT_BYTES) {
            return snapshot;
        }
        var values = snapshot.record && snapshot.record.values || {};
        var dirtyFields = snapshot.record && snapshot.record.dirtyFields || [];
        _.each(_.keys(values), function (name) {
            var meta = snapshot.fields && snapshot.fields[name];
            if (dirtyFields.indexOf(name) === -1 && (!meta || meta.type !== "one2many")) {
                delete values[name];
            }
        });
        if (snapshotByteLength(snapshot) <= MAX_SNAPSHOT_BYTES) {
            return snapshot;
        }
        _.each(_.keys(values), function (name) {
            var meta = snapshot.fields && snapshot.fields[name];
            if (dirtyFields.indexOf(name) === -1 && meta && meta.type === "one2many") {
                delete values[name];
            }
        });
        if (snapshotByteLength(snapshot) <= MAX_SNAPSHOT_BYTES) {
            return snapshot;
        }
        _.each(snapshot.capabilities && snapshot.capabilities.x2many || [], function (item) {
            _.each(item.rows || [], function (row) {
                delete row.displayName;
            });
            _.each(item.controls || [], function (control) {
                delete control.label;
                delete control.recordLabel;
            });
        });
        if (snapshotByteLength(snapshot) <= MAX_SNAPSHOT_BYTES) {
            return snapshot;
        }
        var metadataTooLarge = snapshotMetadataByteLength(snapshot) > MAX_SNAPSHOT_BYTES;
        var error = new Error(metadataTooLarge ?
            "当前 HRP 页面字段元信息超过 256 KiB 快照大小限制。" :
            "当前 HRP 页面必要字段元信息、脏字段值和操作令牌超过 256 KiB 快照大小限制。");
        error.code = "snapshot_too_large";
        error.maxBytes = MAX_SNAPSHOT_BYTES;
        error.actualBytes = snapshotByteLength(snapshot);
        throw error;
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
        controller.__aguiHostSensitiveFields = (options.sensitiveFields || []).slice(0);
        fields = buildFields(record, rawRecord, viewType, options.sensitiveFields || []);
        if (viewType === "form") {
            decorateOne2manyFields(
                controller, record, rawRecord, fields, options.sensitiveFields || []
            );
        }
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
        return compactSnapshot(snapshot);
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

    function patchRecord(controller, snapshot, rowBinding) {
        var record = rowBinding ? controller.model.get(rowBinding.localId) : getRecord(controller, false);
        var rawRecord = rowBinding ?
            controller.model.get(rowBinding.localId, {raw: true}) : getRecord(controller, true);
        return {
            record: record,
            rawRecord: rawRecord,
            fields: rowBinding ? rowBinding.fields : snapshot.fields,
            localId: rowBinding ? rowBinding.localId : record && record.id || controller.handle,
            model: rowBinding ? rowBinding.model : record && record.model,
            fieldName: rowBinding && rowBinding.fieldName,
        };
    }

    function relationField(controller, snapshot, name, rowBinding) {
        var target = patchRecord(controller, snapshot, rowBinding);
        var rawRecord = target.rawRecord;
        var meta = target.fields && target.fields[name];
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
        return {rawRecord: rawRecord, meta: meta, field: field, target: target};
    }

    function relationEnvironment(controller, name, localId) {
        var record = localId ? controller.model.get(localId) : getRecord(controller, false);
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

    function searchRelation(controller, snapshot, args, rowBinding) {
        args = args || {};
        var name = String(args.field || "");
        var relation = relationField(controller, snapshot, name, rowBinding);
        var environment = relationEnvironment(controller, name, relation.target.localId);
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
                rowToken: rowBinding ? args.rowToken : false,
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
                environment = relationEnvironment(controller, check.name, check.localId);
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

    function one2manyError(code, message, details) {
        return _.extend(new Error(message || code), details || {}, {code: code});
    }

    function loadedOne2manyRow(controller, structure, rowId) {
        var listState = structure.list;
        var rowState = _.find(listState && listState.data || [], function (candidate) {
            return candidate && parseInt(candidate.res_id, 10) === rowId;
        });
        var localId = rowState && rowState.id;
        if (!localId) {
            return false;
        }
        var record = localId && controller.model.get(localId);
        var rawRecord = localId && controller.model.get(localId, {raw: true});
        return record && rawRecord ? {
            localId: localId, record: record, rawRecord: rawRecord,
        } : false;
    }

    function snapshotHasOne2manyRow(snapshot, name, rowId) {
        var capability = _.findWhere(
            snapshot.capabilities && snapshot.capabilities.x2many || [], {field: name}
        );
        return _.some(capability && capability.rows || [], function (row) {
            return row && row.id === rowId;
        });
    }

    function childFieldForWrite(structure, row, name, childFields) {
        var field = structure.childFields[name];
        var info = structure.childInfos[name];
        var meta = childFields[name];
        var modifiers = row ? evaluateModifiers(row.record, info) : {};
        if (!field || !info || !meta) {
            throw one2manyError("field_not_in_view", "当前子视图不存在该字段。", {
                childField: name,
            });
        }
        if (meta.redacted) {
            throw one2manyError("field_sensitive", "敏感子字段不可修改。", {
                childField: name,
            });
        }
        if (!meta.loaded) {
            throw one2manyError(
                "requires_form_activation",
                "该子字段仅在明细表单中声明，不能由父表单批量流程隐式装载。",
                {childField: name}
            );
        }
        if (!meta.batchWritable) {
            throw one2manyError(
                "batch_requires_interactive", "该子字段必须通过明细表单交互修改。",
                {childField: name}
            );
        }
        if (field.type === "binary" || field.type === "one2many") {
            throw one2manyError(
                "one2many_operation_not_allowed", "该子字段类型不支持批量修改。",
                {childField: name}
            );
        }
        if (modifiers.readonly) {
            throw one2manyError("field_readonly", "该子字段当前只读。", {
                childField: name,
            });
        }
        if (modifiers.invisible) {
            throw one2manyError("field_invisible", "该子字段当前不可见。", {
                childField: name,
            });
        }
        return field;
    }

    function parseOne2manyValues(structure, row, values, childFields, creating) {
        var changes = {};
        var relationChecks = [];
        if (!_.isObject(values) || _.isArray(values)) {
            throw one2manyError("invalid_one2many_patch", "明细 values 必须是字段映射。");
        }
        _.each(values, function (value, name) {
            var field = childFieldForWrite(structure, row, name, childFields);
            if (creating && (field.type === "many2one" || field.type === "many2many")) {
                throw one2manyError(
                    "batch_requires_interactive",
                    "新增明细的关系字段必须通过明细表单交互选择。",
                    {childField: name}
                );
            }
            if (field.type === "many2many") {
                var operation = String(value && (value.operation || value.op) || "").toLowerCase();
                var inputIds = parseIds(value && (value.ids || value.id) || []);
                var currentValue = row && row.record.data && row.record.data[name];
                var current = resolveRelation(currentValue);
                if (creating && operation === "unlink") {
                    throw one2manyError(
                        "one2many_operation_not_allowed",
                        "待创建明细的 Many2many 不支持 unlink。",
                        {childField: name}
                    );
                }
                changes[name] = many2manyCommand(currentValue, value);
                relationChecks.push({
                    name: name,
                    relation: field.relation,
                    operation: operation,
                    ids: operation === "replace" ? changes[name].ids : inputIds,
                    currentIds: current.ids,
                });
            } else {
                changes[name] = parseScalar(field, value);
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
        });
        return {changes: changes, relationChecks: relationChecks};
    }

    function prepareOne2manyField(controller, snapshot, name, value, meta, record, rawRecord) {
        var structure = one2manyStructure(
            controller, rawRecord, name, record.data && record.data[name]);
        var operations = value && value.operations;
        var childFields;
        var seen = {};
        var result = [];
        if (!structure || !meta.operations || !_.isObject(value) || _.isArray(value) ||
                !_.isArray(operations) || !operations.length) {
            throw one2manyError("invalid_one2many_patch", "One2many patch 结构无效。");
        }
        childFields = childFieldMetadata(
            controller, structure, controller.__aguiHostSensitiveFields || []
        );
        var unloadedChild = _.find(_.keys(childFields), function (childName) {
            return !childFields[childName].loaded;
        });
        if (unloadedChild) {
            throw one2manyError(
                "requires_form_activation",
                "该 One2many 的完整子字段尚未装载，必须进入原生明细表单操作。",
                {childField: unloadedChild}
            );
        }
        _.each(operations, function (item) {
            var operation = String(item && item.operation || "").toLowerCase();
            var rowId = item && item.id;
            var row = false;
            var parsed;
            var oldValues = {};
            if (["create", "update", "delete"].indexOf(operation) === -1) {
                throw one2manyError("invalid_one2many_patch", "明细操作类型无效。");
            }
            if (!meta.operations[operation]) {
                throw one2manyError(
                    "one2many_operation_not_allowed", "当前子视图不允许该明细操作。",
                    {rowId: rowId || false}
                );
            }
            if (operation === "create") {
                if (_.has(item, "id")) {
                    throw one2manyError("invalid_one2many_patch", "create 不接受明细 ID。");
                }
                parsed = parseOne2manyValues(
                    structure, false, item.values, childFields, true
                );
            } else {
                if (!_.isNumber(rowId) || !isFinite(rowId) ||
                        Math.floor(rowId) !== rowId || rowId <= 0) {
                    throw one2manyError("invalid_one2many_patch", "明细 ID 必须是正整数。", {
                        rowId: rowId || false,
                    });
                }
                if (seen[rowId]) {
                    throw one2manyError(
                        "one2many_operation_conflict", "同一明细行只能操作一次。",
                        {rowId: rowId}
                    );
                }
                seen[rowId] = true;
                row = loadedOne2manyRow(controller, structure, rowId);
                if (!row || !snapshotHasOne2manyRow(snapshot, name, rowId)) {
                    var listState = structure.list;
                    throw one2manyError(
                        "one2many_row_not_loaded", "明细行不属于当前有效快照。",
                        {
                            rowId: rowId,
                            liveRowIds: _.pluck(listState && listState.data || [], "res_id"),
                            snapshotRowIds: _.pluck(
                                (_.findWhere(snapshot.capabilities &&
                                    snapshot.capabilities.x2many || [], {field: name}) || {}).rows || [],
                                "id"
                            ),
                        }
                    );
                }
                parsed = operation === "update" ? parseOne2manyValues(
                    structure, row, item.values, childFields, false
                ) : {changes: {}, relationChecks: []};
                _.each(parsed.relationChecks, function (check) {
                    check.localId = row.localId;
                });
                _.each(parsed.changes, function (_change, childName) {
                    oldValues[childName] = previewValue(
                        row.record.data && row.record.data[childName],
                        structure.childFields[childName]
                    );
                });
            }
            result.push({
                operation: operation,
                id: operation === "create" ? false : rowId,
                localId: row && row.localId || false,
                rowLabel: row ? recordDisplayName(row.record) : "新增明细",
                inputValues: clone(item.values || {}),
                changes: parsed.changes,
                oldValues: oldValues,
                relationChecks: parsed.relationChecks,
            });
        });
        return {name: name, operations: result, childFields: childFields};
    }

    function preparePatch(controller, snapshot, args, options) {
        options = options || {};
        var target = patchRecord(controller, snapshot, options.rowBinding);
        var rawRecord = target.rawRecord;
        var record = target.record;
        var patch = normalizePatch(args.patch);
        var changes = {};
        var rejected = [];
        var applied = [];
        var relationChecks = [];
        var beforeValues = {};
        var undoPatch = {};
        var undoSupported = true;
        var one2manyFields = [];
        var one2manyOperationCount = 0;
        var dirtyFields = _.keys(rawRecord && rawRecord._changes || {});
        var stagedFields = controller.__aguiHostStagedFields &&
            controller.__aguiHostStagedFields[target.localId] || [];
        if (options.allowStaged) {
            dirtyFields = _.difference(dirtyFields, stagedFields);
        } else if (!options.rowBinding) {
            dirtyFields = _.uniq((snapshot.record && snapshot.record.dirtyFields || [])
                .concat(dirtyFields, controller.__aguiHostDirtyFields || []));
        }
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
            var meta = target.fields && target.fields[name];
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
                if (field.type === "one2many") {
                    var one2many = prepareOne2manyField(
                        controller, snapshot, name, item.value, meta, record, rawRecord
                    );
                    one2manyOperationCount += one2many.operations.length;
                    if (one2manyOperationCount > MAX_ONE2MANY_OPERATIONS) {
                        throw one2manyError(
                            "one2many_operation_limit_exceeded",
                            "单次 One2many 操作数量不能超过 40 个。"
                        );
                    }
                    one2manyFields.push(one2many);
                    _.each(one2many.operations, function (entry) {
                        relationChecks = relationChecks.concat(entry.relationChecks);
                    });
                } else if (field.type === "many2many") {
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
                        localId: target.localId,
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
                            localId: target.localId,
                        });
                    }
                }
                applied.push(name);
            } catch (error) {
                rejected.push({
                    field: name || false,
                    code: error.code || "invalid_value",
                    message: error.message || false,
                    rowId: error.rowId || false,
                    childField: error.childField || false,
                    liveRowIds: error.liveRowIds || undefined,
                    snapshotRowIds: error.snapshotRowIds || undefined,
                });
            }
        });
        if (rejected.length) {
            changes = {};
            applied = [];
            relationChecks = [];
            one2manyFields = [];
        }
        return {
            changes: changes,
            applied: applied,
            rejected: rejected,
            relationChecks: relationChecks,
            beforeValues: beforeValues,
            undoPatch: undoPatch,
            undoSupported: undoSupported,
            one2manyFields: one2manyFields,
        };
    }

    function one2manyPreview(preparedField) {
        var childFields = preparedField.childFields || {};
        var result = [];
        _.each(preparedField.operations, function (operation) {
            if (operation.operation === "delete") {
                result.push({
                    operation: "delete",
                    rowId: operation.id,
                    rowLabel: operation.rowLabel,
                    childField: false,
                    oldValue: operation.rowLabel,
                    newValue: false,
                    sensitive: false,
                });
                return;
            }
            _.each(operation.inputValues, function (value, name) {
                var sensitive = !!(childFields[name] && childFields[name].redacted);
                result.push({
                    operation: operation.operation,
                    rowId: operation.id,
                    rowLabel: operation.rowLabel,
                    childField: name,
                    oldValue: sensitive ? "[redacted]" :
                        operation.oldValues[name] === undefined ? false : operation.oldValues[name],
                    newValue: sensitive ? "[redacted]" : bounded(value),
                    sensitive: sensitive,
                });
            });
        });
        return result;
    }

    function buildPatchPreview(controller, snapshot, args, options) {
        args = args || {};
        options = options || {};
        var target = patchRecord(controller, snapshot, options.rowBinding);
        var rawRecord = target.rawRecord;
        var record = target.record;
        var prepared = preparePatch(controller, snapshot, args, options);
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
            var meta = target.fields && target.fields[name] || {};
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
            } else if (field.type === "one2many") {
                var preparedField = _.findWhere(prepared.one2manyFields || [], {name: name});
                newValue = preparedField ? one2manyPreview(preparedField) : "[invalid]";
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

    function cloneModelValue(value) {
        var result;
        if (_.isArray(value)) {
            return _.map(value, cloneModelValue);
        }
        if (value && value._isAMomentObject) {
            return value.clone ? value.clone() : value;
        }
        if ($.isPlainObject(value)) {
            result = {};
            _.each(value, function (item, key) {
                result[key] = cloneModelValue(item);
            });
            return result;
        }
        return value;
    }

    function modelSubtreeIds(model, rootId) {
        var ids = {};
        var changed = true;
        ids[rootId] = true;
        while (changed) {
            changed = false;
            _.each(model.localData || {}, function (dataPoint, id) {
                if (!ids[id] && dataPoint && ids[dataPoint.parentID]) {
                    ids[id] = true;
                    changed = true;
                }
            });
        }
        return _.keys(ids);
    }

    function captureModelCheckpoint(controller, rootId) {
        var model = controller.model;
        var states = {};
        if (!model || !model.localData || !model.localData[rootId]) {
            return false;
        }
        _.each(modelSubtreeIds(model, rootId), function (id) {
            var original = model.localData[id];
            var state = _.clone(original);
            _.each([
                "data", "_changes", "_savePoint", "_cache", "res_ids",
                "orderedResIDs", "fields", "fieldsInfo",
            ], function (name) {
                if (_.has(original, name)) {
                    state[name] = cloneModelValue(original[name]);
                }
            });
            states[id] = state;
        });
        return {
            rootId: rootId,
            states: states,
            stagedFields: cloneModelValue(controller.__aguiHostStagedFields || {}),
            dirtyFields: (controller.__aguiHostDirtyFields || []).slice(0),
        };
    }

    function restoreModelCheckpoint(controller, checkpoint) {
        if (!checkpoint) {
            return;
        }
        var model = controller.model;
        _.each(modelSubtreeIds(model, checkpoint.rootId), function (id) {
            delete model.localData[id];
        });
        _.each(checkpoint.states, function (state, id) {
            model.localData[id] = state;
        });
        controller.__aguiHostStagedFields = checkpoint.stagedFields;
        controller.__aguiHostDirtyFields = checkpoint.dirtyFields;
    }

    function applyPatch(controller, snapshot, args, options) {
        options = options || {};
        var target = patchRecord(controller, snapshot, options.rowBinding);
        var prepared = preparePatch(controller, snapshot, args || {}, options);
        var record = target.record;
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
            var event = {
                target: {name: "__agui_host__"},
                data: {
                    context: record.context || {},
                    notifyChange: true,
                    viewType: "form",
                    allowWarning: true,
                },
                stopPropagation: function () {},
            };
            var checkpoint = prepared.one2manyFields && prepared.one2manyFields.length ?
                captureModelCheckpoint(controller, target.localId) : false;
            var applied = _.keys(prepared.changes).length ?
                $.when(controller._applyChanges(target.localId, prepared.changes, event)) : $.when();
            _.each(prepared.one2manyFields || [], function (field) {
                _.each(field.operations, function (operation) {
                    applied = applied.then(function () {
                        var command = operation.operation === "create" ? {
                            operation: "CREATE",
                            data: operation.changes,
                            position: "bottom",
                        } : operation.operation === "update" ? {
                            operation: "UPDATE",
                            id: operation.localId,
                            data: operation.changes,
                        } : {
                            operation: "DELETE",
                            ids: [operation.localId],
                        };
                        var changes = {};
                        changes[field.name] = command;
                        return controller._applyChanges(target.localId, changes, event);
                    });
                });
            });
            return applied.then(function () {
                return prepared;
            }, function (error) {
                restoreModelCheckpoint(controller, checkpoint);
                if (checkpoint && error) {
                    error.aguiModelRestored = true;
                }
                return $.Deferred().reject(error).promise();
            });
        });
    }

    function markStagedPatch(controller, rowBinding, applied) {
        var localId = rowBinding ? rowBinding.localId : controller.handle;
        var rawRecord = controller.model.get(localId, {raw: true});
        controller.__aguiHostStagedFields = controller.__aguiHostStagedFields || {};
        controller.__aguiHostStagedFields[localId] = _.keys(rawRecord && rawRecord._changes || {});
        controller.__aguiHostDirtyFields = _.uniq((controller.__aguiHostDirtyFields || [])
            .concat(applied || [], rowBinding && rowBinding.fieldName || []));
        if (rowBinding) {
            var rawParent = getRecord(controller, true);
            controller.__aguiHostStagedFields[controller.handle] =
                _.keys(rawParent && rawParent._changes || {});
        }
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
        markStagedPatch: markStagedPatch,
        validateForm: validateForm,
        validateFilterDomain: validateFilterDomain,
        validateGroupBy: validateGroupBy,
        applyGroupBy: applyGroupBy,
        expandUniqueRecordCandidate: expandUniqueRecordCandidate,
        clone: clone,
    };
});
