from odoo import fields, models

HR_GROUP = 'bxi_local_conveyance.group_conveyance_hr'
FINANCE_GROUP = 'bxi_local_conveyance.group_conveyance_finance'
ADMIN_GROUP = 'bxi_local_conveyance.group_conveyance_admin'

ROLE_GROUPS = {'finance': FINANCE_GROUP, 'hr': HR_GROUP}


class BxiConveyanceApprovalLine(models.Model):
    """One approval step of a conveyance claim: the Reporting Manager, then Finance, then HR."""
    _name = 'bxi.conveyance.approval.line'
    _description = 'Local Conveyance Approval'
    _order = 'expense_id, sequence, id'

    expense_id = fields.Many2one('hr.expense', string='Claim', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection(
        [('rm', 'Reporting Manager'), ('finance', 'Finance'), ('hr', 'HR')], string='Role', required=True)
    approver_user_id = fields.Many2one(
        'res.users', string='Approver', help="When empty, any member of the role's group can approve.")
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
        group = ROLE_GROUPS.get(self.role)
        return bool(group) and user.has_group(group)

    def _get_candidate_users(self):
        """The users who can approve the step: its approver, or the internal users of the role's group in the
        company of the claim."""
        self.ensure_one()
        if self.approver_user_id or self.role not in ROLE_GROUPS:
            return self.approver_user_id
        company = self.expense_id.sudo().company_id
        return self.env.ref(ROLE_GROUPS[self.role]).sudo().all_user_ids.filtered(
            lambda user: company in user.company_ids and not user.share)
