# -*- coding: utf-8 -*-
from odoo import fields, models


class HrContractAdvantageTemplate(models.Model):
    """Create a new model for adding fields."""
    _name = 'hr.contract.advantage.template'
    _description = "Employee's Advantage on Contract"

    name = fields.Char(string='Name', required=True,
                       help="Name for Employee's Advantage on Contract")
    code = fields.Char(string='Code', required=True,
                       help="Code for Employee's Advantage on Contract")
    lower_bound = fields.Float(string='Lower Bound',
                               help="Lower bound authorized by the employer"
                                    "for this advantage")
    upper_bound = fields.Float(string='Upper Bound',
                               help="Upper bound authorized by the employer"
                                    "for this advantage")
    default_value = fields.Float(string="Default Value",
                                 help='Default value for this advantage')
