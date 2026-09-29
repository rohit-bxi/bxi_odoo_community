from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

PARAM_PREFIX = 'bxi_local_conveyance.'


class BxiConveyanceOfficeAssignment(models.Model):
    """An employee working from a local office other than their regular one.

    The policy covers the first months there only (two by default): later claims are not reimbursed.
    """
    _name = 'bxi.conveyance.office.assignment'
    _description = 'Local Conveyance Office Assignment'
    _inherit = ['mail.thread']
    _order = 'date_from desc, id desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True, tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    work_location_id = fields.Many2one('hr.work.location', string='Office', required=True, tracking=True)
    date_from = fields.Date(string='Working There From', required=True, tracking=True)
    date_to = fields.Date(string='Until', tracking=True, help="Leave empty while the assignment runs.")
    coverage_end_date = fields.Date(
        string='Covered Until', compute='_compute_coverage_end_date',
        help="Last day conveyance is reimbursed during this assignment.")
    note = fields.Text(string='Notes')
    active = fields.Boolean(default=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(self.env._("The assignment cannot end before it starts."))

    @api.model
    def _get_coverage_months(self):
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + 'office_coverage_months', 2)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 2

    @api.depends('date_from')
    def _compute_coverage_end_date(self):
        months = self._get_coverage_months()
        for rec in self:
            rec.coverage_end_date = (
                rec.date_from + relativedelta(months=months, days=-1) if rec.date_from else False)

    @api.model
    def _get_uncovered(self, employee, date):
        """The assignment running on that date whose coverage has already ended, if any."""
        assignments = self.sudo().search([
            ('employee_id', '=', employee.id),
            ('date_from', '<=', date),
            '|', ('date_to', '=', False), ('date_to', '>=', date),
        ])
        return assignments.filtered(lambda rec: date > rec.coverage_end_date)[:1]
