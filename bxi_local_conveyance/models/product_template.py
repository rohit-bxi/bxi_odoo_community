from odoo import fields, models

CONVEYANCE_KINDS = [
    ('vehicle_2w', 'Personal Two-Wheeler'),
    ('vehicle_4w', 'Personal Four-Wheeler'),
    ('auto', 'Auto-Rickshaw'),
    ('taxi', 'Taxi'),
    ('parking_toll', 'Parking & Toll'),
    ('food', 'Food (Sales Team)'),
    ('transfer_2w', 'Domestic Transfer - Drive (Two-Wheeler)'),
    ('transfer_4w', 'Domestic Transfer - Drive (Four-Wheeler)'),
]
# Kinds that are a trip, as opposed to charges claimed along with one (parking, toll) or food.
TRAVEL_KINDS = ('vehicle_2w', 'vehicle_4w', 'auto', 'taxi')
VEHICLE_KINDS = ('vehicle_2w', 'vehicle_4w')
# Driving the own vehicle to the city of a domestic transfer, at the Table A rates.
TRANSFER_KINDS = ('transfer_2w', 'transfer_4w')
# Kinds reimbursed per km: the quantity is the distance.
PER_KM_KINDS = VEHICLE_KINDS + TRANSFER_KINDS
# Kinds reimbursed at actuals only against a bill.
BILL_KINDS = ('auto', 'taxi', 'parking_toll', 'food')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    conveyance_kind = fields.Selection(
        CONVEYANCE_KINDS, string='Local Conveyance',
        help="Claimed under the Local Conveyance Policy (My Local Conveyance on the portal), never as a regular "
             "expense. Personal vehicles are reimbursed per km at the cost of the category.",
    )
