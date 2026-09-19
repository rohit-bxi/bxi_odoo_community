import calendar
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import models, fields
from odoo.tools import date_utils

GENERAL_LEDGER_REPORT_XMLID = 'account_reports_community_v2.general_ledger_report'

# How many raw journal-item rows an unfolded account/partner/tax/journal
# fetches at a time - both on first unfold and on every subsequent "Load
# more" click. Without this, a genuinely active account (a bank account
# with years of statement lines, say) could return thousands of rows for
# one click, which the browser would then have to render as thousands of
# DOM rows in one go. Opening/closing balances are unaffected either way
# (those come from a separate GROUP BY query, not from this list) - only
# the journal-item row list is paginated.
AML_PAGE_SIZE = 100

AGED_BUCKET_DEFS = [
    ('not_due', "Not Due"),
    ('b1_30', "1-30"),
    ('b31_60', "31-60"),
    ('b61_90', "61-90"),
    ('older', "Older"),
]


class AccountReport(models.Model):
    _inherit = 'account.report'

    report_handler = fields.Selection(
        string="Report Handler",
        selection=[
            ('generic', "Generic (hierarchy of report lines/expressions)"),
            ('general_ledger', "General Ledger (raw journal items per account)"),
            ('partner_ledger', "Partner Ledger (raw journal items per partner)"),
            ('aged_partner_balance', "Aged Receivable/Payable (open items bucketed by due date)"),
            ('tax_report', "Tax Report (base/tax amounts per tax)"),
            ('journal_report', "Journal Report (raw journal items per journal)"),
        ],
        default='generic',
        required=True,
        help="Reports whose data isn't a clean hierarchy of aggregated "
             "expressions (e.g. General Ledger, Partner Ledger, Aged "
             "Receivable/Payable) are computed by a bespoke Python method "
             "instead of the generic report line/expression engine.",
    )
    aged_account_type = fields.Selection(
        string="Aged Account Type",
        selection=[
            ('asset_receivable', "Receivable"),
            ('liability_payable', "Payable"),
        ],
        help="Only meaningful when report_handler='aged_partner_balance': "
             "which account type this specific aged report covers (one "
             "report record per type, sharing the same Python method).",
    )

    def _get_default_options(self, params=None):
        """Build a normalized options dict from raw request params, filling
        in sensible defaults (current fiscal year to date)."""
        self.ensure_one()
        params = params or {}
        company = self.env.company
        today = fields.Date.context_today(self)
        fy_from, _fy_to = date_utils.get_fiscal_year(
            today, day=company.fiscalyear_last_day, month=int(company.fiscalyear_last_month),
        )
        return {
            'date_from': params.get('date_from') or fields.Date.to_string(fy_from),
            'date_to': params.get('date_to') or fields.Date.to_string(today),
            'currency_id': params.get('currency_id') or self._get_default_report_currency_id().id,
            'unfolded_line_ids': params.get('unfolded_line_ids') or [],
            'focus_account_id': params.get('focus_account_id'),
            'journal_ids': params.get('journal_ids') or None,
            'all_entries': bool(params.get('all_entries')),
            'search': (params.get('search') or '').strip().lower(),
            'focus_partner_id': params.get('focus_partner_id'),
            'partner_ids': params.get('partner_ids') or None,
            'comparison_periods': int(params.get('comparison_periods') or 0),
            # Set by the frontend's date-preset dropdown (This Month/Quarter/
            # Year, etc.) to a value in ('month', 'quarter', 'year') so
            # comparison periods shift by whole calendar units instead of a
            # raw day count; left as None for manually-typed custom ranges,
            # where a day-count shift is the only generic option available.
            'period_granularity': params.get('period_granularity'),
            # Set only by the PDF/XLSX export controllers: forces every
            # foldable row open and fetches every journal-item row instead
            # of one AML_PAGE_SIZE page, since an export is supposed to
            # contain everything, not just whatever happens to be expanded
            # in the UI right now.
            'export_mode': bool(params.get('export_mode')),
        }

    def _format_period_label(self, date_from, date_to):
        from_date = fields.Date.from_string(date_from)
        to_date = fields.Date.from_string(date_to)
        if from_date.year == to_date.year and from_date.month == to_date.month:
            return to_date.strftime('%b %Y')
        return f"{from_date.strftime('%b %d, %Y')} - {to_date.strftime('%b %d, %Y')}"

    def _shift_period_back(self, date_from, date_to, granularity):
        """Return the (date_from, date_to) of the period immediately
        preceding [date_from, date_to].

        For 'month'/'quarter'/'year' granularity this shifts by whole
        calendar units (so Feb 1-28 correctly compares to Jan 1-31, not to
        a raw 28-day window that would land mid-January) -- this only makes
        sense when date_from/date_to are themselves aligned to that unit's
        boundaries, which is guaranteed when they came from the frontend's
        date-preset dropdown. For anything else (arbitrary custom ranges,
        or no granularity given), fall back to shifting back by the exact
        number of days in the current range, the only generic option there.
        """
        if granularity == 'month':
            prev_from = date_from - relativedelta(months=1)
            last_day = calendar.monthrange(prev_from.year, prev_from.month)[1]
            return prev_from, prev_from.replace(day=last_day)

        if granularity == 'quarter':
            prev_from = date_from - relativedelta(months=3)
            end_month = prev_from + relativedelta(months=2)
            last_day = calendar.monthrange(end_month.year, end_month.month)[1]
            return prev_from, end_month.replace(day=last_day)

        if granularity == 'year':
            return date_from - relativedelta(years=1), date_to - relativedelta(years=1)

        period_length = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_length - 1)
        return prev_from, prev_to

    def _get_comparison_options_list(self, options):
        """Build [current_period_options, previous_period_options, ...],
        one dict per period the report should display, each a copy of
        `options` with date_from/date_to shifted back one period and a
        display label attached. Comparison is entirely a data concern: the
        frontend just renders one extra column-group per period returned
        here, with no logic of its own."""
        comparison_count = options.get('comparison_periods') or 0
        granularity = options.get('period_granularity')

        current = dict(options)
        current['period_label'] = self._format_period_label(options['date_from'], options['date_to'])
        options_list = [current]

        cursor_from = fields.Date.from_string(options['date_from'])
        cursor_to = fields.Date.from_string(options['date_to'])

        for _ in range(comparison_count):
            cursor_from, cursor_to = self._shift_period_back(cursor_from, cursor_to, granularity)
            period_options = dict(options)
            period_options['date_from'] = fields.Date.to_string(cursor_from)
            period_options['date_to'] = fields.Date.to_string(cursor_to)
            period_options['period_label'] = self._format_period_label(
                period_options['date_from'], period_options['date_to'],
            )
            options_list.append(period_options)

        return options_list

    def _get_default_report_currency_id(self):
        """The currency figures are shown in when the user hasn't picked one
        explicitly via the currency filter: the single selected company's
        own currency when there's only one, or the active company's
        currency (env.company, i.e. whichever one is "current" in the
        multi-company switcher) when several companies - possibly with
        different currencies - are selected at once."""
        companies = self.env.companies
        if len(companies) == 1:
            return companies.currency_id
        return self.env.company.currency_id

    def action_get_available_currencies(self):
        """Public RPC entry point feeding the frontend's currency filter
        dropdown: only the currencies actually used by the currently
        selected companies, not every active res.currency - a report never
        needs to be shown in a currency none of its companies use."""
        currencies = self.env.companies.currency_id
        return [
            {'id': currency.id, 'name': currency.name, 'symbol': currency.symbol}
            for currency in currencies.sorted('name')
        ]

    def _convert_amount_to_report_currency(self, amount, company, target_currency, date):
        """Convert `amount` (in `company`'s own currency) into
        `target_currency` as of `date`. Deliberately round=False - rounding
        happens once, at display time (the frontend's formatAmount), not on
        every intermediate conversion, so summing several companies'
        converted subtotals (or accumulating a running balance row by row)
        doesn't drift from rounding the same figure repeatedly."""
        if not amount or company.currency_id == target_currency:
            return amount
        return company.currency_id._convert(amount, target_currency, company, date, round=False)

    def _convert_and_sum_by_company(self, amount_by_company_id, target_currency, date):
        """{company_id: amount} (each amount in that company's own
        currency) -> single float, every amount converted into
        target_currency first. Used everywhere a group-by query mixes rows
        from more than one company (a shared account/partner/tax can have
        postings from companies with different currencies) - summing the
        raw amounts directly would silently blend currencies."""
        if not amount_by_company_id:
            return 0.0
        companies_by_id = {c.id: c for c in self.env['res.company'].browse(list(amount_by_company_id.keys()))}
        return sum(
            self._convert_amount_to_report_currency(amount, companies_by_id[company_id], target_currency, date)
            for company_id, amount in amount_by_company_id.items()
        )

    def action_get_available_journals(self):
        """Public RPC entry point feeding the frontend's journal filter dropdown."""
        journals = self.env['account.journal'].search(
            [('company_id', 'in', self.env.companies.ids)], order='sequence, name',
        )
        return [{'id': journal.id, 'name': journal.name} for journal in journals]

    def action_get_available_partners(self):
        """Public RPC entry point feeding Partner Ledger's partner filter
        dropdown: only partners with at least one receivable/payable
        journal item, not every res.partner record, so the list stays a
        manageable size (the report itself is scoped the same way)."""
        partners = self.env['account.move.line'].search([
            ('company_id', 'in', self.env.companies.ids),
            ('account_id.account_type', 'in', ('asset_receivable', 'liability_payable')),
            ('partner_id', '!=', False),
        ]).partner_id
        return [{'id': partner.id, 'name': partner.name} for partner in partners.sorted('name')]

    def _base_entries_domain(self, options):
        """Shared by the three bespoke handlers below: company scope (the
        user's currently allowed companies, not just env.company - see the
        matching comment in account.report.expression._base_aml_domain),
        posted-vs-all, and journal filter. Each handler still appends its
        own account_type/date/partner conditions on top of this.
        """
        domain = [('company_id', 'in', self.env.companies.ids)]
        if not options.get('all_entries'):
            domain.append(('parent_state', '=', 'posted'))
        if options.get('journal_ids'):
            domain.append(('journal_id', 'in', options['journal_ids']))
        return domain

    def _group_balance(self, domain, groupby_field, target_currency, date):
        """One GROUP BY query -> {key_id: balance_sum}, converted into
        target_currency as of `date`. Shared by General Ledger and Partner
        Ledger's opening-balance computation (the only difference between
        them there is grouping by account_id vs partner_id).

        Grouped by (groupby_field, company_id) rather than just
        groupby_field: an account/partner can have postings from more than
        one company (shared chart of accounts), and those companies can use
        different currencies - summing their raw balances together would
        silently blend currencies, so each company's subtotal is converted
        before being added to the others.
        """
        groups = self.env['account.move.line']._read_group(
            domain, groupby=[groupby_field, 'company_id'], aggregates=['balance:sum'],
        )
        by_key = {}
        for record, company, value in groups:
            by_key.setdefault(record.id, {})[company.id] = value or 0.0
        return {
            key: self._convert_and_sum_by_company(amount_by_company, target_currency, date)
            for key, amount_by_company in by_key.items()
        }

    def _group_balance_and_count(self, domain, groupby_field, target_currency, date):
        """Like _group_balance, but also returns a count per key - used for
        the period-movement query, where a zero *sum* isn't enough to tell
        "no activity" apart from "activity that happened to net to zero"
        (e.g. a same-period reversal); only a zero *count* means the former."""
        groups = self.env['account.move.line']._read_group(
            domain, groupby=[groupby_field, 'company_id'], aggregates=['balance:sum', 'id:count'],
        )
        by_key = {}
        counts = {}
        for record, company, value, count in groups:
            by_key.setdefault(record.id, {})[company.id] = value or 0.0
            counts[record.id] = counts.get(record.id, 0) + count
        balances = {
            key: self._convert_and_sum_by_company(amount_by_company, target_currency, date)
            for key, amount_by_company in by_key.items()
        }
        return balances, counts

    def _group_aml_rows(self, domain, groupby_field, key_ids, limit=None):
        """{key_id: (rows, has_more)}, only called with the keys that are
        actually unfolded, so a collapsed account/partner never pays for
        rows nobody will see.

        limit=None (export_mode only: a PDF/XLSX export is supposed to
        contain everything): one query covering every key_id at once,
        fetching every matching row - has_more is always False.

        limit=N (normal interactive browsing): one bounded query *per*
        key_id (order by date, id, LIMIT N+1, so a group with more than N
        matching rows is detected as has_more=True without a separate
        COUNT query). Bounded per key rather than combined into one query,
        because a single account/partner could itself hold far more than N
        rows - a combined query with one shared LIMIT wouldn't guarantee
        each key gets its fair share of rows.
        """
        if not key_ids:
            return {}

        if limit is None:
            detail_domain = domain + [(groupby_field, 'in', key_ids)]
            result = {}
            for aml in self.env['account.move.line'].search(detail_domain, order=f'{groupby_field}, date, id'):
                result.setdefault(aml[groupby_field].id, []).append(aml)
            return {key: (rows, False) for key, rows in result.items()}

        result = {}
        for key_id in key_ids:
            key_domain = domain + [(groupby_field, '=', key_id)]
            rows = self.env['account.move.line'].search(key_domain, order='date, id', limit=limit + 1)
            has_more = len(rows) > limit
            result[key_id] = (rows[:limit] if has_more else rows, has_more)
        return result

    def _get_more_aml_rows(self, domain, after_date, after_id, limit=AML_PAGE_SIZE):
        """Keyset-paginated continuation of an already-unfolded group's
        journal-item list, used by the "Load more" button:
        WHERE (date, id) > (after_date, after_id), same ORDER BY as the
        initial fetch, so this always returns exactly the next page
        regardless of how deep the group already is - unlike OFFSET-based
        pagination, which gets slower to compute the deeper you page,
        this stays equally fast on page 1 and page 1000."""
        cursor_domain = list(domain)
        if after_date:
            cursor_domain += [
                '|', ('date', '>', after_date),
                '&', ('date', '=', after_date), ('id', '>', after_id),
            ]
        else:
            cursor_domain.append(('id', '>', after_id))
        rows = self.env['account.move.line'].search(cursor_domain, order='date, id', limit=limit + 1)
        has_more = len(rows) > limit
        return (rows[:limit] if has_more else rows), has_more

    def _has_unposted_entries(self, options):
        domain = [('company_id', 'in', self.env.companies.ids), ('parent_state', '=', 'draft')]
        if options.get('date_to'):
            domain.append(('date', '<=', options['date_to']))
        if options.get('journal_ids'):
            domain.append(('journal_id', 'in', options['journal_ids']))
        return bool(self.env['account.move.line'].search_count(domain, limit=1))

    def _get_report_currency(self, options):
        """The currency every figure in this report's response is expressed
        in: whatever the currency filter resolved to (see
        _get_default_report_currency_id), not necessarily env.company's."""
        currency_id = options.get('currency_id')
        currency = self.env['res.currency'].browse(currency_id) if currency_id else self.env['res.currency']
        return currency if currency else self._get_default_report_currency_id()

    def _get_currency_info(self, options):
        """Self-contained currency descriptor sent to the frontend so it can
        format amounts with the right symbol/position/decimals without
        having to reach into Odoo's client-side session internals (whose
        exact shape isn't something this module controls or can verify
        against without a live browser)."""
        currency = self._get_report_currency(options)
        return {
            'symbol': currency.symbol,
            'position': currency.position,
            'decimal_places': currency.decimal_places,
        }

    def _get_report_data(self, options):
        self.ensure_one()
        if self.report_handler == 'general_ledger':
            return self._get_general_ledger_data(options)
        if self.report_handler == 'partner_ledger':
            return self._get_partner_ledger_data(options)
        if self.report_handler == 'aged_partner_balance':
            return self._get_aged_partner_balance_data(options)
        if self.report_handler == 'tax_report':
            return self._get_tax_report_data(options)
        if self.report_handler == 'journal_report':
            return self._get_journal_report_data(options)
        return self._get_generic_report_data(options)

    def _get_generic_report_data(self, options):
        self.ensure_one()
        columns = [{
            'name': column.name,
            'expression_label': column.expression_label,
            'figure_type': column.figure_type,
        } for column in self.column_ids.sorted('sequence')]

        options_list = self._get_comparison_options_list(options)
        periods = [{
            'label': period_options['period_label'],
            'date_from': period_options['date_from'],
            'date_to': period_options['date_to'],
        } for period_options in options_list]

        top_level_lines = self.line_ids.filtered(lambda line: not line.parent_id).sorted('sequence')
        lines = [line._build_line_row(options_list) for line in top_level_lines]

        gl_report = self.env.ref(GENERAL_LEDGER_REPORT_XMLID, raise_if_not_found=False)

        return {
            'report_id': self.id,
            'report_name': self.name,
            'report_handler': self.report_handler,
            'options': options,
            'columns': columns,
            'periods': periods,
            'lines': lines,
            'general_ledger_report_id': gl_report.id if gl_report else False,
            'has_unposted_entries': self._has_unposted_entries(options),
            'currency': self._get_currency_info(options),
        }

    def _convert_aml_field(self, aml, field, target_currency, date):
        """One account.move.line's `field` (debit/credit/balance/
        tax_base_amount/amount_residual - all stored in aml.company_id's
        own currency), converted into target_currency as of `date`. Every
        raw-row builder below routes its monetary fields through this
        instead of reading them directly, since a single row always
        belongs to exactly one company (unlike the group-by aggregates in
        _group_balance, which can span several)."""
        return self._convert_amount_to_report_currency(aml[field], aml.company_id, target_currency, date)

    def _build_gl_row(self, aml, running_balance, target_currency, date):
        return {
            'id': aml.id,
            'move_id': aml.move_id.id,
            'date': fields.Date.to_string(aml.date),
            'move_name': aml.move_id.name,
            'journal': aml.journal_id.name,
            'partner': aml.partner_id.name or '',
            'label': aml.name or '',
            'debit': self._convert_aml_field(aml, 'debit', target_currency, date),
            'credit': self._convert_aml_field(aml, 'credit', target_currency, date),
            'running_balance': running_balance,
            # debit/credit/running_balance are all in the report's target
            # currency (converted above); these two are only populated
            # (non-null) when the transaction itself was in a foreign
            # currency, so a foreign invoice's original amount stays
            # visible at the line level even though it's been converted
            # for every totals/bucket figure.
            'foreign_currency_name': aml.currency_id.name if aml.currency_id != aml.company_currency_id else None,
            'amount_currency': aml.amount_currency if aml.currency_id != aml.company_currency_id else None,
        }

    def _get_general_ledger_aml_domain(self, options, account_id):
        """The move-line domain for one account's journal-item list -
        shared by the initial fetch (_get_general_ledger_data) and the
        "Load more" continuation (_get_more_general_ledger_rows), so both
        always agree on exactly which rows belong to this account/period."""
        entries_domain = self._base_entries_domain(options) + [('account_id', '=', account_id)]
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        if date_from:
            entries_domain.append(('date', '>=', date_from))
        if date_to:
            entries_domain.append(('date', '<=', date_to))
        return entries_domain

    def _get_more_general_ledger_rows(self, options, account_id, after_date, after_id, after_running_balance):
        domain = self._get_general_ledger_aml_domain(options, account_id)
        rows, has_more = self._get_more_aml_rows(domain, after_date, after_id)
        target_currency = self._get_report_currency(options)
        date = options.get('date_to')
        running_balance = after_running_balance or 0.0
        row_dicts = []
        for aml in rows:
            running_balance += self._convert_aml_field(aml, 'balance', target_currency, date)
            row_dicts.append(self._build_gl_row(aml, running_balance, target_currency, date))
        return {'aml_rows': row_dicts, 'aml_rows_has_more': has_more}

    def _get_general_ledger_data(self, options):
        """Bespoke handler: one row per account (opening balance + raw
        journal items + closing balance), rather than the aggregated
        expression-tree the generic engine computes. See the account_codes/
        domain/aggregation evaluators in account.report.expression for why a
        raw item listing doesn't fit that model.

        Query count is O(1) in the number of accounts, not O(n): opening
        balances and period movement are each one GROUP BY query covering
        every account at once, and the raw journal-item rows are fetched
        one bounded page (AML_PAGE_SIZE) at a time, but only for accounts
        that are actually unfolded - there's no point loading rows for a
        collapsed account nobody is looking at, and no point loading more
        than one page until the user asks for more via "Load more".
        """
        self.ensure_one()

        account_domain = []
        focus_account_id = options.get('focus_account_id')
        if focus_account_id:
            account_domain.append(('id', '=', focus_account_id))
        search = options.get('search')
        if search:
            account_domain += ['|', ('code', 'ilike', search), ('name', 'ilike', search)]
        accounts = self.env['account.account'].search(account_domain, order='code')
        if not accounts:
            return {
                'report_id': self.id, 'report_name': self.name, 'report_handler': self.report_handler,
                'options': options, 'lines': [], 'has_unposted_entries': self._has_unposted_entries(options),
                'currency': self._get_currency_info(options),
            }

        date_from = options.get('date_from')
        date_to = options.get('date_to')
        unfolded_ids = set(options.get('unfolded_line_ids') or [])
        entries_domain = self._base_entries_domain(options)
        target_currency = self._get_report_currency(options)

        opening_domain = entries_domain + [('account_id', 'in', accounts.ids)]
        if date_from:
            opening_domain.append(('date', '<', date_from))
        opening_balances = self._group_balance(opening_domain, 'account_id', target_currency, date_to)

        period_domain = entries_domain + [('account_id', 'in', accounts.ids)]
        if date_from:
            period_domain.append(('date', '>=', date_from))
        if date_to:
            period_domain.append(('date', '<=', date_to))
        period_movement, period_count = self._group_balance_and_count(period_domain, 'account_id', target_currency, date_to)

        export_mode = options.get('export_mode')
        unfolded_account_ids = accounts.ids if export_mode else [
            account.id for account in accounts if account.id in unfolded_ids
        ]
        aml_by_account = self._group_aml_rows(
            period_domain, 'account_id', unfolded_account_ids, limit=None if export_mode else AML_PAGE_SIZE,
        )

        lines = []
        for account in accounts:
            opening_balance = opening_balances.get(account.id, 0.0)
            movement = period_movement.get(account.id, 0.0)
            if not period_count.get(account.id) and not opening_balance:
                continue

            unfolded = export_mode or account.id in unfolded_ids
            aml_rows = []
            has_more = False
            if unfolded:
                running_balance = opening_balance
                rows, has_more = aml_by_account.get(account.id, ([], False))
                for aml in rows:
                    running_balance += self._convert_aml_field(aml, 'balance', target_currency, date_to)
                    aml_rows.append(self._build_gl_row(aml, running_balance, target_currency, date_to))

            lines.append({
                'id': account.id,
                'account_id': account.id,
                'name': f'{account.code} {account.name}',
                'opening_balance': opening_balance,
                'closing_balance': opening_balance + movement,
                'foldable': True,
                'unfolded': unfolded,
                'aml_rows': aml_rows,
                'aml_rows_has_more': has_more,
            })

        return {
            'report_id': self.id,
            'report_name': self.name,
            'report_handler': self.report_handler,
            'options': options,
            'lines': lines,
            'has_unposted_entries': self._has_unposted_entries(options),
            'currency': self._get_currency_info(options),
        }

    def _build_partner_ledger_row(self, aml, running_balance, target_currency, date):
        return {
            'id': aml.id,
            'move_id': aml.move_id.id,
            'date': fields.Date.to_string(aml.date),
            'move_name': aml.move_id.name,
            'journal': aml.journal_id.name,
            'account': aml.account_id.display_name,
            'label': aml.name or '',
            'debit': self._convert_aml_field(aml, 'debit', target_currency, date),
            'credit': self._convert_aml_field(aml, 'credit', target_currency, date),
            'running_balance': running_balance,
            # Populated only when the transaction was in a foreign
            # currency - see the matching comment in _get_general_ledger_data.
            'foreign_currency_name': aml.currency_id.name if aml.currency_id != aml.company_currency_id else None,
            'amount_currency': aml.amount_currency if aml.currency_id != aml.company_currency_id else None,
        }

    def _get_partner_ledger_aml_domain(self, options, partner_id):
        """The move-line domain for one partner's journal-item list -
        shared by the initial fetch and the "Load more" continuation."""
        entries_domain = self._base_entries_domain(options) + [
            ('account_id.account_type', 'in', ('asset_receivable', 'liability_payable')),
            ('partner_id', '=', partner_id),
        ]
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        if date_from:
            entries_domain.append(('date', '>=', date_from))
        if date_to:
            entries_domain.append(('date', '<=', date_to))
        return entries_domain

    def _get_more_partner_ledger_rows(self, options, partner_id, after_date, after_id, after_running_balance):
        domain = self._get_partner_ledger_aml_domain(options, partner_id)
        rows, has_more = self._get_more_aml_rows(domain, after_date, after_id)
        target_currency = self._get_report_currency(options)
        date = options.get('date_to')
        running_balance = after_running_balance or 0.0
        row_dicts = []
        for aml in rows:
            running_balance += self._convert_aml_field(aml, 'balance', target_currency, date)
            row_dicts.append(self._build_partner_ledger_row(aml, running_balance, target_currency, date))
        return {'aml_rows': row_dicts, 'aml_rows_has_more': has_more}

    def _get_partner_ledger_data(self, options):
        """Bespoke handler: one row per partner (opening balance + raw
        journal items + closing balance) across their receivable/payable
        movements, mirroring _get_general_ledger_data but grouped by
        partner_id instead of account_id -- this is the report an
        accountant reaches for to reconcile a specific customer/vendor's
        running balance rather than a single account's.

        Unlike _get_general_ledger_data (which enumerates account.account
        first - a bounded, admin-controlled list), this derives the partner
        list directly from qualifying account.move.line rows rather than
        searching res.partner first: a company can have thousands of
        contacts but only a handful with any receivable/payable activity,
        so searching res.partner up front would mean iterating far more
        rows than actually matter. Search/partner_ids/focus_partner_id
        filters are expressed as conditions on the move-line domain instead
        of a separate partner search.
        """
        self.ensure_one()

        date_from = options.get('date_from')
        date_to = options.get('date_to')
        unfolded_ids = set(options.get('unfolded_line_ids') or [])
        entries_domain = self._base_entries_domain(options)
        entries_domain.append(('account_id.account_type', 'in', ('asset_receivable', 'liability_payable')))
        entries_domain.append(('partner_id', '!=', False))

        focus_partner_id = options.get('focus_partner_id')
        if focus_partner_id:
            entries_domain.append(('partner_id', '=', focus_partner_id))
        if options.get('partner_ids'):
            entries_domain.append(('partner_id', 'in', options['partner_ids']))
        search = options.get('search')
        if search:
            entries_domain.append(('partner_id.name', 'ilike', search))

        target_currency = self._get_report_currency(options)

        opening_domain = entries_domain[:]
        if date_from:
            opening_domain.append(('date', '<', date_from))
        opening_balances = self._group_balance(opening_domain, 'partner_id', target_currency, date_to)

        period_domain = entries_domain[:]
        if date_from:
            period_domain.append(('date', '>=', date_from))
        if date_to:
            period_domain.append(('date', '<=', date_to))
        period_movement, period_count = self._group_balance_and_count(period_domain, 'partner_id', target_currency, date_to)

        partner_ids = set(opening_balances) | set(period_movement)
        partners_by_id = {partner.id: partner for partner in self.env['res.partner'].browse(partner_ids)}

        export_mode = options.get('export_mode')
        unfolded_partner_ids = list(partner_ids) if export_mode else [
            pid for pid in partner_ids if pid in unfolded_ids
        ]
        aml_by_partner = self._group_aml_rows(
            period_domain, 'partner_id', unfolded_partner_ids, limit=None if export_mode else AML_PAGE_SIZE,
        )

        lines = []
        for partner_id, partner in partners_by_id.items():
            opening_balance = opening_balances.get(partner_id, 0.0)
            movement = period_movement.get(partner_id, 0.0)
            if not period_count.get(partner_id) and not opening_balance:
                continue

            unfolded = export_mode or partner_id in unfolded_ids
            aml_rows = []
            has_more = False
            if unfolded:
                running_balance = opening_balance
                rows, has_more = aml_by_partner.get(partner_id, ([], False))
                for aml in rows:
                    running_balance += self._convert_aml_field(aml, 'balance', target_currency, date_to)
                    aml_rows.append(self._build_partner_ledger_row(aml, running_balance, target_currency, date_to))

            lines.append({
                'id': partner_id,
                'partner_id': partner_id,
                'name': partner.name,
                'opening_balance': opening_balance,
                'closing_balance': opening_balance + movement,
                'foldable': True,
                'unfolded': unfolded,
                'aml_rows': aml_rows,
                'aml_rows_has_more': has_more,
            })

        lines.sort(key=lambda line: line['name'] or '')

        return {
            'report_id': self.id,
            'report_name': self.name,
            'report_handler': self.report_handler,
            'options': options,
            'lines': lines,
            'has_unposted_entries': self._has_unposted_entries(options),
            'currency': self._get_currency_info(options),
        }

    def _get_aged_bucket(self, days_overdue):
        if days_overdue <= 0:
            return 'not_due'
        if days_overdue <= 30:
            return 'b1_30'
        if days_overdue <= 60:
            return 'b31_60'
        if days_overdue <= 90:
            return 'b61_90'
        return 'older'

    def _build_aged_row(self, aml, as_of_date_d, sign, target_currency, date):
        due_date = aml.date_maturity or aml.date
        days_overdue = (as_of_date_d - due_date).days
        bucket = self._get_aged_bucket(days_overdue)
        amount = sign * self._convert_aml_field(aml, 'amount_residual', target_currency, date)
        return bucket, amount, {
            'id': aml.id,
            'move_id': aml.move_id.id,
            'date': fields.Date.to_string(aml.date),
            'due_date': fields.Date.to_string(due_date),
            'move_name': aml.move_id.name,
            'label': aml.name or '',
            'bucket': bucket,
            'amount': amount,
            # Populated only when the invoice/bill was in a foreign
            # currency - see the matching comment in
            # _get_general_ledger_data. amount_residual_currency is the
            # residual expressed in that original currency.
            'foreign_currency_name': aml.currency_id.name if aml.currency_id != aml.company_currency_id else None,
            'amount_residual_currency': (
                sign * aml.amount_residual_currency if aml.currency_id != aml.company_currency_id else None
            ),
        }

    def _get_aged_partner_balance_aml_domain(self, options, partner_id):
        """The move-line domain for one partner's open items - shared by
        the initial fetch and the "Load more" continuation."""
        as_of_date = options.get('date_to')
        domain = self._base_entries_domain(options) + [
            ('account_id.account_type', '=', self.aged_account_type),
            ('amount_residual', '!=', 0.0),
            ('partner_id', '=', partner_id),
        ]
        if as_of_date:
            domain.append(('date', '<=', as_of_date))
        return domain

    def _get_more_aged_partner_balance_rows(self, options, partner_id, after_maturity, after_date, after_id):
        """Aged Balance sorts by (date_maturity, date, id) rather than the
        (date, id) every other handler's "Load more" cursors on - due date
        is what actually matters for an aging report - so this needs its
        own 3-key keyset cursor instead of the shared _get_more_aml_rows."""
        as_of_date = options.get('date_to')
        as_of_date_d = fields.Date.from_string(as_of_date) if as_of_date else fields.Date.context_today(self)
        sign = -1.0 if self.aged_account_type == 'liability_payable' else 1.0
        target_currency = self._get_report_currency(options)

        domain = self._get_aged_partner_balance_aml_domain(options, partner_id)
        if after_maturity:
            domain += [
                '|', ('date_maturity', '>', after_maturity),
                '&', ('date_maturity', '=', after_maturity),
                '|', ('date', '>', after_date),
                '&', ('date', '=', after_date), ('id', '>', after_id),
            ]
        else:
            domain.append(('id', '>', after_id))

        rows = self.env['account.move.line'].search(
            domain, order='date_maturity, date, id', limit=AML_PAGE_SIZE + 1,
        )
        has_more = len(rows) > AML_PAGE_SIZE
        rows = rows[:AML_PAGE_SIZE] if has_more else rows
        row_dicts = [self._build_aged_row(aml, as_of_date_d, sign, target_currency, as_of_date)[2] for aml in rows]
        return {'aml_rows': row_dicts, 'aml_rows_has_more': has_more}

    def _get_aged_partner_balance_data(self, options):
        """Bespoke handler: one row per partner, with their open
        receivable/payable items bucketed by how overdue they are as of
        the report's `date_to` (the "as of" date - `date_from` is unused,
        matching how every aged report works: it's a snapshot at a single
        point in time, not movement across a range).

        Simplification worth being explicit about: buckets are built from
        each line's *current* `amount_residual`, filtered to lines dated on
        or before the as-of date. That's exact when the as-of date is
        today (the common case) and an approximation for a past as-of date
        if a reconciliation happened after that date - a fully historical
        version would need to walk partial-reconciliation dates, which this
        module doesn't implement.

        Bucket totals need per-item due-date comparison, which can't be
        pushed into a SQL sum the way GL/Partner Ledger's opening/closing
        balances can - so unlike those two, this always needs the actual
        rows, folded or not. What's still worth batching is *how many
        queries* that costs: one search() for every qualifying open item
        across every partner at once, grouped in Python by partner_id,
        instead of one search per partner (previously this also queried
        res.partner first, up to thousands of rows, to find which partners
        to loop over, when only a handful ever have receivable/payable
        activity - deriving the partner list from the move lines themselves
        avoids that too).
        """
        self.ensure_one()
        AccountMoveLine = self.env['account.move.line']
        as_of_date = options.get('date_to')
        as_of_date_d = fields.Date.from_string(as_of_date) if as_of_date else fields.Date.context_today(self)

        unfolded_ids = set(options.get('unfolded_line_ids') or [])
        entries_domain = self._base_entries_domain(options)
        entries_domain += [
            ('account_id.account_type', '=', self.aged_account_type),
            ('amount_residual', '!=', 0.0),
            ('partner_id', '!=', False),
        ]
        if as_of_date:
            entries_domain.append(('date', '<=', as_of_date))

        focus_partner_id = options.get('focus_partner_id')
        if focus_partner_id:
            entries_domain.append(('partner_id', '=', focus_partner_id))
        if options.get('partner_ids'):
            entries_domain.append(('partner_id', 'in', options['partner_ids']))
        search = options.get('search')
        if search:
            entries_domain.append(('partner_id.name', 'ilike', search))

        # Payable accounts are credit-normal, so amount_residual reads
        # negative for an unpaid bill; negate so "amount we owe" displays
        # positive, same convention used for 'balance' throughout this module.
        sign = -1.0 if self.aged_account_type == 'liability_payable' else 1.0
        target_currency = self._get_report_currency(options)

        aml_by_partner = {}
        for aml in AccountMoveLine.search(entries_domain, order='partner_id, date_maturity, date, id'):
            aml_by_partner.setdefault(aml.partner_id.id, []).append(aml)

        export_mode = options.get('export_mode')
        lines = []
        for partner_id, aml_records in aml_by_partner.items():
            partner = aml_records[0].partner_id
            buckets = {key: 0.0 for key, _label in AGED_BUCKET_DEFS}
            all_row_dicts = []
            # Bucket totals need every open item regardless of fold state
            # (see the docstring above) - only how many of them get sent
            # to the browser as aml_rows is paginated/fold-gated.
            for aml in aml_records:
                bucket, amount, row_dict = self._build_aged_row(aml, as_of_date_d, sign, target_currency, as_of_date)
                buckets[bucket] += amount
                all_row_dicts.append(row_dict)

            unfolded = export_mode or partner_id in unfolded_ids
            if unfolded and export_mode:
                aml_rows, has_more = all_row_dicts, False
            elif unfolded:
                aml_rows = all_row_dicts[:AML_PAGE_SIZE]
                has_more = len(all_row_dicts) > AML_PAGE_SIZE
            else:
                aml_rows, has_more = [], False

            lines.append({
                'id': partner_id,
                'partner_id': partner_id,
                'name': partner.name,
                'buckets': buckets,
                'total': sum(buckets.values()),
                'foldable': True,
                'unfolded': unfolded,
                'aml_rows': aml_rows,
                'aml_rows_has_more': has_more,
            })

        lines.sort(key=lambda line: line['name'] or '')

        return {
            'report_id': self.id,
            'report_name': self.name,
            'report_handler': self.report_handler,
            'options': options,
            'bucket_columns': [{'key': key, 'label': label} for key, label in AGED_BUCKET_DEFS],
            'lines': lines,
            'has_unposted_entries': self._has_unposted_entries(options),
            'currency': self._get_currency_info(options),
        }

    def _build_tax_row(self, aml, sign, target_currency, date):
        # Both figures need the same sign flip: tax_base_amount is stored
        # with the tax line's own credit-normal-for-sale-taxes sign (e.g.
        # -1000 for a 1000 sale), same as balance - applying `sign` to only
        # one of the two would make the header total and this drilled-down
        # row disagree on the base amount's sign.
        return {
            'id': aml.id,
            'move_id': aml.move_id.id,
            'date': fields.Date.to_string(aml.date),
            'move_name': aml.move_id.name,
            'partner': aml.partner_id.name or '',
            'base_amount': sign * self._convert_aml_field(aml, 'tax_base_amount', target_currency, date),
            'tax_amount': sign * self._convert_aml_field(aml, 'balance', target_currency, date),
        }

    def _get_tax_report_aml_domain(self, options, tax_id):
        """The move-line domain for one tax's contributing journal items -
        shared by the initial fetch and the "Load more" continuation."""
        domain = self._base_entries_domain(options) + [('tax_line_id', '=', tax_id)]
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    def _get_more_tax_report_rows(self, options, tax_id, after_date, after_id):
        tax = self.env['account.tax'].browse(tax_id)
        sign = -1.0 if tax.type_tax_use == 'sale' else 1.0
        domain = self._get_tax_report_aml_domain(options, tax_id)
        rows, has_more = self._get_more_aml_rows(domain, after_date, after_id)
        target_currency = self._get_report_currency(options)
        date = options.get('date_to')
        return {
            'aml_rows': [self._build_tax_row(aml, sign, target_currency, date) for aml in rows],
            'aml_rows_has_more': has_more,
        }

    def _get_tax_report_data(self, options):
        """Bespoke handler: one row per tax (base amount + tax amount for
        the period), grouped from account.move.line.tax_line_id/
        tax_base_amount directly, rather than through the tax_tags grid
        system (account.account.tag). This is deliberately the simpler
        "group by tax" view rather than the official tax-grid layout a
        specific country localization would define: tax_tag_ids only carry
        real grid numbers once a country's fiscal localization module sets
        them up, which a generic dev chart doesn't have, whereas
        tax_line_id/tax_base_amount are populated by Odoo's tax engine on
        every posted transaction regardless of localization. Enterprise
        itself offers exactly this same "Group by: Account > Tax" alternate
        view for the same reason.
        """
        self.ensure_one()
        AccountMoveLine = self.env['account.move.line']

        entries_domain = self._base_entries_domain(options)
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        if date_from:
            entries_domain.append(('date', '>=', date_from))
        if date_to:
            entries_domain.append(('date', '<=', date_to))
        entries_domain.append(('tax_line_id', '!=', False))
        search = options.get('search')
        if search:
            entries_domain.append(('tax_line_id.name', 'ilike', search))

        unfolded_ids = set(options.get('unfolded_line_ids') or [])
        target_currency = self._get_report_currency(options)
        date_to = options.get('date_to')

        # Grouped by (tax, company) rather than just tax: the same tax can
        # be used by more than one company (companies frequently share a
        # tax template), and those companies can use different currencies -
        # summing their raw balances/base amounts together would silently
        # blend currencies, so each company's subtotal is converted before
        # being added to the others.
        groups = AccountMoveLine._read_group(
            entries_domain, groupby=['tax_line_id', 'company_id'],
            aggregates=['balance:sum', 'tax_base_amount:sum', 'id:count'],
        )
        balance_by_tax = {}
        base_by_tax = {}
        count_by_tax = {}
        taxes_by_id = {}
        for tax, company, balance, base_amount, count in groups:
            taxes_by_id[tax.id] = tax
            balance_by_tax.setdefault(tax.id, {})[company.id] = balance or 0.0
            base_by_tax.setdefault(tax.id, {})[company.id] = base_amount or 0.0
            count_by_tax[tax.id] = count_by_tax.get(tax.id, 0) + count

        export_mode = options.get('export_mode')
        unfolded_tax_ids = [
            tax_id for tax_id, count in count_by_tax.items()
            if count and (export_mode or tax_id in unfolded_ids)
        ]
        aml_by_tax = self._group_aml_rows(
            entries_domain, 'tax_line_id', unfolded_tax_ids, limit=None if export_mode else AML_PAGE_SIZE,
        )

        lines = []
        for tax_id, tax in taxes_by_id.items():
            count = count_by_tax.get(tax_id, 0)
            if not count:
                continue

            # Sale taxes are credit-normal (a liability: tax collected but
            # not yet remitted), so their raw balance reads negative;
            # negate so "tax collected" displays positive, same convention
            # used for liability-side figures throughout this module.
            sign = -1.0 if tax.type_tax_use == 'sale' else 1.0
            unfolded = export_mode or tax_id in unfolded_ids

            aml_rows = []
            has_more = False
            if unfolded:
                rows, has_more = aml_by_tax.get(tax_id, ([], False))
                aml_rows = [self._build_tax_row(aml, sign, target_currency, date_to) for aml in rows]

            balance = self._convert_and_sum_by_company(balance_by_tax.get(tax_id, {}), target_currency, date_to)
            base_amount = self._convert_and_sum_by_company(base_by_tax.get(tax_id, {}), target_currency, date_to)
            lines.append({
                'id': tax_id,
                'tax_id': tax_id,
                'name': tax.name,
                'tax_type': tax.type_tax_use,
                'base_amount': sign * base_amount,
                'tax_amount': sign * balance,
                'foldable': True,
                'unfolded': unfolded,
                'aml_rows': aml_rows,
                'aml_rows_has_more': has_more,
            })

        # Sale taxes first (what you collected), then purchase taxes (what
        # you paid), alphabetical within each group.
        lines.sort(key=lambda line: (line['tax_type'] != 'sale', line['name'] or ''))

        return {
            'report_id': self.id,
            'report_name': self.name,
            'report_handler': self.report_handler,
            'options': options,
            'lines': lines,
            'has_unposted_entries': self._has_unposted_entries(options),
            'currency': self._get_currency_info(options),
        }

    def _build_journal_row(self, aml, target_currency, date):
        return {
            'id': aml.id,
            'move_id': aml.move_id.id,
            'date': fields.Date.to_string(aml.date),
            'move_name': aml.move_id.name,
            'account': aml.account_id.display_name,
            'partner': aml.partner_id.name or '',
            'label': aml.name or '',
            'debit': self._convert_aml_field(aml, 'debit', target_currency, date),
            'credit': self._convert_aml_field(aml, 'credit', target_currency, date),
        }

    def _get_journal_report_aml_domain(self, options, journal_id):
        """The move-line domain for one journal's items - shared by the
        initial fetch and the "Load more" continuation."""
        domain = [] if options.get('all_entries') else [('parent_state', '=', 'posted')]
        domain.append(('company_id', 'in', self.env.companies.ids))
        domain.append(('journal_id', '=', journal_id))
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    def _get_more_journal_report_rows(self, options, journal_id, after_date, after_id):
        domain = self._get_journal_report_aml_domain(options, journal_id)
        rows, has_more = self._get_more_aml_rows(domain, after_date, after_id)
        target_currency = self._get_report_currency(options)
        date = options.get('date_to')
        return {
            'aml_rows': [self._build_journal_row(aml, target_currency, date) for aml in rows],
            'aml_rows_has_more': has_more,
        }

    def _get_journal_report_data(self, options):
        """Bespoke handler: one row per journal (total debit/credit for the
        period + raw journal items), mirroring _get_general_ledger_data but
        grouped by journal_id instead of account_id. Unlike an account or a
        partner, a journal is just a container for entries - it doesn't
        carry a balance across periods - so there's no "opening balance"
        concept here, only a period total.
        """
        self.ensure_one()
        AccountMoveLine = self.env['account.move.line']

        journal_domain = [('company_id', 'in', self.env.companies.ids)]
        search = options.get('search')
        if search:
            journal_domain.append(('name', 'ilike', search))
        journals = self.env['account.journal'].search(journal_domain, order='sequence, name')
        if not journals:
            return {
                'report_id': self.id, 'report_name': self.name, 'report_handler': self.report_handler,
                'options': options, 'lines': [], 'has_unposted_entries': self._has_unposted_entries(options),
                'currency': self._get_currency_info(options),
            }

        date_from = options.get('date_from')
        date_to = options.get('date_to')
        unfolded_ids = set(options.get('unfolded_line_ids') or [])
        target_currency = self._get_report_currency(options)
        entries_domain = [] if options.get('all_entries') else [('parent_state', '=', 'posted')]
        entries_domain.append(('company_id', 'in', self.env.companies.ids))
        entries_domain.append(('journal_id', 'in', journals.ids))
        if date_from:
            entries_domain.append(('date', '>=', date_from))
        if date_to:
            entries_domain.append(('date', '<=', date_to))

        # A journal always belongs to exactly one company (unlike accounts/
        # partners/taxes, which can be shared), so no cross-company blend
        # is possible within a single journal's total - only a straight
        # convert of that one company's amount into the target currency.
        period_totals = AccountMoveLine._read_group(
            entries_domain, groupby=['journal_id'], aggregates=['debit:sum', 'credit:sum', 'id:count'],
        )
        debit_by_journal = {journal.id: (debit or 0.0) for journal, debit, _credit, _count in period_totals}
        credit_by_journal = {journal.id: (credit or 0.0) for journal, _debit, credit, _count in period_totals}
        count_by_journal = {journal.id: count for journal, _debit, _credit, count in period_totals}

        export_mode = options.get('export_mode')
        unfolded_journal_ids = journals.ids if export_mode else [
            journal.id for journal in journals if journal.id in unfolded_ids
        ]
        aml_by_journal = self._group_aml_rows(
            entries_domain, 'journal_id', unfolded_journal_ids, limit=None if export_mode else AML_PAGE_SIZE,
        )

        lines = []
        for journal in journals:
            if not count_by_journal.get(journal.id):
                continue

            unfolded = export_mode or journal.id in unfolded_ids
            aml_rows = []
            has_more = False
            if unfolded:
                rows, has_more = aml_by_journal.get(journal.id, ([], False))
                aml_rows = [self._build_journal_row(aml, target_currency, date_to) for aml in rows]

            lines.append({
                'id': journal.id,
                'journal_id': journal.id,
                'name': journal.name,
                'total_debit': self._convert_amount_to_report_currency(
                    debit_by_journal.get(journal.id, 0.0), journal.company_id, target_currency, date_to),
                'total_credit': self._convert_amount_to_report_currency(
                    credit_by_journal.get(journal.id, 0.0), journal.company_id, target_currency, date_to),
                'foldable': True,
                'unfolded': unfolded,
                'aml_rows': aml_rows,
                'aml_rows_has_more': has_more,
            })

        return {
            'report_id': self.id,
            'report_name': self.name,
            'report_handler': self.report_handler,
            'options': options,
            'lines': lines,
            'has_unposted_entries': self._has_unposted_entries(options),
            'currency': self._get_currency_info(options),
        }

    def action_get_report_data(self, options=None):
        """Public RPC entry point (Odoo blocks direct calls to `_`-prefixed
        methods from the client) used by the OWL frontend to fetch a
        report's computed rows."""
        self.ensure_one()
        resolved_options = self._get_default_options(options or {})
        return self._get_report_data(resolved_options)

    def action_get_more_aml_rows(self, options, group_id, after_id, after_date=None, after_running_balance=None, after_maturity=None):
        """Public RPC entry point for the frontend's "Load more" button:
        returns the next page of journal-item rows for one already-unfolded
        group (an account/partner/tax/journal id, depending on this
        report's report_handler), continuing from (after_date, after_id)
        via keyset pagination - see _get_more_aml_rows for why that scales
        better than OFFSET-based paging. Dispatches by report_handler since
        each bespoke handler's row shape and base domain differ."""
        self.ensure_one()
        resolved_options = self._get_default_options(options or {})
        if self.report_handler == 'general_ledger':
            return self._get_more_general_ledger_rows(resolved_options, group_id, after_date, after_id, after_running_balance)
        if self.report_handler == 'partner_ledger':
            return self._get_more_partner_ledger_rows(resolved_options, group_id, after_date, after_id, after_running_balance)
        if self.report_handler == 'aged_partner_balance':
            return self._get_more_aged_partner_balance_rows(resolved_options, group_id, after_maturity, after_date, after_id)
        if self.report_handler == 'tax_report':
            return self._get_more_tax_report_rows(resolved_options, group_id, after_date, after_id)
        if self.report_handler == 'journal_report':
            return self._get_more_journal_report_rows(resolved_options, group_id, after_date, after_id)
        return {'aml_rows': [], 'aml_rows_has_more': False}
