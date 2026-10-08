from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    gift_government_official = fields.Boolean(
        string='Government Official',
        help="Government official, family member of one, or employee of a state-owned / state-controlled "
             "entity (including state-owned media): the stricter Government Official rules apply.")
    gift_in_tender = fields.Boolean(
        string='Tender / Negotiation in Progress',
        help="BXI is tendering to, negotiating with or otherwise in a process with this party: "
             "no gift may be given to or accepted from it.")
    gift_blacklisted = fields.Boolean(string='Blacklisted (Gift Policy)', tracking=True)
    gift_blacklist_reason = fields.Char(string='Blacklist Reason')
