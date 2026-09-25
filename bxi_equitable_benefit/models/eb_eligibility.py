from odoo import api, fields, models

RATINGS = [
    ('below', 'Below Expectations'),
    ('meets', 'Meets Expectations'),
    ('exceeds', 'Exceeds Expectations'),
    ('outstanding', 'Outstanding'),
]
RATING_ORDER = {key: index for index, (key, _label) in enumerate(RATINGS)}


class BxiEbDisciplinaryAction(models.Model):
    _name = 'bxi.eb.disciplinary.action'
    _description = 'Employee Disciplinary Action'
    _inherit = ['mail.thread']
    _order = 'date_from desc'

    name = fields.Char(string='Subject', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True, tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    date_from = fields.Date(string='Start Date', required=True, default=fields.Date.context_today, tracking=True)
    date_to = fields.Date(string='End Date', tracking=True, help="Leave empty while the action is still active.")
    state = fields.Selection([
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], default='active', required=True, tracking=True)
    description = fields.Text()

    def action_close(self):
        self.write({'state': 'closed', 'date_to': fields.Date.context_today(self)})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    @api.model
    def _overlapping(self, employee, date_from, date_to):
        return self.search([
            ('employee_id', '=', employee.id),
            ('state', '!=', 'cancelled'),
            ('date_from', '<=', date_to),
            '|', ('date_to', '=', False), ('date_to', '>=', date_from),
        ])


class BxiEbPerformanceRating(models.Model):
    _name = 'bxi.eb.performance.rating'
    _description = 'Employee Annual Performance Rating'
    _inherit = ['mail.thread']
    _order = 'fy_start desc'

    employee_id = fields.Many2one('hr.employee', required=True, index=True, tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    fy_start = fields.Date(string='Financial Year Start', required=True, tracking=True)
    fy_name = fields.Char(string='Financial Year', compute='_compute_fy_name', store=True)
    rating = fields.Selection(RATINGS, required=True, tracking=True)
    note = fields.Text()

    _employee_fy_unique = models.Constraint(
        'unique(employee_id, fy_start)', 'An employee can only have one rating per financial year.')

    @api.depends('fy_start')
    def _compute_fy_name(self):
        for rec in self:
            rec.fy_name = rec.fy_start and 'FY %s-%s' % (rec.fy_start.year, str(rec.fy_start.year + 1)[2:])
