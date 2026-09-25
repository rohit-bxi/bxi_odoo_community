from odoo.exceptions import AccessError, RedirectWarning, UserError
from odoo.tests import tagged

from .common import ComplianceCommon


@tagged('post_install', '-at_install')
class TestBidCompliance(ComplianceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rfp_tag = cls.env['crm.tag'].search([('is_rfp_tag', '=', True)], limit=1)
        cls.stage_submit = cls.env['crm.stage'].create({'name': 'Cmp Proposal Submission', 'requires_bid_compliance': True})
        cls.stage_other = cls.env['crm.stage'].create({'name': 'Cmp Qualification'})
        cls.customer = cls.env['res.partner'].create({'name': 'Cmp Customer'})
        cls.product = cls.env['product.product'].create({'name': 'Cmp Service', 'list_price': 1000, 'type': 'service'})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Cmp Government Tender', 'type': 'opportunity', 'partner_id': cls.customer.id,
            'user_id': cls.salesman.id, 'stage_id': cls.stage_other.id,
        })

    def _quotation(self, qty=1):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'opportunity_id': self.lead.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': qty})],
        })

    def _declare(self, user=None):
        declaration = self.env['antitrust.bid.declaration'].with_user(user or self.salesman).create({
            'lead_id': self.lead.id,
            'confirm_independent_pricing': True,
            'confirm_no_exchange': True,
            'confirm_no_agreement': True,
            'confirm_confidentiality': True,
            'pricing_basis': 'Standard rate card',
        })
        declaration.action_submit()
        return declaration

    def _make_rfp(self):
        self.lead.tag_ids = [(4, self.rfp_tag.id)]

    def test_rfp_tags_exist(self):
        names = self.env['crm.tag'].search([('is_rfp_tag', '=', True)]).mapped('name')
        self.assertTrue({'rfp', 'tender'} <= {name.lower() for name in names})

    def test_tag_marks_rfp(self):
        self.assertFalse(self.lead.is_tender_rfp)
        self.assertEqual(self.lead.bid_compliance_state, 'not_required')
        self._make_rfp()
        self.assertTrue(self.lead.is_tender_rfp)
        self.assertEqual(self.lead.bid_compliance_state, 'missing')

    def test_non_rfp_is_not_blocked(self):
        self.lead.stage_id = self.stage_submit
        self._quotation().action_confirm()

    def test_stage_blocked_without_declaration(self):
        self._make_rfp()
        with self.assertRaises(RedirectWarning):
            self.lead.stage_id = self.stage_submit
        self.lead.stage_id = self.stage_other  # stages without the flag are fine
        self._declare()
        self.lead.stage_id = self.stage_submit
        self.assertEqual(self.lead.stage_id, self.stage_submit)

    def test_quotation_blocked_without_declaration(self):
        self._make_rfp()
        order = self._quotation()
        for method in ('action_quotation_send', 'action_quotation_sent', 'action_confirm'):
            with self.assertRaises(RedirectWarning):
                getattr(order, method)()
        self._declare()
        self.assertEqual(self.lead.bid_compliance_state, 'compliant')
        order.action_quotation_sent()
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_won_blocked_without_declaration(self):
        self._make_rfp()
        with self.assertRaises(RedirectWarning):
            self.lead.action_set_won()
        self._declare()
        self.lead.action_set_won()

    def test_all_confirmations_required(self):
        self._make_rfp()
        declaration = self.env['antitrust.bid.declaration'].with_user(self.salesman).create({
            'lead_id': self.lead.id, 'confirm_independent_pricing': True,
        })
        with self.assertRaises(UserError):
            declaration.action_submit()

    def test_only_bid_owner_submits(self):
        self._make_rfp()
        declaration = self.env['antitrust.bid.declaration'].with_user(self.salesman).create({
            'lead_id': self.lead.id, 'confirm_independent_pricing': True, 'confirm_no_exchange': True,
            'confirm_no_agreement': True, 'confirm_confidentiality': True,
        })
        with self.assertRaises(AccessError):
            declaration.with_user(self.employee.user_id).action_submit()

    def test_changed_quotation_needs_new_declaration(self):
        self._make_rfp()
        order = self._quotation()
        declaration = self._declare()
        self.assertEqual(declaration.quotation_snapshot, {str(order.id): order.amount_total})
        order.order_line.product_uom_qty = 2
        self.assertEqual(self.lead.bid_compliance_state, 'outdated')
        with self.assertRaises(RedirectWarning):
            order.action_quotation_sent()
        self._declare()
        order.action_quotation_sent()

    def test_new_quotation_needs_new_declaration(self):
        self._make_rfp()
        self._quotation()
        self._declare()
        new_order = self._quotation(qty=3)
        with self.assertRaises(RedirectWarning):
            new_order.action_quotation_sent()

    def test_declaration_locked(self):
        self._make_rfp()
        declaration = self._declare()
        with self.assertRaises(UserError):
            declaration.with_user(self.salesman).write({'pricing_basis': 'changed'})
        with self.assertRaises(AccessError):
            declaration.with_user(self.salesman).write({'state': 'draft'})

    def test_cpo_signoff(self):
        self.env.company.bid_cpo_signoff = True
        self._make_rfp()
        order = self._quotation()
        declaration = self._declare()
        self.assertEqual(declaration.state, 'to_approve')
        self.assertEqual(self.lead.bid_compliance_state, 'pending_cpo')
        self.assertTrue(declaration.sudo().activity_ids.filtered(lambda a: a.user_id == self.cpo))
        with self.assertRaises(RedirectWarning):
            order.action_quotation_sent()
        with self.assertRaises(AccessError):
            declaration.with_user(self.salesman).action_approve()
        declaration.with_user(self.cpo).action_approve()
        self.assertEqual(self.lead.bid_compliance_state, 'compliant')
        order.action_quotation_sent()

    def test_cpo_rejects_declaration(self):
        self.env.company.bid_cpo_signoff = True
        self._make_rfp()
        declaration = self._declare()
        with self.assertRaises(UserError):
            declaration.with_user(self.cpo).action_reject()
        declaration.with_user(self.cpo).reject_reason = 'Pricing mirrors a competitor quote'
        declaration.with_user(self.cpo).action_reject()
        self.assertEqual(declaration.state, 'rejected')
        self.assertEqual(self.lead.bid_compliance_state, 'missing')

    def test_open_declaration_action(self):
        self._make_rfp()
        action = self.lead.action_open_bid_declaration()
        self.assertEqual(action['context']['default_lead_id'], self.lead.id)
        declaration = self._declare()
        self.assertEqual(self.lead.action_open_bid_declaration()['res_id'], declaration.id)

    def test_declaration_visibility(self):
        self._make_rfp()
        declaration = self._declare()
        Declaration = self.env['antitrust.bid.declaration']
        self.assertTrue(Declaration.with_user(self.salesman).search([('id', '=', declaration.id)]))
        self.assertFalse(Declaration.with_user(self.colleague.user_id).search([('id', '=', declaration.id)]))
        self.assertTrue(Declaration.with_user(self.cpo).search([('id', '=', declaration.id)]))
