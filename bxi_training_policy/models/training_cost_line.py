from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .training_mixin import FINANCE_GROUP, HR_GROUP

# The actual amount of company-paid costs is recorded by HR or Finance after the training.
ACTUAL_FIELDS = {'actual_amount', 'vendor_bill_id'}


class BxiTrainingCostLine(models.Model):
    """One component of the consolidated cost of a training (Training Policy, clause 1)."""
    _name = 'bxi.training.cost.line'
    _description = 'Training Cost'
    _order = 'request_id, sequence, id'

    request_id = fields.Many2one('bxi.training.request', string='Training', required=True, ondelete='cascade',
                                 index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='request_id.company_id', store=True)
    currency_id = fields.Many2one(related='request_id.currency_id')
    category = fields.Selection(
        [
            ('fee', 'Training Fee'),
            ('lodging', 'Boarding & Lodging'),
            ('material', 'Training Material'),
            ('travel', 'Travel'),
            ('other', 'Other'),
        ],
        string='Category', required=True, default='fee',
    )
    description = fields.Char(string='Description')
    paid_by = fields.Selection(
        [('company', 'Company (vendor / booking)'), ('employee', 'Employee (claimed)')],
        string='Paid By', required=True, default='employee',
        help="Company: paid directly to the provider, hotel or travel desk. Employee: paid by the employee "
             "from the advance and claimed after the training.",
    )
    estimated_amount = fields.Monetary(string='Estimated', currency_field='currency_id')
    actual_amount = fields.Monetary(
        string='Actual (Company Paid)', currency_field='currency_id',
        help="Amount actually paid by the company. Employee-paid costs come from the claim lines.",
    )
    vendor_bill_id = fields.Many2one(
        'account.move', string='Vendor Bill', domain="[('move_type', '=', 'in_invoice')]",
        help="Bill of the provider when the company paid the cost directly.",
    )

    _estimated_positive = models.Constraint(
        'CHECK(estimated_amount >= 0 AND actual_amount >= 0)', 'Training costs cannot be negative.',
    )

    @api.onchange('vendor_bill_id')
    def _onchange_vendor_bill_id(self):
        for line in self.filtered('vendor_bill_id'):
            line.actual_amount = line.vendor_bill_id.amount_total_signed and abs(line.vendor_bill_id.amount_total_signed)
            line.paid_by = 'company'

    def _check_can_edit(self, vals_keys=None):
        if self.env.su:
            return
        user = self.env.user
        is_hr = user.has_group(HR_GROUP)
        is_finance = user.has_group(FINANCE_GROUP)
        for line in self:
            request = line.request_id
            if vals_keys is not None and vals_keys <= ACTUAL_FIELDS and (is_hr or is_finance):
                continue
            if is_hr and request.state not in ('settled', 'refused', 'cancelled'):
                continue
            if request.state == 'draft' and request._user_can_nominate(user):
                continue
            raise AccessError(self.env._("The cost of %(training)s can no longer be modified.",
                                         training=request.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_can_edit()
        lines.request_id._on_cost_changed()
        return lines

    def write(self, vals):
        self._check_can_edit(set(vals.keys()))
        if 'actual_amount' in vals and any(line.paid_by == 'employee' for line in self) and vals['actual_amount']:
            raise UserError(self.env._("Employee-paid costs are taken from the claim lines."))
        res = super().write(vals)
        if 'estimated_amount' in vals:
            self.request_id._on_cost_changed()
        return res

    def unlink(self):
        self._check_can_edit()
        requests = self.request_id
        res = super().unlink()
        requests._on_cost_changed()
        return res
