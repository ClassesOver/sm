odoo.define("agui_chat.host_bridge", function (require) {
    "use strict";

    var ajax = require("web.ajax");
    var core = require("web.core");

    var PROTOCOL = "agui.odoo.v2";
    var MODULE_VERSION = "12.0.8.8.0";
    var WRITE_COMMANDS = {
        "odoo.stage_current_form": true,
        "odoo.patch_current_form": true,
        "odoo.save_current_form": true,
        "odoo.discard_current_form": true,
        "odoo.prepare_x2many_import": true,
    };

    function clone(value) {
        if (value === undefined || value === null) {
            return value;
        }
        return JSON.parse(JSON.stringify(value));
    }

    function bridgeError(code, message) {
        var error = new Error(message || code);
        error.code = code;
        return error;
    }

    function resultError(operation, code, message) {
        return {
            ok: false,
            operation: operation || "odoo.unknown",
            code: code,
            error: message || code,
        };
    }

    function HostBridge(owner) {
        this.owner = owner;
        this.config = null;
        this.catalog = [];
        this.allowedTools = {};
    }

    HostBridge.prototype._rpc = function (route, values) {
        return ajax.jsonRpc(route, "call", values || {}, {shadow: true});
    };

    HostBridge.prototype.loadConfig = function () {
        var self = this;
        return this._rpc("/agui_chat/config").then(function (config) {
            self._validateOdooDeclaration(config);
            self.config = config;
            if (!config.chat_enabled) {
                return config;
            }
            return self._loadAgentDeclaration(config).then(function (agent) {
                self._validateAgentDeclaration(config, agent);
                config.agent = agent;
                return config;
            });
        });
    };

    HostBridge.prototype._validateOdooDeclaration = function (config) {
        if (!config || config.protocol !== PROTOCOL) {
            throw bridgeError("protocol_mismatch", "HRP 未声明 agui.odoo.v2 协议。")
        }
        if (config.module_version !== MODULE_VERSION || config.bundle_version !== MODULE_VERSION) {
            throw bridgeError("version_mismatch", "HRP 模块与前端资源版本不一致。")
        }
        if (!config.command_catalog_hash || !/^[a-f0-9]{64}$/.test(config.command_catalog_hash)) {
            throw bridgeError("catalog_mismatch", "HRP 命令目录摘要无效。")
        }
        if (config.chat_enabled) {
            if (!window.AguiChat || window.AguiChat.version !== config.bundle_version ||
                    window.AguiChat.protocol !== PROTOCOL) {
                throw bridgeError("bundle_mismatch", "已加载的 React 资源与 HRP 不匹配。")
            }
        }
    };

    HostBridge.prototype._loadAgentDeclaration = function (config) {
        var url = String(config.runtime_config_url || "").trim();
        var retryDelays = [0, 250, 500, 1000, 2000];
        var deferred = $.Deferred();
        if (!url) {
            return $.Deferred().reject(bridgeError(
                "agent_handshake_missing", "AgentOS 协议配置不可用。"
            )).promise();
        }
        if (!(url[0] === "/" && url.slice(0, 2) !== "//") &&
                !(config.allow_cross_origin_dev && /^https?:\/\//i.test(url))) {
            return $.Deferred().reject(bridgeError(
                "agent_handshake_url_invalid", "不允许使用该 AgentOS 协议配置地址。"
            )).promise();
        }
        function request(attempt) {
            Promise.resolve().then(function () {
                return window.fetch(url, {
                    method: "GET",
                    credentials: config.credentials || "same-origin",
                    headers: {Accept: "application/json"},
                });
            }).then(function (response) {
                if (!response.ok) {
                    var error = bridgeError("agent_handshake_failed", "无法获取 AgentOS 协议配置。")
                    error.status = response.status;
                    throw error;
                }
                return response.json();
            }).then(function (agent) {
                deferred.resolve(agent);
            }).catch(function (error) {
                var status = error && error.status;
                var retryable = !status || status === 429 || status >= 500;
                if (!retryable || attempt >= retryDelays.length - 1) {
                    deferred.reject(error);
                    return;
                }
                setTimeout(function () {
                    return request(attempt + 1);
                }, retryDelays[attempt + 1]);
            });
        }
        request(0);
        return deferred.promise();
    };

    HostBridge.prototype._validateAgentDeclaration = function (config, agent) {
        if (!agent || agent.protocol !== PROTOCOL || agent.bundle_version !== config.bundle_version ||
                agent.command_catalog_hash !== config.command_catalog_hash) {
            throw bridgeError("agent_protocol_mismatch", "AgentOS 与 HRP v2 协议不匹配。")
        }
    };

    HostBridge.prototype.setCatalog = function (catalog) {
        var self = this;
        var enabled = this.config && this.config.enabled_commands || [];
        var business = this.config && this.config.business_tools || [];
        this.catalog = [];
        this.allowedTools = {};
        if (!this.config || !this.config.host_tools_enabled) {
            return [];
        }
        _.each(catalog || [], function (tool) {
            if (enabled.indexOf(tool.name) === -1) {
                return;
            }
            if (!self.config.write_tools_enabled && WRITE_COMMANDS[tool.name]) {
                return;
            }
            self.catalog.push(clone(tool));
            self.allowedTools[tool.name] = "host";
        });
        _.each(business, function (tool) {
                if (!tool || (!self.config.write_tools_enabled && tool.accessLevel !== "read")) {
                    return;
                }
                var name = tool && String(tool.name || "");
                if (
                    !/^odoo\.business\.[a-z0-9_]+\.[a-z0-9_]+$/.test(name) ||
                    !_.isObject(tool.parameters)
                ) {
                    return;
                }
                self.catalog.push(clone(tool));
                self.allowedTools[name] = "business";
            });
        return clone(this.catalog);
    };

    HostBridge.prototype.mountProps = function (hostState, surface) {
        var config = this.config || {};
        return {
            runtimeUrl: config.runtime_url || "",
            allowCrossOriginDev: !!config.allow_cross_origin_dev,
            agentId: config.default_agent_id || undefined,
            user: {
                id: config.user_id,
                name: config.user_name,
            },
            credentials: config.credentials || "same-origin",
            csrfToken: core.csrf_token || "",
            limits: {
                requestBytes: config.limits && config.limits.request_bytes,
                messages: config.limits && config.limits.messages,
                sseEventBytes: config.limits && config.limits.sse_event_bytes,
            },
            handshake: {
                protocol: config.protocol,
                moduleVersion: config.module_version,
                bundleVersion: config.bundle_version,
                agentProtocol: config.agent && config.agent.protocol,
                agentBundleVersion: config.agent && config.agent.bundle_version,
                commandCatalogHash: config.command_catalog_hash,
                agentCommandCatalogHash: config.agent && config.agent.command_catalog_hash,
            },
            hostState: clone(hostState),
            agentState: {},
            tools: clone(this.catalog),
            menuCatalog: clone(this.owner.call("agui_host", "getMenuCatalog") || {}),
            agentSkills: clone(config.agent && config.agent.skills || []),
            surface: surface,
            hostBridge: this.publicApi(),
        };
    };

    HostBridge.prototype.publicApi = function () {
        var self = this;
        return {
            executeTool: function (call) { return self.executeTool(call); },
            getMenuCatalog: function () {
                return clone(self.owner.call("agui_host", "getMenuCatalog") || {});
            },
            confirmTool: function (call, authorizationId, approved) {
                return self.confirmTool(call, authorizationId, approved);
            },
            undoTool: function (authorizationId) { return self.undoTool(authorizationId); },
            searchMentions: function (values) { return self.searchMentions(values); },
            bindMention: function (values) { return self.bindMention(values); },
            getWorkspaceCapability: function (sessionId) {
                return self.getWorkspaceCapability(sessionId);
            },
            previewX2ManyImport: function (values) {
                return self.previewX2ManyImport(values);
            },
            listSessions: function () { return self.listSessions(); },
            createSession: function (values) { return self.createSession(values); },
            loadSession: function (sessionId) { return self.loadSession(sessionId); },
            saveSession: function (sessionId, values) { return self.saveSession(sessionId, values); },
            archiveSession: function (sessionId) { return self.archiveSession(sessionId); },
            forkSession: function (sessionId, values) { return self.forkSession(sessionId, values); },
            openSurface: function (surface) { return self.openSurface(surface); },
        };
    };

    HostBridge.prototype.listSessions = function () {
        return this._rpc("/agui_chat/session/list", {limit: 20});
    };

    HostBridge.prototype.createSession = function (values) {
        values = values || {};
        return this._rpc("/agui_chat/session/create", {
            name: values.name || false,
            surface: values.surface || "dock",
            agent_id: values.agent_id || false,
        });
    };

    HostBridge.prototype.loadSession = function (sessionId) {
        return this._rpc("/agui_chat/session/get", {session_id: sessionId});
    };

    HostBridge.prototype.saveSession = function (sessionId, values) {
        values = values || {};
        return this._rpc("/agui_chat/session/save", {
            session_id: sessionId || false,
            values: values,
            expected_session_revision: values.expectedSessionRevision,
        });
    };

    HostBridge.prototype.archiveSession = function (sessionId) {
        return this._rpc("/agui_chat/session/archive", {session_id: sessionId});
    };

    HostBridge.prototype.forkSession = function (sessionId, values) {
        values = values || {};
        return this._rpc("/agui_chat/session/fork", {
            session_id: sessionId,
            target_message_id: values.targetMessageId || "",
            source_run_id: values.sourceRunId || "",
            expected_session_revision: values.expectedSessionRevision,
        });
    };

    HostBridge.prototype.openSurface = function (surface) {
        return $.when(this.owner.call("agui_host", "setSurface", surface));
    };

    HostBridge.prototype.searchMentions = function (values) {
        values = clone(values || {});
        var context = this.owner.call("agui_host", "getMentionSearchContext") || {};
        return this._rpc("/agui_chat/mention/search", {
            query: values.query || "",
            scope: values.scope || "all",
            model_scope: values.modelScope || false,
            current_model: context.currentModel || false,
            recent_models: context.recentModels || [],
            current_filter: context.currentFilter || false,
        });
    };

    HostBridge.prototype.bindMention = function (values) {
        values = values || {};
        return this._rpc("/agui_chat/mention/bind", {
            candidate_token: values.candidateToken || "",
            action: values.action || "",
        });
    };

    HostBridge.prototype.getWorkspaceCapability = function (sessionId) {
        return this._rpc("/agui_chat/workspace/capability", {
            session_id: sessionId,
        });
    };

    HostBridge.prototype.previewX2ManyImport = function (values) {
        values = clone(values || {});
        return this._rpc("/agui_chat_import/preview", {
            jobToken: values.jobToken || "",
            expectedRevision: values.expectedRevision,
            parseOptions: values.parseOptions || {},
            mapping: values.mapping || {},
            finalize: !!values.finalize,
        });
    };

    HostBridge.prototype._cleanCall = function (call) {
        var result = {
            id: call && call.id || false,
            tool: call && call.tool || "",
            arguments: clone(call && call.arguments || {}),
            message_id: call && call.message_id || false,
            context: clone(call && call.context || {}),
        };
        if (_.isObject(result.arguments)) {
            delete result.arguments.confirmed;
            delete result.arguments.authorizationId;
            delete result.arguments.authorization_id;
            delete result.arguments.__agui_authorized;
        }
        return result;
    };

    HostBridge.prototype.executeTool = function (call) {
        var self = this;
        var cleanCall = this._cleanCall(call);
        if (!this.allowedTools[cleanCall.tool]) {
            return $.when(resultError(cleanCall.tool, "tool_not_declared", "本次运行未声明该客户端工具。"));
        }
        if (this.allowedTools[cleanCall.tool] === "business") {
            return this._businessPrepare(cleanCall);
        }
        return this._browserPrepare(cleanCall, true).then(function (prepared) {
            if (!prepared || !prepared.ok) {
                return prepared || resultError(cleanCall.tool, "host_unavailable");
            }
            return self._serverPrepare(prepared.call, 0);
        }, function (error) {
            return resultError(cleanCall.tool, error.code || "host_unavailable", error.message);
        });
    };

    HostBridge.prototype._businessPrepare = function (call) {
        var self = this;
        return this._rpc("/agui_chat/business/prepare", {
            call: clone(call),
        }).then(function (decision) {
            if (!decision || !decision.ok || decision.needs_confirmation) {
                return decision || resultError(call.tool, "policy_denied");
            }
            return self._executeBusiness(decision);
        }, function (error) {
            return resultError(call.tool, error.code || "policy_unavailable", error.message);
        });
    };

    HostBridge.prototype._executeBusiness = function (decision) {
        var bound = clone(decision && decision.bound_call || {});
        var authorizationId = decision && decision.authorization_id;
        if (!bound.tool || !authorizationId) {
            return $.when(resultError(bound.tool, "authorization_invalid"));
        }
        return this._rpc("/agui_chat/business/execute", {
            command_name: bound.tool,
            payload: bound.arguments,
            authorization_token: authorizationId,
            idempotency_key: authorizationId,
        }).then(function (result) {
            result = clone(result || {});
            result.operation = bound.tool;
            return result;
        }, function (error) {
            return resultError(bound.tool, error.code || "business_command_failed", error.message);
        });
    };

    HostBridge.prototype._browserPrepare = function (call, allowStaleRetry) {
        return $.when(this.owner.call(
            "agui_host", "prepareHostCommand", clone(call), !!allowStaleRetry
        ));
    };

    HostBridge.prototype._serverPrepare = function (call, retryCount) {
        var self = this;
        return this._rpc("/agui_chat/host_command", {
            phase: "prepare",
            call: call,
        }).then(function (decision) {
            if (!decision || !decision.ok || decision.needs_confirmation) {
                return decision || resultError(call.tool, "policy_denied");
            }
            if (decision.replay_result) {
                return self._withUndoReceipt(
                    decision.replay_result, decision.authorization_id
                );
            }
            return self._executeBound(decision, retryCount || 0);
        }, function (error) {
            return resultError(call.tool, error.code || "policy_unavailable", error.message);
        });
    };

    HostBridge.prototype.confirmTool = function (call, authorizationId, approved) {
        var self = this;
        var cleanCall = this._cleanCall(call);
        if (!this.allowedTools[cleanCall.tool]) {
            return $.when(resultError(cleanCall.tool, "tool_not_declared"));
        }
        if (!approved) {
            return this._confirmAuthorization(cleanCall.tool, authorizationId, false);
        }
        if (this.allowedTools[cleanCall.tool] === "business") {
            return this._confirmAuthorization(cleanCall.tool, authorizationId, true).then(
                function (decision) {
                    if (!decision || !decision.ok) {
                        return decision || resultError(cleanCall.tool, "authorization_rejected");
                    }
                    return self._executeBusiness(decision);
                });
        }
        return this._browserPrepare(cleanCall, true).then(function (prepared) {
            if (!prepared || !prepared.ok) {
                return self._retireAuthorization(cleanCall.tool, authorizationId).then(function (retirement) {
                    if (retirement && retirement.replay_result) {
                        return self._withUndoReceipt(
                            retirement.replay_result,
                            retirement.authorization_id || authorizationId
                        );
                    }
                    if (!retirement || !retirement.retired) {
                        return retirement || resultError(cleanCall.tool, "confirmation_failed");
                    }
                    return prepared || resultError(cleanCall.tool, "stale_snapshot");
                });
            }
            if (prepared.retried) {
                return self._retireAuthorization(cleanCall.tool, authorizationId).then(function (retirement) {
                    if (retirement && retirement.replay_result) {
                        return self._withUndoReceipt(
                            retirement.replay_result,
                            retirement.authorization_id || authorizationId
                        );
                    }
                    if (!retirement || !retirement.retired) {
                        return retirement || resultError(cleanCall.tool, "confirmation_failed");
                    }
                    return self._serverPrepare(prepared.call, 0);
                });
            }
            return self._confirmAuthorization(cleanCall.tool, authorizationId, true).then(function (decision) {
                if (!decision || !decision.ok) {
                    return decision || resultError(cleanCall.tool, "authorization_rejected");
                }
                if (decision.replay_result) {
                    return self._withUndoReceipt(
                        decision.replay_result, decision.authorization_id || authorizationId
                    );
                }
                return self._executeBound(decision, 0);
            });
        }, function (error) {
            return resultError(cleanCall.tool, error.code || "confirmation_failed", error.message);
        });
    };

    HostBridge.prototype._confirmAuthorization = function (operation, authorizationId, approved) {
        return this._rpc("/agui_chat/host_command", {
            phase: "confirm",
            authorization_id: authorizationId,
            approved: !!approved,
        }).then(function (decision) {
            return decision || resultError(operation, "confirmation_failed");
        });
    };

    HostBridge.prototype._retireAuthorization = function (operation, authorizationId) {
        return this._confirmAuthorization(operation, authorizationId, false).then(function (decision) {
            if (decision && decision.replay_result) {
                return decision;
            }
            if (decision && ["authorization_rejected", "authorization_expired"].indexOf(
                decision.code
            ) !== -1) {
                return {ok: true, retired: true};
            }
            return decision || resultError(operation, "confirmation_failed");
        }, function (error) {
            return resultError(
                operation, error && error.code || "confirmation_failed", error && error.message
            );
        });
    };

    HostBridge.prototype._withUndoReceipt = function (result, authorizationId) {
        var publicResult = this._publicResult(result);
        if (!result || !result.ok || !result.undo_payload || !authorizationId) {
            return $.when(publicResult);
        }
        if (!_.isObject(publicResult.receipt)) {
            publicResult.receipt = {};
        }
        return this._rpc("/agui_chat/host_command", {
            phase: "undo_prepare",
            authorization_id: authorizationId,
        }).then(function (undo) {
            if (undo && undo.replay_result) {
                publicResult.receipt.undo = {
                    available: false,
                    status: undo.replay_result.undone ? "undone" : "unavailable",
                };
                return publicResult;
            }
            publicResult.receipt.undo = undo && undo.ok && undo.undo_authorization_id ? {
                available: true,
                authorization_id: undo.undo_authorization_id,
                expires_at: undo.expires_at,
                status: "available",
            } : {available: false, status: "unavailable"};
            return publicResult;
        }, function () {
            publicResult.receipt.undo = {available: false, status: "unavailable"};
            return publicResult;
        });
    };

    HostBridge.prototype._persistenceFailure = function (operation, result, completion) {
        var failure = resultError(
            operation,
            "result_persistence_failed",
            "命令结果未能持久化；命令可能已执行，请刷新当前记录确认状态，勿重复提交。"
        );
        failure.retryable = false;
        failure.persistence_code = completion && completion.code || "completion_failed";
        failure.execution = {
            ok: !!(result && result.ok),
            code: result && result.code || false,
            saved: !!(result && result.saved),
            undone: !!(result && result.undone),
        };
        return failure;
    };

    HostBridge.prototype._executeBound = function (decision, retryCount) {
        var self = this;
        var bound = clone(decision.bound_call || {});
        function finish(result) {
            return self._complete(decision.authorization_id, result).then(function (completion) {
                if (!completion || !completion.ok) {
                    return self._persistenceFailure(bound.tool, result, completion);
                }
                if (result && result.code === "stale_snapshot" &&
                        bound.tool === "odoo.patch_current_form" &&
                        !decision.confirmation_required && retryCount < 1) {
                    return self._browserPrepare(bound, true).then(function (prepared) {
                        if (!prepared || !prepared.ok || !prepared.retried) {
                            return self._publicResult(result);
                        }
                        return self._serverPrepare(prepared.call, retryCount + 1);
                    });
                }
                return self._withUndoReceipt(result, decision.authorization_id);
            }, function (error) {
                return self._persistenceFailure(bound.tool, result, error);
            });
        }
        bound.authorizationId = decision.authorization_id;
        var execute = function () {
            return self.owner.call("agui_host", "executeHostCommand", bound);
        };
        var execution = this.owner && typeof this.owner._withChatFocusPreserved === "function" ?
            this.owner._withChatFocusPreserved(execute) : execute();
        return $.when(execution).then(function (result) {
            return finish(result);
        }, function (error) {
            var failure = error && error.ok === false && error.code ? clone(error) :
                resultError(bound.tool, error && error.code || "command_failed", error && error.message);
            failure.ok = false;
            failure.operation = failure.operation || bound.tool;
            failure.retryable = failure.code === "stale_snapshot";
            return finish(failure);
        });
    };

    HostBridge.prototype.undoTool = function (authorizationId) {
        var self = this;
        return this._rpc("/agui_chat/host_command", {
            phase: "undo_execute",
            authorization_id: authorizationId,
        }).then(function (decision) {
            if (!decision || !decision.ok) {
                return decision || resultError("odoo.undo_current_form", "undo_unavailable");
            }
            if (decision.replay_result) {
                return self._publicResult(decision.replay_result);
            }
            return self._executeBound(decision, 0);
        }, function (error) {
            return resultError(
                "odoo.undo_current_form", error.code || "undo_failed", error.message
            );
        });
    };

    HostBridge.prototype._publicResult = function (result) {
        var value = clone(result || {});
        delete value.undo_payload;
        return value;
    };

    HostBridge.prototype._complete = function (authorizationId, result, attempt) {
        var self = this;
        attempt = attempt || 0;
        return this._rpc("/agui_chat/host_command", {
            phase: "complete",
            authorization_id: authorizationId,
            result: clone(result),
        }).then(function (completion) {
            if (completion && completion.ok) {
                return completion;
            }
            if (attempt < 1) {
                return self._complete(authorizationId, result, attempt + 1);
            }
            return completion || {ok: false, code: "completion_failed"};
        }, function (error) {
            if (attempt < 1) {
                return self._complete(authorizationId, result, attempt + 1);
            }
            return {
                ok: false,
                code: error && error.code || "completion_failed",
                error: error && error.message,
            };
        });
    };

    return {
        HostBridge: HostBridge,
    };
});
