# -*- coding: utf-8 -*-
import base64
import hashlib
import itertools
import json
import logging
import re
import uuid
from datetime import timedelta

from psycopg2 import sql

from odoo import SUPERUSER_ID, api, fields, models

from odoo.addons.agui_chat.models.agui_chat_tool import (
    canonical_json,
    register_business_command,
)


COMMAND_NAME = "odoo.business.x2many_import.execute"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 2000
MAX_COLUMNS = 50
MAX_HEADER_CHARS = 80
MAX_CELL_CHARS = 240
PREVIEW_ROWS = 20
MAX_PREVIEW_BYTES = 96 * 1024
MAX_PREVIEW_ERRORS = 10
MAX_ERROR_MESSAGES = 3
SUPPORTED_ENCODINGS = {
    "ascii", "utf-8", "utf-8-sig", "gb18030", "gbk", "big5",
    "iso-8859-1", "windows-1252",
}
SUPPORTED_SEPARATORS = {",", ";", "\t", " ", "|", "\x1f"}
SUPPORTED_MIMETYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
IMPORT_PROFILES = {}
_logger = logging.getLogger(__name__)


class X2ManyImportError(Exception):
    def __init__(self, code, message=None):
        super(X2ManyImportError, self).__init__(message or code)
        self.code = code


def _profile_hash(parent_model, field_name, columns, version):
    material = {
        "parent_model": parent_model,
        "field_name": field_name,
        "version": version,
        "columns": [
            {
                "header": header,
                "field": spec["field"],
                "required": bool(spec.get("required")),
                "type": spec.get("type") or False,
            }
            for header, spec in sorted(columns.items())
        ],
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def register_x2many_import_profile(parent_model, field_name, columns,
                                    version="1", parent_check=None,
                                    row_prepare=None):
    key = (str(parent_model or ""), str(field_name or ""))
    if not key[0] or not key[1] or not isinstance(columns, dict) or not columns:
        raise ValueError("One2many 导入 profile 必须精确指定模型、字段和列。")
    if parent_check is not None and not callable(parent_check):
        raise ValueError("parent_check 必须是可调用对象。")
    if row_prepare is not None and not callable(row_prepare):
        raise ValueError("row_prepare 必须是可调用对象。")
    normalized = {}
    target_fields = set()
    for header, value in columns.items():
        header = str(header or "").strip()
        value = {"field": value} if isinstance(value, str) else dict(value or {})
        target_field = str(value.get("field") or "").strip()
        if not header or not target_field:
            raise ValueError("导入 profile 的列名和字段名不能为空。")
        if len(header) > MAX_HEADER_CHARS:
            raise ValueError("导入 profile 的列名过长。")
        if target_field in target_fields:
            raise ValueError("导入 profile 的目标字段不能重复。")
        converter = value.get("converter")
        if converter is not None and not callable(converter):
            raise ValueError("导入列 converter 必须是可调用对象。")
        target_fields.add(target_field)
        normalized[header] = {
            "field": target_field,
            "label": str(value.get("label") or header)[:MAX_HEADER_CHARS],
            "required": bool(value.get("required")),
            "type": value.get("type") or False,
            "converter": converter,
        }
    if key in IMPORT_PROFILES:
        raise ValueError("One2many 导入 profile 已注册：%s.%s" % key)
    version = str(version or "1")
    IMPORT_PROFILES[key] = {
        "parent_model": key[0],
        "field_name": key[1],
        "columns": normalized,
        "version": version,
        "hash": _profile_hash(key[0], key[1], normalized, version),
        "parent_check": parent_check,
        "row_prepare": row_prepare,
    }


def _json(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _short_cell(value):
    value = str(value or "")
    return value if len(value) <= MAX_CELL_CHARS else value[:MAX_CELL_CHARS] + "..."


def _safe_error(value):
    return _short_cell(value or "导入数据无效。")


class AguiChatX2ManyImportJob(models.Model):
    _name = "agui.chat.x2many.import.job"
    _description = "AG-UI One2many 批量导入任务"
    _order = "create_date desc"

    token = fields.Char(
        string="任务令牌", required=True, index=True,
        default=lambda self: str(uuid.uuid4()),
    )
    state = fields.Selection([
        ("preview", "预览中"),
        ("ready", "待确认"),
        ("running", "执行中"),
        ("done", "已完成"),
        ("failed", "失败"),
    ], string="状态", required=True, default="preview", index=True)
    user_id = fields.Many2one("res.users", string="提交用户", required=True, index=True)
    company_id = fields.Many2one("res.company", string="提交公司", required=True, index=True)
    parent_model = fields.Char(string="父模型", required=True, index=True)
    parent_res_id = fields.Integer(string="父记录 ID", required=True, index=True)
    field_name = fields.Char(string="One2many 字段", required=True)
    parent_write_date = fields.Char(string="父记录版本", required=True)
    schema_hash = fields.Char(string="页面 Schema 摘要", required=True)
    profile_hash = fields.Char(string="Profile 摘要", required=True)
    profile_version = fields.Char(string="Profile 版本", required=True)
    source_attachment_id = fields.Many2one(
        "ir.attachment", string="任务文件副本", ondelete="cascade"
    )
    error_attachment_id = fields.Many2one(
        "ir.attachment", string="错误报告", ondelete="set null"
    )
    source_name = fields.Char(string="文件名", required=True)
    source_mimetype = fields.Char(string="文件类型", required=True)
    file_size = fields.Integer(string="文件大小", required=True)
    file_sha256 = fields.Char(string="文件 SHA-256", required=True)
    row_count = fields.Integer(string="数据行数", default=0)
    headers_json = fields.Text(string="表头", default="[]")
    mapping_json = fields.Text(string="字段映射", default="{}")
    parse_options_json = fields.Text(string="解析选项", default="{}")
    preview_rows_json = fields.Text(string="预览行", default="[]")
    rows_json = fields.Text(string="已校验数据", default="[]")
    errors_json = fields.Text(string="校验错误", default="[]")
    mapping_hash = fields.Char(string="映射摘要", index=True)
    revision = fields.Integer(string="修订版本", required=True, default=0)
    result_json = fields.Text(string="执行结果", default="{}")
    started_at = fields.Datetime(string="开始时间")
    finished_at = fields.Datetime(string="完成时间")

    _sql_constraints = [
        ("token_unique", "unique(token)", "导入任务令牌必须唯一。"),
    ]

    @api.model
    def _profile(self, parent_model, field_name):
        profile = IMPORT_PROFILES.get((parent_model, field_name))
        if not profile:
            raise X2ManyImportError(
                "dynamic_schema_requires_profile",
                "当前 One2many 字段没有专用批量导入 profile，请使用明细表单交互。",
            )
        return profile

    @api.model
    def _owned_job(self, token):
        token = str(token or "").strip()
        if not token or len(token) > 160:
            raise X2ManyImportError("invalid_job_token", "导入任务令牌无效。")
        job = self.sudo().search([
            ("token", "=", token),
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
        ], limit=1)
        if not job:
            raise X2ManyImportError("job_unavailable", "导入任务不存在或无权访问。")
        return job

    @api.model
    def _prepare_job(self, parent_model, parent_id, field_name, attachment_id,
                     schema_hash):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        if not config.chat_enabled or not config.host_tools_enabled:
            raise X2ManyImportError("host_tools_disabled")
        if not config.write_tools_enabled:
            raise X2ManyImportError("write_tools_disabled")
        parent_model = str(parent_model or "").strip()
        field_name = str(field_name or "").strip()
        profile = self._profile(parent_model, field_name)
        try:
            parent_id = int(parent_id)
            attachment_id = int(attachment_id)
        except (TypeError, ValueError):
            raise X2ManyImportError("invalid_import_target", "导入目标或附件 ID 无效。")
        if parent_id <= 0:
            raise X2ManyImportError("parent_must_be_saved", "父单必须先保存。")
        if not isinstance(schema_hash, str) or not re.match(r"^[a-f0-9]{64}$", schema_hash):
            raise X2ManyImportError("invalid_schema_hash", "页面 Schema 摘要无效。")
        if parent_model not in self.env:
            raise X2ManyImportError("invalid_import_target", "父模型不存在。")
        parent = self.env[parent_model].browse(parent_id).exists()
        if not parent:
            raise X2ManyImportError("record_unavailable", "父记录不存在。")
        parent.check_access_rights("write")
        parent.check_access_rule("write")
        parent_field = parent._fields.get(field_name)
        if not parent_field or parent_field.type != "one2many":
            raise X2ManyImportError("invalid_import_target", "目标字段不是 One2many。")
        if profile["parent_check"]:
            code = profile["parent_check"](parent)
            if code:
                raise X2ManyImportError(str(code))
        attachment = self.env["ir.attachment"].sudo().browse(attachment_id).exists()
        session = attachment and attachment.res_model == "agui.chat.session" and \
            self.env["agui.chat.session"].sudo().browse(attachment.res_id).exists()
        if not attachment or not session or session.user_id.id != self.env.user.id:
            raise X2ManyImportError("attachment_unavailable", "导入附件不存在或无权访问。")
        mimetype = attachment.mimetype or "application/octet-stream"
        extension = (attachment.name or "").lower().rsplit(".", 1)[-1]
        if mimetype not in SUPPORTED_MIMETYPES and extension not in ("csv", "xlsx"):
            raise X2ManyImportError("unsupported_import_format", "仅支持 CSV 或 XLSX 文件。")
        try:
            raw = base64.b64decode(attachment.datas or b"")
        except (TypeError, ValueError):
            raw = b""
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise X2ManyImportError("import_file_size_invalid", "导入文件必须小于等于 10 MB。")
        with self.env.cr.savepoint():
            job = self.sudo().create({
                "user_id": self.env.user.id,
                "company_id": self.env.user.company_id.id,
                "parent_model": parent_model,
                "parent_res_id": parent.id,
                "field_name": field_name,
                "parent_write_date": fields.Datetime.to_string(parent.write_date),
                "schema_hash": schema_hash,
                "profile_hash": profile["hash"],
                "profile_version": profile["version"],
                "source_name": (attachment.name or "import")[:255],
                "source_mimetype": mimetype,
                "file_size": len(raw),
                "file_sha256": hashlib.sha256(raw).hexdigest(),
            })
            source_copy = attachment.copy({
                "res_model": self._name,
                "res_id": job.id,
                "name": attachment.name or "import",
            })
            job.write({"source_attachment_id": source_copy.id})
            return job._preview_job(0, {}, {}, False)

    def _user_environment(self):
        self.ensure_one()
        return api.Environment(self.env.cr, self.user_id.id, dict(
            self.env.context,
            force_company=self.company_id.id,
            allowed_company_ids=[self.company_id.id],
        ))

    @api.model
    def _normalize_parse_options(self, value):
        if value in (None, False):
            value = {}
        if not isinstance(value, dict) or len(value) > 8:
            raise X2ManyImportError("invalid_parse_options", "导入格式选项无效。")
        unknown = set(value) - {"encoding", "separator", "quoting"}
        if unknown:
            raise X2ManyImportError("invalid_parse_options", "包含不支持的导入格式选项。")
        encoding = value.get("encoding") or False
        separator = value.get("separator") or False
        quoting = value.get("quoting") or '"'
        if encoding:
            if not isinstance(encoding, str) or encoding.lower() not in SUPPORTED_ENCODINGS:
                raise X2ManyImportError("invalid_parse_options", "导入文件编码不受支持。")
            encoding = encoding.lower()
        if separator:
            if not isinstance(separator, str) or separator not in SUPPORTED_SEPARATORS:
                raise X2ManyImportError("invalid_parse_options", "导入分隔符不受支持。")
        if not isinstance(quoting, str) or quoting not in ('"', "'"):
            raise X2ManyImportError("invalid_parse_options", "文本限定符不受支持。")
        return {
            "headers": True,
            "advanced": False,
            "keep_matches": False,
            "name_create_enabled_fields": {},
            "encoding": encoding,
            "separator": separator,
            "quoting": quoting,
        }

    @api.model
    def _public_parse_options(self, options):
        encoding = options.get("encoding") or False
        encoding = encoding.lower() if isinstance(encoding, str) else False
        return {
            "encoding": encoding if encoding in SUPPORTED_ENCODINGS else False,
            "separator": options.get("separator") or False,
            "quoting": options.get("quoting") or '"',
        }

    def _parse_source(self, parse_options):
        self.ensure_one()
        if not self.source_attachment_id:
            raise X2ManyImportError("import_source_unavailable", "导入源文件已不可用。")
        raw = base64.b64decode(self.source_attachment_id.datas or b"")
        user_env = self._user_environment()
        parent_field = user_env[self.parent_model]._fields.get(self.field_name)
        if not parent_field or parent_field.type != "one2many":
            raise X2ManyImportError("invalid_import_target")
        wizard = user_env["base_import.import"].create({
            "res_model": parent_field.comodel_name,
            "file": raw,
            "file_name": self.source_name,
            "file_type": self.source_mimetype,
        })
        options = self._normalize_parse_options(parse_options)
        try:
            result = wizard.parse_preview(options, count=PREVIEW_ROWS)
            normalized_options = self._public_parse_options(
                (result.get("options") or options) if isinstance(result, dict) else options
            )
            if not isinstance(result, dict) or result.get("error"):
                fallback_failed = False
                try:
                    fallback_rows = list(itertools.islice(
                        wizard._read_file(options), MAX_ROWS + 2
                    ))
                except Exception:
                    fallback_failed = True
                    fallback_rows = []
                if not fallback_failed and len(fallback_rows) <= 1:
                    return {
                        "headers": list(fallback_rows[0]) if fallback_rows else [],
                        "preview": [],
                        "rows": fallback_rows,
                        "options": normalized_options,
                        "errors": [],
                    }
                return {
                    "headers": [],
                    "preview": [],
                    "rows": [],
                    "options": normalized_options,
                    "errors": [{
                        "row": False,
                        "code": "import_parse_failed",
                        "errors": ["无法解析导入文件，请检查文件和格式选项。"],
                    }],
                }
            headers = list(result.get("headers") or [])
            preview = list(result.get("preview") or [])
            read_options = dict(options)
            read_options.update(normalized_options)
            try:
                rows = list(itertools.islice(
                    wizard._read_file(read_options), MAX_ROWS + 2
                ))
            except Exception:
                return {
                    "headers": [],
                    "preview": preview,
                    "rows": [],
                    "options": normalized_options,
                    "errors": [{
                        "row": False,
                        "code": "import_parse_failed",
                        "errors": ["无法解析完整导入文件，请检查文件和格式选项。"],
                    }],
                }
            return {
                "headers": headers,
                "preview": preview,
                "rows": rows,
                "options": normalized_options,
                "errors": [],
            }
        finally:
            wizard.unlink()

    @api.model
    def _target_specs(self, profile):
        return {
            spec["field"]: dict(spec, source_header=header)
            for header, spec in profile["columns"].items()
        }

    def _normalize_mapping(self, profile, headers, value):
        if value in (None, False):
            value = {}
        if not isinstance(value, dict) or len(value) > MAX_COLUMNS:
            raise X2ManyImportError("invalid_import_mapping", "导入字段映射无效。")
        if set(value) - set(headers):
            raise X2ManyImportError("invalid_import_mapping", "映射包含当前文件不存在的源列。")
        targets = self._target_specs(profile)
        mapping = {}
        for header in headers:
            target = value.get(header) if header in value else (
                profile["columns"].get(header, {}).get("field") or False
            )
            if target in (None, "", False):
                mapping[header] = False
                continue
            if not isinstance(target, str) or target not in targets:
                raise X2ManyImportError("invalid_import_mapping", "映射目标不在导入 profile 中。")
            if header not in profile["columns"]:
                raise X2ManyImportError("invalid_import_source_column", "该源列未在导入 profile 中注册。")
            mapping[header] = target
        errors = []
        selected = [target for target in mapping.values() if target]
        duplicates = sorted({target for target in selected if selected.count(target) > 1})
        if duplicates:
            errors.append({
                "row": False,
                "code": "duplicate_import_mapping",
                "fields": duplicates,
                "errors": ["同一目标字段不能被多个源列重复映射。"],
            })
        missing = sorted(
            target for target, spec in targets.items()
            if spec.get("required") and target not in selected
        )
        if missing:
            errors.append({
                "row": False,
                "code": "required_import_mapping_missing",
                "fields": missing,
                "errors": ["必填目标字段尚未完成映射。"],
            })
        return mapping, errors

    def _mapping_digest(self, profile, parse_options, mapping):
        self.ensure_one()
        material = {
            "file_sha256": self.file_sha256,
            "profile_hash": profile["hash"],
            "parse_options": parse_options,
            "mapping": mapping,
        }
        return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()

    def _validate_headers(self, headers, rows):
        errors = []
        normalized = [str(value or "").strip() for value in headers]
        if not normalized or not all(normalized) or len(set(normalized)) != len(normalized):
            errors.append({
                "row": False,
                "code": "invalid_import_headers",
                "errors": ["导入表头不能为空或重复。"],
            })
        if len(normalized) > MAX_COLUMNS or any(
            len(header) > MAX_HEADER_CHARS for header in normalized
        ):
            errors.append({
                "row": False,
                "code": "import_column_limit_exceeded",
                "errors": ["导入列数量或表头长度超过限制。"],
            })
        row_count = max(len(rows) - 1, 0)
        if row_count == 0:
            errors.append({
                "row": False,
                "code": "import_file_empty",
                "errors": ["导入文件没有数据行。"],
            })
        if row_count > MAX_ROWS:
            errors.append({
                "row": False,
                "code": "import_row_limit_exceeded",
                "errors": ["导入数据不能超过 2,000 行。"],
            })
        bounded = [header[:MAX_HEADER_CHARS] for header in normalized[:MAX_COLUMNS]]
        return bounded, row_count, errors

    def _convert_value(self, profile_column, child_field, value, row):
        converter = profile_column.get("converter")
        value = value.strip() if isinstance(value, str) else value
        if value in (None, ""):
            if profile_column.get("required"):
                raise ValueError("必填值为空")
            return False
        if converter:
            return converter(self._user_environment(), value, row)
        field_type = profile_column.get("type") or child_field.type
        if field_type in ("char", "text", "html"):
            return str(value)
        if field_type == "integer":
            return int(value)
        if field_type in ("float", "monetary"):
            return float(value)
        if field_type == "boolean":
            normalized = str(value).strip().lower()
            if normalized in ("1", "true", "yes", "是"):
                return True
            if normalized in ("0", "false", "no", "否"):
                return False
            raise ValueError("布尔值格式无效")
        if field_type == "date":
            return fields.Date.to_string(fields.Date.from_string(str(value)))
        if field_type == "datetime":
            return fields.Datetime.to_string(fields.Datetime.from_string(str(value)))
        if field_type == "selection":
            allowed = dict(child_field._description_selection(self._user_environment()))
            if value not in allowed:
                raise ValueError("选项值不存在")
            return value
        raise ValueError("字段类型 %s 必须由 profile converter 处理" % child_field.type)

    def _validate_rows(self, profile, headers, rows, mapping):
        parent_field = self._user_environment()[self.parent_model]._fields[self.field_name]
        child_model = self._user_environment()[parent_field.comodel_name]
        child_model.check_access_rights("create")
        targets = self._target_specs(profile)
        allowed_fields = set(targets)
        parsed_rows = []
        errors = []
        for row_number, row in enumerate(rows[1:], 2):
            if len(row) != len(headers):
                errors.append({"row": row_number, "errors": ["列数与表头不一致"]})
                continue
            source = dict(zip(headers, row))
            values = {}
            row_errors = []
            for header, target in mapping.items():
                if not target:
                    continue
                child_field = child_model._fields.get(target)
                if not child_field:
                    row_errors.append("%s: 目标字段不存在" % header)
                    continue
                try:
                    values[target] = self._convert_value(
                        targets[target], child_field, source.get(header), source
                    )
                except (TypeError, ValueError) as error:
                    row_errors.append("%s: %s" % (header, _safe_error(error)))
            if not row_errors and profile["row_prepare"]:
                try:
                    values = profile["row_prepare"](
                        self._user_environment(), values, source
                    )
                    if not isinstance(values, dict) or set(values) - allowed_fields:
                        raise ValueError("row_prepare 返回了 profile 之外的字段")
                except Exception as error:
                    row_errors.append(_safe_error(error))
            if row_errors:
                errors.append({"row": row_number, "errors": row_errors[:20]})
            else:
                parsed_rows.append(values)
            if len(errors) >= 200:
                break
        return parsed_rows, errors

    def _clear_error_report(self):
        self.ensure_one()
        attachment = self.error_attachment_id.sudo()
        if not attachment:
            return
        self.sudo().write({"error_attachment_id": False})
        attachment.unlink()

    def _write_error_report(self, errors):
        self.ensure_one()
        self._clear_error_report()
        content = json.dumps(
            {"file": self.source_name, "errors": errors},
            ensure_ascii=False, indent=2,
        ).encode("utf-8")
        attachment = self.env["ir.attachment"].sudo().create({
            "name": "%s.errors.json" % self.source_name,
            "datas_fname": "%s.errors.json" % self.source_name,
            "mimetype": "application/json",
            "datas": base64.b64encode(content),
            "res_model": self._name,
            "res_id": self.id,
        })
        self.sudo().write({"error_attachment_id": attachment.id})

    def _preview_job(self, expected_revision, parse_options, mapping, finalize=False):
        self.ensure_one()
        if isinstance(expected_revision, bool):
            raise X2ManyImportError("invalid_import_revision")
        try:
            expected_revision = int(expected_revision)
        except (TypeError, ValueError):
            raise X2ManyImportError("invalid_import_revision", "导入预览修订版本无效。")
        if not isinstance(finalize, bool):
            raise X2ManyImportError("invalid_finalize_value")
        self.env.cr.execute(
            "SELECT state, revision FROM agui_chat_x2many_import_job "
            "WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        locked = self.env.cr.fetchone()
        if not locked:
            raise X2ManyImportError("job_unavailable")
        state, revision = locked
        if state != "preview":
            raise X2ManyImportError("job_not_editable", "导入任务已锁定，不能再修改预览。")
        if revision != expected_revision:
            raise X2ManyImportError("import_revision_conflict", "导入预览已更新，请刷新后重试。")
        self.invalidate_cache()
        profile = self._profile(self.parent_model, self.field_name)
        parsed = self._parse_source(parse_options)
        headers, row_count, header_errors = self._validate_headers(
            parsed["headers"], parsed["rows"]
        ) if not parsed["errors"] else ([], 0, [])
        errors = list(parsed["errors"]) + header_errors
        normalized_mapping = {}
        mapping_errors = []
        if not errors:
            normalized_mapping, mapping_errors = self._normalize_mapping(
                profile, headers, mapping
            )
            errors.extend(mapping_errors)
        normalized_options = parsed["options"]
        mapping_hash = self._mapping_digest(
            profile, normalized_options, normalized_mapping
        )
        validated_rows = []
        if finalize and not errors:
            validated_rows, row_errors = self._validate_rows(
                profile, headers, parsed["rows"], normalized_mapping
            )
            errors.extend(row_errors)
        preview_rows = [
            [_short_cell(cell) for cell in row[:MAX_COLUMNS]]
            for row in parsed["preview"][:PREVIEW_ROWS]
        ]
        next_state = "ready" if finalize and not errors else "preview"
        values = {
            "state": next_state,
            "revision": revision + 1,
            "headers_json": canonical_json(headers),
            "mapping_json": canonical_json(normalized_mapping),
            "parse_options_json": canonical_json(normalized_options),
            "preview_rows_json": canonical_json(preview_rows),
            "rows_json": canonical_json(validated_rows) if next_state == "ready" else "[]",
            "row_count": row_count,
            "errors_json": canonical_json(errors[:200]),
            "mapping_hash": mapping_hash,
        }
        self.sudo().write(values)
        if errors:
            self._write_error_report(errors[:200])
        else:
            self._clear_error_report()
        return self._preview_response()

    def _preview_envelope(self):
        self.ensure_one()
        profile = self._profile(self.parent_model, self.field_name)
        headers = _json(self.headers_json, [])
        mapping = _json(self.mapping_json, {})
        errors = _json(self.errors_json, [])
        result = _json(self.result_json, {})
        public_errors = []
        for error in errors[:MAX_PREVIEW_ERRORS]:
            public_error = dict(error) if isinstance(error, dict) else {
                "row": False,
                "code": "invalid_import_data",
            }
            messages = public_error.get("errors")
            public_error["errors"] = [
                _safe_error(message) for message in (
                    messages[:MAX_ERROR_MESSAGES] if isinstance(messages, list) else []
                )
            ]
            error_fields = public_error.get("fields")
            if isinstance(error_fields, list):
                public_error["fields"] = error_fields[:10]
            public_errors.append(public_error)
        fields_summary = [
            {
                "name": spec["field"],
                "label": spec.get("label") or header,
                "type": spec.get("type") or False,
                "required": bool(spec.get("required")),
            }
            for header, spec in sorted(profile["columns"].items())
        ]
        envelope = {
            "kind": "x2many_import",
            "import": {
                "jobToken": self.token,
                "state": self.state,
                "revision": self.revision,
                "fileName": self.source_name,
                "fileSize": self.file_size,
                "sha256": self.file_sha256,
                "rowCount": self.row_count,
                "headers": headers,
                "columns": [
                    {
                        "index": index,
                        "header": header,
                        "mappedField": mapping.get(header) or False,
                        "mappable": header in profile["columns"],
                    }
                    for index, header in enumerate(headers)
                ],
                "rows": _json(self.preview_rows_json, [])[:PREVIEW_ROWS],
                "previewRowCount": len(_json(self.preview_rows_json, [])),
                "parseOptions": _json(self.parse_options_json, {}),
                "errors": public_errors,
                "errorCount": len(errors),
                "errorReport": "/agui_chat_import/error/%s" % self.token
                if self.error_attachment_id else False,
                "mappingHash": self.mapping_hash or False,
                "target": {
                    "model": self.parent_model,
                    "resId": self.parent_res_id,
                    "field": self.field_name,
                },
                "schema": {
                    "pageHash": self.schema_hash,
                    "profileHash": self.profile_hash,
                    "profileVersion": self.profile_version,
                    "fields": fields_summary,
                },
                "result": result,
            },
        }
        while (
            envelope["import"]["rows"] and
            len(canonical_json(envelope).encode("utf-8")) > MAX_PREVIEW_BYTES
        ):
            envelope["import"]["rows"].pop()
        envelope["import"]["previewRowCount"] = len(envelope["import"]["rows"])
        return envelope

    def _preview_response(self):
        self.ensure_one()
        return {
            "ok": True,
            "jobToken": self.token,
            "state": self.state,
            "revision": self.revision,
            "preview": self._preview_envelope(),
        }

    @api.model
    def _preview_owned_job(self, token, expected_revision, parse_options,
                           mapping, finalize=False):
        return self._owned_job(token)._preview_job(
            expected_revision, parse_options, mapping, finalize
        )

    @api.model
    def _job_status(self, token):
        return self._owned_job(token)._preview_response()

    def _assert_payload_integrity(self, profile):
        self.ensure_one()
        mapping = _json(self.mapping_json, {})
        options = _json(self.parse_options_json, {})
        if self.mapping_hash != self._mapping_digest(profile, options, mapping):
            raise X2ManyImportError("mapping_conflict", "导入映射已变化，请重新准备任务。")
        if not self.source_attachment_id:
            raise X2ManyImportError("import_source_unavailable")
        raw = base64.b64decode(self.source_attachment_id.datas or b"")
        if len(raw) != self.file_size or hashlib.sha256(raw).hexdigest() != self.file_sha256:
            raise X2ManyImportError("import_source_conflict")
        rows = _json(self.rows_json, [])
        if not rows or len(rows) != self.row_count or len(rows) > MAX_ROWS:
            raise X2ManyImportError("validated_rows_invalid")
        return rows

    @api.model
    def _prepare_business_payload(self, payload):
        token = str((payload or {}).get("jobToken") or "").strip()
        job = self._owned_job(token)
        if job.state != "ready":
            raise X2ManyImportError("job_not_ready", "导入任务尚未通过完整校验。")
        profile = self._profile(job.parent_model, job.field_name)
        if profile["hash"] != job.profile_hash or profile["version"] != job.profile_version:
            raise X2ManyImportError("schema_conflict", "导入 profile 已变化，请重新准备任务。")
        parent = self.env[job.parent_model].browse(job.parent_res_id).exists()
        if not parent:
            raise X2ManyImportError("record_unavailable")
        parent.check_access_rights("write")
        parent.check_access_rule("write")
        parent.invalidate_cache(["write_date"])
        if fields.Datetime.to_string(parent.write_date) != job.parent_write_date:
            raise X2ManyImportError("write_date_conflict", "父记录已变化，请重新准备任务。")
        job._assert_payload_integrity(profile)
        return {
            "payload": {"jobToken": job.token},
            "policy_context": {
                "model": job.parent_model,
                "field": job.field_name,
            },
            "risk_reasons": ["one2many_bulk_import", "relation_field"],
            "preview": job._preview_envelope(),
        }

    def _clear_terminal_payload(self):
        self.ensure_one()
        source = self.source_attachment_id.sudo()
        self.sudo().write({
            "source_attachment_id": False,
            "rows_json": "[]",
            "preview_rows_json": "[]",
        })
        if source:
            source.unlink()

    @api.model
    def _execute_business_job(self, payload):
        job = self._owned_job((payload or {}).get("jobToken"))
        self.env.cr.execute(
            "SELECT state FROM agui_chat_x2many_import_job WHERE id = %s FOR UPDATE",
            (job.id,),
        )
        locked = self.env.cr.fetchone()
        if not locked or locked[0] != "ready":
            raise X2ManyImportError("job_not_ready")
        job.invalidate_cache()
        self._prepare_business_payload({"jobToken": job.token})
        job.sudo().write({"state": "running", "started_at": fields.Datetime.now()})
        try:
            if (
                (job.user_id.id != SUPERUSER_ID and not job.user_id.active) or
                job.user_id.company_id.id != job.company_id.id
            ):
                raise X2ManyImportError("user_company_conflict")
            user_env = job._user_environment()
            user_job = user_env[self._name].browse(job.id)
            profile = user_job._profile(user_job.parent_model, user_job.field_name)
            if profile["hash"] != user_job.profile_hash or \
                    profile["version"] != user_job.profile_version:
                raise X2ManyImportError("schema_conflict")
            parent_model = user_env[user_job.parent_model]
            parent = parent_model.browse(user_job.parent_res_id).exists()
            if not parent:
                raise X2ManyImportError("record_unavailable")
            parent.check_access_rights("write")
            parent.check_access_rule("write")
            child_model = user_env[parent._fields[user_job.field_name].comodel_name]
            child_model.check_access_rights("create")
            user_env.cr.execute(
                sql.SQL("SELECT id FROM {} WHERE id = %s FOR UPDATE").format(
                    sql.Identifier(parent._table)
                ),
                (parent.id,),
            )
            parent.invalidate_cache(["write_date"])
            if fields.Datetime.to_string(parent.write_date) != user_job.parent_write_date:
                raise X2ManyImportError("write_date_conflict")
            if profile["parent_check"]:
                code = profile["parent_check"](parent)
                if code:
                    raise X2ManyImportError(str(code))
            rows = user_job._assert_payload_integrity(profile)
            with user_env.cr.savepoint():
                parent.write({
                    user_job.field_name: [(0, 0, values) for values in rows],
                })
                result = {"created": len(rows), "parentId": parent.id}
                job.sudo().write({
                    "state": "done",
                    "finished_at": fields.Datetime.now(),
                    "result_json": canonical_json(result),
                })
                job._clear_terminal_payload()
                response = {
                    "jobToken": job.token,
                    "state": "done",
                    "created": len(rows),
                    "parentId": parent.id,
                    "preview": job._preview_envelope(),
                }
            return response
        except Exception as error:
            job.invalidate_cache()
            code = getattr(error, "code", False) or "x2many_import_failed"
            _logger.exception("One2many import job %s failed with %s", job.id, code)
            errors = [{"row": False, "code": code, "errors": ["导入执行失败。"]}]
            job.sudo().write({
                "state": "failed",
                "finished_at": fields.Datetime.now(),
                "errors_json": canonical_json(errors),
                "result_json": canonical_json({"ok": False, "code": code}),
            })
            job._write_error_report(errors)
            job._clear_terminal_payload()
            return {
                "jobToken": job.token,
                "state": "failed",
                "code": code,
                "preview": job._preview_envelope(),
            }


class AguiChatToolAudit(models.Model):
    _inherit = "agui.chat.tool.audit"

    @api.model
    def _cleanup_expired(self):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        now = fields.Datetime.from_string(fields.Datetime.now())
        cutoff = fields.Datetime.to_string(
            now - timedelta(days=max(config.audit_retention_days or 180, 1))
        )
        jobs = self.env["agui.chat.x2many.import.job"].sudo().search([
            ("create_date", "<", cutoff),
        ])
        attachments = jobs.mapped("source_attachment_id") | jobs.mapped("error_attachment_id")
        if jobs:
            jobs.write({"source_attachment_id": False, "error_attachment_id": False})
        if attachments:
            attachments.sudo().unlink()
        if jobs:
            jobs.unlink()
        return super(AguiChatToolAudit, self)._cleanup_expired()


def _prepare_execute(env, payload):
    return env["agui.chat.x2many.import.job"]._prepare_business_payload(payload)


def _execute(env, payload):
    return env["agui.chat.x2many.import.job"]._execute_business_job(payload)


register_business_command(
    COMMAND_NAME,
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["jobToken"],
        "properties": {
            "jobToken": {"type": "string", "minLength": 1, "maxLength": 160},
        },
    },
    _execute,
    description="确认并同步执行已完整校验的 One2many 批量导入任务。",
    prepare=_prepare_execute,
)
