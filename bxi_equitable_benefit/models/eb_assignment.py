from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .eb_rate import DEPLOYMENT, WORK_CATEGORY


class BxiEbAssignment(models.Model):
    """A period during which an employee followed one work pattern."""
    _name = 'bxi.eb.assignment'
    _description = 'Equitable Benefit Work Pattern Assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', required=True, index=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    manager_id = fields.Many2one(related='employee_id.parent_id', store=True, string='Manager')
    date_from = fields.Date(string='From', required=True, tracking=True)
    date_to = fields.Date(string='To', tracking=True, help="Leave empty while the pattern is ongoing.")
    work_category = fields.Selection(WORK_CATEGORY, required=True, default='client', tracking=True)
    deployment = fields.Selection(DEPLOYMENT, required=True, default='offshore', tracking=True)
    work_pattern_id = fields.Many2one('bxi.eb.work.pattern', required=True, ondelete='restrict', tracking=True)
    client_name = fields.Char(string='Client', tracking=True)
    project_reference = fields.Char(string='Project / Business Objective', tracking=True)
    justification = fields.Text(string='Client / Project Requirement')
    requirement_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_eb_assignment_attachment_rel', 'assignment_id', 'attachment_id',
        string='Requirement Documents',
        help="Documented client or project requirement for this work pattern.")
    rate_percent = fields.Float(
        string='Current Rate (%)', digits=(16, 4), compute='_compute_rate_percent',
        help="Rate valid on the start date. Payouts use the rate valid on each day.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Date(readonly=True, copy=False)
    rejection_reason = fields.Text(copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.eb.assignment') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group('bxi_equitable_benefit.group_eb_revenue_assurance') \
                and not self.env.su and any(rec.state != 'draft' for rec in self):
            raise UserError(_("Only draft work pattern assignments can be modified."))
        return super().write(vals)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(_("Only draft or cancelled assignments can be deleted."))
        return super().unlink()

    @api.depends('work_pattern_id', 'work_category', 'deployment', 'date_from', 'company_id')
    def _compute_rate_percent(self):
        Rate = self.env['bxi.eb.rate'].sudo()
        for rec in self:
            rate = Rate
            if rec.work_pattern_id and rec.date_from:
                rate = Rate._find_rate(rec.work_pattern_id, rec.work_category, rec.deployment,
                                       rec.date_from, rec.company_id or self.env.company)
            rec.rate_percent = rate.rate_percent

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_("The end date cannot be before the start date."))

    @api.constrains('employee_id', 'date_from', 'date_to', 'state')
    def _check_overlap(self):
        for rec in self.filtered(lambda r: r.state in ('submitted', 'approved')):
            domain = [
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('state', 'in', ('submitted', 'approved')),
                '|', ('date_to', '=', False), ('date_to', '>=', rec.date_from),
            ]
            if rec.date_to:
                domain.append(('date_from', '<=', rec.date_to))
            if self.search_count(domain, limit=1):
                raise ValidationError(_(
                    "%(employee)s already has a work pattern assignment overlapping this period.",
                    employee=rec.employee_id.name))

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft assignments can be submitted."))
            rate = self.env['bxi.eb.rate'].sudo()._find_rate(
                rec.work_pattern_id, rec.work_category, rec.deployment, rec.date_from, rec.company_id)
            if not rate:
                raise UserError(_(
                    "No benefit rate is configured for %(pattern)s / %(category)s / %(deployment)s. "
                    "Ask the Equitable Benefit administrator to update the rate matrix.",
                    pattern=rec.work_pattern_id.name,
                    category=dict(WORK_CATEGORY)[rec.work_category],
                    deployment=dict(DEPLOYMENT)[rec.deployment]))
            if rec.work_category == 'client' and not rec.requirement_attachment_ids and not rec.justification:
                raise UserError(_("Client aligned work patterns must be supported by a documented "
                                  "client or project requirement."))
        self.sudo().write({'state': 'submitted'})

    def action_approve(self):
        self._check_reviewer()
        if any(rec.state != 'submitted' for rec in self):
            raise UserError(_("Only submitted assignments can be approved."))
        self.write({
            'state': 'approved',
            'approved_by_id': self.env.user.id,
            'approved_date': fields.Date.context_today(self),
        })

    def action_reject(self):
        self._check_reviewer()
        if any(rec.state != 'submitted' for rec in self):
            raise UserError(_("Only submitted assignments can be rejected."))
        self.write({'state': 'rejected'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'approved':
                rec._check_reviewer()
        self.sudo().write({'state': 'cancelled'})

    def action_reset_draft(self):
        if any(rec.state not in ('rejected', 'cancelled', 'submitted') for rec in self):
            raise UserError(_("Only submitted, rejected or cancelled assignments can be reset to draft."))
        self.sudo().write({'state': 'draft', 'approved_by_id': False, 'approved_date': False})

    def _check_reviewer(self):
        if not self.env.user.has_group('bxi_equitable_benefit.group_eb_revenue_assurance'):
            raise UserError(_("Only Revenue Assurance can approve or reject work pattern assignments."))
