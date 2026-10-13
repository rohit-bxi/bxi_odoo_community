from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.hr_employee_appraisal import SALARY_LETTER_TYPES

# Offer letter: Flexible Allowance = 70% of Basic, and Component A = (Basic + Flexible) x 12.
FLEXIBLE_RATIO = 0.7


class BxiEbComponentAWizard(models.TransientModel):
    """Propose the Annualized Component A of employees for HR to review before it is saved."""
    _name = 'bxi.eb.component.a.wizard'
    _description = 'Fill Annualized Component A'

    scope = fields.Selection([
        ('assigned', 'Employees with an approved work pattern'),
        ('all', 'All active employees'),
    ], default='assigned', required=True)
    only_missing = fields.Boolean(string='Only Missing Component A', default=True)
    line_ids = fields.One2many('bxi.eb.component.a.wizard.line', 'wizard_id', string='Employees')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' in fields_list:
            res['line_ids'] = self._line_commands(res.get('scope', 'assigned'), res.get('only_missing', True))
        return res

    @api.onchange('scope', 'only_missing')
    def _onchange_scope(self):
        self.line_ids = self._line_commands(self.scope, self.only_missing)

    @api.model
    def _line_commands(self, scope, only_missing):
        Employee = self.env['hr.employee'].sudo()
        if scope == 'assigned':
            employees = self.env['bxi.eb.assignment'].sudo().search([('state', '=', 'approved')]).employee_id
        else:
            employees = Employee.search([('company_id', 'in', self.env.companies.ids)])
        employees = employees.filtered(lambda e: e.active and e.company_id in self.env.companies)
        commands = [(5, 0, 0)]
        for employee in employees.sorted('name'):
            current = employee.version_id.eb_annual_component_a
            if only_missing and current:
                continue
            amount, source = self._propose(employee)
            commands.append((0, 0, {
                'employee_id': employee.id,
                'current_amount': current,
                'proposed_amount': amount,
                'source': source,
                'apply': bool(amount),
            }))
        return commands

    @api.model
    def _propose(self, employee):
        """Return (amount, source): the latest released appraisal, else the basic salary."""
        appraisal = self.env['hr.employee.appraisal'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'released'),
            ('letter_type', 'in', SALARY_LETTER_TYPES),
            ('annual_fixed', '>', 0),
            '|', ('effective_date', '=', False), ('effective_date', '<=', fields.Date.context_today(self)),
        ], order='effective_date desc, id desc', limit=1)
        if appraisal:
            return appraisal.annual_fixed, _("Appraisal effective %s", appraisal.effective_date or appraisal.release_date)
        basic = employee.l10n_in_basic_salary_amount or employee.version_id.wage
        if basic:
            return round(basic * (1 + FLEXIBLE_RATIO) * 12, 2), _("Basic salary + 70% flexible allowance, x 12")
        return 0.0, _("No salary recorded")

    def action_apply(self):
        self.ensure_one()
        if not (self.env.user.has_group('hr.group_hr_user')
                or self.env.user.has_group('bxi_equitable_benefit.group_eb_admin')):
            raise UserError(_("Only HR officers can set the Annualized Component A."))
        lines = self.line_ids.filtered(lambda l: l.apply and l.proposed_amount > 0)
        if not lines:
            raise UserError(_("Select at least one employee with a proposed amount."))
        for line in lines:
            employee = line.employee_id.sudo()
            # Earlier versions without a value would leave past periods unpaid: fill them as well.
            versions = employee.version_id | employee.version_ids.filtered(lambda v: not v.eb_annual_component_a)
            versions.write({'eb_annual_component_a': line.proposed_amount})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Annualized Component A set for %s employee(s).", len(lines)),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class BxiEbComponentAWizardLine(models.TransientModel):
    _name = 'bxi.eb.component.a.wizard.line'
    _description = 'Fill Annualized Component A Line'

    wizard_id = fields.Many2one('bxi.eb.component.a.wizard', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True)
    currency_id = fields.Many2one(related='employee_id.company_id.currency_id')
    current_amount = fields.Monetary(string='Current Component A', readonly=True)
    proposed_amount = fields.Monetary(string='New Component A')
    source = fields.Char(readonly=True)
    apply = fields.Boolean()
