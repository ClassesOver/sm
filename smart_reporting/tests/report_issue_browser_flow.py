"""为同次隔离服务提供浏览器连接；不替换任何业务响应。"""

import asyncio
import json
import socket
from pathlib import Path

import uvicorn


async def run_management_browser(app, config, output, *, script='smoke/management-issue-postgres-smoke.mjs'):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', lifespan='off'))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    process = None
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.05)
        assert server.started
        config = {**config, 'apiOrigin': f'http://127.0.0.1:{listener.getsockname()[1]}', 'output': str(output)}
        process = await asyncio.create_subprocess_exec('node', script,
            cwd=Path(__file__).resolve().parents[1] / 'report_editor/frontend',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(config).encode()), timeout=150)
        assert process.returncode == 0, (stdout + stderr).decode()[-6000:]
        return json.loads((output / 'browser-evidence.json').read_text())
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=10)
        listener.close()
