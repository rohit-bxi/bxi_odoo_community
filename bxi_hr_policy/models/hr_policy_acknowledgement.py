# -*- coding: utf-8 -*-
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError
from odoo.http import request

OPEN_STATES = ('pending', 'overdue')


class HrPolicyAcknowledgement(models.Model):
    _name = 'hr.policy.acknowledgement'
    _description = 'Policy Acknowledgement'
    _order = 'state_sequence, due_date, id desc'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True, readonly=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, string='User')
    manager_id = fields.Many2one(related='employee_id.parent_id', store=True, string='Manager')
    department_id = fields.Many2one(related='employee_id.department_id', store=True, string='Department')
    company_id = fields.Many2one(related='employee_id.company_id', store=True, string='Company')
    version_id = fields.Many2one(
        'hr.company.policy.version',
        string='Policy Version',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    policy_id = fields.Many2one(related='version_id.policy_id', store=True, string='Policy')
    version_no = fields.Integer(related='version_id.version_no', string='Version')
    is_current_version = fields.Boolean(compute='_compute_is_current_version', search='_search_is_current_version')
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('overdue', 'Overdue'),
            ('acknowledged', 'Acknowledged'),
            ('waived', 'Waived'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='pending',
        required=True,
        readonly=True,
        index=True,
    )
    state_sequence = fields.Integer(compute='_compute_state_sequence', store=True)
    requested_date = fields.Date(string='Requested On', readonly=True)
    due_date = fields.Date(string='Due Date', readonly=True)
    document_opened = fields.Boolean(string='Document Opened', readonly=True)
    opened_date = fields.Datetime(string='Opened On', readonly=True)
    acknowledged_date = fields.Datetime(string='Acknowledged On', readonly=True)
    ip_address = fields.Char(string='IP Address', readonly=True)
    user_agent = fields.Char(string='Browser', readonly=True)
    channel = fields.Selection([('backend', 'Odoo'), ('portal', 'Portal')], string='Channel', readonly=True)
    statement = fields.Text(string='Statement', readonly=True)
    last_reminder_date = fields.Date(string='Last Reminder', readonly=True)
    escalated_manager = fields.Boolean(string='Escalated to Manager', readonly=True)
    escalated_hr = fields.Boolean(string='Escalated to HR', readonly=True)
    waive_reason = fields.Text(string='Waiver Reason')
    waived_by_id = fields.Many2one('res.users', string='Waived By', readonly=True)
    preview_html = fields.Html(compute='_compute_preview_html', sanitize=False)

    _employee_version_uniq = models.Constraint(
        'unique(employee_id, version_id)',
        'The employee already has an acknowledgement for this policy version.',
    )

    # ── Computes ─────────────────────────────────────────────────────────
    @api.depends('state')
    def _compute_state_sequence(self):
        order = {'overdue': 0, 'pending': 1, 'acknowledged': 2, 'waived': 3, 'cancelled': 4}
        for ack in self:
            ack.state_sequence = order.get(ack.state, 9)

    @api.depends('version_id.state')
    def _compute_is_current_version(self):
        for ack in self:
            ack.is_current_version = ack.version_id.state == 'published'

    def _search_is_current_version(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        positive = (operator == '=') == value
        return [('version_id.state', '=' if positive else '!=', 'published')]

    @api.depends('version_id')
    def _compute_preview_html(self):
        Policy = self.env['hr.company.policy']
        for ack in self:
            version = ack.sudo().version_id
            ack.preview_html = Policy._build_preview_html(
                f'/bxi_hr_policy/preview/version/{version.id}', version.display_name,
                version.filename, version.mimetype,
            ) if version.document else False

    def _compute_display_name(self):
        for ack in self:
            ack.display_name = f"{ack.sudo().version_id.display_name} - {ack.sudo().employee_id.name}"

    # ── Protection ───────────────────────────────────────────────────────
    def write(self, vals):
        if not self.env.su:
            if vals.keys() - {'waive_reason'}:
                raise AccessError(self.env._("Acknowledgements are updated by the system only."))
            if any(ack.state not in OPEN_STATES for ack in self):
                raise UserError(self.env._("Closed acknowledgements cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_never_acknowledged(self):
        if any(ack.state in ('acknowledged', 'waived') for ack in self):
            raise UserError(self.env._("Acknowledgements are kept as evidence and cannot be deleted."))

    # ── Actions ──────────────────────────────────────────────────────────
    def _mark_opened(self):
        to_mark = self.filtered(lambda a: a.state in OPEN_STATES and not a.document_opened)
        to_mark.sudo().write({'document_opened': True, 'opened_date': fields.Datetime.now()})

    def _check_can_acknowledge(self):
        for ack in self:
            if ack.state not in OPEN_STATES:
                raise UserError(self.env._("This policy has already been handled."))
            if not self.env.su and ack.user_id != self.env.user:
                raise AccessError(self.env._("You can only acknowledge policies assigned to you."))
            if not ack.document_opened:
                raise UserError(self.env._("Please open and read the policy document before acknowledging it."))

    def _do_acknowledge(self, channel, ip_address=False, user_agent=False):
        self._check_can_acknowledge()
        self.sudo().write({
            'state': 'acknowledged',
            'acknowledged_date': fields.Datetime.now(),
            'channel': channel,
            'ip_address': ip_address,
            'user_agent': (user_agent or '')[:255] or False,
        })
        self._close_activities()

    def action_acknowledge(self):
        ip_address = user_agent = False
        if request:
            ip_address = request.httprequest.remote_addr
            user_agent = request.httprequest.user_agent.string
        self._do_acknowledge('backend', ip_address, user_agent)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_waive(self):
        if not (self.env.su or self.env.user.has_group('hr.group_hr_manager')
                or self.env.user.has_group('bxi_hr_policy.group_policy_cpo')):
            raise AccessError(self.env._("Only HR managers can waive acknowledgements."))
        for ack in self:
            if ack.state not in OPEN_STATES:
                raise UserError(self.env._("Only open acknowledgements can be waived."))
            if not ack.waive_reason:
                raise UserError(self.env._("Enter the reason for waiving the acknowledgement."))
        self.sudo().write({'state': 'waived', 'waived_by_id': self.env.user.id})
        self._close_activities()

    def action_send_reminder(self):
        self._send_grouped_mails({ack.user_id: [ack] for ack in self.filtered(lambda a: a.state in OPEN_STATES)},
                                 'reminder')
        self.sudo().write({'last_reminder_date': fields.Date.context_today(self)})

    def _cancel(self):
        self.sudo().write({'state': 'cancelled'})
        self._close_activities()

    def _close_activities(self):
        """Remove the acknowledgement to-dos from the employees' activity list."""
        for ack in self.sudo():
            ack.version_id.activity_ids.filtered(
                lambda act: act.user_id == ack.user_id and act.summary == ack._activity_summary()
            ).unlink()

    def _activity_summary(self):
        return self.env._("Acknowledge %(policy)s", policy=self.sudo().version_id.display_name)

    # ── Notifications ────────────────────────────────────────────────────
    def _notify_request(self):
        """Ask employees to acknowledge: to-do for Odoo users, one email for everyone."""
        for ack in self.sudo():
            if ack.user_id and not ack.user_id.share:
                ack.version_id.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=ack.user_id.id,
                    date_deadline=ack.due_date,
                    summary=ack._activity_summary(),
                )
        grouped = defaultdict(list)
        for ack in self.sudo():
            grouped[ack.user_id].append(ack)
        self._send_grouped_mails(grouped, 'request')

    def _send_grouped_mails(self, acks_by_user, kind):
        """Send one email per recipient listing all the acknowledgements concerned."""
        subjects = {
            'request': self.env._("Please acknowledge company policies"),
            'reminder': self.env._("Reminder: company policies waiting for your acknowledgement"),
            'manager': self.env._("Your team members have not acknowledged company policies"),
            'hr': self.env._("Employees have not acknowledged company policies"),
        }
        intros = {
            'request': self.env._("The following company policies need your acknowledgement:"),
            'reminder': self.env._("The following company policies are still waiting for your acknowledgement:"),
            'manager': self.env._("These members of your team have not acknowledged the following policies:"),
            'hr': self.env._("These employees have not acknowledged the following policies:"),
        }
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        mails = self.env['mail.mail'].sudo()
        for user, acks in acks_by_user.items():
            if not user or not user.partner_id.email:
                continue
            rows = Markup('').join(
                Markup('<li>{employee}{policy} (due {due})</li>').format(
                    employee=Markup('<b>{}</b>: ').format(ack.employee_id.name) if kind in ('manager', 'hr') else '',
                    policy=ack.version_id.display_name,
                    due=ack.due_date or '',
                ) for ack in acks
            )
            link = f"{base_url}/my/policies" if kind in ('request', 'reminder') else f"{base_url}/odoo"
            body = Markup(
                '<p>{greeting}</p><p>{intro}</p><ul>{rows}</ul><p><a href="{link}">{cta}</a></p>'
            ).format(
                greeting=self.env._("Dear %(name)s,", name=user.name),
                intro=intros[kind],
                rows=rows,
                link=link,
                cta=self.env._("Open my policies") if kind in ('request', 'reminder') else self.env._("Open Odoo"),
            )
            mails |= mails.create({
                'subject': subjects[kind],
                'body_html': body,
                'recipient_ids': [(4, user.partner_id.id)],
                'auto_delete': True,
            })
        return mails

    # ── Scheduled job ────────────────────────────────────────────────────
    @api.model
    def _cron_process_acknowledgements(self):
        """Mark overdue, send reminders and escalate, grouping emails per recipient."""
        today = fields.Date.context_today(self)
        acks = self.sudo().search([('state', 'in', OPEN_STATES)])
        acks.filtered(lambda a: a.state == 'pending' and a.due_date and a.due_date < today).write(
            {'state': 'overdue'})

        reminders, managers, hr = defaultdict(list), defaultdict(list), defaultdict(list)
        reminded = escalated_manager = escalated_hr = self.browse()
        for ack in acks:
            policy = ack.policy_id
            interval = policy.reminder_interval_days
            last = ack.last_reminder_date or ack.requested_date
            if interval and last and (today - last).days >= interval:
                reminders[ack.user_id].append(ack)
                reminded |= ack
            if ack.state != 'overdue':
                continue
            days_overdue = (today - ack.due_date).days
            manager_user = ack.employee_id.parent_id.user_id
            if (policy.escalate_manager_after_days and not ack.escalated_manager
                    and days_overdue >= policy.escalate_manager_after_days and manager_user):
                managers[manager_user].append(ack)
                escalated_manager |= ack
            if (policy.escalate_hr_after_days and not ack.escalated_hr
                    and days_overdue >= policy.escalate_hr_after_days):
                for hr_user in ack._get_hr_managers():
                    hr[hr_user].append(ack)
                escalated_hr |= ack

        self._send_grouped_mails(reminders, 'reminder')
        self._send_grouped_mails(managers, 'manager')
        self._send_grouped_mails(hr, 'hr')
        reminded.write({'last_reminder_date': today})
        escalated_manager.write({'escalated_manager': True})
        escalated_hr.write({'escalated_hr': True})

    def _get_hr_managers(self):
        self.ensure_one()
        group = self.env.ref('hr.group_hr_manager')
        return group.sudo().user_ids.filtered(
            lambda u: not u.share and self.company_id in u.company_ids and u.partner_id.email)

    # ── Employee changes ─────────────────────────────────────────────────
    @api.model
    def _sync_employees(self, employees):
        """Ask employees for every published policy that applies to them."""
        versions = self.env['hr.company.policy.version'].sudo().search([
            ('state', '=', 'published'),
            ('policy_id.requires_acknowledgement', '=', True),
            ('policy_id.active', '=', True),
        ])
        for version in versions:
            applicable = employees.filtered(lambda e: e.user_id and version.policy_id._applies_to(e))
            if applicable:
                version._create_acknowledgements(applicable)

    # ── Reports ──────────────────────────────────────────────────────────
    def action_print_certificate(self):
        return self.env.ref('bxi_hr_policy.action_report_policy_acknowledgement').report_action(self)
