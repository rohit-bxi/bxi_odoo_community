# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BxiShiftRequest(models.Model):
    _name = 'bxi.shift.request'
    _description = 'Shift Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    # ─────────────────────────────────────────────
    #  Basic Info
    # ─────────────────────────────────────────────
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True,
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda self: self._default_employee_id(),
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        tracking=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        tracking=True,
    )

    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        readonly=True,
        tracking=True,
    )

    # ─────────────────────────────────────────────
    #  Shift / Schedule Details
    # ─────────────────────────────────────────────
    date_from = fields.Date(
        string='From Date',
        required=True,
        tracking=True,
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        tracking=True,
    )
    requested_shift_id = fields.Many2one(
        'resource.calendar',
        string='Requested Working Schedule',
        required=True,
        tracking=True,
    )
    original_shift_id = fields.Many2one(
        'resource.calendar',
        string='Original Working Schedule',
        readonly=True,
        copy=False,
        help='Captured automatically from the employee master when the schedule is applied.',
    )
    reason = fields.Text(
        string='Reason / Description',
        required=True,
        tracking=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'bxi_shift_request_attachment_rel',
        'shift_request_id',
        'attachment_id',
        string='Attachments',
    )

    # ─────────────────────────────────────────────
    #  Workflow State
    # ─────────────────────────────────────────────
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('manager_approval', 'Manager Approval'),
            ('hr_approval', 'HR Approval'),
            ('approved', 'Approved'),
            ('refused', 'Refused'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )

    # ─────────────────────────────────────────────
    #  Manager Approval
    # ─────────────────────────────────────────────
    manager_remark = fields.Text(
        string='Manager Remark',
        tracking=True,
    )
    manager_approved_by = fields.Many2one(
        'hr.employee',
        string='Manager Approved By',
        readonly=True,
        copy=False,
        tracking=True,
    )
    manager_approved_date = fields.Datetime(
        string='Manager Approved On',
        readonly=True,
        copy=False,
        tracking=True,
    )

    # ─────────────────────────────────────────────
    #  HR Approval
    # ─────────────────────────────────────────────
    hr_remark = fields.Text(
        string='HR Remark',
        tracking=True,
    )
    hr_approved_by = fields.Many2one(
        'hr.employee',
        string='HR Approved By',
        readonly=True,
        copy=False,
        tracking=True,
    )
    hr_approved_date = fields.Datetime(
        string='HR Approved On',
        readonly=True,
        copy=False,
        tracking=True,
    )

    # ─────────────────────────────────────────────
    #  Refusal
    # ─────────────────────────────────────────────
    refused_by = fields.Many2one(
        'hr.employee',
        string='Refused By',
        readonly=True,
        copy=False,
        tracking=True,
    )
    refused_date = fields.Datetime(
        string='Refused On',
        readonly=True,
        copy=False,
        tracking=True,
    )

    # ─────────────────────────────────────────────
    #  Schedule Application Tracking
    # ─────────────────────────────────────────────
    schedule_applied = fields.Boolean(
        string='Schedule Applied',
        default=False,
        copy=False,
        tracking=True,
        help='Set to True once the requested shift is applied to the employee master.',
    )
    schedule_reverted = fields.Boolean(
        string='Schedule Reverted',
        default=False,
        copy=False,
        tracking=True,
        help='Set to True once the original shift is restored after date_to.',
    )

    # ─────────────────────────────────────────────
    #  Computed Fields
    # ─────────────────────────────────────────────
    can_manager_approve = fields.Boolean(
        compute='_compute_can_manager_approve',
        string='Can Manager Approve',
    )
    can_hr_approve = fields.Boolean(
        compute='_compute_can_hr_approve',
        string='Can HR Approve',
    )

    # ─────────────────────────────────────────────
    #  Defaults
    # ─────────────────────────────────────────────
    @api.model
    def _default_employee_id(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)], limit=1
        )
        return employee.id if employee else False

    # ─────────────────────────────────────────────
    #  Onchange
    # ─────────────────────────────────────────────
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                rec.manager_id = rec.employee_id.parent_id or False
                rec.department_id = rec.employee_id.department_id or False
                rec.company_id = rec.employee_id.company_id or self.env.company

    # ─────────────────────────────────────────────
    #  Computed: Can Approve
    # ─────────────────────────────────────────────
    def _compute_can_manager_approve(self):
        current_employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)], limit=1
        )
        is_hr_admin = self.env.user.has_group('bxi_shift_management.group_shift_hr')
        for rec in self:
            is_direct_manager = bool(
                current_employee
                and rec.employee_id
                and rec.employee_id.parent_id
                and rec.employee_id.parent_id.id == current_employee.id
            )
            rec.can_manager_approve = is_direct_manager or is_hr_admin

    def _compute_can_hr_approve(self):
        is_hr = self.env.user.has_group('bxi_shift_management.group_shift_hr')
        for rec in self:
            rec.can_hr_approve = is_hr

    # ─────────────────────────────────────────────
    #  Constraints
    # ─────────────────────────────────────────────
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise UserError(_('To Date cannot be earlier than From Date.'))

    @api.constrains('requested_shift_id', 'employee_id')
    def _check_different_shift(self):
        for rec in self:
            if (
                rec.requested_shift_id
                and rec.employee_id
                and rec.employee_id.resource_calendar_id
                and rec.requested_shift_id.id == rec.employee_id.resource_calendar_id.id
                and rec.state == 'draft'
            ):
                raise UserError(
                    _('The requested working schedule is the same as the employee\'s current schedule.')
                )

    # ─────────────────────────────────────────────
    #  CRUD Override
    # ─────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('bxi.shift.request')
                    or 'BXI/SR/0001'
                )
        return super().create(vals_list)

    # ─────────────────────────────────────────────
    #  Workflow Actions
    # ─────────────────────────────────────────────
    def action_submit(self):
        """Employee submits the request → moves to Manager Approval."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            rec.write({'state': 'manager_approval'})
            rec.message_post(body=_('Shift request submitted for manager approval.'))

    def action_manager_approve(self):
        """Direct Manager approves → moves to HR Approval."""
        for rec in self:
            if rec.state != 'manager_approval':
                raise UserError(_('This action is only available in Manager Approval state.'))
            if not rec.can_manager_approve:
                raise UserError(
                    _('Only the direct manager of the employee can approve at this stage.')
                )
            rec.write({
                'state': 'hr_approval',
                'manager_approved_by': self.env.user.employee_id.id or False,
                'manager_approved_date': fields.Datetime.now(),
            })
            rec.message_post(
                body=_('Approved by manager %s. Awaiting HR approval.') % (
                    self.env.user.name
                )
            )

    def action_hr_approve(self):
        """HR approves → Final Approved state."""
        for rec in self:
            if rec.state != 'hr_approval':
                raise UserError(_('This action is only available in HR Approval state.'))
            if not rec.can_hr_approve:
                raise UserError(_('Only HR users can approve at this stage.'))
            rec.write({
                'state': 'approved',
                'hr_approved_by': self.env.user.employee_id.id or False,
                'hr_approved_date': fields.Datetime.now(),
            })
            rec.message_post(
                body=_('Approved by HR %s. The shift will be applied on %s.') % (
                    self.env.user.name, rec.date_from
                )
            )

    def action_refuse(self):
        """Refuse at any approval stage."""
        for rec in self:
            if rec.state not in ('manager_approval', 'hr_approval'):
                raise UserError(_('Only requests pending approval can be refused.'))
            # Check permission
            if rec.state == 'manager_approval' and not rec.can_manager_approve:
                raise UserError(_('Only the direct manager can refuse at this stage.'))
            if rec.state == 'hr_approval' and not rec.can_hr_approve:
                raise UserError(_('Only HR users can refuse at this stage.'))
            rec.write({
                'state': 'refused',
                'refused_by': self.env.user.employee_id.id or False,
                'refused_date': fields.Datetime.now(),
            })
            rec.message_post(
                body=_('Request refused by %s.') % self.env.user.name
            )

    def action_cancel(self):
        """Employee cancels a draft or submitted request."""
        for rec in self:
            if rec.state not in ('draft', 'manager_approval'):
                raise UserError(
                    _('Only draft or pending-manager-approval requests can be cancelled.')
                )
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Request cancelled by %s.') % self.env.user.name)

    def action_reset_to_draft(self):
        """Admin-only reset to draft."""
        if not (
            self.env.user.has_group('bxi_shift_management.group_shift_hr')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only HR Admin can reset a request to draft.'))
        self.write({
            'state': 'draft',
            'manager_approved_by': False,
            'manager_approved_date': False,
            'manager_remark': False,
            'hr_approved_by': False,
            'hr_approved_date': False,
            'hr_remark': False,
            'refused_by': False,
            'refused_date': False,
            'schedule_applied': False,
            'schedule_reverted': False,
            'original_shift_id': False,
        })

    # ─────────────────────────────────────────────
    #  Scheduled Action Methods
    # ─────────────────────────────────────────────
    @api.model
    def _cron_apply_approved_shifts(self):
        """Apply the requested schedule to the employee on date_from."""
        today = fields.Date.today()
        records = self.search([
            ('state', '=', 'approved'),
            ('date_from', '<=', today),
            ('schedule_applied', '=', False),
        ])
        for rec in records:
            if rec.employee_id and rec.requested_shift_id:
                # Save the original schedule before overwriting
                rec.original_shift_id = rec.employee_id.resource_calendar_id.id or False
                rec.employee_id.resource_calendar_id = rec.requested_shift_id.id
                rec.schedule_applied = True
                rec.message_post(
                    body=_('Working schedule changed to "%s" effective %s.') % (
                        rec.requested_shift_id.name, today
                    )
                )

    @api.model
    def _cron_revert_expired_shifts(self):
        """Revert the employee's schedule back to the original after date_to."""
        today = fields.Date.today()
        records = self.search([
            ('state', '=', 'approved'),
            ('date_to', '<', today),
            ('schedule_applied', '=', True),
            ('schedule_reverted', '=', False),
        ])
        for rec in records:
            if rec.employee_id and rec.original_shift_id:
                rec.employee_id.resource_calendar_id = rec.original_shift_id.id
                rec.schedule_reverted = True
                rec.message_post(
                    body=_('Working schedule reverted to original "%s" after shift period ended.') % (
                        rec.original_shift_id.name
                    )
                )
            elif rec.employee_id and not rec.original_shift_id:
                # No original captured — just mark reverted to avoid re-processing
                rec.schedule_reverted = True
                rec.message_post(
                    body=_('Shift period ended. Original schedule was not captured; please update manually.')
                )
