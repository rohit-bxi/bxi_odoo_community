from odoo import api, fields, models

VEHICLE_OPTIONS = [
    ('drive', 'Drive to the New City (Table A per km)'),
    ('shipment', 'Vehicle Movement (Domestic Transfer Policy)'),
]


class BxiConveyanceTransfer(models.Model):
    """A domestic transfer of an employee to another city.

    The employee is reimbursed either for the movement of their vehicle under the Domestic Transfer Policy, or for
    driving it to the new city at the Table A rates, but not both, and for one vehicle only.
    """
    _name = 'bxi.conveyance.transfer'
    _description = 'Domestic Transfer (Vehicle)'
    _inherit = ['mail.thread']
    _order = 'transfer_date desc, id desc'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True, tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    from_city = fields.Char(string='From City', required=True, tracking=True)
    to_city = fields.Char(string='To City', required=True, tracking=True)
    transfer_date = fields.Date(string='Transfer Date', required=True, tracking=True)
    vehicle_option = fields.Selection(
        VEHICLE_OPTIONS, string='Vehicle Reimbursement', required=True, default='drive', tracking=True,
        help="Either the movement of the vehicle or driving it to the new city, not both.")
    claim_ids = fields.One2many('hr.expense', 'conveyance_transfer_id', string='Drive Claims')
    claim_id = fields.Many2one(
        'hr.expense', string='Drive Claim', compute='_compute_claim_id',
        help="The drive claim of the transfer (one vehicle only).")
    note = fields.Text(string='Notes')
    active = fields.Boolean(default=True)

    @api.depends('employee_id', 'from_city', 'to_city', 'transfer_date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.employee_id.name}: {rec.from_city} - {rec.to_city} ({rec.transfer_date})"

    @api.depends('claim_ids.state')
    def _compute_claim_id(self):
        for rec in self:
            rec.claim_id = rec.sudo().claim_ids.filtered(lambda exp: exp.state not in ('draft', 'refused'))[:1]

    @api.model
    def _get_claimable(self, employee):
        """The transfers of the employee whose vehicle can still be claimed as driven to the new city."""
        transfers = self.sudo().search([('employee_id', '=', employee.id), ('vehicle_option', '=', 'drive')])
        return transfers.filtered(lambda rec: not rec.claim_id)
