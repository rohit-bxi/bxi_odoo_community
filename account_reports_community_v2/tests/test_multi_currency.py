from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


def _find_account_row(lines, account_id):
    """Depth-first search for the row carrying `account_id` - unlike
    test_balance_sheet.py's _flatten_values (keyed by report-line `code`),
    this looks up by account_id directly: two different companies'
    default charts can legitimately reuse the same account code, so
    keying by code would silently collide in a multi-company scenario."""
    for line in lines:
        if line.get('account_id') == account_id:
            return line
        found = _find_account_row(line.get('children') or [], account_id)
        if found:
            return found
    return None


@tagged('post_install', '-at_install')
class TestMultiCompanyMultiCurrency(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.trial_balance = cls.env.ref('account_reports_community_v2.trial_balance_report')
        cls.gl_report = cls.env.ref('account_reports_community_v2.general_ledger_report')

        # A currency distinct from company_data's, with a *global* rate
        # (no company_id) so the lookup succeeds regardless of which
        # company gets passed to res.currency._convert()/
        # _get_conversion_rate() - a rate row scoped to one specific
        # company is only visible when converting *for* that same company.
        cls.other_currency = cls.env['res.currency'].create({'name': 'Multi X', 'symbol': 'X$'})
        cls.env['res.currency.rate'].create({
            'currency_id': cls.other_currency.id,
            'name': '2025-01-01',
            'rate': 2.0,
        })
        cls.company_data_2 = cls.setup_other_company(currency_id=cls.other_currency.id)
        cls.main_currency = cls.company_data['currency']

        # Share one revenue account across both companies (Odoo's shared
        # chart of accounts, account.account.company_ids) so a single
        # Trial Balance/General Ledger row ends up aggregating postings
        # made in two different currencies. `code` is company-dependent
        # (backed by code_mapping_ids, one row per company) - adding a
        # company to company_ids without also giving it a code mapping
        # trips _ensure_code_is_unique's "code must be set for every
        # company" check.
        cls.shared_revenue_account = cls.company_data['default_account_revenue']
        # A distinct code for company_2's mapping - company_2 uses the same
        # default chart template, so it already has its own native revenue
        # account under this account's original code; reusing that code
        # here would collide with it under _ensure_code_is_unique.
        cls.shared_revenue_account.write({
            'company_ids': [Command.link(cls.company_data_2['company'].id)],
            'code_mapping_ids': [Command.create({
                'company_id': cls.company_data_2['company'].id,
                'code': '999000',
            })],
        })

        move_1 = cls.env['account.move'].with_company(cls.company_data['company']).create({
            'move_type': 'entry',
            'journal_id': cls.company_data['default_journal_misc'].id,
            'date': '2025-01-15',
            'line_ids': [
                Command.create({'account_id': cls.company_data['default_account_receivable'].id, 'debit': 100.0, 'credit': 0.0}),
                Command.create({'account_id': cls.shared_revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move_1.action_post()

        move_2 = cls.env['account.move'].with_company(cls.company_data_2['company']).create({
            'move_type': 'entry',
            'journal_id': cls.company_data_2['default_journal_misc'].id,
            'date': '2025-01-20',
            'line_ids': [
                Command.create({'account_id': cls.company_data_2['default_account_receivable'].id, 'debit': 200.0, 'credit': 0.0}),
                Command.create({'account_id': cls.shared_revenue_account.id, 'debit': 0.0, 'credit': 200.0}),
            ],
        })
        move_2.action_post()

    def _both_companies(self):
        return [self.company_data['company'].id, self.company_data_2['company'].id]

    def _expected_revenue_balance(self, target_currency):
        """-(company_1's 100 converted into target_currency) -
        (company_2's 200 converted into target_currency), computed via the
        same res.currency._convert() the report itself uses - so this
        stays correct regardless of which direction Odoo's rate convention
        actually points, rather than hardcoding a number derived by hand."""
        company_1_in_target = self.main_currency._convert(
            100.0, target_currency, self.company_data['company'], '2025-01-31', round=False)
        company_2_in_target = self.other_currency._convert(
            200.0, target_currency, self.company_data_2['company'], '2025-01-31', round=False)
        return -(company_1_in_target + company_2_in_target)

    def test_trial_balance_converts_across_companies(self):
        """Trial Balance's account row (groupby='account_id', exercising
        _evaluate_batch_by_account/_sum_aml) must convert company_2's
        postings into the report's target currency before summing them
        with company_1's, not blend the two currencies' raw amounts."""
        report = self.trial_balance.with_context(allowed_company_ids=self._both_companies())
        data = report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-01-31',
            'currency_id': self.main_currency.id,
        })
        row = _find_account_row(data['lines'], self.shared_revenue_account.id)
        self.assertTrue(row, "Expected the shared revenue account to appear in the Trial Balance")
        end_balance = next(col['value'] for col in row['periods'][0]['columns'] if col['expression_label'] == 'end_balance')
        self.assertAlmostEqual(end_balance, self._expected_revenue_balance(self.main_currency), places=2)

    def test_general_ledger_converts_across_companies(self):
        """General Ledger's bespoke handler (_group_balance/
        _group_balance_and_count) must show the same converted total for
        the shared account as Trial Balance does."""
        report = self.gl_report.with_context(allowed_company_ids=self._both_companies())
        data = report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-01-31',
            'currency_id': self.main_currency.id,
        })
        line = next(line for line in data['lines'] if line['account_id'] == self.shared_revenue_account.id)
        self.assertAlmostEqual(line['closing_balance'], self._expected_revenue_balance(self.main_currency), places=2)

    def test_currency_override_flips_the_total(self):
        """Explicitly requesting `other_currency` as the report currency
        (the currency filter override) must convert company_1's leg into
        it instead, while leaving company_2's own-currency leg untouched -
        the reverse of the default (main_currency) case above."""
        report = self.gl_report.with_context(allowed_company_ids=self._both_companies())
        data = report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-01-31',
            'currency_id': self.other_currency.id,
        })
        line = next(line for line in data['lines'] if line['account_id'] == self.shared_revenue_account.id)
        self.assertAlmostEqual(line['closing_balance'], self._expected_revenue_balance(self.other_currency), places=2)

    def test_single_company_selection_is_unaffected(self):
        """Regression guard: with only company_1 selected (the pre-existing
        single-company case), the shared account's balance must be exactly
        company_1's own 100 - no conversion path should trigger at all
        since company.currency_id == target_currency short-circuits."""
        report = self.gl_report.with_context(allowed_company_ids=[self.company_data['company'].id])
        data = report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-01-31',
        })
        line = next(line for line in data['lines'] if line['account_id'] == self.shared_revenue_account.id)
        self.assertAlmostEqual(line['closing_balance'], -100.0, places=2)
