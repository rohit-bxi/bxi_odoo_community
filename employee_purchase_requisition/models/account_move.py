# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

FINANCE_GROUP = 'employee_purchase_requisition.material_category_finance_group'
RA_GROUP = 'employee_purchase_requisition.material_category_ra_group'


class AccountMove(models.Model):
    """Add Finance and Revenue Assurance stages to invoices and bills."""
    _inherit = 'account.move'

    state = fields.Selection(
        selection_add=[('finance', 'Finance'),
                       ('revenue_assurance', 'Revenue Assurance'),
                       ('posted',)],
        ondelete={'finance': 'set default',
                  'revenue_assurance': 'set default'})
    # Computed from `state`, so it must accept the new stages as well
    status_in_payment = fields.Selection(
        selection_add=[('finance', 'Finance'),
                       ('revenue_assurance', 'Revenue Assurance')])

    def _check_approval_group(self, xml_id):
        if not self.env.user.has_group(xml_id):
            raise UserError(_("You are not allowed to perform this action."))

    def action_confirm_to_finance(self):
        """Move draft invoices/bills to the Finance stage."""
        for move in self.filtered(lambda m: m.state == 'draft'):
            if move.move_type == 'entry':
                continue
            move.state = 'finance'
        return True

    def action_finance_approve(self):
        self._check_approval_group(FINANCE_GROUP)
        for move in self.filtered(lambda m: m.state == 'finance'):
            move.state = 'revenue_assurance'
        return True

    def action_finance_reject(self):
        self._check_approval_group(FINANCE_GROUP)
        for move in self.filtered(lambda m: m.state == 'finance'):
            move.state = 'draft'
        return True

    def action_revenue_assurance_confirm(self):
        """Standard posting, only from the Revenue Assurance stage."""
        self._check_approval_group(RA_GROUP)
        moves = self.filtered(lambda m: m.state == 'revenue_assurance')
        # Standard posting only handles draft moves
        moves.write({'state': 'draft'})
        return moves.with_context(
            validate_analytic=True,
            disable_abnormal_invoice_detection=False).action_post()
