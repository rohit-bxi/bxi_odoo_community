import ast
import operator
import re
from datetime import timedelta

from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools import date_utils

ACCOUNT_CODES_ENGINE_SPLIT_REGEX = re.compile(r'(?=[+-])')
ACCOUNT_CODES_ENGINE_TERM_REGEX = re.compile(
    r'^(?P<sign>[+-]?)(?P<prefix>[a-zA-Z0-9_.]+?)(?:\\(?:\((?P<excluded_prefixes>[^)]+)\)|(?P<excluded_prefixes_bare>[a-zA-Z0-9_,\.]+)))?(?P<balance_character>[CD])?$'
)

# Original safe-arithmetic evaluator for the 'aggregation' engine, used only
# +-*/() expressions over numbers via a whitelisted AST walk. 
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_AGGREGATION_TOKEN_RE = re.compile(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+|[-+*/()]|\d+(?:\.\d+)?')
_AGGREGATION_REF_RE = re.compile(r'^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$')


def _safe_eval_arithmetic(expr_str):
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[type(node.op)](_eval(node.operand))
        raise UserError(_("Unsafe or invalid aggregation expression: %s", expr_str))
    return _eval(ast.parse(expr_str, mode='eval'))


class AccountReportExpression(models.Model):
    _inherit = 'account.report.expression'

    def _evaluate(self, options, extra_domain=None):
        """Compute this expression's value for the given options.

        :return: (value: float, domains: list[list]) where `domains` is the
                 list of account.move.line domains that contributed to the
                 value (used both to compute it and to power drill-down).
        """
        self.ensure_one()
        date_from, date_to = self._resolve_date_scope(options)
        method = getattr(self, f'_evaluate_{self.engine}', None)
        if method is None:
            raise UserError(_("Computation engine '%s' is not supported.", self.engine))
        return method(options, date_from, date_to, extra_domain)

    def _resolve_date_scope(self, options):
        self.ensure_one()
        date_to = options.get('date_to')
        date_to_d = fields.Date.from_string(date_to) if date_to else fields.Date.context_today(self)
        scope = self.date_scope

        if scope == 'strict_range':
            return options.get('date_from'), date_to
        if scope == 'from_beginning':
            return None, date_to
        if scope == 'to_beginning_of_period':
            date_from = options.get('date_from')
            if not date_from:
                return None, date_to
            date_from_d = fields.Date.from_string(date_from)
            return None, fields.Date.to_string(date_from_d - timedelta(days=1))

        company = self.env.company
        fy_from, _fy_to = date_utils.get_fiscal_year(
            date_to_d, day=company.fiscalyear_last_day, month=int(company.fiscalyear_last_month),
        )
        if scope == 'from_fiscalyear':
            return fields.Date.to_string(fy_from), date_to
        if scope == 'to_beginning_of_fiscalyear':
            return None, fields.Date.to_string(fy_from - timedelta(days=1))

        raise UserError(_("Date scope '%s' is not supported yet.", scope))

    def _base_aml_domain(self, options, date_from, date_to, extra_domain=None):
        # Scoped to the user's currently allowed companies (env.companies,
        # the multi-company selector), not just env.company: without this,
        # a user with several companies selected would silently get figures
        # blended across all of them (record rules alone don't stop that -
        # they only stop access to companies the user can't see at all).
        domain = [('company_id', 'in', self.env.companies.ids)]
        if not options.get('all_entries'):
            domain.append(('parent_state', '=', 'posted'))
        if date_to:
            domain.append(('date', '<=', date_to))
        if date_from:
            domain.append(('date', '>=', date_from))
        if options.get('journal_ids'):
            domain.append(('journal_id', 'in', options['journal_ids']))
        if extra_domain:
            domain = domain + list(extra_domain)
        return domain

    def _sum_aml(self, options, domain, field, date):
        """Sum `field` over `domain`, converted into the report's target
        currency as of `date`. Grouped by company_id rather than a plain
        aggregate: the domain can span more than one company (a shared
        account/tax can have postings from several), and those companies
        can use different currencies - summing their raw amounts directly
        would silently blend currencies, so each company's subtotal gets
        converted before being added to the others."""
        groups = self.env['account.move.line']._read_group(domain, groupby=['company_id'], aggregates=[f'{field}:sum'])
        amount_by_company = {company.id: (value or 0.0) for company, value in groups}
        report = self.report_line_id.report_id
        target_currency = report._get_report_currency(options)
        return report._convert_and_sum_by_company(amount_by_company, target_currency, date)

    # -- engine: domain ---------------------------------------------------
    def _domain_engine_field_and_sign(self):
        """Shared by _evaluate_domain and _evaluate_batch_by_account: turn
        the subformula ('sum'/'-sum'/'sum_debit'/'sum_credit') into the AML
        field to sum and whether to negate the result."""
        subformula = (self.subformula or 'sum').strip()
        negate = subformula.startswith('-')
        key = subformula[1:] if negate else subformula
        field = {'sum': 'balance', 'sum_debit': 'debit', 'sum_credit': 'credit'}.get(key)
        if not field:
            raise UserError(_("Unsupported domain subformula '%s'.", self.subformula))
        return field, negate

    def _evaluate_domain(self, options, date_from, date_to, extra_domain):
        formula = (self.formula or '[]').strip()
        base_domain = ast.literal_eval(formula) if formula not in ('', '[]') else []
        domain = self._base_aml_domain(options, date_from, date_to, extra_domain) + base_domain

        field, negate = self._domain_engine_field_and_sign()
        value = self._sum_aml(options, domain, field, date_to)
        if negate:
            value = -value
        return value, [domain]

    def _evaluate_batch_by_account(self, options, account_ids):
        """Like _evaluate(), but computes the value for every id in
        account_ids with a *single* query instead of one query per account.

        Used by account.report.line._build_groupby_row so that a
        groupby='account_id' line (Trial Balance's account rows, every
        Balance Sheet/P&L leaf category) doesn't fan out into one query per
        account per column per period - with a few hundred accounts and a
        handful of columns that was hundreds of round-trips for something a
        single GROUP BY query answers directly.

        Only implemented for the 'domain' engine, which is what every
        current groupby line actually uses. Returns None for any other
        engine so the caller can fall back to the slower per-account
        _evaluate() loop (still correct, just not batched).
        """
        self.ensure_one()
        if self.engine != 'domain' or not account_ids:
            return None

        date_from, date_to = self._resolve_date_scope(options)
        formula = (self.formula or '[]').strip()
        base_domain = ast.literal_eval(formula) if formula not in ('', '[]') else []
        domain = self._base_aml_domain(options, date_from, date_to) + base_domain + [('account_id', 'in', account_ids)]

        field, negate = self._domain_engine_field_and_sign()
        # Grouped by (account, company) rather than just account: an
        # account can be shared across companies (Odoo's shared chart of
        # accounts), and those companies can use different currencies - see
        # the matching comment on _sum_aml.
        groups = self.env['account.move.line']._read_group(
            domain, groupby=['account_id', 'company_id'], aggregates=[f'{field}:sum'],
        )
        report = self.report_line_id.report_id
        target_currency = report._get_report_currency(options)
        amount_by_account = {}
        for account, company, value in groups:
            amount_by_account.setdefault(account.id, {})[company.id] = value or 0.0
        values = {
            account_id: report._convert_and_sum_by_company(amount_by_company, target_currency, date_to)
            for account_id, amount_by_company in amount_by_account.items()
        }
        if negate:
            values = {account_id: -value for account_id, value in values.items()}
        return values

    # -- engine: account_codes ---------------------------------------------
    def _parse_account_codes_formula(self):
        terms = []
        for token in ACCOUNT_CODES_ENGINE_SPLIT_REGEX.split((self.formula or '').replace(' ', '')):
            if not token:
                continue
            match = ACCOUNT_CODES_ENGINE_TERM_REGEX.match(token)
            if not match or not match.group('prefix'):
                raise UserError(_("Invalid account_codes formula '%s'.", self.formula))
            excluded_raw = match.group('excluded_prefixes') or match.group('excluded_prefixes_bare') or ''
            terms.append({
                'sign': -1 if match.group('sign') == '-' else 1,
                'prefix': match.group('prefix'),
                'excluded_prefixes': [p for p in excluded_raw.split(',') if p],
                'balance_character': match.group('balance_character') or None,
            })
        return terms

    def _evaluate_account_codes(self, options, date_from, date_to, extra_domain):
        total = 0.0
        domains = []
        for term in self._parse_account_codes_formula():
            if term['prefix'].startswith('tag('):
                raise UserError(_("account_codes formulas using tag() prefixes are not supported yet."))
            account_domain = [('code', '=like', term['prefix'] + '%')]
            for excluded in term['excluded_prefixes']:
                account_domain = ['&'] + account_domain + [('code', 'not like', excluded + '%')]
            accounts = self.env['account.account'].search(account_domain)

            aml_domain = self._base_aml_domain(options, date_from, date_to, extra_domain) + [('account_id', 'in', accounts.ids)]
            balance = self._sum_aml(options, aml_domain, 'balance', date_to)
            if term['balance_character'] == 'D':
                balance = max(balance, 0.0)
            elif term['balance_character'] == 'C':
                balance = min(balance, 0.0)

            total += term['sign'] * balance
            domains.append(aml_domain)
        return total, domains

    # -- engine: aggregation -----------------------------------------------
    def _evaluate_aggregation(self, options, date_from, date_to, extra_domain):
        formula = (self.formula or '').strip()
        domains = []

        if formula == 'sum_children':
            total = 0.0
            for child in self.report_line_id.children_ids:
                child_expr = child.expression_ids.filtered(lambda e: e.label == self.label)
                if child_expr:
                    value, sub_domains = child_expr[0]._evaluate(options, extra_domain=extra_domain)
                    total += value
                    domains += sub_domains
            return total, domains

        substituted = []
        for match in _AGGREGATION_TOKEN_RE.finditer(formula):
            token = match.group(0)
            if _AGGREGATION_REF_RE.match(token):
                code, label = token.split('.')
                ref_line = self.env['account.report.line'].search([
                    ('report_id', '=', self.report_line_id.report_id.id),
                    ('code', '=', code),
                ], limit=1)
                if not ref_line:
                    raise UserError(_("Cannot resolve aggregation reference '%s': no line with code '%s'.", token, code))
                ref_expr = ref_line.expression_ids.filtered(lambda e: e.label == label)
                if not ref_expr:
                    raise UserError(_("Cannot resolve aggregation reference '%s': no expression labeled '%s'.", token, label))
                value, sub_domains = ref_expr[0]._evaluate(options, extra_domain=extra_domain)
                domains += sub_domains
                substituted.append(repr(value))
            else:
                substituted.append(token)

        value = _safe_eval_arithmetic(' '.join(substituted))
        return value, domains

    # -- engine: tax_tags ----------------------------------------------------
    def _evaluate_tax_tags(self, options, date_from, date_to, extra_domain):
        country = self.report_line_id.report_id.country_id
        tags = self.env['account.account.tag']._get_tax_tags(self.formula, country.id)
        domain = self._base_aml_domain(options, date_from, date_to, extra_domain) + [('tax_tag_ids', 'in', tags.ids)]
        value = self._sum_aml(options, domain, 'balance', date_to)
        if tags and tags[0].balance_negate:
            value = -value
        return value, [domain]

    # -- engine: external ----------------------------------------------------
    def _evaluate_external(self, options, date_from, date_to, extra_domain):
        domain = [('target_report_expression_id', '=', self.id)]
        if date_to:
            domain.append(('date', '<=', date_to))
        record = self.env['account.report.external.value'].search(domain, order='date desc', limit=1)
        return (record.value if record else 0.0), []

    # -- engine: custom --------------------------------------------------
    def _evaluate_custom(self, options, date_from, date_to, extra_domain):
        raise UserError(_("The 'custom' computation engine is not implemented in this module."))
