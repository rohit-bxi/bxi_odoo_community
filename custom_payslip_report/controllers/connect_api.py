from odoo.http import request, Controller, route
import datetime


class BXIController(Controller):

    @route('/api/v1/userpayslipdata', type="jsonrpc", auth='public', methods=["POST"], csrf=False)
    def user_payslip_data(self, **kw):
        # ✅ In jsonrpc, request payload comes in request.params
        payload = request.params or {}

        emp_email = payload.get("emp_email")
        month = payload.get("month")
        year = payload.get("year")

        if not emp_email:
            return {"status": 0, "message": "Request atleast contains the emp_email"}
        if not month:
            return {"status": 0, "message": "Request atleast contains the month"}
        if not year:
            return {"status": 0, "message": "Request atleast contains the year"}

        try:
            month = int(month)
            year = int(year)
        except Exception:
            return {"status": 0, "message": "month and year must be integers"}

        env = request.env
        emp = env["hr.employee"].sudo().search(
                    [("work_email", "ilike", emp_email.strip())],
                    limit=1
                )
        if not emp:
            return {"status": 0, "message": "No Employee is found for this Employee Email"}

        slips = env["hr.payslip"].sudo().search([("employee_id", "=", emp.id)])
        slips = slips.filtered(lambda s: s.date_from and s.date_from.month == month and s.date_from.year == year)

        if not slips:
            return {"status": 200, "message": "No Payslip Data is Found", "data": []}

        def _sum_rule_total(slip, codes):
            if isinstance(codes, str):
                codes = [codes]
            lines = slip.line_ids.filtered(lambda l: l.code in codes)
            return sum(lines.mapped("total")) if lines else 0.0

        def _sum_category_total(slip, category_code):
            lines = slip.line_ids.filtered(lambda l: l.category_id and l.category_id.code == category_code)
            return sum(lines.mapped("total")) if lines else 0.0

        def _fy_start_year(date_from):
            return date_from.year if date_from.month >= 4 else (date_from.year - 1)

        def _fy_month_wise_tds(employee, upto_date_from):
            fy_start = _fy_start_year(upto_date_from)
            all_slips = employee.slip_ids.sudo()
            out = []

            def add_month(y, m):
                month_date = datetime.date(y, m, 1)
                if month_date <= upto_date_from:
                    ms = all_slips.filtered(lambda s:
                        s.date_from and s.date_from.month == m and s.date_from.year == y and s.date_from <= upto_date_from
                    )
                    tax = abs(sum(ms.mapped("line_ids").filtered(lambda l: l.code == "TDS").mapped("total")) or 0.0)
                    out.append({
                        "month": month_date.strftime("%B"),
                        "year": y,
                        "label": f"{month_date.strftime('%B')}'{str(y)[-2:]}",
                        "tds": float(tax),
                    })

            for m in [4, 5, 6, 7, 8, 9, 10, 11, 12]:
                add_month(fy_start, m)
            for m in [1, 2, 3]:
                add_month(fy_start + 1, m)

            return out

        data = []
        for slip in slips:
            header = {
                "salary_payslip_month": slip.date_to.strftime("%B %Y") if slip.date_to else "",
                "pay_period_from": slip.date_from.strftime("%d.%m.%Y") if slip.date_from else "",
                "pay_period_to": slip.date_to.strftime("%d.%m.%Y") if slip.date_to else "",
                "employee_name": emp.name or "",
                "company_label": (slip.company_id.name or "") if slip.company_id else "",
                "company_tagline_1": "Technology Brilliance",
                "company_tagline_2": "Service First Mindset",
            }

            bank_accounts = [{
                "bank_name": acc.bank_id.name if acc.bank_id else "",
                "account_no": acc.acc_number or "",
            } for acc in emp.bank_account_ids]

            work_days_line = slip.worked_days_line_ids.filtered(lambda l: l.code == "WORK100")
            lwp_input_line = slip.input_line_ids.filtered(lambda i: i.code == "LWP_DAYS")

            work_days = (work_days_line and work_days_line[0].number_of_days) or 0.0
            lwp_days = (lwp_input_line and lwp_input_line[0].amount) or 0.0

            employee_details = {
                "employee_no": emp.employee_code or "",
                "employee_name": emp.name or "",
                "bank_accounts": bank_accounts,
                "designation": emp.job_title or "",
                "location": getattr(emp, "psa", "") or "",
                "doj": emp.contract_date_start.isoformat() if emp.contract_date_start else "",
                "gender": (getattr(emp, "sex", "") or "").capitalize(),
                "department": emp.department_id.name if emp.department_id else "",
                "pan_number": getattr(emp, "l10n_in_pan", "") or "",
                "band": getattr(emp, "role_band", "") or "",
                "medical_insurance_no": getattr(emp, "medical_insurance_no", "") or "",
                "day_worked_in_month": round((work_days or 0.0) - (lwp_days or 0.0)),
                "pf_pension_no": "",
                "lwp_current_previous": float(sum(slip.input_line_ids.filtered(lambda l: l.code == "LWP_DAYS").mapped("amount")) or 0.0),
                "uan_no": getattr(emp, "l10n_in_uan", "") or "",
                "sabbatical_leave": "",
            }

            standard_monthly_salary = {
                "basic_salary": float(getattr(emp, "l10n_in_basic_salary_amount", 0.0) or 0.0),
                "hra": float(getattr(emp, "l10n_in_hra", 0.0) or 0.0),
                "flexible_allowance": float(getattr(emp, "l10n_in_fixed_allowance", 0.0) or 0.0),
            }
            standard_monthly_salary["total_standard_salary"] = float(
                (standard_monthly_salary["basic_salary"] or 0.0) +
                (standard_monthly_salary["flexible_allowance"] or 0.0)
            )

            earnings = {
                "basic_salary": float(_sum_rule_total(slip, "BASIC")),
                "hra": float(_sum_rule_total(slip, "HRA")),
                "flexible_allowance": float(_sum_rule_total(slip, "SPL")),
                "arrear_allowance": float(abs(_sum_rule_total(slip, "ARA"))),
                "gross_earning": float(_sum_category_total(slip, "GROSS")),
            }

            deductions = {
                "medical_premium": float(abs(_sum_rule_total(slip, "MIP"))),
                "ee_pf_monthly": float(abs(_sum_rule_total(slip, "PF"))),
                "income_tax": float(abs(_sum_rule_total(slip, "TDS"))),
                "deduction": float(abs(_sum_rule_total(slip, "DEDUCTION"))),
                "gross_deduction": float(abs(_sum_category_total(slip, "DED"))),
            }

            earnings_deductions = {
                "standard_monthly_salary": standard_monthly_salary,
                "earnings": earnings,
                "deductions": deductions,
                "show_arrear_deduction_row": bool(slip.line_ids.filtered(lambda l: l.code in ("ARA", "DEDUCTION"))),
                "net_pay": float(_sum_rule_total(slip, "NET")),
            }

            income_tax_computation = {
                "exception_us_10": {
                    "er_pf_monthly": float(getattr(emp, "l10n_in_pf_employer_amount", 0.0) or 0.0),
                    "er_nps_monthly": float(getattr(emp, "nps_contribution", 0.0) or 0.0),
                },
                "monthly_tax_deduction": _fy_month_wise_tds(emp, slip.date_from) if slip.date_from else [],
            }

            footer = {
                "note_1": "This is a computer-generated payslip and does not require a signature or company seal.",
                "note_2": "One-time payments are subject to applicable tax slab.",
                "note_3": "Refer EPF portal for Pension details.",
            }

            data.append({
                "payslip_id": slip.id,
                "header": header,
                "employee_details": employee_details,
                "earnings_deductions": earnings_deductions,
                "income_tax_computation": income_tax_computation,
                "footer": footer,
            })

        return {"status": 200, "message": "Success", "data": data}