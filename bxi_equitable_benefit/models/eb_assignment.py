from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .eb_rate import DEPLOYMENT, WORK_CATEGORY

# Set by the workflow actions only, never directly by employees or managers.
WORKFLOW_FIELDS = {'state', 'approved_by_id', 'approved_date'}


class BxiEbAssignment(models.Model):
    """A period during which an employee followed one work pattern."""
    _name = 'bxi.eb.assignment'
    _description = 'Equitable Benefit Work Pattern Assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'bxi.eb.notify.mixin']
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
    project_ids = fields.Many2many(
        'project.project', 'bxi_eb_assignment_project_rel', 'assignment_id', 'project_id',
        string='Project / Business Objective',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    client_id = fields.Many2one(
        'res.partner', string='Client', compute='_compute_client_id', store=True, tracking=True,
        help="Customer of the projects.")
    justification = fields.Text(string='Client / Project Requirement')
    requirement_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_eb_assignment_attachment_rel', 'assignment_id', 'attachment_id',
        string='Requirement Documents',
        help="Documented client or project requirement for this work pattern.")
    rate_percent = fields.Float(
        string='Current Rate (%)', digits=(16, 4), compute='_compute_rate_percent',
        help="Rate valid on the start date. Payouts use the rate valid on each day.")
    component_a_missing = fields.Boolean(
        string='Component A Missing', compute='_compute_component_a_missing',
        search='_search_component_a_missing',
        groups='hr.group_hr_user,bxi_equitable_benefit.group_eb_revenue_assurance,bxi_equitable_benefit.group_eb_finance',
        help="The employee's contract has no Annualized Component A for this period, so it would pay nothing.")
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
            if not self._is_reviewer() and (vals.get('state', 'draft') != 'draft'
                                            or vals.get('approved_by_id') or vals.get('approved_date')):
                raise UserError(_("Work pattern assignments are created as drafts and approved by "
                                  "Revenue Assurance."))
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.eb.assignment') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self._is_reviewer():
            if WORKFLOW_FIELDS & set(vals):
                raise UserError(_("Use the Submit, Cancel and Reset to Draft buttons to change the status "
                                  "of a work pattern assignment."))
            if any(rec.state != 'draft' for rec in self):
                raise UserError(_("Only draft work pattern assignments can be modified."))
        return super().write(vals)

    def _is_reviewer(self):
        """Superuser (the workflow actions write as sudo) or Revenue Assurance."""
        return self.env.su or self.env.user.has_group('bxi_equitable_benefit.group_eb_revenue_assurance')

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

    @api.depends('project_ids.partner_id')
    def _compute_client_id(self):
        for rec in self:
            rec.client_id = rec.project_ids.partner_id[:1]

    @api.depends('employee_id', 'date_from', 'date_to', 'rate_percent')
    def _compute_component_a_missing(self):
        today = fields.Date.context_today(self)
        for rec in self:
            missing = False
            if rec.employee_id and rec.date_from and rec.rate_percent:
                employee = rec.employee_id.sudo()
                days = {rec.date_from, max(rec.date_from, min(rec.date_to or today, today))}
                missing = any(not employee._get_version(day).eb_annual_component_a for day in days)
            rec.component_a_missing = missing

    def _search_component_a_missing(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        candidates = self.search([('state', 'in', ('submitted', 'approved'))])
        missing = candidates.filtered('component_a_missing')
        return [('id', 'in' if (operator == '=') == value else 'not in', missing.ids)]

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
            others = self.search(domain)
            if rec.state == 'submitted':
                # A change of pattern: the ongoing assignment is closed when this one is approved.
                others -= rec._superseded_assignments()
            if others:
                raise ValidationError(_(
                    "%(employee)s already has a work pattern assignment overlapping this period.",
                    employee=rec.employee_id.sudo().name))

    def _superseded_assignments(self):
        """Approved open-ended assignments of the employee that started before this one."""
        self.ensure_one()
        return self.search([
            ('id', '!=', self.id),
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'approved'),
            ('date_to', '=', False),
            ('date_from', '<', self.date_from),
        ])

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft assignments can be submitted."))
            suspended_from = (rec.company_id or self.env.company).sudo().eb_suspended_from
            if suspended_from and rec.date_from >= suspended_from:
                raise UserError(_("The Equitable Benefit Policy is suspended from %s.", suspended_from))
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
            if rec.work_category == 'non_client' and rate.rate_percent and not (
                    rec.requirement_attachment_ids or rec.justification or rec.project_ids):
                raise UserError(_("State the project or business objective that requires this work pattern: "
                                  "non-client aligned extended schedules must be documented too."))
        self.sudo().write({'state': 'submitted'})
        for rec in self:
            rec._eb_notify_group(
                'bxi_equitable_benefit.group_eb_revenue_assurance',
                _("Review the work pattern of %s", rec.employee_id.sudo().name))

    def action_approve(self):
        self._check_reviewer()
        if any(rec.state != 'submitted' for rec in self):
            raise UserError(_("Only submitted assignments can be approved."))
        for rec in self.sorted('date_from'):
            previous = rec._superseded_assignments()
            if previous:
                previous.write({'date_to': rec.date_from - timedelta(days=1)})
                for assignment in previous:
                    assignment.message_post(body=_("Closed on %(day)s: superseded by %(new)s.",
                                                   day=assignment.date_to, new=rec.name))
        self.write({
            'state': 'approved',
            'approved_by_id': self.env.user.id,
            'approved_date': fields.Date.context_today(self),
        })
        self._eb_close_activities()
        for rec in self:
            rec._eb_notify_employee(_("Your work pattern %(pattern)s from %(day)s was approved for the "
                                      "Equitable Benefit.", pattern=rec.work_pattern_id.name, day=rec.date_from))

    def action_reject(self):
        self._check_reviewer()
        if any(rec.state != 'submitted' for rec in self):
            raise UserError(_("Only submitted assignments can be rejected."))
        self.write({'state': 'rejected'})
        self._eb_close_activities()
        for rec in self:
            rec._eb_notify_employee(_("Your work pattern %(pattern)s from %(day)s was rejected. %(reason)s",
                                      pattern=rec.work_pattern_id.name, day=rec.date_from,
                                      reason=rec.rejection_reason or ''))

    def action_cancel(self):
        for rec in self:
            if rec.state == 'approved':
                rec._check_reviewer()
        self.sudo().write({'state': 'cancelled'})
        self._eb_close_activities()

    def action_reset_draft(self):
        if any(rec.state not in ('rejected', 'cancelled', 'submitted') for rec in self):
            raise UserError(_("Only submitted, rejected or cancelled assignments can be reset to draft."))
        self.sudo().write({'state': 'draft', 'approved_by_id': False, 'approved_date': False})

    def _check_reviewer(self):
        if not self.env.user.has_group('bxi_equitable_benefit.group_eb_revenue_assurance'):
            raise UserError(_("Only Revenue Assurance can approve or reject work pattern assignments."))
