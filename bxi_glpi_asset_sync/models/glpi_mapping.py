# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .glpi_client import GLPI_ITEMTYPES


class GlpiTypeMap(models.Model):
    _name = 'glpi.type.map'
    _description = 'GLPI Item Type Mapping'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    glpi_itemtype = fields.Selection(GLPI_ITEMTYPES, string='GLPI Item Type', required=True)
    glpi_type_name = fields.Char(string='GLPI Type',
        help="GLPI type name (e.g. 'Notebook', 'Desktop'). Leave empty to match any type "
             "of this item type.")
    asset_type_id = fields.Many2one('asset.type', string='Asset Type', required=True,
                                    ondelete='cascade')
    tag_ids = fields.Many2many('asset.tag', string='Tags',
        help="Tags added to assets created from matching GLPI items.")

    _itemtype_type_uniq = models.Constraint(
        'unique (glpi_itemtype, glpi_type_name)',
        "This GLPI item type / type combination is already mapped.",
    )

    @api.model
    def _find(self, itemtype, type_name):
        """Most specific mapping for a GLPI item: exact type first, then any type."""
        maps = self.search([('glpi_itemtype', '=', itemtype)])
        type_name = (type_name or '').strip().lower()
        exact = maps.filtered(lambda m: (m.glpi_type_name or '').strip().lower() == type_name
                              and m.glpi_type_name)
        return exact[:1] or maps.filtered(lambda m: not m.glpi_type_name)[:1]

    @api.model
    def _itemtype_for_asset_type(self, asset_type):
        return self.search([('asset_type_id', '=', asset_type.id)], limit=1).glpi_itemtype


class GlpiStatusMap(models.Model):
    _name = 'glpi.status.map'
    _description = 'GLPI Status Mapping'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    glpi_state_name = fields.Char(string='GLPI Status', required=True,
        help="Exact name of the status in GLPI (Setup > Dropdowns > Status of items).")
    odoo_status = fields.Selection(
        selection=lambda self: self.env['asset.management']._fields['status'].selection,
        string='Operational Status', required=True)

    _glpi_state_uniq = models.Constraint(
        'unique (glpi_state_name)',
        "This GLPI status is already mapped.",
    )

    @api.model
    def _odoo_status_for(self, glpi_state_name):
        if not glpi_state_name:
            return False
        maps = self.search([])
        name = glpi_state_name.strip().lower()
        return maps.filtered(lambda m: m.glpi_state_name.strip().lower() == name)[:1].odoo_status

    @api.model
    def _glpi_state_for(self, odoo_status):
        return self.search([('odoo_status', '=', odoo_status)], limit=1).glpi_state_name


class GlpiUserMap(models.Model):
    _name = 'glpi.user.map'
    _description = 'GLPI User Mapping'
    _order = 'glpi_login'
    _rec_name = 'glpi_login'

    glpi_login = fields.Char(string='GLPI Login / Contact', required=True,
        help="GLPI username, or the 'Alternate username' reported by the GLPI Agent "
             "(DOMAIN\\login is matched on the login part).")
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True,
                                  ondelete='cascade')

    _glpi_login_uniq = models.Constraint(
        'unique (glpi_login)',
        "This GLPI login is already mapped.",
    )

    @api.model
    def _employee_for(self, login):
        login = _normalize_login(login)
        if not login:
            return self.env['hr.employee']
        maps = self.search([])
        return maps.filtered(lambda m: _normalize_login(m.glpi_login) == login)[:1].employee_id

    @api.model
    def _login_for(self, employee):
        return self.search([('employee_id', '=', employee.id)], limit=1).glpi_login


def _normalize_login(login):
    """'BXI\\jdoe' / ' JDoe ' -> 'jdoe'."""
    login = (login or '').strip().lower()
    if '\\' in login:
        login = login.rsplit('\\', 1)[1]
    return login
