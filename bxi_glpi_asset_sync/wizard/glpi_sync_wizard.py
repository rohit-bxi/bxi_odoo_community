# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class GlpiSyncWizard(models.TransientModel):
    _name = 'glpi.sync.wizard'
    _description = 'Run GLPI Sync'

    config_id = fields.Many2one('glpi.config', string='GLPI Connection', required=True,
                                default=lambda self: self.env['glpi.config']._get_active())
    mode = fields.Selection([
        ('both', 'Pull from GLPI, then push to GLPI'),
        ('pull', 'Pull from GLPI only'),
        ('push', 'Push to GLPI only'),
    ], string='Direction', required=True, default='both')
    dry_run = fields.Boolean(string='Dry Run', default=True,
        help="Only report what would be created, linked or updated in Odoo. "
             "Nothing is written in Odoo or GLPI.")
    write_back_enabled = fields.Boolean(related='config_id.write_back_enabled')

    def action_run(self):
        self.ensure_one()
        if self.mode == 'push' and not self.write_back_enabled:
            raise UserError(_("Write-back to GLPI is disabled in the GLPI connection settings."))
        log = self.config_id._run_sync(
            pull=self.mode in ('both', 'pull'),
            push=self.mode in ('both', 'push'),
            dry_run=self.dry_run,
        )
        return {
            'name': _('GLPI Sync Log'),
            'type': 'ir.actions.act_window',
            'res_model': 'glpi.sync.log',
            'res_id': log.id,
            'view_mode': 'form',
            'target': 'current',
        }
