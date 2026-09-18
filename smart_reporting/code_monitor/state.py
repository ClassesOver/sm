"""把 iopub 事件投影为有界、可供浏览器读取的执行状态。"""

from collections import OrderedDict
from time import time
from typing import Any

MAX_CELLS = 30
MAX_TEXT = 65536


class KernelState:
    def __init__(self, kernel_id: str, label: str):
        self.kernel_id = kernel_id
        self.label = label
        self.status = "unknown"
        self.notice = "已订阅，等待执行消息；不会主动查询 kernel。"
        self.cells: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.last_event_at: float | None = None

    def accept(self, message: dict[str, Any]) -> None:
        kind = message.get("header", {}).get("msg_type")
        if kind not in {"execute_input", "execute_result", "display_data", "stream",
                        "error", "status", "clear_output"}:
            return
        content = message.get("content", {})
        parent = message.get("parent_header", {}).get("msg_id")
        self.last_event_at = time()
        if kind == "status":
            state = content.get("execution_state")
            if state in {"busy", "idle", "starting"}:
                self.status = state
            if state == "idle" and parent in self.cells:
                cell = self.cells[parent]
                cell["finished_at"] = time()
                if cell["status"] == "running":
                    cell["status"] = "completed"
            return
        if not parent:
            return
        if parent not in self.cells:
            # 允许中途接入：没有 execute_input 也保留正在产生的输出。
            self.cells[parent] = {
                "id": parent, "code": None, "output": "", "status": "running",
                "started_at": time(), "finished_at": None, "truncated": False,
                "clear_pending": False,
            }
            while len(self.cells) > MAX_CELLS:
                self.cells.popitem(last=False)
        cell = self.cells[parent]
        if kind == "execute_input":
            code = str(content.get("code", ""))
            cell["code"] = code[:MAX_TEXT]
            cell["truncated"] |= len(code) > MAX_TEXT
            self.status = "busy"
        elif kind == "clear_output":
            if content.get("wait"):
                cell["clear_pending"] = True
            else:
                cell["output"] = ""
                cell["clear_pending"] = False
        else:
            if kind == "stream":
                text = str(content.get("text", ""))
            elif kind == "error":
                text = "\n".join(str(line) for line in content.get("traceback", []))
                cell["status"] = "error"
            else:
                data = content.get("data", {})
                text = str(data.get("text/plain", "[富媒体输出：此页面仅展示文本]")) + "\n"
            if cell["clear_pending"]:
                cell["output"] = ""
                cell["clear_pending"] = False
            room = MAX_TEXT - len(cell["output"])
            cell["output"] += text[:room]
            cell["truncated"] |= len(text) > room

    def disconnected(self, notice: str) -> None:
        self.status = "disconnected"
        self.notice = notice
        for cell in self.cells.values():
            if cell["finished_at"] is None:
                cell["status"] = "unknown"
                cell["finished_at"] = time()

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.kernel_id, "label": self.label, "status": self.status,
            "notice": self.notice, "last_event_at": self.last_event_at,
            "cells": [{k: v for k, v in cell.items() if k != "clear_pending"}
                      for cell in self.cells.values()],
        }
