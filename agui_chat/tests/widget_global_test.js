"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

function read(relativePath) {
    return fs.readFileSync(path.join(__dirname, "..", relativePath), "utf8");
}

function main() {
    const manifest = read("__manifest__.py");
    const assets = read("views/assets.xml");
    const adapter = read("static/src/js/agui_model_adapter.js");
    const commands = read("static/src/js/agui_command_registry.js");
    const service = read("static/src/js/agui_host_service.js");
    const bridge = read("static/src/js/agui_chat_bridge.js");
    const surfaces = read("static/src/js/agui_chat_surfaces.js");
    const surfaceStyles = read("static/src/scss/agui_chat.scss");
    const controller = read("controllers/main.py");
    const session = read("models/agui_chat_session.py");
    const runtime = read("react_widget/src/runtime/ChatRuntime.ts");
    const transport = read("react_widget/src/runtime/transport.ts");
    const types = read("react_widget/src/types.ts");
    const bundlePath = path.join(__dirname, "../static/lib/agui-chat-react/agui_chat_widget.12.0.8.8.11.js");
    const cssPath = path.join(__dirname, "../static/lib/agui-chat-react/agui_chat_widget.12.0.8.8.11.css");

    assert(manifest.includes('"version": "12.0.8.8.11"'));
    assert(assets.includes("agui_model_adapter.js"));
    assert(assets.includes("agui_command_registry.js"));
    assert(assets.includes("agui_host_service.js"));
    assert(!assets.includes("view_state_bridge.js"));
    assert(!assets.includes("odoo_tools.js"));
    assert(!assets.includes("agui_chat_action.js"));
    assert(!assets.includes("agui_chat_widget.12.0.8.8.11.css"));

    assert(adapter.includes("captureModelCheckpoint"));
    assert(adapter.includes("restoreModelCheckpoint"));
    assert(adapter.includes("controller._rpc"));
    assert(!adapter.includes("controller.model._rpc"));
    assert(adapter.includes("record.getDomain({fieldName: name})"));
    assert(adapter.includes("relation_domain_mismatch"));
    assert(!adapter.includes("notifyChanges"));
    assert(adapter.includes("controller._applyChanges"));
    assert(adapter.includes("renderer.canBeSaved"));
    assert(adapter.includes("one2many"));
    assert(service.includes('core.serviceRegistry.add("agui_host"'));
    assert(service.includes("getCurrentController"));
    assert(service.includes("current_action_updated"));
    assert(service.includes("command_busy"));
    assert(commands.includes("odoo.search_relation"));
    assert(commands.includes("odoo.apply_group"));
    assert(commands.includes("Adapter.searchRelation"));
    assert.strictEqual((adapter.match(/\{shadow: true\}/g) || []).length, 2);

    assert(!bridge.includes("ChatWorkspace"));
    assert(!bridge.includes("StateBridge"));
    assert(!bridge.includes("Preview"));
    assert(bridge.includes("agent_protocol_mismatch"));
    assert(bridge.includes("deferred.resolve(agent)"));
    assert(!bridge.includes("$.when(request(0))"));
    assert(bridge.includes('values || {}, {shadow: true}'));
    assert(bridge.includes('"/agui_chat/host_command"'));
    assert(bridge.includes('"/agui_chat/business/prepare"'));
    assert(bridge.includes('"odoo.stage_current_form": true'));
    assert.strictEqual((surfaces.match(/this\.chatHandle = window\.AguiChat\.mount/g) || []).length, 1);
    assert(surfaces.includes("attachShadow"));
    assert(surfaces.includes("agui_chat_widget.12.0.8.8.11.css"));
    assert(surfaces.includes("this.webClient.action_manager.getCurrentAction()"));
    assert(!surfaces.includes("Dialog"));
    assert(!surfaces.includes("popup"));
    assert(!surfaces.includes("do_action(\"agui_chat.action\")"));
    assert(surfaces.includes('var DIRECTIONS = ["left", "right", "top", "bottom"]'));
    assert(surfaces.includes('STORAGE_PREFIX = "agui_chat.layout.v1."'));
    assert(surfaces.includes('MOBILE_BREAKPOINT = 768'));
    assert(surfaceStyles.includes(".o_agui_chat_standalone_active .o_agui_chat_surface_actions"));
    assert(surfaceStyles.includes("display: flex;"));
    assert(surfaceStyles.includes("box-sizing: border-box;"));
    assert(surfaceStyles.includes("background: #ffffff;"));
    const toggleStyles = surfaceStyles.slice(
        surfaceStyles.indexOf("    .o_agui_chat_dock_toggle {"),
        surfaceStyles.indexOf("    .o_agui_chat_dock,")
    );
    assert(!surfaceStyles.includes("    --main-color: #7C7BAD;"));
    assert(!surfaceStyles.includes("    --main-hover-color: #5f5e97;"));
    assert(toggleStyles.includes("background: var(--main-color, #7C7BAD);"));
    assert(toggleStyles.includes("background: var(--main-hover-color, #5f5e97);"));
    assert(toggleStyles.includes("border: 1px solid var(--font-main-color, #7C7BAD);"));
    assert(toggleStyles.includes("border-color: var(--font-main-hover-color, #5f5e97);"));
    assert(!toggleStyles.includes("background-image: none;"));
    assert(toggleStyles.includes(".o_agui_chat_toggle_icon"));
    assert(toggleStyles.includes('content: "\\f27b";'));
    assert(!toggleStyles.includes(".o_agui_chat_dock_toggle::after"));
    const toggleVariables = Array.from(new Set(toggleStyles.match(/--[\w-]+/g) || [])).sort();
    assert.deepStrictEqual(toggleVariables, [
        "--font-main-color", "--font-main-hover-color", "--main-color", "--main-hover-color",
    ]);
    assert(!surfaceStyles.includes(".o_agui_chat_standalone_overlay {\n        border:"));

    assert(controller.includes('"/agui_chat/host_command"'));
    assert(controller.includes('"/agui_chat/business/execute"'));
    assert(controller.includes('"/agui_chat/business/prepare"'));

    assert(session.includes("agent_state_json"));
    assert(session.includes("session_revision"));
    assert(session.includes('(\"standalone\", \"浮动窗口\")'));
    assert(controller.includes('"database": request.session.db'));

    assert(!types.includes("PreviewState"));
    assert(!types.includes("onStateChange"));
    assert(types.includes("hostState: OdooHostSnapshot"));
    assert(types.includes("agentState: Record<string, unknown>"));
    assert(runtime.includes("activeClientTools"));
    assert(runtime.includes("reportHostStateMutation"));
    assert(transport.includes("host: agentHostProjection(props)"));
    assert(!transport.includes("host: clone(props.hostState)"));
    assert(transport.includes("agent: clone(agentState"));

    assert(fs.existsSync(bundlePath));
    assert(fs.existsSync(cssPath));
    assert(fs.readFileSync(bundlePath, "utf8").includes("AguiChat"));
    const widgetCss = fs.readFileSync(cssPath, "utf8");
    assert(!widgetCss.includes("*,:before,:after{"));
    assert(!/(^|[{}])\.container\{/.test(widgetCss));
    assert(!/-?\d*\.?\d+rem\b/.test(widgetCss));

    console.log("widget_global_test: ok");
}

main();
