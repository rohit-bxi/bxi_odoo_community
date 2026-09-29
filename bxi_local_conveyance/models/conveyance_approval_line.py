from odoo import fields, models

HR_GROUP = 'bxi_local_conveyance.group_conveyance_hr'


class BxiConveyanceApprovalLine(models.Model):
    """One approval step of a conveyance claim: the Reporting Manager, then HR when the policy requires it."""
    _name = 'bxi.conveyance.approval.line'
    _description = 'Local Conveyance Approval'
    _order = 'expense_id, sequence, id'

    expense_id = fields.Many2one('hr.expense', string='Claim', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection([('rm', 'Reporting Manager'), ('hr', 'HR')], string='Role', required=True)
    approver_user_id = fields.Many2one(
        'res.users', string='Approver', help="When empty, any Local Conveyance HR Officer can approve.")
    state = fields.Selection(
        [('pending', 'Pending'), ('approved', 'Approved'), ('refused', 'Refused')],
        string='Status', default='pending', required=True,
    )
    date = fields.Datetime(string='Date', readonly=True)
    done_by_user_id = fields.Many2one('res.users', string='Done By', readonly=True)
    comment = fields.Text(string='Comment')

    def _is_approver(self, user):
        self.ensure_one()
        if self.expense_id.sudo().employee_id.user_id == user:
            return False
        if self.approver_user_id:
            return self.approver_user_id == user
        return self.role == 'hr' and user.has_group(HR_GROUP)
