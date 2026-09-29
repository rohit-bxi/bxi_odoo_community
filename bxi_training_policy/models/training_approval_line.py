from odoo import fields, models

from .training_mixin import ES_GROUP, HR_GROUP

ROLE_GROUPS = {'hr': HR_GROUP, 'es': ES_GROUP}


class BxiTrainingApprovalLine(models.Model):
    """One step of the claim approval: Reporting Manager, HR, then Employee Services."""
    _name = 'bxi.training.approval.line'
    _description = 'Training Claim Approval'
    _order = 'request_id, sequence, id'

    request_id = fields.Many2one('bxi.training.request', string='Training', required=True, ondelete='cascade',
                                 index=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection(
        [('rm', 'Reporting Manager'), ('hr', 'HR'), ('es', 'Employee Services')],
        string='Role', required=True,
    )
    approver_user_id = fields.Many2one(
        'res.users', string='Approver',
        help="When empty, any member of the role's group can approve.",
    )
    state = fields.Selection(
        [('pending', 'Pending'), ('approved', 'Approved'), ('refused', 'Refused')],
        string='Status', default='pending', required=True,
    )
    date = fields.Datetime(string='Date', readonly=True)
    done_by_user_id = fields.Many2one('res.users', string='Done By', readonly=True)
    comment = fields.Text(string='Comment')

    def _get_role_group(self):
        self.ensure_one()
        return ROLE_GROUPS.get(self.role)

    def _is_approver(self, user):
        self.ensure_one()
        if self.approver_user_id:
            return self.approver_user_id == user
        group = self._get_role_group()
        return bool(group) and user.has_group(group) and self.request_id.sudo().employee_id.user_id != user
