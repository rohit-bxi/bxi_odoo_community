from collections import defaultdict
from odoo import models, api, fields


class CustomPLReport(models.Model):
    _name = 'custom.pl.report'

    @api.model
    def get_filtered_data(self, financial_year=None, quarters=None, company_ids=None, currency_id=None):

        if company_ids:
            self = self.with_context(
                allowed_company_ids=company_ids,
                company_id=company_ids[0]
            )

        start_date = False
        end_date = False

        if financial_year:
            fy_start = int(financial_year)
            fy_end = fy_start + 1
            start_date = f"{fy_start}-04-01"
            end_date = f"{fy_end}-03-31"

        def get_quarter(date):
            if not date or not financial_year:
                return None

            fy_start = int(financial_year)
            fy_end = fy_start + 1

            if fields.Date.from_string(f"{fy_start}-04-01") <= date <= fields.Date.from_string(f"{fy_start}-06-30"):
                return 'q1'
            elif fields.Date.from_string(f"{fy_start}-07-01") <= date <= fields.Date.from_string(f"{fy_start}-09-30"):
                return 'q2'
            elif fields.Date.from_string(f"{fy_start}-10-01") <= date <= fields.Date.from_string(f"{fy_start}-12-31"):
                return 'q3'
            elif fields.Date.from_string(f"{fy_end}-01-01") <= date <= fields.Date.from_string(f"{fy_end}-03-31"):
                return 'q4'
            return None

        target_currency = (
            self.env['res.currency'].browse(currency_id)
            if currency_id else self.env.company.currency_id
        )

        invoices_domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['paid', 'in_payment']),
        ]

        if company_ids:
            invoices_domain.append(('company_id', 'in', company_ids))

        if start_date and end_date:
            invoices_domain += [
                ('invoice_date', '>=', start_date),
                ('invoice_date', '<=', end_date),
            ]

        invoices = self.env['account.move'].search(invoices_domain)

        customers = defaultdict(lambda: {
            'salespersons': {},
            'total_booking': 0,
            'total_billing': 0,
            'quarters_projected': defaultdict(float),
            'quarters_actual': defaultdict(float),
            'country': '',
        })

        for inv in invoices:
            partner = inv.partner_id
            customer = partner.name if partner else 'N/A'
            salesperson = inv.user_id.name or 'N/A'
            q = get_quarter(inv.invoice_date)

            cust = customers[customer]

            if not cust['country']:
                cust['country'] = partner.country_id.name or ''

            if salesperson not in cust['salespersons']:
                cust['salespersons'][salesperson] = {
                    'salesperson': salesperson,
                    'products': '',
                    'booking': 0,
                    'billing': 0,
                    'quarters_projected': defaultdict(float),
                    'quarters_actual': defaultdict(float),
                }

            sp = cust['salespersons'][salesperson]

            company_currency = inv.company_id.currency_id
            date = inv.invoice_date or fields.Date.today()

            amount = target_currency.round(inv.amount_total)

            sp['billing'] = target_currency.round(sp['billing'] + amount)
            cust['total_billing'] = target_currency.round(cust['total_billing'] + amount)

            if q:
                sp['quarters_actual'][q] = target_currency.round(
                    sp['quarters_actual'][q] + amount
                )
                cust['quarters_actual'][q] = target_currency.round(
                    cust['quarters_actual'][q] + amount
                )

        result = []

        for cust_name, cust_data in customers.items():

            cust_data['total_billing'] = target_currency.round(cust_data['total_billing'])

            for q in cust_data['quarters_actual']:
                cust_data['quarters_actual'][q] = target_currency.round(
                    cust_data['quarters_actual'][q]
                )

            salespersons = []
            for sp in cust_data['salespersons'].values():
                sp['booking'] = 0
                sp['billing'] = target_currency.round(sp['billing'])

                for q in sp['quarters_actual']:
                    sp['quarters_actual'][q] = target_currency.round(
                        sp['quarters_actual'][q]
                    )
                salespersons.append(sp)

            result.append({
                'customer': cust_name,
                'country': cust_data['country'],
                'salespersons': salespersons,
                'total_booking': 0,
                'total_billing': cust_data['total_billing'],
                'quarters_projected': cust_data['quarters_projected'],
                'quarters_actual': cust_data['quarters_actual'],
            })

        expense_domain = [
            ('state', 'in', ['done', 'approved', 'post', 'posted'])
        ]

        if company_ids:
            expense_domain.append(('company_id', 'in', company_ids))

        expenses = self.env['hr.expense'].search(expense_domain)

        expenses_data = {
            'people': 0,
            'tools': 0,
            'travel': 0,
            'misc': 0
        }

        for exp in expenses:
            name = (exp.name or '').lower()

            if any(x in name for x in ['salary', 'employee', 'wage']):
                expenses_data['people'] += exp.total_amount
            elif any(x in name for x in ['tool', 'software', 'license']):
                expenses_data['tools'] += exp.total_amount
            elif 'travel' in name:
                expenses_data['travel'] += exp.total_amount
            else:
                expenses_data['misc'] += exp.total_amount

        return {
            'customers': result,
            'expenses': expenses_data,
            'quarters': ['q1', 'q2', 'q3', 'q4'],
            'currency': {
                'name': target_currency.name,
                'symbol': target_currency.symbol,
            }
        }

# class CustomPLLine(models.Model):
#     _name = 'custom.pl.line'

#     report_id = fields.Many2one('custom.pl.report')
#     partner_id = fields.Many2one('res.partner', string="Customer")

#     country_id = fields.Many2one(related='partner_id.country_id', store=True)

#     work_order = fields.Char()
#     tenure = fields.Integer()

#     financial_year = fields.Selection([
#         ('2025', '2025-2026'),
#         ('2026', '2026-2027'),
#     ])

    # quarter = fields.Selection([
    #     ('q1', 'Q1'),
    #     ('q2', 'Q2'),
    #     ('q3', 'Q3'),
    #     ('q4', 'Q4'),
    # ])

    # ================= XLSX EXPORT =================
    # @api.model
    # def action_download_xlsx(self, financial_year=None, quarters=None):

    #     data = self.get_filtered_data(financial_year, quarters)['data']

    #     output = io.BytesIO()
    #     workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    #     sheet = workbook.add_worksheet('P&L Report')

    #     # Formats
    #     bold = workbook.add_format({'bold': True, 'border': 1})
    #     normal = workbook.add_format({'border': 1})
    #     header = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#0b3c4c', 'color': 'white'})
    #     yellow = workbook.add_format({'border': 1, 'bg_color': '#ffe600'})
    #     green = workbook.add_format({'border': 1, 'bg_color': '#7bdcb5', 'bold': True})

    #     row = 0

    #     # Header
    #     headers = ['Client Partner', 'GEO', 'Customer', 'Workorder', 'Tenure', 'Value','Value1']
    #     for col, h in enumerate(headers):
    #         sheet.write(row, col, h, header)

    #     col_offset = len(headers)

    #     quarters_list = quarters or ['q1', 'q2', 'q3', 'q4']

    #     for q in quarters_list:
    #         sheet.write(row, col_offset, q.upper() + " REV", header)
    #         sheet.write(row, col_offset + 1, "EXP", header)
    #         sheet.write(row, col_offset + 2, "GP", header)
    #         sheet.write(row, col_offset + 3, "GM", header)
    #         col_offset += 4

    #     row += 1

    #     # Data
    #     for partner in data.values():
    #         for geo in partner['geo_map'].values():
    #             for customer in geo['customers'].values():

    #                 for wo in customer['workorders']:
    #                     col = 0
    #                     sheet.write(row, col, partner['partner'], normal); col += 1
    #                     sheet.write(row, col, geo['geo'], normal); col += 1
    #                     sheet.write(row, col, customer['customer'], normal); col += 1
    #                     sheet.write(row, col, wo['workorder'], normal); col += 1
    #                     sheet.write(row, col, wo['tenure'], normal); col += 1
    #                     sheet.write(row, col, wo['value'], normal); col += 1
    #                     sheet.write(row, col, wo['value'], normal); col += 1
                        
                        # for q in quarters_list:
                        #     qdata = customer['quarters'].get(q, {})
                        #     sheet.write(row, col, qdata.get('rev', 0), yellow); col += 1
                        #     sheet.write(row, col, qdata.get('exp', 0), yellow); col += 1
                        #     sheet.write(row, col, qdata.get('gp', 0), yellow); col += 1
                        #     sheet.write(row, col, qdata.get('gm', 0), yellow); col += 1

                        # row += 1

                # ✅ Portfolio row
    #             sheet.write(row, 0, 'Portfolio Total', green)
    #             sheet.write(row, 5, geo['total_value'], green)
    #             row += 1

    #     workbook.close()
    #     output.seek(0)

    #     file = base64.b64encode(output.read())

    #     attachment = self.env['ir.attachment'].create({
    #         'name': 'PL_Report.xlsx',
    #         'type': 'binary',
    #         'datas': file,
    #     })

    #     return {
    #         'type': 'ir.actions.act_url',
    #         'url': f'/web/content/{attachment.id}?download=true',
    #         'target': 'self',
    #     }

    # # ================= PDF =================
    # def action_print_pdf(self):
    #     return self.env.ref(
    #         'bxi_accounting_report.pl_report_pdf_action'
    #     ).report_action(self)


# ================= LINE MODEL =================
