import pytest
from agno.run import RunContext

import smart_reporting.workspace as workspace
from smart_reporting.workspace import (
    MAX_PATH_BYTES,
    MAX_PATH_COMPONENT_BYTES,
    MAX_PATH_DEPTH,
    MAX_UPLOAD_BYTES,
    WorkspaceError,
    _thread,
    normalize_workspace_path,
    validate_patch_hash,
    validate_workspace_content,
)


def test_workspace模块不再导出沙箱实现():
    for name in ("WorkspaceService", "WorkspaceTools", "DaytonaProvider", "SandboxRegistry"):
        assert not hasattr(workspace, name)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("reports/结果.json", "reports/结果.json"),
        ("./a//b/./c.txt", "a/b/c.txt"),
        ("a\\b\\c.txt", "a/b/c.txt"),
        ("", ""),
        (None, ""),
        (".", ""),
    ],
)
def test_路径规范为工作区内相对路径(raw, expected):
    assert normalize_workspace_path(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("/etc/passwd", "绝对路径"),
        ("C:/data.txt", "绝对路径"),
        ("a/../../b", "目录穿越"),
        ("a\x00b", "控制字符"),
        ("a\nb", "控制字符"),
        ("a" * (MAX_PATH_BYTES + 1), "字节"),
        ("/".join(["d"] * (MAX_PATH_DEPTH + 1)), "层级"),
        ("中" * (MAX_PATH_COMPONENT_BYTES // 3 + 1), "名称"),
    ],
)
def test_中文路径长度层级控制字符和目录穿越受到限制(raw, message):
    with pytest.raises(WorkspaceError, match=message):
        normalize_workspace_path(raw)


def test_非根操作拒绝空路径():
    with pytest.raises(WorkspaceError, match="没有提供工作区路径"):
        normalize_workspace_path("./", allow_root=False)


def test_文件内容必须是字节且不超过上传上限(monkeypatch):
    validate_workspace_content(b"ok")
    with pytest.raises(WorkspaceError, match="二进制"):
        validate_workspace_content("text")  # type: ignore[arg-type]
    monkeypatch.setattr(workspace, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(WorkspaceError, match="200 MiB"):
        validate_workspace_content(b"12345")
    assert MAX_UPLOAD_BYTES == 200 * 1024 * 1024


def test_补丁哈希统一小写且拒绝非法值():
    assert validate_patch_hash("A" * 64) == "a" * 64
    for value in ("a" * 63, "g" * 64, None, 1):
        with pytest.raises(WorkspaceError, match="哈希格式无效"):
            validate_patch_hash(value)


def test_工具调用必须绑定对话():
    assert _thread(RunContext(run_id="run", session_id="thread")) == "thread"
    with pytest.raises(WorkspaceError, match="没有绑定对话"):
        _thread(None)
