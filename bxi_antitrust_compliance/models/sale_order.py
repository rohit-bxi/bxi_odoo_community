# -*- coding: utf-8 -*-
from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _check_bid_compliance(self):
        self.opportunity_id.filtered('is_tender_rfp')._check_bid_compliance()

    def action_quotation_send(self):
        self._check_bid_compliance()
        return super().action_quotation_send()

    def action_quotation_sent(self):
        self._check_bid_compliance()
        return super().action_quotation_sent()

    def action_confirm(self):
        self._check_bid_compliance()
        return super().action_confirm()
