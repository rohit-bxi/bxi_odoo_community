# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class HdfcReleaseWizard(models.TransientModel):
    _name = 'hdfc.release.wizard'
    _description = 'Pay Payslips via HDFC'

    payslip_ids = fields.Many2many('hr.payslip', string='Payslips', required=True)
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    summary_html = fields.Html(compute='_compute_preview', sanitize=False)
    error_message = fields.Text(compute='_compute_preview')
    has_errors = fields.Boolean(compute='_compute_preview')

    @api.depends('payslip_ids')
    def _compute_preview(self):
        for wizard in self:
            lines_by_config, errors = wizard.payslip_ids._hdfc_prepare_payout()
            rows = Markup()
            for config, vals_list in lines_by_config.items():
                currency = config.company_id.currency_id
                total = sum(v['amount'] for v in vals_list)
                rows += Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td class="text-end">%s</td></tr>') % (
                    config.company_id.name,
                    len({v['payslip_id'] for v in vals_list}),
                    len(vals_list),
                    escape(currency.format(total)),
                )
            wizard.summary_html = rows and Markup(
                '<table class="table table-sm"><thead><tr><th>%s</th><th>%s</th><th>%s</th>'
                '<th class="text-end">%s</th></tr></thead><tbody>%s</tbody></table>'
            ) % (_('Company'), _('Payslips'), _('Transfers'), _('Total'), rows)
            wizard.error_message = '\n'.join(errors) or False
            wizard.has_errors = bool(errors)

    def action_release(self):
        self.ensure_one()
        lines_by_config, errors = self.payslip_ids._hdfc_prepare_payout()
        if errors:
            raise UserError(_('Fix the following before paying:\n%s', '\n'.join(errors)))
        if not lines_by_config:
            raise UserError(_('Nothing to pay.'))

        batches = self.env['hdfc.payout.batch']
        for config, vals_list in lines_by_config.items():
            size = config.max_lines_per_batch
            for start in range(0, len(vals_list), size):
                batches |= batches.create({
                    'company_id': config.company_id.id,
                    'config_id': config.id,
                    'payment_date': self.payment_date,
                    'line_ids': [Command.create(vals) for vals in vals_list[start:start + size]],
                })

        action = {
            'type': 'ir.actions.act_window',
            'name': _('HDFC Payout Batches'),
            'res_model': 'hdfc.payout.batch',
        }
        if len(batches) == 1:
            action.update(view_mode='form', res_id=batches.id)
        else:
            action.update(view_mode='list,form', domain=[('id', 'in', batches.ids)])
        return action
