# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Inherit res_config_settings model for adding some fields in Settings"""
    _inherit = 'res.config.settings'

    module_account_accountant = fields.Boolean(string='Account Accountant',
                                               help="Is Account Accountant")
    module_l10n_fr_hr_payroll = fields.Boolean(string='French Payroll',
                                               help="Is French Payroll")
    module_l10n_be_hr_payroll = fields.Boolean(string='Belgium Payroll',
                                               help="Is Belgium Payroll")
    module_l10n_in_hr_payroll = fields.Boolean(string='Indian Payroll',
                                               help="Is Indian Payroll")
