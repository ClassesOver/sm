# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat.models.agui_chat_tool import business_tool_catalog
from odoo.addons.agui_chat_test.models.business_command import (
    COMMAND_NAME,
    MODEL_NAME,
)


class TestBusinessCommand(TransactionCase):

    def setUp(self):
        super(TestBusinessCommand, self).setUp()
        self.config = self.env["agui.chat.config"].sudo().get_active_config()
        self.config.write({"sensitive_field_names": "configured_secret"})
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
        ].prepare_business_command(self._call("business-disabled"))
        self.assertEqual(disabled["code"], "unsupported_business_command")

        self.config.write({
            "enabled_business_commands": COMMAND_NAME,
            "write_tools_enabled": False,
        })
        write_disabled = self.env[
            "agui.chat.tool.authorization"
        ].prepare_business_command(self._call("business-write-disabled"))
        self.assertEqual(write_disabled["code"], "write_tools_disabled")

    def test_schema_and_missing_policy_fail_closed(self):
        authorization = self.env["agui.chat.tool.authorization"]
        wrong_model = self._payload()
        wrong_model["model"] = "res.partner"
        invalid = authorization.prepare_business_command(
            self._call("business-invalid-model", wrong_model)
        )
        self.assertEqual(invalid["code"], "schema_validation_failed")

        extra = self._payload()
        extra["unexpected"] = True
        invalid = authorization.prepare_business_command(
            self._call("business-extra-field", extra)
        )
        self.assertEqual(invalid["code"], "schema_validation_failed")

        self.env.ref("agui_chat_test.policy_test_document_confirm").write({
            "active": False,
        })
        denied = authorization.prepare_business_command(
            self._call("business-policy-missing")
        )
        self.assertEqual(denied["code"], "policy_missing")

    def test_confirmation_payload_binding_and_idempotent_execution(self):
        authorizations = self.env["agui.chat.tool.authorization"]
        decision = authorizations.prepare_business_command(
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
        tampered = authorizations.prepare_business_command(
            self._call("business-confirm", self._payload(other))
        )
        self.assertEqual(tampered["code"], "idempotency_payload_mismatch")

        approved = authorization.transition(True)
        self.assertTrue(approved["ok"])
        self.assertEqual(approved["bound_call"]["arguments"], self._payload())
        authorization.invalidate_cache(["state"])
        self.assertEqual(authorization.state, "approved")

        executions = self.env["agui.chat.command.execution"]
        result = executions.execute_named(
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

        replay = executions.execute_named(
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
        decision = authorizations.prepare_business_command(
            self._call("business-state-conflict")
        )
        authorization = authorizations.search([
            ("token", "=", decision["authorization_id"]),
        ])
        authorization.transition(True)

        executions = self.env["agui.chat.command.execution"]
        failed = executions.execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["code"], "state_conflict")

        replay = executions.execute_named(
            COMMAND_NAME,
            self._payload(),
            authorization.token,
            authorization.token,
        )
        self.assertEqual(replay, failed)
        self.document.invalidate_cache(["state"])
        self.assertEqual(self.document.state, "confirmed")
