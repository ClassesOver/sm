# -*- coding: utf-8 -*-
from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def load_menus(self, debug):
        menu_root = super(IrUiMenu, self).load_menus(debug)

        def add_explicit_action_id(node):
            action = str(node.get("action") or "")
            parts = action.split(",")
            node["action_id"] = (
                int(parts[1])
                if len(parts) == 2 and parts[0] == "ir.actions.act_window" and
                parts[1].isdigit() and int(parts[1]) > 0
                else False
            )
            for child in node.get("children") or []:
                add_explicit_action_id(child)

        add_explicit_action_id(menu_root)
        return menu_root
