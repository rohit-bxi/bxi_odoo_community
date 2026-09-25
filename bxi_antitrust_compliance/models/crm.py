# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import RedirectWarning


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    requires_bid_compliance = fields.Boolean(
        string='Requires Bid Compliance Declaration',
        help="RFP/tender opportunities can only enter this stage with a valid antitrust bid declaration.",
    )


class CrmTag(models.Model):
    _inherit = 'crm.tag'

    is_rfp_tag = fields.Boolean(
        string='RFP / Tender Tag',
        help="Opportunities with this tag are treated as RFP/tender bids.",
    )

    @api.model
    def _ensure_rfp_tags(self):
        """Create (or flag) the RFP and Tender tags without clashing with existing names."""
        for name in ('RFP', 'Tender'):
            tag = self.search([('name', '=ilike', name)], limit=1)
            if tag:
                tag.is_rfp_tag = True
            else:
                self.create({'name': name, 'is_rfp_tag': True})


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    is_tender_rfp = fields.Boolean(
        string='RFP / Tender',
        compute='_compute_is_tender_rfp',
        store=True,
        readonly=False,
        help="Bids on this opportunity need an antitrust bid declaration.",
    )
    bid_declaration_ids = fields.One2many('antitrust.bid.declaration', 'lead_id', string='Bid Declarations')
    bid_compliance_state = fields.Selection(
        [
            ('not_required', 'Not Required'),
            ('missing', 'Declaration Missing'),
            ('outdated', 'Declaration Outdated'),
            ('pending_cpo', 'Waiting for CPO'),
            ('compliant', 'Compliant'),
        ],
        string='Bid Compliance',
        compute='_compute_bid_compliance_state',
    )

    @api.depends('tag_ids.is_rfp_tag')
    def _compute_is_tender_rfp(self):
        for lead in self:
            if lead.tag_ids.filtered('is_rfp_tag'):
                lead.is_tender_rfp = True
            elif not lead.is_tender_rfp:
                lead.is_tender_rfp = False

    def _current_bid_declaration(self):
        self.ensure_one()
        declarations = self.sudo().bid_declaration_ids.filtered(lambda d: d.state in ('to_approve', 'confirmed'))
        return declarations.sorted('id', reverse=True)[:1]

    @api.depends('is_tender_rfp', 'bid_declaration_ids.state', 'order_ids.amount_total', 'order_ids.state')
    def _compute_bid_compliance_state(self):
        for lead in self:
            if not lead.is_tender_rfp:
                lead.bid_compliance_state = 'not_required'
                continue
            declaration = lead._current_bid_declaration()
            if not declaration:
                lead.bid_compliance_state = 'missing'
            elif not declaration._matches_quotations():
                lead.bid_compliance_state = 'outdated'
            elif declaration.state == 'to_approve':
                lead.bid_compliance_state = 'pending_cpo'
            else:
                lead.bid_compliance_state = 'compliant'

    def _check_bid_compliance(self):
        """Block a bid step on RFP/tender opportunities without a valid declaration."""
        for lead in self.filtered('is_tender_rfp'):
            state = lead.bid_compliance_state
            if state == 'compliant':
                continue
            messages = {
                'missing': self.env._("%(lead)s is an RFP/tender: complete the antitrust bid declaration first."),
                'outdated': self.env._("The quotations of %(lead)s changed after the bid declaration: "
                                       "please declare again."),
                'pending_cpo': self.env._("The bid declaration of %(lead)s is waiting for CPO approval."),
            }
            raise RedirectWarning(
                messages[state] % {'lead': lead.name},
                lead.action_open_bid_declaration(),
                self.env._("Bid Declaration"),
            )

    def action_open_bid_declaration(self):
        self.ensure_one()
        declaration = self._current_bid_declaration()
        if declaration and declaration._matches_quotations():
            return {'type': 'ir.actions.act_window', 'res_model': 'antitrust.bid.declaration',
                    'view_mode': 'form', 'res_id': declaration.id, 'target': 'new'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Bid Declaration'),
            'res_model': 'antitrust.bid.declaration',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def write(self, vals):
        res = super().write(vals)
        if vals.get('stage_id') and not self.env.context.get('skip_bid_compliance'):
            stage = self.env['crm.stage'].browse(vals['stage_id'])
            if stage.requires_bid_compliance:
                self._check_bid_compliance()
        return res

    def action_set_won(self):
        self._check_bid_compliance()
        return super().action_set_won()
