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

        # DSO running accumulators — tracked separately per year
        # DSO Amount = cumulative AR outstanding (billed but unpaid) to date within the year
        # DSO Days   = (Cumulative AR Outstanding / Cumulative Revenue) × Days elapsed since year start
        running_dso_amount = {'y1': 0.0, 'y2': 0.0}
        running_billed     = {'y1': 0.0, 'y2': 0.0}
        year_start_dates   = {
            'y1': fields.Date.from_string(f'{y1_start}-04-01'),
            'y2': fields.Date.from_string(f'{y2_start}-04-01'),
        }
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






            # 4. DSO Calculation
            # ------------------------------------------------------------------
            # DSO Amount = Cumulative AR outstanding (billed but not yet paid)
            #              It accumulates quarter-over-quarter within the same year.
            #
            # DSO Days   = Standard formula:
            #              (Cumulative AR Outstanding / Cumulative Revenue Billed) × Days elapsed
            #
            #   Per-Quarter DSO Days = (This quarter outstanding / This quarter billed) × 90
            #   Running    DSO Days  = (All AR outstanding so far / All revenue so far) × Days elapsed this year
            #
            # We show the running DSO for each quarter so you can see the trend improving or worsening.
            # ------------------------------------------------------------------
            q_start_date = fields.Date.from_string(qdef['start'])
            q_end_date   = fields.Date.from_string(qdef['end'])

            dso_amount_val = 0.0
            dso_days_val   = 0

            if q_start_date <= today_date:
                # Accumulate per year
                outstanding_this_q = billed_val - actual_val
                running_dso_amount[year_key] += outstanding_this_q
                running_billed[year_key]     += billed_val

                dso_amount_val = running_dso_amount[year_key]

                # Days elapsed from year start to end of this quarter (or today if quarter not yet complete)
                year_start_dt  = year_start_dates[year_key]
                effective_end  = min(q_end_date, today_date)
                days_elapsed   = (effective_end - year_start_dt).days + 1

                # Standard DSO: (Cumulative Outstanding / Cumulative Billed) × Days Elapsed
                if running_billed[year_key] > 0:
                    dso_days_val = round(
                        (running_dso_amount[year_key] / running_billed[year_key]) * days_elapsed
                    )
                else:
                    dso_days_val = 0

                # DSO days cannot be negative
                if dso_days_val < 0:
                    dso_days_val = 0




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
            margin_val = min(100.0, margin_val)

            # 8. Cash Flow: IN (all bank/cash debits) - OUT (all bank/cash credits) = Net Cash
            #    Strictly uses lines where account itself is bank/cash (asset_cash) to avoid double counting counterpart lines
            cash_flow_val = 0.0
            q_start_date = fields.Date.from_string(qdef['start'])
            q_end_date = fields.Date.from_string(qdef['end'])

            if 'account.move.line' in self.env and q_start_date <= today_date:
                effective_end = q_end_date if q_end_date <= today_date else today_date
                domain = [
                    ('company_id', 'in', company_ids),
                    ('parent_state', '=', 'posted'),
                    ('date', '>=', qdef['start']),
                    ('date', '<=', effective_end),
                    ('account_id.account_type', '=', 'asset_cash'),  # Only the bank/cash account lines itself
                ]

                q_in = 0.0
                q_out = 0.0
                cash_lines = self.env['account.move.line'].sudo().search(domain)
                for cl in cash_lines:
                    if cl.debit > 0:
                        q_in += cl.company_id.currency_id._convert(
                            cl.debit, target_currency, get_rate_company(cl), cl.date or fields.Date.today()
                        )
                    elif cl.credit > 0:
                        q_out += cl.company_id.currency_id._convert(
                            cl.credit, target_currency, get_rate_company(cl), cl.date or fields.Date.today()
                        )
                cash_flow_val = q_in - q_out

            # 9. Calibration: Incoming bank/cash receipts NOT linked to customer invoices
            #    = money received into bank other than customer invoice payments (e.g. investor funds, loans, etc.)
            calibration_val = 0.0
            if 'account.move.line' in self.env and q_start_date <= today_date:
                effective_end = q_end_date if q_end_date <= today_date else today_date
                cal_domain = [
                    ('company_id', 'in', company_ids),
                    ('parent_state', '=', 'posted'),
                    ('debit', '>', 0.0),
                    ('date', '>=', qdef['start']),
                    ('date', '<=', effective_end),
                    ('account_id.account_type', '=', 'asset_cash'),  # Only actual bank/cash account lines
                ]

                inflow_lines = self.env['account.move.line'].sudo().search(cal_domain)
                for line in inflow_lines:
                    move = line.move_id
                    is_invoice_receipt = False

                    # Method 1: Check via payment's reconciled invoices
                    pay = getattr(line, 'payment_id', False) or getattr(move, 'payment_id', False)
                    if pay:
                        reconciled_invs = getattr(pay, 'reconciled_invoice_ids', False)
                        if reconciled_invs and any(getattr(m, 'move_type', '') == 'out_invoice' for m in reconciled_invs):
                            is_invoice_receipt = True

                    # Method 2: Check reconciliation partials on any line in the move
                    if not is_invoice_receipt:
                        for ml in move.line_ids:
                            for partial in getattr(ml, 'matched_credit_ids', []):
                                credit_move = getattr(getattr(partial, 'credit_move_id', False), 'move_id', False)
                                if credit_move and getattr(credit_move, 'move_type', '') == 'out_invoice':
                                    is_invoice_receipt = True
                                    break
                            for partial in getattr(ml, 'matched_debit_ids', []):
                                debit_move = getattr(getattr(partial, 'debit_move_id', False), 'move_id', False)
                                if debit_move and getattr(debit_move, 'move_type', '') == 'out_invoice':
                                    is_invoice_receipt = True
                                    break
                            if is_invoice_receipt:
                                break

                    if not is_invoice_receipt:
                        calibration_val += line.company_id.currency_id._convert(
                            line.debit, target_currency, get_rate_company(line), line.date or fields.Date.today()
                        )

            if q_start_date > today_date:
                cash_flow_val = 0.0
                calibration_val = 0.0

            data[year_key][q_key] = {
                'booking': target_currency.round(booking_val),
                'billed': target_currency.round(billed_val),
                'actual': target_currency.round(actual_val),
                'dso_days': int(round(dso_days_val)),
                'dso_amount': target_currency.round(dso_amount_val),
                'expenses': target_currency.round(expenses_val),
                'profit': target_currency.round(profit_val),
                'margin': round(margin_val, 2),
                'cash_flow': target_currency.round(cash_flow_val),
                'calibration': target_currency.round(calibration_val)
            }

        # Calculate Totals for Year 1 and Year 2
        for y in ['y1', 'y2']:
            sum_booking = sum(data[y][q]['booking'] for q in ['q1', 'q2', 'q3', 'q4'])
            sum_billed = sum(data[y][q]['billed'] for q in ['q1', 'q2', 'q3', 'q4'])
            sum_actual = sum(data[y][q]['actual'] for q in ['q1', 'q2', 'q3', 'q4'])

            # Point-in-time DSO and Cash Flow totals default to q4 or active quarter
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
            total_margin = min(100.0, total_margin)
            sum_cash_flow = data[y][dso_q]['cash_flow']
            sum_calibration = sum(data[y][q]['calibration'] for q in ['q1', 'q2', 'q3', 'q4'])

            data[y]['total'] = {
                'booking': target_currency.round(sum_booking),
                'billed': target_currency.round(sum_billed),
                'actual': target_currency.round(sum_actual),
                'dso_days': int(round(avg_dso_days)),
                'dso_amount': target_currency.round(sum_dso_amount),
                'expenses': target_currency.round(sum_expenses),
                'profit': target_currency.round(total_profit),
                'margin': round(total_margin, 2),
                'cash_flow': target_currency.round(sum_cash_flow),
                'calibration': target_currency.round(sum_calibration)
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
                    service_line_name = contract.service_line_id.name if contract.service_line_id else ''
                    if service_line_name:
                        pd['businesses'].add(service_line_name)
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

        # Monthly Cash Flow Section Calculation (Month-Wise Format)
        import calendar
        months_def = [
            {'name': 'April', 'm': 4, 'year_offset': 0},
            {'name': 'May', 'm': 5, 'year_offset': 0},
            {'name': 'June', 'm': 6, 'year_offset': 0},
            {'name': 'July', 'm': 7, 'year_offset': 0},
            {'name': 'August', 'm': 8, 'year_offset': 0},
            {'name': 'September', 'm': 9, 'year_offset': 0},
            {'name': 'October', 'm': 10, 'year_offset': 0},
            {'name': 'November', 'm': 11, 'year_offset': 0},
            {'name': 'December', 'm': 12, 'year_offset': 0},
            {'name': 'January', 'm': 1, 'year_offset': 1},
            {'name': 'February', 'm': 2, 'year_offset': 1},
            {'name': 'March', 'm': 3, 'year_offset': 1},
        ]

        # Monthly Cash Flow: Strictly use only lines where the account itself is a bank/cash account (asset_cash)
        # This avoids double-counting counterpart lines (receivables, payables) that appear in the same journal entry
        # IN  = all debits on bank/cash accounts (customer payments, fund receipts, any money in)
        # OUT = all credits on bank/cash accounts (vendor payments, expenses paid, salary paid)
        # Remaining = IN - OUT
        monthly_cashflow = []

        def _get_bank_cash_account_type_domain(env, company_ids, date_gte, date_lte):
            """Domain that strictly targets the bank/cash account line only."""
            return [
                ('company_id', 'in', company_ids),
                ('parent_state', '=', 'posted'),
                ('date', '>=', date_gte),
                ('date', '<=', date_lte),
                ('account_id.account_type', '=', 'asset_cash'),
            ]

        for mdef in months_def:
            row_data = {
                'month': mdef['name'],
                'y1_in': 0.0,
                'y1_out': 0.0,
                'y1_remaining': 0.0,
                'y2_in': 0.0,
                'y2_out': 0.0,
                'y2_remaining': 0.0,
            }

            for y_key, start_yr in [('y1', y1_start), ('y2', y2_start)]:
                cal_yr = start_yr + mdef['year_offset']
                m_num = mdef['m']
                last_day = calendar.monthrange(cal_yr, m_num)[1]
                m_start_str = f"{cal_yr:04d}-{m_num:02d}-01"
                m_end_str = f"{cal_yr:04d}-{m_num:02d}-{last_day:02d}"
                m_start_dt = fields.Date.from_string(m_start_str)

                in_val = 0.0
                out_val = 0.0

                if 'account.move.line' in self.env and m_start_dt <= today_date:
                    domain_month = _get_bank_cash_account_type_domain(
                        self.env, company_ids, m_start_str, m_end_str
                    )

                    m_lines = self.env['account.move.line'].sudo().search(domain_month)
                    for ml in m_lines:
                        if ml.debit > 0:
                            in_val += ml.company_id.currency_id._convert(
                                ml.debit, target_currency, get_rate_company(ml), ml.date or fields.Date.today()
                            )
                        elif ml.credit > 0:
                            out_val += ml.company_id.currency_id._convert(
                                ml.credit, target_currency, get_rate_company(ml), ml.date or fields.Date.today()
                            )

                row_data[f'{y_key}_in'] = target_currency.round(in_val)
                row_data[f'{y_key}_out'] = target_currency.round(out_val)
                row_data[f'{y_key}_remaining'] = target_currency.round(in_val - out_val)

            monthly_cashflow.append(row_data)

        total_cf_y1_in = target_currency.round(sum(m['y1_in'] for m in monthly_cashflow))
        total_cf_y1_out = target_currency.round(sum(m['y1_out'] for m in monthly_cashflow))
        total_cf_y1_remaining = target_currency.round(total_cf_y1_in - total_cf_y1_out)

        total_cf_y2_in = target_currency.round(sum(m['y2_in'] for m in monthly_cashflow))
        total_cf_y2_out = target_currency.round(sum(m['y2_out'] for m in monthly_cashflow))
        total_cf_y2_remaining = target_currency.round(total_cf_y2_in - total_cf_y2_out)

        # Calibration / Investor Section Calculation (Received Amounts Only)
        def get_q_num(d_str, fy_yr):
            if f"{fy_yr:04d}-04-01" <= d_str <= f"{fy_yr:04d}-06-30":
                return 1
            elif f"{fy_yr:04d}-07-01" <= d_str <= f"{fy_yr:04d}-09-30":
                return 2
            elif f"{fy_yr:04d}-10-01" <= d_str <= f"{fy_yr:04d}-12-31":
                return 3
            elif f"{fy_yr+1:04d}-01-01" <= d_str <= f"{fy_yr+1:04d}-03-31":
                return 4
            return None

        y1_fy_start = y1_start
        y2_cy_start = y2_start
        y1_start_str = f"{y1_fy_start:04d}-04-01"
        y1_end_str = f"{y1_fy_start+1:04d}-03-31"
        y2_start_str = f"{y2_cy_start:04d}-04-01"
        y2_end_str = today_date.strftime('%Y-%m-%d') if today_date <= fields.Date.from_string(f"{y2_cy_start+1:04d}-03-31") else f"{y2_cy_start+1:04d}-03-31"

        investor_data_map = {}

        if 'account.move.line' in self.env:
            # Strictly only bank/cash account lines (asset_cash) with debit > 0 = received money
            domain_inv = [
                ('company_id', 'in', company_ids),
                ('parent_state', '=', 'posted'),
                ('debit', '>', 0.0),
                ('account_id.account_type', '=', 'asset_cash'),
                ('date', '>=', min(y1_start_str, y2_start_str)),
                ('date', '<=', max(y1_end_str, y2_end_str)),
            ]

            inv_lines = self.env['account.move.line'].sudo().search(domain_inv)
            for line in inv_lines:
                move = line.move_id
                is_customer_invoice = False

                # Method 1: Check via payment's reconciled invoices
                pay = getattr(line, 'payment_id', False) or getattr(move, 'payment_id', False)
                if pay:
                    reconciled_invs = getattr(pay, 'reconciled_invoice_ids', False)
                    if reconciled_invs and any(getattr(m, 'move_type', '') == 'out_invoice' for m in reconciled_invs):
                        is_customer_invoice = True

                # Method 2: Check reconciliation partials to detect customer invoice receipts
                if not is_customer_invoice:
                    for ml in move.line_ids:
                        for partial in getattr(ml, 'matched_credit_ids', []):
                            credit_move = getattr(getattr(partial, 'credit_move_id', False), 'move_id', False)
                            if credit_move and getattr(credit_move, 'move_type', '') == 'out_invoice':
                                is_customer_invoice = True
                                break
                        for partial in getattr(ml, 'matched_debit_ids', []):
                            debit_move = getattr(getattr(partial, 'debit_move_id', False), 'move_id', False)
                            if debit_move and getattr(debit_move, 'move_type', '') == 'out_invoice':
                                is_customer_invoice = True
                                break
                        if is_customer_invoice:
                            break

                if is_customer_invoice:
                    continue

                partner = line.partner_id or move.partner_id
                inv_name = partner.name.strip() if partner and partner.name else 'Direct / Miscellaneous Investor'
                category = ', '.join(partner.category_id.mapped('name')) if partner and partner.category_id else 'General'
                inv_key = inv_name.lower()

                if inv_key not in investor_data_map:
                    investor_data_map[inv_key] = {
                        'name': inv_name,
                        'category': category,
                        'y1_quarters': {f'q{i}': 0.0 for i in range(1, 5)},
                        'y2_quarters': {f'q{i}': 0.0 for i in range(1, 5)},
                    }

                conv_debit = line.company_id.currency_id._convert(
                    line.debit, target_currency, get_rate_company(line), line.date or fields.Date.today()
                )

                ldate = line.date
                ldate_str = ldate.strftime('%Y-%m-%d') if ldate else ''

                if y1_start_str <= ldate_str <= y1_end_str:
                    q_num = get_q_num(ldate_str, y1_fy_start)
                    if q_num:
                        investor_data_map[inv_key]['y1_quarters'][f'q{q_num}'] += conv_debit

                if y2_start_str <= ldate_str <= y2_end_str:
                    q_num = get_q_num(ldate_str, y2_cy_start)
                    if q_num:
                        investor_data_map[inv_key]['y2_quarters'][f'q{q_num}'] += conv_debit

        investor_rows = []
        for inv_key in sorted(investor_data_map.keys()):
            inv_info = investor_data_map[inv_key]

            y1_q1 = inv_info['y1_quarters']['q1']
            y1_q2 = inv_info['y1_quarters']['q2']
            y1_q3 = inv_info['y1_quarters']['q3']
            y1_q4 = inv_info['y1_quarters']['q4']
            y1_tot = y1_q1 + y1_q2 + y1_q3 + y1_q4

            y2_q1 = inv_info['y2_quarters']['q1']
            y2_q2 = inv_info['y2_quarters']['q2']
            y2_q3 = inv_info['y2_quarters']['q3']
            y2_q4 = inv_info['y2_quarters']['q4']
            y2_tot = y2_q1 + y2_q2 + y2_q3 + y2_q4

            if (y1_tot < 0.01 and y2_tot < 0.01):
                continue

            row = {
                'investor': inv_info['name'],
                'category': inv_info['category'],
                'y1_q1': target_currency.round(y1_q1),
                'y1_q2': target_currency.round(y1_q2),
                'y1_q3': target_currency.round(y1_q3),
                'y1_q4': target_currency.round(y1_q4),
                'y1_tot': target_currency.round(y1_tot),

                'y2_q1': target_currency.round(y2_q1),
                'y2_q2': target_currency.round(y2_q2),
                'y2_q3': target_currency.round(y2_q3),
                'y2_q4': target_currency.round(y2_q4),
                'y2_tot': target_currency.round(y2_tot),
            }
            investor_rows.append(row)

        investor_totals = {
            'y1_q1': target_currency.round(sum(r['y1_q1'] for r in investor_rows)),
            'y1_q2': target_currency.round(sum(r['y1_q2'] for r in investor_rows)),
            'y1_q3': target_currency.round(sum(r['y1_q3'] for r in investor_rows)),
            'y1_q4': target_currency.round(sum(r['y1_q4'] for r in investor_rows)),
            'y1_tot': target_currency.round(sum(r['y1_tot'] for r in investor_rows)),

            'y2_q1': target_currency.round(sum(r['y2_q1'] for r in investor_rows)),
            'y2_q2': target_currency.round(sum(r['y2_q2'] for r in investor_rows)),
            'y2_q3': target_currency.round(sum(r['y2_q3'] for r in investor_rows)),
            'y2_q4': target_currency.round(sum(r['y2_q4'] for r in investor_rows)),
            'y2_tot': target_currency.round(sum(r['y2_tot'] for r in investor_rows)),
        }

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
            'monthly_cashflow': monthly_cashflow,
            'total_cf_y1_in': total_cf_y1_in,
            'total_cf_y1_out': total_cf_y1_out,
            'total_cf_y1_remaining': total_cf_y1_remaining,
            'total_cf_y2_in': total_cf_y2_in,
            'total_cf_y2_out': total_cf_y2_out,
            'total_cf_y2_remaining': total_cf_y2_remaining,
            'investor_rows': investor_rows,
            'investor_totals': investor_totals,
        }

