from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    bonus_in_compensation = fields.Boolean(
        string="Performance Bonus in Compensation",
        help="Enable when a performance bonus is part of the employee's compensation structure."
    )
    bonus_employment_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("fte", "FTE"),
            ("other", "Other"),
        ],
        string="Bonus Employment Type",
        default="permanent",
    )
    bonus_grade = fields.Char(
        string="Bonus Grade",
        help="Policy grade, e.g. E0, E1, E2 or E3."
    )
    bonus_geography = fields.Selection(
        [
            ("india", "India"),
            ("europe_apac_row", "Europe / APAC / ROW"),
            ("americas_canada", "Americas / Canada"),
        ],
        string="Bonus Geography",
        default="india",
        help="Used to determine the applicable annual bonus type."
    )
    bonus_is_sales_employee = fields.Boolean(
        string="Sales Incentive Employee",
        help="Sales employees are covered by the Sales Incentive Policy."
    )
    bonus_is_rebadged = fields.Boolean(
        string="Rebadged Employee",
        help="Rebadged employees are governed by a separate bonus plan."
    )
    bonus_annual_base = fields.Monetary(
        string="Annual Bonus Salary Basis",
        currency_field="bonus_currency_id",
        help="Annual salary amount used as the bonus calculation basis."
    )
    bonus_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
