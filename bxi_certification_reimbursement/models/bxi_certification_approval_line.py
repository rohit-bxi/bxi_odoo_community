from odoo import models, fields


class BxiCertificationApprovalLine(models.Model):
    _name = 'bxi.certification.approval.line'
    _description = 'Certification Claim Approval'
    _order = 'request_id, sequence, id'

    request_id = fields.Many2one(
        'bxi.certification.request',
        string='Certification Request',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    role = fields.Selection(
        [
            ('skip_manager', "Manager's Manager (late claim)"),
            ('band4', 'Band 4 Head'),
            ('band3', 'Band 3 Head'),
            ('band2', 'Band 2 Head'),
            ('academy', 'LoB Academy Head'),
        ],
        string='Role',
        required=True,
    )
    approver_id = fields.Many2one('hr.employee', string='Approver', required=True)
    approver_user_id = fields.Many2one(
        'res.users',
        related='approver_id.user_id',
        string='Approver User',
        store=True,
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('refused', 'Refused'),
        ],
        string='Status',
        default='pending',
        required=True,
    )
    date = fields.Datetime(string='Date', readonly=True)
    done_by_user_id = fields.Many2one('res.users', string='Done By', readonly=True)
    comment = fields.Text(string='Comment')
