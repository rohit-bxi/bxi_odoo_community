# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class AssetDisposalWizard(models.TransientModel):
    _name = 'asset.disposal.wizard'
    _description = 'Asset Disposal Wizard'

    asset_id = fields.Many2one('asset.management', string='Asset', required=True,
                                readonly=True)
    asset_name = fields.Char(related='asset_id.asset_name', string='Asset Name')
    purchase_cost = fields.Float(related='asset_id.amount', string='Purchase Cost')
    accumulated_depreciation = fields.Float(
        related='asset_id.total_depreciation_amount', string='Accumulated Depreciation')
    net_book_value = fields.Float(related='asset_id.current_amount', string='Net Book Value')

    disposal_date = fields.Date(string='Disposal Date', required=True,
                                 default=fields.Date.today)
    disposal_type = fields.Selection([
        ('write_off', 'Write-Off / Scrap'),
        ('sale', 'Sale'),
        ('transfer', 'Transfer'),
    ], string='Disposal Type', required=True, default='write_off')

    sale_proceeds = fields.Float(string='Sale Proceeds',
        help="Amount received from selling the asset (for 'Sale' type)")
    proceeds_account_id = fields.Many2one('account.account',
        string='Proceeds Account',
        help="Account to credit with sale proceeds (e.g. Cash/Bank)")

    loss_on_disposal_account_id = fields.Many2one('account.account',
        string='Loss on Disposal Account',
        help="P&L account for loss on disposal (e.g. Loss on Write-Off)",
        domain="[('account_type', 'in', ['expense', 'expense_depreciation'])]")
    gain_on_disposal_account_id = fields.Many2one('account.account',
        string='Gain on Disposal Account',
        help="P&L account for gain on disposal (e.g. Gain on Sale of Assets)")

    notes = fields.Text(string='Disposal Notes')

    @api.onchange('disposal_type')
    def _onchange_disposal_type(self):
        if self.disposal_type != 'sale':
            self.sale_proceeds = 0.0
            self.proceeds_account_id = False

    def action_confirm_disposal(self):
        """Post disposal journal entry and mark asset as disposed."""
        self.ensure_one()
        asset = self.asset_id

        if asset.state != 'confirmed':
            raise UserError(_("Only confirmed assets can be disposed."))

        if not asset.fixed_asset_account_id:
            raise UserError(_(
                "Please configure the Fixed Asset Account on the asset before disposing."))

        journal = asset.asset_journal_id or self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)],
            limit=1)
        if not journal:
            raise UserError(_("No accounting journal found. Please configure an Asset Journal."))

        nbv = asset.current_amount
        cost = asset.amount
        accum_dep = asset.total_depreciation_amount
        proceeds = self.sale_proceeds if self.disposal_type == 'sale' else 0.0
        gain_loss = proceeds - nbv  # positive = gain, negative = loss

        line_ids = []

        # 1) Clear Accumulated Depreciation (Debit)
        if accum_dep > 0.01 and asset.accumulated_depreciation_account_id:
            line_ids.append((0, 0, {
                'name': _('Clear Accumulated Depreciation: %s') % asset.name,
                'account_id': asset.accumulated_depreciation_account_id.id,
                'debit': accum_dep,
                'credit': 0.0,
            }))

        # 2) Record sale proceeds if any (Debit Cash/Receivable)
        if proceeds > 0.01:
            if not self.proceeds_account_id:
                raise UserError(_(
                    "Please set a Proceeds Account for the sale."))
            line_ids.append((0, 0, {
                'name': _('Sale Proceeds: %s') % asset.name,
                'account_id': self.proceeds_account_id.id,
                'debit': proceeds,
                'credit': 0.0,
            }))

        # 3) Loss on disposal (Debit) — if NBV > proceeds
        if gain_loss < -0.01:
            loss_account = (self.loss_on_disposal_account_id or
                            self.env['account.account'].search([
                                ('account_type', '=', 'expense'),
                                ('company_id', '=', self.env.company.id),
                            ], limit=1))
            if loss_account:
                line_ids.append((0, 0, {
                    'name': _('Loss on Disposal: %s') % asset.name,
                    'account_id': loss_account.id,
                    'debit': abs(gain_loss),
                    'credit': 0.0,
                }))

        # 4) Credit Fixed Asset Account (Cost)
        line_ids.append((0, 0, {
            'name': _('Dispose Asset: %s') % asset.name,
            'account_id': asset.fixed_asset_account_id.id,
            'debit': 0.0,
            'credit': cost,
        }))

        # 5) Gain on disposal (Credit) — if proceeds > NBV
        if gain_loss > 0.01:
            gain_account = (self.gain_on_disposal_account_id or
                            self.env['account.account'].search([
                                ('account_type', '=', 'income'),
                                ('company_id', '=', self.env.company.id),
                            ], limit=1))
            if gain_account:
                line_ids.append((0, 0, {
                    'name': _('Gain on Disposal: %s') % asset.name,
                    'account_id': gain_account.id,
                    'debit': 0.0,
                    'credit': gain_loss,
                }))

        if not line_ids:
            raise UserError(_(
                "Cannot create disposal entry: Please configure the accounting accounts "
                "(Fixed Asset, Accumulated Depreciation)."))

        move_vals = {
            'journal_id': journal.id,
            'date': self.disposal_date,
            'ref': _('Asset Disposal: %(name)s - %(type)s') % {
                'name': asset.name,
                'type': dict(self._fields['disposal_type'].selection).get(
                    self.disposal_type, ''),
            },
            'move_type': 'entry',
            'line_ids': line_ids,
            'narration': self.notes or '',
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()

        # Update asset
        asset.write({
            'state': 'disposed',
            'status': 'destroyed',
            'disposal_date': self.disposal_date,
            'disposal_move_id': move.id,
        })

        # Also update linked account.asset if exists (account_asset module optional)
        if asset.account_asset_id_int:
            AccountAsset = self.env.get('account.asset')
            if AccountAsset:
                try:
                    aa = AccountAsset.browse(asset.account_asset_id_int).exists()
                    if aa:
                        aa.write({'state': 'close'})
                except Exception:
                    pass

        asset.message_post(
            body=_("Asset disposed via %s on %s. Journal entry: %s") % (
                dict(self._fields['disposal_type'].selection).get(self.disposal_type, ''),
                self.disposal_date,
                move.name,
            ))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Disposal Journal Entry'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
