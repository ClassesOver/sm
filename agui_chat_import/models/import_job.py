# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import logging
import re
import uuid

from psycopg2 import sql

from odoo import SUPERUSER_ID, api, fields, models

from odoo.addons.agui_chat.models.agui_chat_tool import (
    canonical_json,
    register_business_command,
)


COMMAND_NAME = "odoo.business.x2many_import.execute"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 2000
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
    for header, value in columns.items():
        header = str(header or "").strip()
        value = {"field": value} if isinstance(value, str) else dict(value or {})
        field_name_value = str(value.get("field") or "").strip()
        if not header or not field_name_value:
            raise ValueError("导入 profile 的列名和字段名不能为空。")
        normalized[header] = {
            "field": field_name_value,
            "required": bool(value.get("required")),
            "type": value.get("type") or False,
            "converter": value.get("converter"),
        }
        if normalized[header]["converter"] is not None and not callable(
            normalized[header]["converter"]
        ):
            raise ValueError("导入列 converter 必须是可调用对象。")
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


class AguiChatX2ManyImportJob(models.Model):
    _name = "agui.chat.x2many.import.job"
    _description = "AG-UI One2many 批量导入任务"
    _order = "create_date desc"

    token = fields.Char(
        string="任务令牌", required=True, index=True,
        default=lambda self: str(uuid.uuid4()),
    )
    state = fields.Selection([
        ("validating", "校验中"),
        ("ready", "待确认"),
        ("queued", "已排队"),
        ("running", "执行中"),
        ("done", "已完成"),
        ("failed", "失败"),
    ], string="状态", required=True, default="validating", index=True)
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
    rows_json = fields.Text(string="已校验数据", default="[]")
    errors_json = fields.Text(string="校验错误", default="[]")
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
        raw = base64.b64decode(attachment.datas or b"")
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise X2ManyImportError("import_file_size_invalid", "导入文件必须小于等于 10 MB。")
        write_date = fields.Datetime.to_string(parent.write_date)
        job = self.sudo().create({
            "user_id": self.env.user.id,
            "company_id": self.env.user.company_id.id,
            "parent_model": parent_model,
            "parent_res_id": parent.id,
            "field_name": field_name,
            "parent_write_date": write_date,
            "schema_hash": schema_hash,
            "profile_hash": profile["hash"],
            "profile_version": profile["version"],
            "source_name": (attachment.name or "import")[:255],
            "source_mimetype": mimetype,
            "file_size": len(raw),
            "file_sha256": hashlib.sha256(raw).hexdigest(),
        })
        copy = attachment.copy({
            "res_model": self._name,
            "res_id": job.id,
            "name": attachment.name or "import",
        })
        job.write({"source_attachment_id": copy.id})
        return {"ok": True, "jobToken": job.token, "state": job.state}

    def _user_environment(self):
        self.ensure_one()
        return api.Environment(self.env.cr, self.user_id.id, dict(
            self.env.context,
            force_company=self.company_id.id,
            allowed_company_ids=[self.company_id.id],
        ))

    def _read_rows(self):
        self.ensure_one()
        raw = base64.b64decode(self.source_attachment_id.datas or b"")
        wizard = self.env["base_import.import"].sudo().create({
            "res_model": self.parent_model,
            "file": raw,
            "file_name": self.source_name,
            "file_type": self.source_mimetype,
        })
        try:
            return list(wizard._read_file({
                "quoting": '"', "separator": False, "encoding": False,
            }))
        finally:
            wizard.unlink()

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

    def _write_error_report(self, errors):
        self.ensure_one()
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

    def _validate_job(self):
        self.ensure_one()
        if self.state != "validating":
            return False
        profile = self._profile(self.parent_model, self.field_name)
        errors = []
        parsed_rows = []
        headers = []
        try:
            rows = self._read_rows()
            if len(rows) < 2:
                raise X2ManyImportError("import_file_empty", "导入文件没有数据行。")
            if len(rows) - 1 > MAX_ROWS:
                raise X2ManyImportError("import_row_limit_exceeded", "导入数据不能超过 2,000 行。")
            headers = [str(value or "").strip() for value in rows[0]]
            if not all(headers) or len(set(headers)) != len(headers):
                raise X2ManyImportError("invalid_import_headers", "导入表头不能为空或重复。")
            unknown = set(headers) - set(profile["columns"])
            missing = {
                header for header, spec in profile["columns"].items()
                if spec.get("required") and header not in headers
            }
            if unknown or missing:
                raise X2ManyImportError(
                    "invalid_import_headers",
                    "导入表头与 profile 不匹配。",
                )
            relation_model = self.env[self.parent_model]._fields[self.field_name].comodel_name
            child_model = self.env[relation_model]
            for row_number, row in enumerate(rows[1:], 2):
                if len(row) != len(headers):
                    errors.append({
                        "row": row_number,
                        "errors": ["列数与表头不一致"],
                    })
                    continue
                source = dict(zip(headers, list(row) + [""] * len(headers)))
                values = {}
                row_errors = []
                for header in headers:
                    column = profile["columns"][header]
                    child_field = child_model._fields.get(column["field"])
                    if not child_field:
                        row_errors.append("%s: 目标字段不存在" % header)
                        continue
                    try:
                        values[column["field"]] = self._convert_value(
                            column, child_field, source.get(header), source
                        )
                    except (TypeError, ValueError) as error:
                        row_errors.append("%s: %s" % (header, str(error)))
                if not row_errors and profile["row_prepare"]:
                    try:
                        values = profile["row_prepare"](
                            self._user_environment(), values, source
                        )
                    except Exception as error:
                        row_errors.append(str(error))
                if row_errors:
                    errors.append({"row": row_number, "errors": row_errors[:20]})
                else:
                    parsed_rows.append(values)
        except X2ManyImportError as error:
            errors.append({"row": False, "code": error.code, "errors": [str(error)]})
        except Exception as error:
            errors.append({
                "row": False, "code": "import_parse_failed", "errors": [str(error)]
            })
        values = {
            "headers_json": canonical_json(headers),
            "row_count": len(parsed_rows),
            "errors_json": canonical_json(errors[:200]),
            "rows_json": canonical_json(parsed_rows) if not errors else "[]",
        }
        if errors:
            values.update({"state": "failed", "finished_at": fields.Datetime.now()})
            self.sudo().write(values)
            self._write_error_report(errors[:200])
        else:
            values["state"] = "ready"
            self.sudo().write(values)
        return not errors

    @api.model
    def _job_status(self, token):
        job = self._owned_job(token)
        errors = _json(job.errors_json, [])
        result = _json(job.result_json, {})
        return {
            "ok": True,
            "jobToken": job.token,
            "state": job.state,
            "fileName": job.source_name,
            "sha256": job.file_sha256,
            "rowCount": job.row_count,
            "headers": _json(job.headers_json, []),
            "errors": errors[:20],
            "errorCount": len(errors),
            "errorReport": "/agui_chat_import/error/%s" % job.token
            if job.error_attachment_id else False,
            "result": result,
        }

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
        parent.invalidate_cache(["write_date"])
        if fields.Datetime.to_string(parent.write_date) != job.parent_write_date:
            raise X2ManyImportError("write_date_conflict", "父记录已变化，请重新准备任务。")
        fields_summary = [
            {"header": header, "field": spec["field"], "type": spec.get("type") or False}
            for header, spec in sorted(profile["columns"].items())
        ]
        return {
            "payload": {"jobToken": job.token},
            "policy_context": {
                "model": job.parent_model,
                "field": job.field_name,
            },
            "risk_reasons": ["one2many_bulk_import", "relation_field"],
            "preview": {
                "import": {
                    "fileName": job.source_name,
                    "fileSize": job.file_size,
                    "sha256": job.file_sha256,
                    "rowCount": job.row_count,
                    "headers": _json(job.headers_json, []),
                    "fields": fields_summary,
                    "target": {
                        "model": job.parent_model,
                        "resId": job.parent_res_id,
                        "field": job.field_name,
                    },
                    "schema": {
                        "pageHash": job.schema_hash,
                        "profileHash": job.profile_hash,
                        "profileVersion": job.profile_version,
                    },
                },
            },
        }

    @api.model
    def _queue_business_job(self, payload):
        job = self._owned_job((payload or {}).get("jobToken"))
        self.env.cr.execute(
            "SELECT state FROM agui_chat_x2many_import_job WHERE id = %s FOR UPDATE",
            (job.id,),
        )
        state = self.env.cr.fetchone()[0]
        if state != "ready":
            raise X2ManyImportError("job_not_ready")
        self._prepare_business_payload({"jobToken": job.token})
        job.sudo().write({"state": "queued"})
        return {"jobToken": job.token, "state": "queued"}

    def _run_job(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state FROM agui_chat_x2many_import_job WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        state = self.env.cr.fetchone()
        if not state or state[0] != "queued":
            return False
        user_env = self._user_environment()
        job = user_env[self._name].browse(self.id)
        job.sudo().write({"state": "running", "started_at": fields.Datetime.now()})
        try:
            if (
                job.user_id.id != SUPERUSER_ID and not job.user_id.active or
                job.user_id.company_id.id != job.company_id.id
            ):
                raise X2ManyImportError("user_company_conflict")
            profile = job._profile(job.parent_model, job.field_name)
            if profile["hash"] != job.profile_hash or profile["version"] != job.profile_version:
                raise X2ManyImportError("schema_conflict")
            parent_model = user_env[job.parent_model]
            parent = parent_model.browse(job.parent_res_id).exists()
            if not parent:
                raise X2ManyImportError("record_unavailable")
            parent.check_access_rights("write")
            parent.check_access_rule("write")
            child_model = user_env[parent._fields[job.field_name].comodel_name]
            child_model.check_access_rights("create")
            user_env.cr.execute(
                sql.SQL("SELECT id FROM {} WHERE id = %s FOR UPDATE").format(
                    sql.Identifier(parent._table)
                ),
                (parent.id,),
            )
            parent.invalidate_cache(["write_date"])
            if fields.Datetime.to_string(parent.write_date) != job.parent_write_date:
                raise X2ManyImportError("write_date_conflict")
            if profile["parent_check"]:
                code = profile["parent_check"](parent)
                if code:
                    raise X2ManyImportError(str(code))
            rows = _json(job.rows_json, [])
            if not rows or len(rows) != job.row_count or len(rows) > MAX_ROWS:
                raise X2ManyImportError("validated_rows_invalid")
            with user_env.cr.savepoint():
                parent.write({
                    job.field_name: [(0, 0, values) for values in rows],
                })
            result = {"created": len(rows), "parentId": parent.id}
            job.sudo().write({
                "state": "done",
                "finished_at": fields.Datetime.now(),
                "result_json": canonical_json(result),
            })
            return True
        except Exception as error:
            code = getattr(error, "code", False) or "x2many_import_failed"
            _logger.exception("One2many import job %s failed with %s", job.id, code)
            job.sudo().write({
                "state": "failed",
                "finished_at": fields.Datetime.now(),
                "result_json": canonical_json({"ok": False, "code": code}),
            })
            return False

    @api.model
    def _process_pending_jobs(self, limit=5):
        limit = min(max(int(limit or 5), 1), 20)
        validating = self.sudo().search(
            [("state", "=", "validating")], order="id", limit=limit
        )
        for job in validating:
            job._validate_job()
        queued = self.sudo().search(
            [("state", "=", "queued")], order="id", limit=limit
        )
        for job in queued:
            job._run_job()
        return True


def _prepare_execute(env, payload):
    return env["agui.chat.x2many.import.job"]._prepare_business_payload(payload)


def _execute(env, payload):
    return env["agui.chat.x2many.import.job"]._queue_business_job(payload)


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
    description="确认并排队执行已完整校验的 One2many 批量导入任务。",
    prepare=_prepare_execute,
)
