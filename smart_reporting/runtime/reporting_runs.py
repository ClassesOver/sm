"""让报表聊天执行独立于 SSE 连接，使用 Agno 原生后台与重连协议。"""

from functools import wraps

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts


def enable_reporting_background_streams(app: FastAPI, agent_id: str) -> None:
    paths = {"/agents/{agent_id}/runs", "/agents/{agent_id}/runs/{run_id}/continue"}
    for route in iter_route_contexts(app.routes):
        if not isinstance(route.original_route, APIRoute) or route.path not in paths or "POST" not in route.methods:
            continue
        endpoint = route.dependant.call

        def wrap_endpoint(call):
            @wraps(call)
            async def run(**kwargs):
                if kwargs.get("agent_id") == agent_id and kwargs.get("stream", True):
                    # 即使旧客户端显式提交 background=false，也不能把报表绑定到连接。
                    kwargs["background"] = True
                return await call(**kwargs)

            return run

        # 保留原生依赖、认证、表单校验和 OpenAPI，仅在执行入口固定报表策略。
        route.dependant.call = wrap_endpoint(endpoint)
