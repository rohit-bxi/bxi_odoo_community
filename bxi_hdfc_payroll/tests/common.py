# -*- coding: utf-8 -*-
from datetime import date

from odoo.fields import Command
from odoo.tests import TransactionCase


class HdfcPayrollCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inr = cls.env.ref('base.INR')
        cls.inr.active = True
        cls.hdfc_bank = cls.env['res.bank'].create({'name': 'HDFC Bank', 'bic': 'HDFC0001234'})
        cls.sbi_bank = cls.env['res.bank'].create({'name': 'State Bank of India', 'bic': 'SBIN0005678'})

        cls.company = cls._create_company('HDFC Test Co')
        cls.config = cls._create_config(cls.company)
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))

    @classmethod
    def _create_company(cls, name):
        return cls.env['res.company'].create({'name': name, 'currency_id': cls.inr.id})

    @classmethod
    def _create_config(cls, company, **vals):
        env = cls.env(context=dict(cls.env.context, allowed_company_ids=company.ids))
        Account = env['account.account'].with_company(company)
        payable = Account.create({'code': '2101', 'name': 'Salary Payable', 'account_type': 'liability_current',
                                  'reconcile': True})
        expense = Account.create({'code': '6101', 'name': 'Salary Expense', 'account_type': 'expense'})
        outstanding = Account.create({'code': '1102', 'name': 'Outstanding Payments', 'account_type': 'asset_current',
                                      'reconcile': True})
        bank_account = Account.create({'code': '1101', 'name': 'HDFC Current Account', 'account_type': 'asset_cash'})
        journal = env['account.journal'].create({
            'name': 'HDFC Bank', 'type': 'bank', 'code': 'HDFB',
            'company_id': company.id, 'default_account_id': bank_account.id,
        })
        return env['hdfc.bank.config'].create({
            'name': 'HDFC %s' % company.name,
            'company_id': company.id,
            'environment': 'mock',
            'debit_account_number': '50200012345678',
            'debit_ifsc': 'HDFC0000001',
            'journal_id': journal.id,
            'salary_entry_mode': 'payable',
            'salary_payable_account_id': payable.id,
            'salary_expense_account_id': expense.id,
            'credit_account_id': outstanding.id,
            **vals,
        })

    @classmethod
    def _create_employee(cls, name, accounts=(), company=None, distribution=None):
        """:param accounts: iterable of ``(acc_number, bank, trusted)``"""
        company = company or cls.company
        env = cls.env(context=dict(cls.env.context, allowed_company_ids=company.ids))
        employee = env['hr.employee'].create({'name': name, 'company_id': company.id})
        bank_accounts = env['res.partner.bank']
        for acc_number, bank, trusted in accounts:
            bank_accounts |= env['res.partner.bank'].create({
                'partner_id': employee.work_contact_id.id,
                'acc_number': acc_number,
                'bank_id': bank.id,
                'allow_out_payment': trusted,
            })
        employee.bank_account_ids = [Command.set(bank_accounts.ids)]
        if distribution:
            employee.salary_distribution = {
                str(bank_accounts[index].id): vals for index, vals in distribution.items()
            }
        return employee

    @classmethod
    def _create_payslip(cls, employee, net, state='done', **vals):
        env = cls.env(context=dict(cls.env.context, allowed_company_ids=employee.company_id.ids))
        slip = env['hr.payslip'].create({
            'employee_id': employee.id,
            'name': 'Salary %s' % employee.name,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
            'company_id': employee.company_id.id,
            **vals,
        })
        slip.write({'net_wage': net, 'state': state})
        return slip

    def _release(self, slips, payment_date=date(2026, 9, 30)):
        wizard = self.env['hdfc.release.wizard'].create({
            'payslip_ids': [Command.set(slips.ids)],
            'payment_date': payment_date,
        })
        action = wizard.action_release()
        if action.get('res_id'):
            return self.env['hdfc.payout.batch'].browse(action['res_id'])
        return self.env['hdfc.payout.batch'].search(action['domain'])
