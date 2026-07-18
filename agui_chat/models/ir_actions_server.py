# -*- coding: utf-8 -*-
from psycopg2 import sql

from odoo import models


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    def _auto_init(self):
        result = super(IrActionsServer, self)._auto_init()
        self.env.cr.execute(
            """
            SELECT column_default
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = %s
               AND column_name = 'activity_user_type'
            """,
            (self._table,),
        )
        column = self.env.cr.fetchone()
        if column and column[0] is None:
            self.env.cr.execute(sql.SQL(
                "ALTER TABLE {} ALTER COLUMN activity_user_type SET DEFAULT 'specific'"
            ).format(sql.Identifier(self._table)))
        return result
