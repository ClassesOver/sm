"""将正文图片引用绑定到调用方已经授权的冻结文件身份，不读取文件。"""
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from ..contract import safe_relative_posix_path
from .report_runtime.validation import IMAGE_SUFFIXES, MAX_IMAGE_BYTES


def resource_issue():
    return {'code': 'report_template_body_resource_unavailable',
        'message': '模板正文图片缺少本修订已登记且身份一致的安全资源，未读取任意路径；正文保留供复核。'}


def bind_template_images(markdown, markdown_path, identities):
    """以当前成稿相对路径精确匹配，不按文件名或正文自报身份猜测。"""
    registered, conflicts = {}, set()
    for item in identities:
        identity = {key: item[key] for key in ('path', 'size', 'sha256')}
        previous = registered.get(identity['path'])
        if previous is not None and previous != identity:
            conflicts.add(identity['path'])
        registered[identity['path']] = identity
    bindings, issues = {}, []
    for token in MarkdownIt('commonmark', {'html': False}).parse(markdown):
        for child in token.children or ():
            if child.type != 'image':
                continue
            source = child.attrGet('src') or ''
            parsed = urlsplit(source)
            decoded = unquote(parsed.path)
            try:
                if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                    raise ValueError('unsafe resource reference')
                safe_relative_posix_path(decoded, 'unsafe resource path')
                path = (PurePosixPath(markdown_path).parent / decoded).as_posix()
                if path in conflicts or path not in registered:
                    raise ValueError('resource not registered')
                if (PurePosixPath(path).suffix.lower() not in IMAGE_SUFFIXES
                        or not 0 < registered[path]['size'] <= MAX_IMAGE_BYTES):
                    raise ValueError('resource is not a bounded image')
            except ValueError:
                issues.append(resource_issue())
            else:
                bindings[source] = registered[path]
    return bindings, issues
