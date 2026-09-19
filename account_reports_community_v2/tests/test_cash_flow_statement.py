from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


def _flatten_values(lines, period_index=0):
    result = {}
    for line in lines:
        for col in line['periods'][period_index]['columns']:
            result[line['code']] = col['value']
        result.update(_flatten_values(line.get('children') or [], period_index=period_index))
    return result


@tagged('post_install', '-at_install')
class TestCashFlowStatement(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.cash_flow_statement_report')
        cls.receivable_account = cls.company_data['default_account_receivable']
        cls.payable_account = cls.company_data['default_account_payable']
        cls.revenue_account = cls.company_data['default_account_revenue']
        cls.expense_account = cls.company_data['default_account_expense']
        # account.account has no company_id field (it uses company_ids, a
        # many2many, to support a shared chart of accounts across
        # companies) - _check_company_domain is the model's own helper for
        # "visible to this company", same as core account test commons use.
        cls.cash_account = cls.env['account.account'].search([
            *cls.env['account.account']._check_company_domain(cls.env.company),
            ('account_type', '=', 'asset_cash'),
        ], limit=1)
        journal = cls.company_data['default_journal_misc']

        # Invoice a customer 1000 on credit (a non-cash sale: revenue is
        # earned now, but no cash moves yet).
        move_invoice = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-05',
            'line_ids': [
                (0, 0, {'account_id': cls.receivable_account.id, 'debit': 1000.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 1000.0}),
            ],
        })
        move_invoice.action_post()

        # Customer pays 600 of it in cash.
        move_payment = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-10',
            'line_ids': [
                (0, 0, {'account_id': cls.cash_account.id, 'debit': 600.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.receivable_account.id, 'debit': 0.0, 'credit': 600.0}),
            ],
        })
        move_payment.action_post()

        # Pay a 200 expense in cash.
        move_expense_paid = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 200.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.cash_account.id, 'debit': 0.0, 'credit': 200.0}),
            ],
        })
        move_expense_paid.action_post()

        # Incur a 100 expense on credit (an unpaid bill - no cash moves yet).
        move_bill = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-20',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.payable_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move_bill.action_post()

    def _get_values(self):
        # CF_OPERATING_TOTAL/CF_INVESTING_TOTAL/CF_FINANCING_TOTAL are
        # foldable and collapsed by default - like Balance Sheet's
        # categories (see test_balance_sheet.py), their children
        # (CF_AR/CF_AP/CF_NET_INCOME/...) simply aren't in the response at
        # all unless explicitly unfolded, not just hidden client-side.
        section_ids = self.env['account.report.line'].search([
            ('report_id', '=', self.report.id),
            ('code', 'in', ['CF_OPERATING_TOTAL', 'CF_INVESTING_TOTAL', 'CF_FINANCING_TOTAL']),
        ]).ids
        data = self.report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-03-01',
            'unfolded_line_ids': section_ids,
        })
        return _flatten_values(data['lines'])

    def test_net_change_matches_actual_cash_movement(self):
        """The report's own Net Change in Cash must equal the real change in
        the Cash account's balance over the same period - the fundamental
        self-check of the indirect method (see the comment block in
        cash_flow_statement_report.xml for why this identity holds)."""
        values = self._get_values()

        cash_result = self.env['account.move.line']._read_group(
            [
                ('account_id', '=', self.cash_account.id),
                ('parent_state', '=', 'posted'),
                ('date', '>=', '2025-01-01'), ('date', '<=', '2025-03-01'),
            ],
            aggregates=['balance:sum'],
        )
        actual_cash_change = cash_result[0][0] or 0.0
        self.assertAlmostEqual(values['CF_NET_CHANGE'], actual_cash_change, places=2)
        # 600 collected - 200 paid out = 400 net cash movement.
        self.assertAlmostEqual(values['CF_NET_CHANGE'], 400.0, places=2)

    def test_change_in_receivables_is_negative_when_ar_increases(self):
        values = self._get_values()
        # Customer still owes 400 (1000 invoiced - 600 collected): AR grew
        # by 400, which ties up cash -> negative contribution.
        self.assertAlmostEqual(values['CF_AR'], -400.0, places=2)

    def test_change_in_payables_is_positive_when_ap_increases(self):
        values = self._get_values()
        # 100 owed on the unpaid bill: AP grew by 100, a source of cash
        # (we haven't paid it out yet) -> positive contribution.
        self.assertAlmostEqual(values['CF_AP'], 100.0, places=2)

    def test_net_income_matches_manual_calc(self):
        values = self._get_values()
        # Revenue 1000 - expenses (200 + 100) = 700.
        self.assertAlmostEqual(values['CF_NET_INCOME'], 700.0, places=2)

    def test_operating_total_matches_sum_of_children(self):
        values = self._get_values()
        self.assertAlmostEqual(
            values['CF_OPERATING_TOTAL'],
            values['CF_NET_INCOME'] + values['CF_AR'] + values['CF_AP'] + values['CF_OTHER_CA'] + values['CF_OTHER_CL'],
            places=2,
        )

    def test_net_change_matches_sum_of_sections(self):
        values = self._get_values()
        self.assertAlmostEqual(
            values['CF_NET_CHANGE'],
            values['CF_OPERATING_TOTAL'] + values['CF_INVESTING_TOTAL'] + values['CF_FINANCING_TOTAL'],
            places=2,
        )
