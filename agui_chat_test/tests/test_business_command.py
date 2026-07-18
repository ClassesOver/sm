# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat.models.agui_chat_tool import business_tool_catalog
from odoo.addons.agui_chat.models.agui_chat_report import ReportError, _currency_rules
from odoo.addons.agui_chat_test.models.business_command import (
    COMMAND_NAME,
    MODEL_NAME,
    READ_COMMAND_NAME,
)


class TestBusinessCommand(TransactionCase):

    def setUp(self):
        super(TestBusinessCommand, self).setUp()
        self.config = self.env["agui.chat.config"].sudo().get_active_config()
        self.config.write({
            "enabled_business_commands": COMMAND_NAME,
            "sensitive_field_names": "configured_secret",
        })
        self.document = self.env[MODEL_NAME].create({
            "name": "业务命令测试",
            "required_code": "BUSINESS-1",
        })

    def _payload(self, document=None):
        return {
            "model": MODEL_NAME,
            "document_id": (document or self.document).id,
            "expected_state": "draft",
        }

    def _call(self, call_id, payload=None):
        return {
            "id": call_id,
            "tool": COMMAND_NAME,
            "arguments": payload or self._payload(),
            "context": {
                "requestId": "request-%s" % call_id,
                "runId": "run-%s" % call_id,
                "threadId": "thread-%s" % call_id,
            },
        }

    def test_catalog_only_publishes_registered_enabled_commands(self):
        catalog = business_tool_catalog(self.env, self.config)

        self.assertEqual([tool["name"] for tool in catalog], [COMMAND_NAME])
        self.assertEqual(catalog[0]["parameters"]["additionalProperties"], False)

        self.config.write({"enabled_business_commands": False})
        self.assertEqual(business_tool_catalog(self.env, self.config), [])
        disabled = self.env[
            "agui.chat.tool.authorization"
        ]._prepare_business_command(self._call("business-disabled"))
        self.assertEqual(disabled["code"], "unsupported_business_command")

        self.config.write({
            "enabled_business_commands": COMMAND_NAME,
            "write_tools_enabled": False,
        })
        write_disabled = self.env[
            "agui.chat.tool.authorization"
        ]._prepare_business_command(self._call("business-write-disabled"))
        self.assertEqual(write_disabled["code"], "write_tools_disabled")

    def test_read_business_command_works_while_write_tools_are_disabled(self):
        self.env["agui.chat.command"].create({
            "name": "读取测试单据",
            "code": READ_COMMAND_NAME,
            "command_type": "business",
        })
        self.env["agui.chat.tool.policy"].create({
            "name": "读取测试单据",
            "tool_name": READ_COMMAND_NAME,
            "access_level": "read",
            "model_name": MODEL_NAME,
            "field_names": "name",
            "confirmation_mode": "never",
        })
        self.config.write({
            "enabled_business_commands": "%s,%s" % (COMMAND_NAME, READ_COMMAND_NAME),
            "write_tools_enabled": False,
        })
        catalog = business_tool_catalog(self.env, self.config)
        by_name = {item["name"]: item for item in catalog}
        self.assertEqual(by_name[READ_COMMAND_NAME]["accessLevel"], "read")
        self.assertEqual(by_name[COMMAND_NAME]["accessLevel"], "write")

        payload = {"model": MODEL_NAME, "document_id": self.document.id}
        call = self._call("business-read-without-write", payload)
        call["tool"] = READ_COMMAND_NAME
        decision = self.env["agui.chat.tool.authorization"]._prepare_business_command(call)
        self.assertTrue(decision["ok"])
        result = self.env["agui.chat.command.execution"]._execute_named(
            READ_COMMAND_NAME, payload, decision["authorization_id"],
            decision["authorization_id"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["document_id"], self.document.id)

        denied = self.env["agui.chat.tool.authorization"]._prepare_business_command(
            self._call("business-write-still-disabled")
        )
        self.assertEqual(denied["code"], "write_tools_disabled")

    def test_report_monetary_aggregation_requires_currency_dimension(self):
        binding = {"model": MODEL_NAME}
        with self.assertRaises(ReportError) as caught:
            _currency_rules(self.env, binding, {
                "dimensions": [],
                "metrics": [{"field": "amount", "aggregation": "sum"}],
            })
        self.assertEqual(caught.exception.code, "currency_dimension_required")
        rules = _currency_rules(self.env, binding, {
            "dimensions": ["currency_id"],
            "metrics": [{"field": "amount", "aggregation": "sum"}],
        })
        self.assertEqual(rules[0]["currencyField"], "currency_id")

    def test_inactive_business_command_blocks_catalog_prepare_and_execute(self):
        command = self.env.ref("agui_chat_test.command_test_document_confirm")
        authorizations = self.env["agui.chat.tool.authorization"]
        decision = authorizations._prepare_business_command(
            self._call("business-active-before-disable")
        )
        authorization = authorizations.search([
            ("token", "=", decision["authorization_id"]),
        ])
        authorization._transition(True)

        command.write({"active": False})
        self.assertEqual(business_tool_catalog(self.env, self.config), [])
        disabled = authorizations._prepare_business_command(
            self._call("business-inactive")
        )
        self.assertEqual(disabled["code"], "unsupported_business_command")
        execution = self.env["agui.chat.command.execution"]._execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertEqual(execution["code"], "unsupported_business_command")

        command.write({"active": True})
        self.assertEqual(
            [tool["name"] for tool in business_tool_catalog(self.env, self.config)],
            [COMMAND_NAME],
        )

    def test_schema_and_missing_policy_fail_closed(self):
        authorization = self.env["agui.chat.tool.authorization"]
        wrong_model = self._payload()
        wrong_model["model"] = "res.partner"
        invalid = authorization._prepare_business_command(
            self._call("business-invalid-model", wrong_model)
        )
        self.assertEqual(invalid["code"], "schema_validation_failed")

        extra = self._payload()
        extra["unexpected"] = True
        invalid = authorization._prepare_business_command(
            self._call("business-extra-field", extra)
        )
        self.assertEqual(invalid["code"], "schema_validation_failed")

        self.env.ref("agui_chat_test.policy_test_document_confirm").write({
            "active": False,
        })
        denied = authorization._prepare_business_command(
            self._call("business-policy-missing")
        )
        self.assertEqual(denied["code"], "policy_missing")

    def test_confirmation_payload_binding_and_idempotent_execution(self):
        authorizations = self.env["agui.chat.tool.authorization"]
        decision = authorizations._prepare_business_command(
            self._call("business-confirm")
        )
        self.assertTrue(decision["needs_confirmation"])
        self.assertEqual(decision["preview"]["payload"], self._payload())

        authorization = authorizations.search([
            ("token", "=", decision["authorization_id"]),
        ])
        self.assertEqual(authorization.authorization_kind, "business")
        self.assertEqual(authorization.state, "pending")

        other = self.env[MODEL_NAME].create({
            "name": "篡改目标",
            "required_code": "BUSINESS-2",
        })
        tampered = authorizations._prepare_business_command(
            self._call("business-confirm", self._payload(other))
        )
        self.assertEqual(tampered["code"], "idempotency_payload_mismatch")

        approved = authorization._transition(True)
        self.assertTrue(approved["ok"])
        self.assertEqual(approved["bound_call"]["arguments"], self._payload())
        authorization.invalidate_cache(["state"])
        self.assertEqual(authorization.state, "approved")

        executions = self.env["agui.chat.command.execution"]
        result = executions._execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["state"], "confirmed")
        self.assertEqual(result["result"]["phone_number"], "[redacted]")
        self.assertEqual(result["result"]["configured_secret"], "[redacted]")
        self.document.invalidate_cache(["state"])
        self.assertEqual(self.document.state, "confirmed")

        replay = executions._execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertEqual(replay, result)
        self.assertEqual(executions.search_count([
            ("command_name", "=", COMMAND_NAME),
            ("idempotency_key", "=", authorization.token),
        ]), 1)

        audits = self.env["agui.chat.tool.audit"].search([
            ("tool_name", "=", COMMAND_NAME),
            ("authorization_id", "=", authorization.id),
        ])
        self.assertEqual(set(audits.mapped("result")), {"allowed", "ok"})
        self.assertFalse(any(
            any(value in (audit.details_json or "") for value in ("13800138000", "configured-sensitive-value"))
            for audit in audits
        ))

    def test_state_conflict_rolls_back_and_is_replayed(self):
        self.document.action_confirm()
        authorizations = self.env["agui.chat.tool.authorization"]
        decision = authorizations._prepare_business_command(
            self._call("business-state-conflict")
        )
        authorization = authorizations.search([
            ("token", "=", decision["authorization_id"]),
        ])
        authorization._transition(True)

        executions = self.env["agui.chat.command.execution"]
        failed = executions._execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["code"], "state_conflict")

        replay = executions._execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertEqual(replay, failed)
        self.document.invalidate_cache(["state"])
        self.assertEqual(self.document.state, "confirmed")
