odoo.define("agui_chat.surfaces", function (require) {
    "use strict";

    var Widget = require("web.Widget");
    var WebClient = require("web.WebClient");
    var core = require("web.core");
    var ChatBridge = require("agui_chat.host_bridge");
    var CHAT_CSS_URL = "/agui_chat/static/lib/agui-chat-react/" +
        "agui_chat_widget.12.0.8.4.0.css";
    var DIRECTIONS = ["left", "right", "top", "bottom"];
    var WEBCLIENT_CLASSES = [
        "o_agui_chat_webclient_dock_left", "o_agui_chat_webclient_dock_right",
        "o_agui_chat_webclient_dock_top", "o_agui_chat_webclient_dock_bottom",
    ];
    var STORAGE_PREFIX = "agui_chat.layout.v1.";
    var MOBILE_BREAKPOINT = 768;
    var FLOAT_MARGIN = 16;

    function setClass($el, className, enabled) {
        if ($el && _.isFunction($el.toggleClass)) {
            $el.toggleClass(className, !!enabled);
        }
    }

    function numberInRange(value, minimum, maximum) {
        return typeof value === "number" && isFinite(value) && value >= minimum && value <= maximum;
    }

    function clamp(value, minimum, maximum) {
        return Math.min(Math.max(value, minimum), maximum);
    }

    function viewport() {
        return {
            width: Math.max(document.documentElement && document.documentElement.clientWidth || 0, window.innerWidth || 0),
            height: Math.max(document.documentElement && document.documentElement.clientHeight || 0, window.innerHeight || 0),
        };
    }

    function button(icon, className, title, pressed, extra) {
        return "<button type='button' class='o_agui_chat_action " + className + "' " +
            "title='" + title + "' aria-label='" + title + "'" +
            (pressed ? " aria-pressed='false'" : "") + (extra || "") + ">" +
            "<i class='fa " + icon + "' role='presentation'></i></button>";
    }

    var ChatSurfaceManager = Widget.extend({
        className: "o_agui_chat_surface_manager",
        events: {
            "focusin": "_onSurfaceFocusIn",
            "click .o_agui_chat_dock_toggle": "_onToggleDock",
            "click .o_agui_chat_direction": "_onDirection",
            "click .o_agui_chat_float": "_onFloat",
            "click .o_agui_chat_close": "_onClose",
            "pointerdown .o_agui_chat_surface_actions": "_onTitlebarPointerDown",
            "pointerdown .o_agui_chat_resize_handle": "_onResizePointerDown",
            "keydown .o_agui_chat_resize_handle": "_onResizeKeyDown",
            "click .o_agui_chat_error_close": "_onErrorClose",
        },

        init: function (parent) {
            this._super.apply(this, arguments);
            this.webClient = parent;
            this.bridge = new ChatBridge.HostBridge(this);
            this.hostState = null;
            this.surface = "standalone";
            this.dockDirection = "right";
            this.dockOpen = false;
            this.dockSizes = {left: 720, right: 720, top: 420, bottom: 420};
            this.floatRect = {width: 720, height: 720, left: null, top: null};
            this.storageKey = null;
            this.chatHandle = null;
            this.runtimeHost = null;
            this.runtimeMountTarget = null;
            this.runtimeStyleReady = false;
            this.runtimeStyleFailed = false;
            this.runtimeStyleError = "";
            this.runtimeMountRequested = false;
            this._chatFocusLease = null;
            this.subscribed = false;
            this.interaction = null;
            this._boundPointerMove = this._onWindowPointerMove.bind(this);
            this._boundPointerUp = this._onWindowPointerUp.bind(this);
            this._boundViewportResize = this._onViewportResize.bind(this);
        },

        start: function () {
            var self = this;
            var result;
            var controls =
                button("fa-angle-left", "o_agui_chat_direction", "停靠到左侧", true, " data-direction='left'") +
                button("fa-angle-right", "o_agui_chat_direction", "停靠到右侧", true, " data-direction='right'") +
                button("fa-angle-up", "o_agui_chat_direction", "停靠到顶部", true, " data-direction='top'") +
                button("fa-angle-down", "o_agui_chat_direction", "停靠到底部", true, " data-direction='bottom'") +
                button("fa-window-restore", "o_agui_chat_float", "浮动窗口", true) +
                button("fa-times", "o_agui_chat_close", "关闭", false);
            var handles = ["top", "right", "bottom", "left", "top-left", "top-right", "bottom-right", "bottom-left"].map(function (edge) {
                return "<div class='o_agui_chat_resize_handle o_agui_chat_resize_" + edge +
                    "' data-edge='" + edge + "' role='separator' tabindex='0' aria-label='调整窗口大小'></div>";
            }).join("");
            this.$el.html(
                "<button type='button' class='o_agui_chat_dock_toggle' " +
                    "title='打开智能助手' aria-label='打开智能助手'>" +
                    "<i class='fa fa-commenting-o o_agui_chat_toggle_icon' role='presentation'></i></button>" +
                "<div class='o_agui_chat_dock'><div class='o_agui_chat_dock_slot'></div></div>" +
                "<div class='o_agui_chat_standalone_overlay'><div class='o_agui_chat_standalone_slot'></div></div>" +
                "<div class='o_agui_chat_surface_actions'><span class='o_agui_chat_title'>助手</span>" +
                    "<div class='o_agui_chat_action_buttons'>" + controls + "</div></div>" +
                "<div class='o_agui_chat_resize_handles'>" + handles + "</div>" +
                "<div class='o_agui_chat_error' role='status'><span class='o_agui_chat_error_text'></span>" +
                    button("fa-times", "o_agui_chat_error_close", "关闭提示", false) + "</div>"
            );
            this.runtimeHost = document.createElement("div");
            this.runtimeHost.className = "o_agui_chat_runtime_host";
            if (_.isFunction(this.runtimeHost.attachShadow)) {
                var shadowRoot = this.runtimeHost.attachShadow({mode: "open"});
                var styleLink = document.createElement("link");
                this.runtimeMountTarget = document.createElement("div");
                this.runtimeMountTarget.style.height = "100%";
                this.runtimeMountTarget.style.minHeight = "0";
                styleLink.rel = "stylesheet";
                styleLink.href = CHAT_CSS_URL;
                styleLink.onload = function () {
                    if (!self.runtimeHost) return;
                    self.runtimeStyleReady = true;
                    if (self.runtimeMountRequested) self._mountOnce();
                };
                styleLink.onerror = function () {
                    if (!self.runtimeHost) return;
                    self.runtimeStyleFailed = true;
                    self.runtimeStyleError = "聊天样式加载失败。";
                    self.runtimeMountRequested = false;
                    self._setEnabled(false);
                    self._showError(self.runtimeStyleError);
                };
                shadowRoot.appendChild(styleLink);
                shadowRoot.appendChild(this.runtimeMountTarget);
            } else {
                this.runtimeStyleFailed = true;
                this.runtimeStyleError = "浏览器不支持隔离的聊天界面。";
            }
            this.$(".o_agui_chat_dock_slot")[0].appendChild(this.runtimeHost);
            if (_.isFunction(window.addEventListener)) window.addEventListener("resize", this._boundViewportResize);
            result = this._super.apply(this, arguments);
            $.when(result).then(function () { self._initialize(); });
            return result;
        },

        destroy: function () {
            this._cancelChatFocusLease();
            if (_.isFunction(window.removeEventListener)) window.removeEventListener("resize", this._boundViewportResize);
            this._stopInteraction();
            this._clearWebClientLayout();
            if (this.subscribed) {
                try { this.call("agui_host", "unsubscribe", this, this._onHostState); } catch (error) {}
                this.subscribed = false;
            }
            if (this.chatHandle) {
                this.chatHandle.unmount();
                this.chatHandle = null;
            }
            this.runtimeHost = null;
            this.runtimeMountTarget = null;
            return this._super.apply(this, arguments);
        },

        _initialize: function () {
            var self = this;
            try {
                if (this.webClient) {
                    this.call("agui_host", "configureNavigation", this.webClient, this.webClient.menu_data);
                    if (this.webClient.action_manager) {
                        this.call("agui_host", "setCurrentController",
                            this.webClient.action_manager.getCurrentAction(), {
                                __actionManager: this.webClient.action_manager,
                            });
                    }
                }
                this.hostState = this.call("agui_host", "getSnapshot");
                this.call("agui_host", "subscribe", this, this._onHostState);
                this.subscribed = true;
            } catch (error) {
                this._showError("聊天页面宿主不可用。");
                return;
            }
            this.bridge.loadConfig().then(function (config) {
                core.bus.trigger("agui_host:configure", {
                    enabled: !!config.chat_enabled,
                    sensitiveFields: config.sensitive_fields || [],
                });
                if (!config.chat_enabled) {
                    self._setEnabled(false);
                    return;
                }
                self.storageKey = STORAGE_PREFIX + String(config.database || "default") + "." + String(config.user_id || "anonymous");
                self._restoreLayout();
                self._setEnabled(true);
                self.bridge.setCatalog(self.call("agui_host", "getToolCatalog"));
                self._mountOnce();
            }, function (error) {
                core.bus.trigger("agui_host:configure", {enabled: false, sensitiveFields: []});
                self._setEnabled(false);
                self._showError(error && error.message || "聊天初始化失败。");
            });
        },

        _setEnabled: function (enabled) {
            setClass(this.$el, "o_agui_chat_enabled", enabled);
            if (!enabled) {
                this._cancelChatFocusLease();
                this._clearWebClientLayout();
            }
        },

        _mountOnce: function () {
            if (this.chatHandle || !this.runtimeHost) return;
            if (this.runtimeStyleFailed || !this.runtimeMountTarget) {
                this._setEnabled(false);
                this._showError(this.runtimeStyleError || "聊天样式加载失败。");
                return;
            }
            if (!this.runtimeStyleReady) {
                this.runtimeMountRequested = true;
                return;
            }
            if (!window.AguiChat || !_.isFunction(window.AguiChat.mount)) {
                this._showError("聊天资源加载失败。");
                return;
            }
            try {
                this.runtimeMountRequested = false;
                this.chatHandle = window.AguiChat.mount(
                    this.runtimeMountTarget,
                    this.bridge.mountProps(this.hostState, this.surface)
                );
                if (this.dockOpen) this._applySurface(this.surface);
            } catch (error) {
                this.chatHandle = null;
                this._showError(error && error.message || "聊天初始化失败。");
            }
        },

        _onHostState: function (snapshot) {
            this.hostState = snapshot;
            if (this.dockOpen && snapshot && snapshot.surface && snapshot.surface !== this.surface) {
                this._applySurface(snapshot.surface);
            }
            if (this.chatHandle) this.chatHandle.update({
                hostState: snapshot,
                menuOptions: this.call("agui_host", "getMenuOptions"),
                surface: this.surface,
            });
            if (this._chatFocusLease) this._chatFocusLease.schedule();
        },

        _withChatFocusPreserved: function (task) {
            var self = this;
            var root = this.runtimeHost && this.runtimeHost.shadowRoot;
            var active = root && root.activeElement;
            var lease;
            var result;
            if (!this.dockOpen || !root || !active || !root.contains(active)) return task();

            this._cancelChatFocusLease();
            lease = {
                root: root,
                target: active,
                selection: null,
                frame: null,
                cancelled: false,
                finished: false,
            };

            function captureSelection(target) {
                lease.selection = null;
                try {
                    if (typeof target.selectionStart === "number" && typeof target.selectionEnd === "number") {
                        lease.selection = {
                            start: target.selectionStart,
                            end: target.selectionEnd,
                            direction: target.selectionDirection,
                        };
                    }
                } catch (error) {}
            }

            function isVisibleAndEnabled(target) {
                var style;
                if (!target || target.disabled || !lease.root.contains(target) || target.isConnected === false) return false;
                if (target.getClientRects && !target.getClientRects().length) return false;
                if (_.isFunction(window.getComputedStyle)) {
                    style = window.getComputedStyle(target);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                }
                return true;
            }

            function restore() {
                var target = lease.target;
                var detached = !target || !lease.root.contains(target) || target.isConnected === false;
                var selection = lease.selection;
                if (lease.cancelled || self._chatFocusLease !== lease || !self.dockOpen ||
                        !self.runtimeHost || self.runtimeHost.shadowRoot !== lease.root) return;
                if (detached) target = lease.root.querySelector("textarea:not([disabled])");
                if (!isVisibleAndEnabled(target)) return;
                try {
                    target.focus({preventScroll: true});
                } catch (error) {
                    target.focus();
                }
                if (selection && _.isFunction(target.setSelectionRange)) {
                    try {
                        target.setSelectionRange(
                            selection.start,
                            selection.end,
                            selection.direction
                        );
                    } catch (error) {}
                }
            }

            function cleanup() {
                lease.root.removeEventListener("focusin", onFocusIn);
                document.removeEventListener("pointerdown", onPointerDown, true);
                document.removeEventListener("keydown", onKeyDown, true);
                if (self._chatFocusLease === lease) self._chatFocusLease = null;
            }

            function cancel() {
                if (lease.cancelled) return;
                lease.cancelled = true;
                if (lease.frame !== null && _.isFunction(window.cancelAnimationFrame)) {
                    window.cancelAnimationFrame(lease.frame);
                }
                lease.frame = null;
                cleanup();
            }

            function onFocusIn(event) {
                if (!event.target || !lease.root.contains(event.target)) return;
                lease.target = event.target;
                captureSelection(event.target);
            }

            function onPointerDown(event) {
                var path = _.isFunction(event.composedPath) ? event.composedPath() : [];
                var inside = path.indexOf(self.runtimeHost) !== -1 ||
                    self.runtimeHost && self.runtimeHost.contains(event.target);
                if (!inside) cancel();
            }

            function onKeyDown(event) {
                if (event.key === "Tab") cancel();
            }

            lease.schedule = function () {
                if (lease.cancelled || lease.frame !== null) return;
                lease.frame = window.requestAnimationFrame(function () {
                    lease.frame = null;
                    restore();
                    if (lease.finished) cleanup();
                });
            };
            lease.cancel = cancel;
            captureSelection(active);
            root.addEventListener("focusin", onFocusIn);
            document.addEventListener("pointerdown", onPointerDown, true);
            document.addEventListener("keydown", onKeyDown, true);
            this._chatFocusLease = lease;

            function finish() {
                if (lease.cancelled || self._chatFocusLease !== lease) return;
                lease.finished = true;
                lease.schedule();
            }

            try {
                result = task();
            } catch (error) {
                cancel();
                throw error;
            }
            return $.when(result).then(function (value) {
                finish();
                return value;
            }, function (error) {
                finish();
                return $.Deferred().reject(error).promise();
            });
        },

        _cancelChatFocusLease: function () {
            if (this._chatFocusLease) this._chatFocusLease.cancel();
        },

        openSurface: function (surface) {
            if (surface !== "dock" && surface !== "standalone") return false;
            try {
                this.call("agui_host", "setSurface", surface);
            } catch (error) {
                this._showError("聊天界面不可用。");
                return false;
            }
            this._applySurface(surface);
            return true;
        },

        _applySurface: function (surface) {
            var slot;
            if (surface !== "dock" && surface !== "standalone") return;
            this.surface = surface;
            this.dockOpen = true;
            slot = this.$(surface === "dock" ? ".o_agui_chat_dock_slot" : ".o_agui_chat_standalone_slot")[0];
            if (slot && this.runtimeHost && this.runtimeHost.parentNode !== slot) slot.appendChild(this.runtimeHost);
            setClass(this.$el, "o_agui_chat_dock_open", surface === "dock");
            setClass(this.$el, "o_agui_chat_standalone_active", surface === "standalone");
            DIRECTIONS.forEach(function (direction) {
                setClass(this.$el, "o_agui_chat_dock_" + direction, surface === "dock" && this.dockDirection === direction);
            }, this);
            this._applyGeometry();
            this._updatePressedStates();
            this._saveLayout();
            if (this.chatHandle) this.chatHandle.update({
                surface: surface,
                hostState: this.hostState,
                menuOptions: this.call("agui_host", "getMenuOptions"),
            });
        },

        _applyGeometry: function () {
            var view;
            var size;
            var rect;
            if (this._isMobile()) {
                view = viewport();
                size = this.dockSizes[this.dockDirection];
                rect = {width: view.width, height: view.height, left: 0, top: 0};
                this._setGeometryStyles(size, rect);
                this._applyWebClientLayout(size);
                return;
            }
            size = this._clampDockSize(this.dockDirection, this.dockSizes[this.dockDirection]);
            rect = this._clampFloatRect(this.floatRect);
            this.dockSizes[this.dockDirection] = size;
            this.floatRect = rect;
            this._setGeometryStyles(size, rect);
            this._applyWebClientLayout(size);
        },

        _setGeometryStyles: function (size, rect) {
            this._setStyle(this.$el && this.$el[0], "--agui-dock-size", size + "px");
            this._setStyle(this.$el && this.$el[0], "--agui-float-width", rect.width + "px");
            this._setStyle(this.$el && this.$el[0], "--agui-float-height", rect.height + "px");
            this._setStyle(this.$el && this.$el[0], "--agui-float-left", rect.left + "px");
            this._setStyle(this.$el && this.$el[0], "--agui-float-top", rect.top + "px");
        },

        _applyWebClientLayout: function (size) {
            this._clearWebClientLayout();
            if (this.surface !== "dock" || !this.dockOpen || this._isMobile()) return;
            setClass(this.webClient && this.webClient.$el, "o_agui_chat_webclient_dock_" + this.dockDirection, true);
            this._setStyle(this.webClient && this.webClient.$el && this.webClient.$el[0], "--agui-chat-dock-size", size + "px");
        },

        _clearWebClientLayout: function () {
            var $root = this.webClient && this.webClient.$el;
            WEBCLIENT_CLASSES.forEach(function (className) { setClass($root, className, false); });
            this._removeStyle($root && $root[0], "--agui-chat-dock-size");
        },

        _setStyle: function (element, name, value) {
            if (element && element.style && _.isFunction(element.style.setProperty)) element.style.setProperty(name, value);
        },

        _removeStyle: function (element, name) {
            if (element && element.style && _.isFunction(element.style.removeProperty)) element.style.removeProperty(name);
        },

        _updatePressedStates: function () {
            var self = this;
            var $directions = this.$(".o_agui_chat_direction");
            if ($directions && _.isFunction($directions.each)) {
                $directions.each(function () {
                    var direction = this.getAttribute("data-direction");
                    this.setAttribute("aria-pressed", String(self.surface === "dock" && self.dockDirection === direction));
                });
            }
            var $float = this.$(".o_agui_chat_float");
            if ($float && _.isFunction($float.attr)) $float.attr("aria-pressed", String(this.surface === "standalone"));
        },

        _showError: function (message) {
            this.$(".o_agui_chat_error_text").text(message || "聊天不可用。");
            setClass(this.$el, "o_agui_chat_has_error", true);
        },

        _onErrorClose: function () { setClass(this.$el, "o_agui_chat_has_error", false); },

        _onSurfaceFocusIn: function (event) {
            // 阻止 Odoo modal 的全局焦点约束将焦点抢回弹窗。
            event.stopPropagation();
        },

        _onToggleDock: function () {
            this.dockOpen = true;
            this.openSurface(this.surface);
        },

        _onClose: function () {
            this._cancelChatFocusLease();
            this.dockOpen = false;
            setClass(this.$el, "o_agui_chat_dock_open", false);
            setClass(this.$el, "o_agui_chat_standalone_active", false);
            this._clearWebClientLayout();
        },

        _onDirection: function (event) {
            var direction = event.currentTarget.getAttribute("data-direction");
            if (DIRECTIONS.indexOf(direction) === -1) return;
            this.dockDirection = direction;
            this.openSurface("dock");
        },

        _onFloat: function () { this.openSurface("standalone"); },

        _onTitlebarPointerDown: function (event) {
            if (this.surface !== "standalone" || this._isMobile() || event.button > 0) return;
            if (event.target && event.target.closest && event.target.closest("button")) return;
            this._beginInteraction(event, "move", null);
        },

        _onResizePointerDown: function (event) {
            if (this._isMobile() || event.button > 0) return;
            this._beginInteraction(event, this.surface === "dock" ? "dock" : "resize", event.currentTarget.getAttribute("data-edge"));
        },

        _beginInteraction: function (event, kind, edge) {
            this.interaction = {
                kind: kind,
                edge: edge,
                x: event.clientX,
                y: event.clientY,
                dockSize: this.dockSizes[this.dockDirection],
                rect: Object.assign({}, this.floatRect),
            };
            if (_.isFunction(window.addEventListener)) {
                window.addEventListener("pointermove", this._boundPointerMove);
                window.addEventListener("pointerup", this._boundPointerUp);
            }
            if (event.preventDefault) event.preventDefault();
        },

        _onWindowPointerMove: function (event) {
            var state = this.interaction;
            var dx;
            var dy;
            var rect;
            if (!state) return;
            dx = event.clientX - state.x;
            dy = event.clientY - state.y;
            if (state.kind === "dock") {
                if (this.dockDirection === "left") this.dockSizes.left = state.dockSize + dx;
                if (this.dockDirection === "right") this.dockSizes.right = state.dockSize - dx;
                if (this.dockDirection === "top") this.dockSizes.top = state.dockSize + dy;
                if (this.dockDirection === "bottom") this.dockSizes.bottom = state.dockSize - dy;
                this.dockSizes[this.dockDirection] = this._clampDockSize(this.dockDirection, this.dockSizes[this.dockDirection]);
            } else if (state.kind === "move") {
                this.floatRect.left = state.rect.left + dx;
                this.floatRect.top = state.rect.top + dy;
            } else {
                rect = Object.assign({}, state.rect);
                var view = viewport();
                var right = state.rect.left + state.rect.width;
                var bottom = state.rect.top + state.rect.height;
                if (state.edge.indexOf("left") !== -1) {
                    rect.left = clamp(state.rect.left + dx, FLOAT_MARGIN, right - 420);
                    rect.width = right - rect.left;
                }
                if (state.edge.indexOf("right") !== -1) {
                    rect.width = clamp(state.rect.width + dx, 420, view.width - FLOAT_MARGIN - state.rect.left);
                }
                if (state.edge.indexOf("top") !== -1) {
                    rect.top = clamp(state.rect.top + dy, FLOAT_MARGIN, bottom - 320);
                    rect.height = bottom - rect.top;
                }
                if (state.edge.indexOf("bottom") !== -1) {
                    rect.height = clamp(state.rect.height + dy, 320, view.height - FLOAT_MARGIN - state.rect.top);
                }
                this.floatRect = rect;
            }
            this._applyGeometry();
        },

        _onWindowPointerUp: function () {
            if (!this.interaction) return;
            this._saveLayout();
            this._stopInteraction();
        },

        _stopInteraction: function () {
            this.interaction = null;
            if (_.isFunction(window.removeEventListener)) {
                window.removeEventListener("pointermove", this._boundPointerMove);
                window.removeEventListener("pointerup", this._boundPointerUp);
            }
        },

        _onResizeKeyDown: function (event) {
            var amount = 16;
            var edge = event.currentTarget.getAttribute("data-edge");
            var delta = event.shiftKey ? -amount : amount;
            if (this._isMobile() || ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].indexOf(event.key) === -1) return;
            if (this.surface === "dock") {
                if ((this.dockDirection === "left" && event.key === "ArrowRight") ||
                    (this.dockDirection === "right" && event.key === "ArrowLeft") ||
                    (this.dockDirection === "top" && event.key === "ArrowDown") ||
                    (this.dockDirection === "bottom" && event.key === "ArrowUp")) delta = amount;
                else delta = -amount;
                this.dockSizes[this.dockDirection] = this._clampDockSize(this.dockDirection, this.dockSizes[this.dockDirection] + delta);
            } else {
                if (edge.indexOf("left") !== -1 && event.key === "ArrowLeft") this.floatRect.width += amount;
                if (edge.indexOf("left") !== -1 && event.key === "ArrowRight") this.floatRect.width -= amount;
                if (edge.indexOf("right") !== -1 && event.key === "ArrowRight") this.floatRect.width += amount;
                if (edge.indexOf("right") !== -1 && event.key === "ArrowLeft") this.floatRect.width -= amount;
                if (edge.indexOf("top") !== -1 && event.key === "ArrowUp") this.floatRect.height += amount;
                if (edge.indexOf("top") !== -1 && event.key === "ArrowDown") this.floatRect.height -= amount;
                if (edge.indexOf("bottom") !== -1 && event.key === "ArrowDown") this.floatRect.height += amount;
                if (edge.indexOf("bottom") !== -1 && event.key === "ArrowUp") this.floatRect.height -= amount;
            }
            this._applyGeometry();
            this._saveLayout();
            if (event.preventDefault) event.preventDefault();
        },

        _onViewportResize: function () {
            this._stopInteraction();
            this._applyGeometry();
            this._saveLayout();
        },

        _isMobile: function () { return viewport().width < MOBILE_BREAKPOINT; },

        _clampDockSize: function (direction, value) {
            var view = viewport();
            var horizontal = direction === "left" || direction === "right";
            var minimum = horizontal ? 420 : 320;
            var maximum = horizontal ? view.width - 320 : view.height - 240;
            return clamp(Number(value) || (horizontal ? 720 : 420), minimum, Math.max(minimum, maximum));
        },

        _clampFloatRect: function (candidate) {
            var view = viewport();
            var maxWidth = Math.max(420, view.width - FLOAT_MARGIN * 2);
            var maxHeight = Math.max(320, view.height - FLOAT_MARGIN * 2);
            var width = clamp(Number(candidate.width) || 720, 420, maxWidth);
            var height = clamp(Number(candidate.height) || 720, 320, maxHeight);
            var defaultLeft = Math.round((view.width - width) / 2);
            var defaultTop = Math.round((view.height - height) / 2);
            var left = typeof candidate.left === "number" ? candidate.left : defaultLeft;
            var top = typeof candidate.top === "number" ? candidate.top : defaultTop;
            return {
                width: width,
                height: height,
                left: clamp(left, FLOAT_MARGIN, Math.max(FLOAT_MARGIN, view.width - width - FLOAT_MARGIN)),
                top: clamp(top, FLOAT_MARGIN, Math.max(FLOAT_MARGIN, view.height - height - FLOAT_MARGIN)),
            };
        },

        _restoreLayout: function () {
            var stored = this._readStorage();
            if (!stored || typeof stored !== "object") return;
            if (stored.surface === "dock" || stored.surface === "standalone") this.surface = stored.surface;
            if (DIRECTIONS.indexOf(stored.direction) !== -1) this.dockDirection = stored.direction;
            DIRECTIONS.forEach(function (direction) {
                var horizontal = direction === "left" || direction === "right";
                if (stored.dockSizes && numberInRange(stored.dockSizes[direction], horizontal ? 420 : 320, 10000)) {
                    this.dockSizes[direction] = stored.dockSizes[direction];
                }
            }, this);
            if (stored.floatRect && numberInRange(stored.floatRect.width, 420, 10000) &&
                    numberInRange(stored.floatRect.height, 320, 10000) &&
                    typeof stored.floatRect.left === "number" && typeof stored.floatRect.top === "number") {
                this.floatRect = Object.assign({}, stored.floatRect);
            }
        },

        _readStorage: function () {
            if (!this.storageKey) return null;
            try {
                var value = window.localStorage && window.localStorage.getItem(this.storageKey);
                return value ? JSON.parse(value) : null;
            } catch (error) {
                return null;
            }
        },

        _saveLayout: function () {
            if (!this.storageKey) return;
            try {
                window.localStorage.setItem(this.storageKey, JSON.stringify({
                    surface: this.surface,
                    direction: this.dockDirection,
                    dockSizes: this.dockSizes,
                    floatRect: this.floatRect,
                }));
            } catch (error) {}
        },
    });

    WebClient.include({
        start: function () {
            var self = this;
            try {
                var result = this._super.apply(this, arguments);
            } catch(result_error) {
                var result = $.when();
            }
            $.when(result).then(function () {
                try {
                    self.aguiChatSurfaceManager = new ChatSurfaceManager(self);
                    $.when(self.aguiChatSurfaceManager.appendTo(self.$el)).then(null, function (error) {
                        if (window.console && console.error) console.error("AG-UI surface initialization failed", error);
                    });
                } catch (error) {
                    if (window.console && console.error) console.error("AG-UI surface initialization failed", error);
                }
            });
            return result;
        },

        destroy: function () {
            if (this.aguiChatSurfaceManager) {
                this.aguiChatSurfaceManager.destroy();
                this.aguiChatSurfaceManager = null;
            }
            return this._super.apply(this, arguments);
        },
    });

    return ChatSurfaceManager;
});
