# -*- coding: utf-8 -*-
from odoo import models, fields, api

class FbookReportWizard(models.TransientModel):
    _name = 'fbook.report.wizard'
    _description = 'Fbook Report Wizard'

    company_ids = fields.Many2many(
        'res.company',
        string='Companies',
        required=True,
        default=lambda self: self.env.companies
    )
    @api.model
    def _get_year_selection(self):
        from datetime import date
        current_year = date.today().year
        # Generate dynamic year selections starting from 2024 to current_year + 5
        selection = []
        for y in range(2024, current_year + 6):
            fy_num = y - 2000 + 1
            selection.append((str(y), f"FY{fy_num} - {y} -{y+1}"))
        return selection

    def _get_default_year(self):
        from datetime import date
        today = date.today()
        # Default to the current fiscal year (starts April 1st)
        if today.month < 4:
            return str(today.year - 1)
        return str(today.year)

    start_financial_year = fields.Selection(
        selection='_get_year_selection',
        string='Start Financial Year',
        required=True,
        default=_get_default_year
    )
    currency_id = fields.Many2one(
        'res.currency', 
        string='Currency', 
        required=True, 
        default=lambda self: self.env.company.currency_id
    )


    def action_submit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'bxi_fbook_report_dashboard',
            'name': 'Financial Book',
            'context': {
                'company_ids': self.company_ids.ids,
                'company_names': ", ".join(self.company_ids.mapped('name')),
                'start_financial_year': self.start_financial_year,
                'currency_id': self.currency_id.id,
                'currency_symbol': self.currency_id.symbol or self.currency_id.name,
            }
        }

    @api.model
    def get_report_data(self, company_ids, start_financial_year, currency_id):
        if not company_ids:
            company_ids = self.env.companies.ids
        elif isinstance(company_ids, int):
            company_ids = [company_ids]

        companies = self.env['res.company'].browse(company_ids)
        # Primary company used as fallback for currency rate lookups
        company = companies[0] if companies else self.env.company
        target_currency = self.env['res.currency'].browse(currency_id)

        def get_rate_company(record):
            """Return the record's own company for exchange rate lookup, or fallback."""
            rec_company = getattr(record, 'company_id', False)
            return rec_company if rec_company else company


        y2_start = int(start_financial_year)
        y1_start = y2_start - 1

        from datetime import date
        today_date = date.today()
        current_fy_start = today_date.year - 1 if today_date.month < 4 else today_date.year


        # We construct dates for 2 financial years side-by-side: April 1st to March 31st.
        quarters_def = [
            # Year 1 (e.g. FY26)
            {
                'q': 'q1',
                'year': 'y1',
                'start': f'{y1_start}-04-01',
                'end': f'{y1_start}-06-30',
            },
            {
                'q': 'q2',
                'year': 'y1',
                'start': f'{y1_start}-07-01',
                'end': f'{y1_start}-09-30',
            },
            {
                'q': 'q3',
                'year': 'y1',
                'start': f'{y1_start}-10-01',
                'end': f'{y1_start}-12-31',
            },
            {
                'q': 'q4',
                'year': 'y1',
                'start': f'{y1_start + 1}-01-01',
                'end': f'{y1_start + 1}-03-31',
            },
            # Year 2 (e.g. FY27)
            {
                'q': 'q1',
                'year': 'y2',
                'start': f'{y2_start}-04-01',
                'end': f'{y2_start}-06-30',
            },
            {
                'q': 'q2',
                'year': 'y2',
                'start': f'{y2_start}-07-01',
                'end': f'{y2_start}-09-30',
            },
            {
                'q': 'q3',
                'year': 'y2',
                'start': f'{y2_start}-10-01',
                'end': f'{y2_start}-12-31',
            },
            {
                'q': 'q4',
                'year': 'y2',
                'start': f'{y2_start + 1}-01-01',
                'end': f'{y2_start + 1}-03-31',
            },
        ]

        data = {
            'y1': {'q1': {}, 'q2': {}, 'q3': {}, 'q4': {}, 'total': {}},
            'y2': {'q1': {}, 'q2': {}, 'q3': {}, 'q4': {}, 'total': {}}
        }

        running_dso_amount = 0.0
        running_dso_days = 0.0
        for qdef in quarters_def:
            year_key = qdef['year']
            q_key = qdef['q']

            # 1. Bookings (Based on contract quarter breakdown if present, fallback to start date)
            booking_val = 0.0
            if 'project.contract.management' in self.env:
                contracts = self.env['project.contract.management'].sudo().search([
                    ('company_id', 'in', company_ids)
                ])
                q_start_dt = fields.Date.from_string(qdef['start'])
                q_end_dt = fields.Date.from_string(qdef['end'])
                for contract in contracts:

                    if contract.contract_start_date and q_start_dt <= contract.contract_start_date <= q_end_dt:
                        booking_val += contract.currency_id._convert(
                            contract.contract_amount, target_currency, get_rate_company(contract), fields.Date.today()
                        )




            # Helper function to check if an invoice is linked to a contract
            def is_linked_to_contract(inv):
                if inv.contract_id:
                    if inv.contract_id.company_id and inv.contract_id.company_id.id in company_ids:
                        return True
                # Check via Many2many invoice_ids on contract model
                linked_m2m = self.env['project.contract.management'].sudo().search([
                    ('invoice_ids', 'in', [inv.id]),
                    ('company_id', 'in', company_ids)
                ])
                if linked_m2m:
                    return True
                # Check via Sales Orders
                sale_orders = inv.line_ids.sale_line_ids.order_id
                if sale_orders:
                    linked_contracts = self.env['project.contract.management'].sudo().search([
                        ('sale_order_ids', 'in', sale_orders.ids),
                        ('company_id', 'in', company_ids)
                    ])
                    if linked_contracts:
                        return True
                return False



            # 2. Billed — ALL customer invoices (except cancel/rejected) for selected companies in the quarter
            billed_val = 0.0
            actual_val = 0.0
            invoices = self.env['account.move'].sudo().search([
                ('company_id', 'in', company_ids),
                ('move_type', '=', 'out_invoice'),
                ('state', 'not in', ('cancel', 'rejected')),
                ('invoice_date', '>=', qdef['start']),
                ('invoice_date', '<=', qdef['end'])
            ])
            for inv in invoices:
                inv_amount = inv.currency_id._convert(
                    inv.amount_total, target_currency,
                    get_rate_company(inv), inv.invoice_date or fields.Date.today()
                )
                # Billed = ALL posted invoices raised in the quarter
                billed_val += inv_amount
                # Actual = invoices that are fully paid (payment_state = paid)
                if inv.payment_state == 'paid':

                    actual_val += inv_amount






            # 4. DSO — Split into DSO (Days) and DSO (Amount)
            running_dso_amount += billed_val - actual_val
            dso_amount_val = running_dso_amount

            running_dso_days += ((billed_val - actual_val) / billed_val * 90) if billed_val > 0 else 0.0
            if running_dso_days < 0.0:
                running_dso_days = 0.0
            dso_days_val = running_dso_days

            # If the quarter has not started yet relative to today's date, set point-in-time DSO to 0
            q_start_date = fields.Date.from_string(qdef['start'])
            if q_start_date > today_date:
                dso_amount_val = 0.0
                dso_days_val = 0.0




            # 5. Expenses (Combination of hr.expense + vendor bills + payroll salary)
            expenses_val = 0.0

            # A. Expenses
            if 'hr.expense' in self.env:
                expenses = self.env['hr.expense'].sudo().search([
                    ('company_id', 'in', company_ids),
                    ('date', '>=', qdef['start']),
                    ('date', '<=', qdef['end'])
                ])
                for exp in expenses:
                    expenses_val += exp.currency_id._convert(
                        exp.total_amount_currency, target_currency, get_rate_company(exp), exp.date or fields.Date.today()
                    )

            # B. Vendor Bills
            if 'account.move' in self.env:
                bills = self.env['account.move'].sudo().search([
                    ('company_id', 'in', company_ids),
                    ('move_type', 'in', ('in_invoice', 'in_receipt', 'in_refund')),
                    ('expense_ids', '=', False),
                    ('invoice_date', '>=', qdef['start']),
                    ('invoice_date', '<=', qdef['end'])
                ])
                for bill in bills:
                    sign = -1.0 if bill.move_type == 'in_refund' else 1.0
                    expenses_val += sign * bill.currency_id._convert(
                        bill.amount_total, target_currency, get_rate_company(bill), bill.invoice_date or fields.Date.today()
                    )

            # C. Payroll / Payslips (Salary)
            if 'hr.payslip' in self.env:
                payslips = self.env['hr.payslip'].sudo().search([
                    ('company_id', 'in', company_ids),
                    ('date_to', '>=', qdef['start']),
                    ('date_to', '<=', qdef['end'])
                ])
                for slip in payslips:
                    net_amt = 0.0
                    if hasattr(slip, 'get_salary_line_total'):
                        net_amt = slip.get_salary_line_total('NET')
                    else:
                        line = slip.line_ids.filtered(lambda l: l.code == 'NET')
                        if line:
                            net_amt = line[0].total
                    
                    expenses_val += slip.company_id.currency_id._convert(
                        net_amt, target_currency, get_rate_company(slip), slip.date_to or fields.Date.today()
                    )





            # 6. Profit
            profit_val = billed_val - expenses_val

            # 7. Margin %
            margin_val = (profit_val / billed_val * 100) if billed_val > 0 else 0.0

            data[year_key][q_key] = {
                'booking': target_currency.round(booking_val),
                'billed': target_currency.round(billed_val),
                'actual': target_currency.round(actual_val),
                'dso_days': int(round(dso_days_val)),
                'dso_amount': target_currency.round(dso_amount_val),
                'expenses': target_currency.round(expenses_val),
                'profit': target_currency.round(profit_val),
                'margin': round(margin_val, 2)
            }

        # Calculate Totals for Year 1 and Year 2
        for y in ['y1', 'y2']:
            sum_booking = sum(data[y][q]['booking'] for q in ['q1', 'q2', 'q3', 'q4'])
            sum_billed = sum(data[y][q]['billed'] for q in ['q1', 'q2', 'q3', 'q4'])
            sum_actual = sum(data[y][q]['actual'] for q in ['q1', 'q2', 'q3', 'q4'])

            # Point-in-time DSO totals default to q4
            dso_q = 'q4'
            y_start = y1_start if y == 'y1' else y2_start
            if y_start == current_fy_start:
                if today_date.month in [4, 5, 6]:
                    dso_q = 'q1'
                elif today_date.month in [7, 8, 9]:
                    dso_q = 'q2'
                elif today_date.month in [10, 11, 12]:
                    dso_q = 'q3'
                else:
                    dso_q = 'q4'

            avg_dso_days = data[y][dso_q]['dso_days']
            sum_dso_amount = data[y][dso_q]['dso_amount']
            sum_expenses = sum(data[y][q]['expenses'] for q in ['q1', 'q2', 'q3', 'q4'])
            total_profit = sum_billed - sum_expenses
            total_margin = (total_profit / sum_billed * 100) if sum_billed > 0 else 0.0

            data[y]['total'] = {
                'booking': target_currency.round(sum_booking),
                'billed': target_currency.round(sum_billed),
                'actual': target_currency.round(sum_actual),
                'dso_days': int(round(avg_dso_days)),
                'dso_amount': target_currency.round(sum_dso_amount),
                'expenses': target_currency.round(sum_expenses),
                'profit': target_currency.round(total_profit),
                'margin': round(total_margin, 2)
            }

        # Calculate Detailed Contracts Data (Revenue section)
        contracts_data = []
        from datetime import date as _date_rev
        total_contract_value = 0.0
        total_y1_booking = 0.0
        total_y1_billed = 0.0
        total_y2_booking = 0.0
        total_y2_billed = 0.0

        if 'project.contract.management' in self.env:
            all_contracts = self.env['project.contract.management'].sudo().search([
                ('company_id', 'in', company_ids)
            ])
            
            partners_data = {}
            
            for contract in all_contracts:
                # Engagement
                engagement = ''
                if contract.contract_type:
                    engagement_dict = dict(self.env['project.contract.management']._fields['contract_type'].selection or [])
                    engagement = engagement_dict.get(contract.contract_type, '')

                # Year 1 Dates
                y1_start_date = _date_rev(y1_start, 4, 1)
                y1_end_date = _date_rev(y1_start + 1, 3, 31)

                # Year 2 Dates
                y2_start_date = _date_rev(y2_start, 4, 1)
                y2_end_date = _date_rev(y2_start + 1, 3, 31)

                y1_booking = 0.0
                y2_booking = 0.0

                if contract.contract_start_date:
                    val_converted = contract.currency_id._convert(
                        contract.contract_amount, target_currency, get_rate_company(contract), fields.Date.today()
                    )
                    if y1_start_date <= contract.contract_start_date <= y1_end_date:
                        y1_booking += val_converted
                    elif y2_start_date <= contract.contract_start_date <= y2_end_date:
                        y2_booking += val_converted

                # Billed Y1 & Y2
                y1_billed = 0.0
                y2_billed = 0.0

                # Search invoices linked to this contract (use sudo to bypass company record rules)
                invoices = self.env['account.move'].sudo().search([
                    ('company_id', 'in', company_ids),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted')
                ])

                for inv in invoices:
                    is_linked = False
                    if inv.contract_id and inv.contract_id.id == contract.id:
                        is_linked = True
                    elif inv.id in contract.invoice_ids.ids:
                        is_linked = True
                    else:
                        sale_orders = inv.line_ids.sale_line_ids.order_id
                        if sale_orders:
                            linked_contracts = self.env['project.contract.management'].sudo().search([
                                ('sale_order_ids', 'in', sale_orders.ids),
                                ('company_id', 'in', company_ids)
                            ])
                            if contract.id in linked_contracts.ids:
                                is_linked = True

                    if is_linked:
                        inv_date = inv.invoice_date
                        if inv_date:
                            inv_val = inv.currency_id._convert(
                                inv.amount_total, target_currency, get_rate_company(inv), inv_date
                            )

                            if y1_start_date <= inv_date <= y1_end_date:
                                y1_billed += inv_val
                            elif y2_start_date <= inv_date <= y2_end_date:
                                y2_billed += inv_val

                # Convert contract amount to target currency
                val_converted = contract.currency_id._convert(
                    contract.contract_amount, target_currency, get_rate_company(contract), fields.Date.today()
                )

                clients = contract.client_ids or [self.env['res.partner']]
                for client in clients:
                    partner_name = client.name or 'Unknown Customer'
                    partner_key = partner_name.strip().lower()
                    if partner_key not in partners_data:
                        partners_data[partner_key] = {
                            'customer': partner_name,
                            'industry': client.industry_id.name or contract.industry_id.name or '',
                            'businesses': set(),
                            'engagements': set(),
                            'contract_value': 0.0,
                            'y1_booking': 0.0,
                            'y1_billed': 0.0,
                            'y2_booking': 0.0,
                            'y2_billed': 0.0
                        }
                    pd = partners_data[partner_key]
                    if contract.name:
                        pd['businesses'].add(contract.name)
                    if engagement:
                        pd['engagements'].add(engagement)
                    pd['contract_value'] += val_converted
                    pd['y1_booking'] += y1_booking
                    pd['y1_billed'] += y1_billed
                    pd['y2_booking'] += y2_booking
                    pd['y2_billed'] += y2_billed

            for key, pd in partners_data.items():
                contracts_data.append({
                    'industry': pd['industry'],
                    'customers': pd['customer'],
                    'business': ', '.join(sorted(pd['businesses'])) or '',
                    'engagement': ', '.join(sorted(pd['engagements'])) or '',
                    'contract_value': target_currency.round(pd['contract_value']),
                    'y1_booking': target_currency.round(pd['y1_booking']),
                    'y1_billed': target_currency.round(pd['y1_billed']),
                    'y1_expenses': 0.0,
                    'y1_margin': 0.0,
                    'y2_booking': target_currency.round(pd['y2_booking']),
                    'y2_billed': target_currency.round(pd['y2_billed']),
                    'y2_expenses': 0.0,
                    'y2_margin': 0.0
                })

        total_contract_value = sum(c['contract_value'] for c in contracts_data)
        total_y1_booking = sum(c['y1_booking'] for c in contracts_data)
        total_y1_billed = sum(c['y1_billed'] for c in contracts_data)
        total_y2_booking = sum(c['y2_booking'] for c in contracts_data)
        total_y2_billed = sum(c['y2_billed'] for c in contracts_data)

        # Calculate Detailed Expense Data consolidated by Category
        expenses_data = []
        from datetime import date as _date

        categories_dict = {}

        def _add_expense_val(cat_label, y_key, val_booked, val_billed):
            if cat_label not in categories_dict:
                categories_dict[cat_label] = {
                    'category': cat_label,
                    'y1_booked': 0.0,
                    'y1_billed': 0.0,
                    'y2_booked': 0.0,
                    'y2_billed': 0.0,
                }
            categories_dict[cat_label][f'{y_key}_booked'] += val_booked
            categories_dict[cat_label][f'{y_key}_billed'] += val_billed

        y1_start_date = _date(y1_start, 4, 1)
        y1_end_date = _date(y1_start + 1, 3, 31)
        y2_start_date = _date(y2_start, 4, 1)
        y2_end_date = _date(y2_start + 1, 3, 31)

        def _get_y_key(rec_date):
            if rec_date and y1_start_date <= rec_date <= y1_end_date:
                return 'y1'
            elif rec_date and y2_start_date <= rec_date <= y2_end_date:
                return 'y2'
            return None

        # A. hr.expense -> consolidated under "Employee(reimbursement)"
        if 'hr.expense' in self.env:
            exps = self.env['hr.expense'].sudo().search([
                ('company_id', 'in', company_ids),
                ('date', '>=', y1_start_date),
                ('date', '<=', y2_end_date),
            ])
            for exp in exps:
                y_key = _get_y_key(exp.date)
                if not y_key:
                    continue
                conv = exp.currency_id._convert(
                    exp.total_amount_currency, target_currency,
                    get_rate_company(exp), exp.date or fields.Date.today()
                )
                is_paid = getattr(exp, 'state', '') in ('paid', 'posted', 'in_payment', 'done')
                _add_expense_val('Employee(reimbursement)', y_key, conv, conv if is_paid else 0.0)

        # B. Vendor Bills -> consolidated by vendor_category
        category_labels = {
            'technology': 'Technology',
            'miscellaneous': 'Miscellaneous',
            'employee': 'Employee',
            'travel': 'Travel',
            'administration': 'Administration',
        }
        if 'account.move' in self.env:
            bills = self.env['account.move'].sudo().search([
                ('company_id', 'in', company_ids),
                ('move_type', 'in', ('in_invoice', 'in_receipt', 'in_refund')),
                ('expense_ids', '=', False),
                ('invoice_date', '>=', y1_start_date),
                ('invoice_date', '<=', y2_end_date),
            ])
            for bill in bills:
                y_key = _get_y_key(bill.invoice_date)
                if not y_key:
                    continue
                partner = bill.partner_id
                vendor_cat = partner.vendor_category if partner else 'miscellaneous'
                if not vendor_cat:
                    vendor_cat = 'miscellaneous'
                cat_label = category_labels.get(vendor_cat, 'Miscellaneous')

                sign = -1.0 if bill.move_type == 'in_refund' else 1.0
                conv = sign * bill.currency_id._convert(
                    bill.amount_total, target_currency,
                    get_rate_company(bill), bill.invoice_date or fields.Date.today()
                )
                is_paid = bill.payment_state in ('paid', 'in_payment', 'partial') if hasattr(bill, 'payment_state') else False
                _add_expense_val(cat_label, y_key, conv, conv if is_paid else 0.0)

        # C. Payroll / Payslips -> consolidated under "Employee(salary)"
        if 'hr.payslip' in self.env:
            payslips = self.env['hr.payslip'].sudo().search([
                ('company_id', 'in', company_ids),
                ('date_to', '>=', y1_start_date),
                ('date_to', '<=', y2_end_date),
            ])
            y1_salaries = []
            y2_salaries = []
            for slip in payslips:
                y_key = _get_y_key(slip.date_to)
                if not y_key:
                    continue
                net_amt = 0.0
                if hasattr(slip, 'get_salary_line_total'):
                    net_amt = slip.get_salary_line_total('NET')
                else:
                    line = slip.line_ids.filtered(lambda l: l.code == 'NET')
                    if line:
                        net_amt = line[0].total
                conv = slip.company_id.currency_id._convert(
                    net_amt, target_currency, get_rate_company(slip), slip.date_to or fields.Date.today()
                )
                if y_key == 'y1':
                    y1_salaries.append((slip.date_to, conv))
                elif y_key == 'y2':
                    y2_salaries.append((slip.date_to, conv))

            today = fields.Date.today()
            current_ym = today.strftime('%Y-%m')

            def _calc_year_salary(salaries, start_date, end_date):
                actual_val = sum(val for date_val, val in salaries)
                if end_date < today:
                    return actual_val, actual_val

                # Ongoing financial year:
                # Exclude the current ongoing month from the average calculation
                past_salaries = [val for d, val in salaries if d and d.strftime('%Y-%m') < current_ym]
                total_past_sal = sum(past_salaries)
                elapsed_months = (today.year - start_date.year) * 12 + (today.month - start_date.month)
                plan_val = (total_past_sal / elapsed_months * 12) if elapsed_months > 0 else actual_val
                return plan_val, actual_val

            y1_plan, y1_actual = _calc_year_salary(y1_salaries, y1_start_date, y1_end_date)
            y2_plan, y2_actual = _calc_year_salary(y2_salaries, y2_start_date, y2_end_date)

            _add_expense_val('Employee(salary)', 'y1', y1_plan, y1_actual)
            _add_expense_val('Employee(salary)', 'y2', y2_plan, y2_actual)

        # Populate expenses_data
        for cat_label in sorted(categories_dict.keys()):
            r = categories_dict[cat_label]
            expenses_data.append({
                'category': r['category'],
                'y1_booked': target_currency.round(r['y1_booked']),
                'y1_billed': target_currency.round(r['y1_billed']),
                'y2_booked': target_currency.round(r['y2_booked']),
                'y2_billed': target_currency.round(r['y2_billed']),
            })

        salary_data = []
        total_exp_y1_booked = target_currency.round(sum(e['y1_booked'] for e in expenses_data))
        total_exp_y1_billed = target_currency.round(sum(e['y1_billed'] for e in expenses_data))
        total_exp_y2_booked = target_currency.round(sum(e['y2_booked'] for e in expenses_data))
        total_exp_y2_billed = target_currency.round(sum(e['y2_billed'] for e in expenses_data))

        total_sal_y1_booked = 0.0
        total_sal_y2_booked = 0.0

        y1_prefix = 'CY' if y1_start == current_fy_start else 'FY'
        y2_prefix = 'CY' if y2_start == current_fy_start else 'FY'

        return {
            'company_name': company.name,
            'currency_symbol': f"{target_currency.symbol} {target_currency.name}" if target_currency.symbol else target_currency.name,
            'year1_label': f'{y1_prefix}{y1_start - 2000 + 1} - {y1_start} -{y1_start + 1}',
            'year2_label': f'{y2_prefix}{y2_start - 2000 + 1} - {y2_start} -{y2_start + 1}',
            'y1_prefix': y1_prefix,
            'y2_prefix': y2_prefix,
            'y1_date_range_label': f'1st Apr-{y1_start-2000} to 31st Mar-{y1_start-2000+1}',
            'y1_short_label': f'{y1_prefix}{y1_start - 2000 + 1}',
            'y2_date_range_label': f'1st Apr-{y2_start-2000} to 31st Mar-{y2_start-2000+1}',
            'y2_short_label': f'{y2_prefix}{y2_start - 2000 + 1}',
            'data': data,
            'contracts_data': contracts_data,
            'total_contract_value': target_currency.round(total_contract_value),
            'total_y1_booking': target_currency.round(total_y1_booking),
            'total_y1_billed': target_currency.round(total_y1_billed),
            'total_y2_booking': target_currency.round(total_y2_booking),
            'total_y2_billed': target_currency.round(total_y2_billed),
            'total_y1_expenses': 0.0,
            'total_y1_margin': 0.0,
            'total_y2_expenses': 0.0,
            'total_y2_margin': 0.0,
            'expenses_data': expenses_data,
            'salary_data': salary_data,
            'total_exp_y1_booked': total_exp_y1_booked,
            'total_exp_y1_billed': total_exp_y1_billed,
            'total_exp_y2_booked': total_exp_y2_booked,
            'total_exp_y2_billed': total_exp_y2_billed,
            'total_sal_y1_booked': total_sal_y1_booked,
            'total_sal_y2_booked': total_sal_y2_booked,
        }

