import base64
import itertools
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, new_test_user

_receipt_counter = itertools.count()


class ConveyanceTestMixin:
    """A Reporting Manager with employees of each travel plan, Finance and HR officers, and the policy defaults."""

    @classmethod
    def _setup_conveyance_data(cls):
        # The tests must not depend on the configuration of the database they run on.
        cls.company = cls.env.company
        cls.company.conveyance_hr_user_id = cls.company.conveyance_finance_user_id = False
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        for key, value in {
            'claim_days': 45, 'reminder_days': 7, 'office_coverage_months': 2, 'food_daily_limit': 1000,
            'non_working_day_mode': 'block',
        }.items():
            set_param(f'bxi_local_conveyance.{key}', value)

        cls.today = fields.Date.today()
        # A working schedule from Monday to Friday, without public holidays of the database.
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Conveyance Test 40h', 'company_id': cls.company.id, 'tz': 'Asia/Kolkata',
            'attendance_ids': [
                Command.create({'name': f'Day {day} {period}', 'dayofweek': str(day), 'hour_from': start,
                                'hour_to': end, 'day_period': period})
                for day in range(5)
                for period, start, end in (('morning', 9, 13), ('afternoon', 14, 18))
            ],
        })
        cls.workday = cls._last_day(lambda day: day.weekday() < 5)
        cls.weekend_day = cls._last_day(lambda day: day.weekday() == 5)

        cls.hr_user = new_test_user(
            cls.env, login='lc_test_hr', name='Conveyance HR',
            groups='base.group_user,bxi_local_conveyance.group_conveyance_hr')
        cls.finance_user = new_test_user(
            cls.env, login='lc_test_finance', name='Conveyance Finance',
            groups='base.group_user,bxi_local_conveyance.group_conveyance_finance')
        cls.outsider = new_test_user(cls.env, login='lc_test_outsider', name='Outsider', groups='base.group_user')
        cls.department = cls.env['hr.department'].create({'name': 'Conveyance Engineering'})
        cls.sales = cls.env['hr.department'].create({'name': 'Conveyance Sales', 'is_sales_team': True})
        cls.manager = cls._create_employee('Manager', band='7')
        cls.employee = cls._create_employee('Engineer', band='4.1', parent=cls.manager)       # TP2
        cls.junior = cls._create_employee('Junior', band='1.2', parent=cls.manager)            # TP3
        cls.senior = cls._create_employee('Senior', band='8', parent=cls.manager)              # TP1
        cls.salesman = cls._create_employee('Salesman', band='2', parent=cls.manager, department=cls.sales)

        cls.product_2w = cls.env.ref('bxi_local_conveyance.product_conveyance_2w')
        cls.product_4w = cls.env.ref('bxi_local_conveyance.product_conveyance_4w')
        cls.product_auto = cls.env.ref('bxi_local_conveyance.product_conveyance_auto')
        cls.product_taxi = cls.env.ref('bxi_local_conveyance.product_conveyance_taxi')
        cls.product_parking = cls.env.ref('bxi_local_conveyance.product_conveyance_parking')
        cls.product_food = cls.env.ref('bxi_local_conveyance.product_food_sales')
        cls.product_transfer_2w = cls.env.ref('bxi_local_conveyance.product_conveyance_transfer_2w')
        cls.product_transfer_4w = cls.env.ref('bxi_local_conveyance.product_conveyance_transfer_4w')
        # Table A rates, whatever the database says.
        cls.product_2w.standard_price = cls.product_transfer_2w.standard_price = 2.5
        cls.product_4w.standard_price = cls.product_transfer_4w.standard_price = 5.0

    @classmethod
    def _last_day(cls, condition):
        """The most recent past day (from yesterday) meeting the condition."""
        day = cls.today - timedelta(days=1)
        while not condition(day):
            day -= timedelta(days=1)
        return day

    @classmethod
    def _create_employee(cls, name, band=False, parent=None, department=None):
        login = 'lc_test_' + name.lower()
        user = new_test_user(cls.env, login=login, groups='base.group_user', email=f"{login}@example.com", name=name)
        return cls.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'role_band': band,
            'parent_id': parent.id if parent else False,
            'department_id': (department or cls.department).id,
            'work_email': f"{login}@example.com",
            'resource_calendar_id': cls.calendar.id,
            'tz': 'Asia/Kolkata',
        })

    @classmethod
    def _office(cls, name, street=None):
        address = cls.env['res.partner'].create({'name': name, 'street': street or f"{name} Street"})
        return cls.env['hr.work.location'].create({
            'name': name, 'location_type': 'office', 'address_id': address.id,
        })

    def _receipt(self, expense, content=None):
        content = content or f"Receipt {next(_receipt_counter)}".encode()
        return self.env['ir.attachment'].create({
            'name': 'receipt.txt',
            'datas': base64.b64encode(content),
            'res_model': 'hr.expense',
            'res_id': expense.id,
        })

    def _claim(self, product, employee=None, receipt=True, **vals):
        """A draft claim of the employee, filed as them, with a receipt for bill-based types."""
        employee = employee or self.employee
        kind = product.conveyance_kind
        values = {
            'name': f"{product.name} claim",
            'product_id': product.id,
            'employee_id': employee.id,
            'date': self.workday,
            'payment_mode': 'own_account',
        }
        if kind in ('vehicle_2w', 'vehicle_4w', 'auto', 'taxi'):
            values.update({
                'conveyance_purpose': 'client_visit', 'conveyance_from': 'Saket office',
                'conveyance_to': 'Client, Gurugram', 'conveyance_within_city': True,
            })
        if kind in ('vehicle_2w', 'vehicle_4w', 'transfer_2w', 'transfer_4w'):
            values['conveyance_distance'] = 10
        else:
            values['total_amount_currency'] = 300
        values.update(vals)
        expense = self.env['hr.expense'].with_user(employee.user_id).create(values)
        if receipt and kind not in ('vehicle_2w', 'vehicle_4w', 'transfer_2w', 'transfer_4w'):
            self._receipt(expense.sudo())
        return expense

    def _submit(self, expense):
        expense.with_user(expense.sudo().employee_id.user_id).action_submit()
        return expense


class ConveyanceCommon(ConveyanceTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_conveyance_data()
