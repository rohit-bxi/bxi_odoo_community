# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from odoo import _, fields, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    """Class to add new field in purchase order"""
    _inherit = 'purchase.order'

    requisition_order = fields.Char(string='Requisition Order',
                                    help='Set a requisition Order')
    state = fields.Selection(
        selection_add=[('finance', 'Finance'),
                       ('revenue_assurance', 'Revenue Assurance'),
                       ('purchase',)],
        ondelete={'finance': 'set default',
                  'revenue_assurance': 'set default'})

    def _check_po_group(self, xml_id):
        if not self.env.user.has_group(xml_id):
            raise UserError(_("You are not allowed to perform this action."))

    def action_confirm_po(self):
        """Move RFQ / RFQ Sent to the Finance stage."""
        for order in self:
            if order.state not in ('draft', 'sent'):
                continue
            order.state = 'finance'
        return True

    def action_finance_approve(self):
        self._check_po_group(
            'employee_purchase_requisition.material_category_finance_group')
        for order in self.filtered(lambda o: o.state == 'finance'):
            order.state = 'revenue_assurance'
        return True

    def action_finance_reject(self):
        self._check_po_group(
            'employee_purchase_requisition.material_category_finance_group')
        for order in self.filtered(lambda o: o.state == 'finance'):
            order.state = 'draft'
        return True

    def action_revenue_assurance_confirm(self):
        """Standard confirmation, only from the Revenue Assurance stage."""
        self._check_po_group(
            'employee_purchase_requisition.material_category_ra_group')
        orders = self.filtered(lambda o: o.state == 'revenue_assurance')
        # Standard confirmation only handles draft/sent orders
        orders.write({'state': 'draft'})
        return orders.with_context(validate_analytic=True).button_confirm()
