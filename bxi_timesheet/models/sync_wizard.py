# -*- coding: utf-8 -*-
from odoo import fields, models, api, _

class BxiDesktimeSyncWizard(models.TransientModel):
    _name = 'bxi.desktime.sync.wizard'
    _description = 'DeskTime Sync Date Wizard'

    config_id = fields.Many2one('bxi.desktime.config', string='Configuration', required=True)
    sync_date = fields.Date(string='Date to Sync', default=fields.Date.today, required=True)

    def action_sync(self):
        self.ensure_one()
        self.config_id._sync_for_date(self.sync_date)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('DeskTime Sync'),
                'message': _('Sync completed for %s.') % self.sync_date,
                'type': 'success',
                'sticky': False,
            }
        }
