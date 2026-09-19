from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestExpressionEngines(AccountTestInvoicingCommon):
    """Trial Balance/General Ledger/Partner Ledger/Balance Sheet/P&L only
    ever exercise the 'domain' and 'aggregation' engines (that's all their
    shipped report content uses). 'account_codes' and 'tax_tags' were
    written for future use but never actually run by any existing test -
    these build minimal, throwaway account.report/line/expression records
    to exercise them directly, in isolation from any of the module's
    shipped reports.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.expense_account = cls.company_data['default_account_expense']
        cls.revenue_account = cls.company_data['default_account_revenue']
        journal = cls.company_data['default_journal_misc']

        cls.move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        cls.move.action_post()

        # A throwaway report/line to host test expressions - not one of
        # the module's shipped reports. country_id is set explicitly (and
        # reused by the tax_tags test below) because _get_tax_tags() matches
        # tags by (name, country_id) - it must agree with whatever country
        # the test tag/tax get created under, or the lookup silently misses.
        cls.test_country = cls.env.company.account_fiscal_country_id or cls.env.ref('base.us')
        cls.test_report = cls.env['account.report'].create({
            'name': 'Test Report (engines)',
            'report_handler': 'generic',
            'country_id': cls.test_country.id,
        })
        cls.test_line = cls.env['account.report.line'].create({
            'name': 'Test Line',
            'code': 'TEST_ENGINE_LINE',
            'report_id': cls.test_report.id,
        })

    def _make_expression(self, **vals):
        vals.setdefault('report_line_id', self.test_line.id)
        vals.setdefault('date_scope', 'strict_range')
        return self.env['account.report.expression'].create(vals)

    def _options(self):
        return self.test_report._get_default_options({'date_from': '2025-01-01', 'date_to': '2025-03-01'})

    # -- account_codes engine ------------------------------------------------
    def test_account_codes_engine_sums_matching_prefix(self):
        expr = self._make_expression(label='balance', engine='account_codes', formula=self.expense_account.code)
        value, domains = expr._evaluate(self._options())
        self.assertAlmostEqual(value, 100.0, places=2)
        self.assertTrue(domains)
        # The returned domain must actually resolve to the posted line.
        matched = self.env['account.move.line'].search(domains[0])
        self.assertIn(self.move.line_ids.filtered(lambda l: l.account_id == self.expense_account), matched)

    def test_account_codes_engine_excludes_prefix(self):
        code = self.expense_account.code
        formula = f'{code[:2]}\\({code})'
        expr = self._make_expression(label='balance', engine='account_codes', formula=formula)
        value, _domains = expr._evaluate(self._options())
        self.assertAlmostEqual(value, 0.0, places=2)

    def test_account_codes_engine_balance_character_debit_only(self):
        code = self.expense_account.code
        expr = self._make_expression(label='balance', engine='account_codes', formula=f'{code}D')
        value, _domains = expr._evaluate(self._options())
        self.assertAlmostEqual(value, 100.0, places=2)

    def test_account_codes_engine_balance_character_credit_only(self):
        # The expense account only moved on the debit side, so a
        # credit-only filter on it must report zero, not the debit amount.
        code = self.expense_account.code
        expr = self._make_expression(label='balance', engine='account_codes', formula=f'{code}C')
        value, _domains = expr._evaluate(self._options())
        self.assertAlmostEqual(value, 0.0, places=2)

    def test_account_codes_engine_sign(self):
        expr_plus = self._make_expression(label='plus', engine='account_codes', formula=self.expense_account.code)
        expr_minus = self._make_expression(label='minus', engine='account_codes', formula=f'-{self.expense_account.code}')
        value_plus, _ = expr_plus._evaluate(self._options())
        value_minus, _ = expr_minus._evaluate(self._options())
        self.assertAlmostEqual(value_plus, -value_minus, places=2)

    # -- tax_tags engine ------------------------------------------------------
    def test_tax_tags_engine(self):
        tag = self.env['account.account.tag'].create({
            'name': 'test_engine_tag',
            'applicability': 'taxes',
            'country_id': self.test_country.id,
        })
        tax = self.env['account.tax'].create({
            'name': 'Test Engine Tax 10%',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'country_id': self.test_country.id,
            'invoice_repartition_line_ids': [
                (0, 0, {'repartition_type': 'base', 'factor_percent': 100}),
                (0, 0, {'repartition_type': 'tax', 'factor_percent': 100, 'tag_ids': [(6, 0, tag.ids)]}),
            ],
        })

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': '2025-01-20',
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product_a.id,
                'quantity': 1,
                'price_unit': 1000.0,
                'tax_ids': [(6, 0, tax.ids)],
            })],
        })
        invoice.action_post()

        tax_line = invoice.line_ids.filtered(lambda l: tag in l.tax_tag_ids)
        self.assertTrue(tax_line, "Expected the posted invoice to carry a line tagged with our test tag")

        expr = self._make_expression(label='balance', engine='tax_tags', formula='test_engine_tag')
        value, domains = expr._evaluate(self._options())
        self.assertTrue(domains)
        self.assertAlmostEqual(abs(value), 100.0, places=2)  # 10% of 1000.0

    # -- aggregation engine drilldown -----------------------------------------
    def test_aggregation_drilldown_matches_displayed_value(self):
        """Regression test for _get_drilldown_domain's domain-union logic
        on an 'aggregation' engine line: clicking a cell must return a
        domain whose account.move.line sum equals the value actually shown,
        not just *some* plausible-looking domain."""
        receivable_account = self.company_data['default_account_receivable']
        journal = self.company_data['default_journal_misc']
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-20',
            'line_ids': [
                (0, 0, {'account_id': receivable_account.id, 'debit': 500.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.revenue_account.id, 'debit': 0.0, 'credit': 500.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('account_reports_community_v2.balance_sheet_report')
        total_assets_line = self.env.ref('account_reports_community_v2.bs_line_assets_total')
        options = report._get_default_options({'date_from': '2025-01-01', 'date_to': '2025-03-01'})

        expression = total_assets_line.expression_ids.filtered(lambda e: e.label == 'balance')
        value, _domains = expression._evaluate(options)

        domain = total_assets_line._get_drilldown_domain(options, 'balance')
        manual_sum = sum(self.env['account.move.line'].search(domain).mapped('balance'))
        self.assertAlmostEqual(value, manual_sum, places=2)
