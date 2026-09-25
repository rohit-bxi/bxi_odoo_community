from datetime import timedelta

from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    deputation_ids = fields.One2many(
        'bxi.deputation', 'employee_id', string='Deputations',
        groups='bxi_international_deputation.group_deputation_officer',
    )
    deputation_count = fields.Integer(
        compute='_compute_deputation_count',
        groups='bxi_international_deputation.group_deputation_officer',
    )
    is_on_deputation = fields.Boolean(
        string='On International Deputation',
        compute='_compute_deputation_status', store=True, compute_sudo=True,
        help='The employee is currently on a host country payroll.',
    )
    deputation_country_id = fields.Many2one(
        'res.country', string='Deputation Country',
        compute='_compute_deputation_status', store=True, compute_sudo=True,
    )

    def _compute_deputation_count(self):
        counts = dict(self.env['bxi.deputation']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for employee in self:
            employee.deputation_count = counts.get(employee, 0)

    @api.depends('deputation_ids.state', 'deputation_ids.host_country_id')
    def _compute_deputation_status(self):
        Deputation = self.env['bxi.deputation'].sudo()
        for employee in self:
            current = Deputation.search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'transferred'),
            ], limit=1) if employee.id else Deputation
            employee.is_on_deputation = bool(current)
            employee.deputation_country_id = current.host_country_id

    def _get_off_home_payroll_days(self, date_from, date_to):
        """Number of days between ``date_from`` and ``date_to`` (inclusive) the
        employee is on a host country payroll instead of the home payroll."""
        self.ensure_one()
        deputations = self.env['bxi.deputation'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', 'in', ('transferred', 'returned')),
            ('home_last_date', '<', date_to),
            '|', ('home_restart_date', '=', False), ('home_restart_date', '>', date_from),
        ])
        off_days = set()
        for deputation in deputations:
            first, last = deputation._off_home_payroll_range()
            start = max(first, date_from)
            end = min(last, date_to) if last else date_to
            current = start
            while current <= end:
                off_days.add(current)
                current += timedelta(days=1)
        return len(off_days)

    def action_open_deputations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_international_deputation.action_bxi_deputation')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action
