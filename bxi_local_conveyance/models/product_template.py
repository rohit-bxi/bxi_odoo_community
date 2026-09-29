from odoo import fields, models

CONVEYANCE_KINDS = [
    ('vehicle_2w', 'Personal Two-Wheeler'),
    ('vehicle_4w', 'Personal Four-Wheeler'),
    ('auto', 'Auto-Rickshaw'),
    ('taxi', 'Taxi'),
    ('parking_toll', 'Parking & Toll'),
    ('food', 'Food (Sales Team)'),
]
# Kinds that are a trip, as opposed to charges claimed along with one (parking, toll) or food.
TRAVEL_KINDS = ('vehicle_2w', 'vehicle_4w', 'auto', 'taxi')
VEHICLE_KINDS = ('vehicle_2w', 'vehicle_4w')
# Kinds reimbursed at actuals only against a bill.
BILL_KINDS = ('auto', 'taxi', 'parking_toll', 'food')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    conveyance_kind = fields.Selection(
        CONVEYANCE_KINDS, string='Local Conveyance',
        help="Claimed under the Local Conveyance Policy (My Local Conveyance on the portal), never as a regular "
             "expense. Personal vehicles are reimbursed per km at the cost of the category.",
    )
