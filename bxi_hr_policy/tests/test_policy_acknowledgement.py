from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import PolicyCommon


@tagged('post_install', '-at_install')
class TestPolicyAcknowledgement(PolicyCommon):

    # ── Creation ─────────────────────────────────────────────────────────
    def test_publish_asks_everyone_in_every_company(self):
        version = self._publish()
        acks = self._acks(version)
        self.assertIn(self.employee, acks.employee_id)
        self.assertIn(self.other_employee, acks.employee_id, "Policies without company apply to all companies")
        self.assertNotIn(self.no_user_employee, acks.employee_id, "Employees need a user to acknowledge")
        ack = self._ack_of(version, self.employee)
        self.assertEqual(ack.state, 'pending')
        self.assertEqual(ack.due_date, self.today + timedelta(days=7))
        self.assertEqual(ack.statement, self.policy.ack_statement)
        self.assertTrue(version.activity_ids.filtered(lambda a: a.user_id == self.employee.user_id))

    def test_one_email_per_employee(self):
        mails_before = self.env['mail.mail'].search_count([])
        version = self._publish()
        self.assertEqual(self.env['mail.mail'].search_count([]) - mails_before >= len(self._acks(version)), True)
        mail = self.env['mail.mail'].search([('recipient_ids', 'in', self.employee.user_id.partner_id.ids)],
                                            order='id desc', limit=1)
        self.assertIn('Test Antitrust Policy', mail.body_html)

    def test_policy_without_acknowledgement(self):
        self.policy.requires_acknowledgement = False
        version = self._publish()
        self.assertFalse(self._acks(version))
        with self.assertRaises(UserError):
            self.policy.action_request_acknowledgement()

    def test_company_scope(self):
        self.policy.company_id = self.company
        version = self._publish()
        self.assertNotIn(self.other_employee, self._acks(version).employee_id)

    def test_selected_companies_scope(self):
        self.policy.write({'scope': 'companies', 'scope_company_ids': [(6, 0, self.other_company.ids)]})
        version = self._publish()
        self.assertEqual(self._acks(version).employee_id, self.other_employee)

    def test_department_scope(self):
        department = self.env['hr.department'].create({'name': 'Policy Sales'})
        sub_department = self.env['hr.department'].create({'name': 'Policy Sales EU', 'parent_id': department.id})
        self.employee.department_id = sub_department
        self.policy.write({'scope': 'departments', 'scope_department_ids': [(6, 0, department.ids)]})
        version = self._publish()
        self.assertEqual(self._acks(version).employee_id, self.employee)

    def test_new_version_cancels_open_acknowledgements(self):
        first = self._publish()
        done = self._ack_of(first, self.manager)
        done._mark_opened()
        done.with_user(self.manager.user_id)._do_acknowledge('backend')
        second = self._publish()
        self.assertEqual(self._ack_of(first, self.employee).state, 'cancelled')
        self.assertEqual(done.state, 'acknowledged', "Past acknowledgements are kept")
        self.assertEqual(self._ack_of(second, self.manager).state, 'pending', "A new version asks again")

    def test_request_acknowledgement_only_adds_missing(self):
        version = self._publish()
        count = len(self._acks(version))
        self.policy.action_request_acknowledgement()
        self.assertEqual(len(self._acks(version)), count)

    def test_new_joiner(self):
        version = self._publish()
        joiner = self._employee('Policy Joiner')
        self.assertEqual(self._ack_of(version, joiner).state, 'pending')

    def test_user_given_later(self):
        version = self._publish()
        user = self.env['res.users'].create({'name': 'Late User', 'login': 'policy_test_late'})
        self.no_user_employee.user_id = user
        self.assertTrue(self._ack_of(version, self.no_user_employee))

    def test_leaver_and_rehire(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        self.employee.active = False
        self.assertEqual(ack.state, 'cancelled')
        self.employee.active = True
        self.assertEqual(ack.state, 'cancelled', "The cancelled record is kept as history")

    # ── Acknowledging ────────────────────────────────────────────────────
    def test_document_must_be_opened(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee).with_user(self.employee.user_id)
        with self.assertRaises(UserError):
            ack.action_acknowledge()
        ack._mark_opened()
        self.assertTrue(ack.document_opened)
        ack.action_acknowledge()
        self.assertEqual(ack.state, 'acknowledged')
        self.assertEqual(ack.channel, 'backend')
        self.assertTrue(ack.acknowledged_date)
        self.assertFalse(version.activity_ids.filtered(lambda a: a.user_id == self.employee.user_id))

    def test_only_own_acknowledgement(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        ack._mark_opened()
        with self.assertRaises(AccessError):
            ack.with_user(self.manager.user_id).action_acknowledge()

    def test_acknowledged_record_is_frozen(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        ack._mark_opened()
        ack.with_user(self.employee.user_id).action_acknowledge()
        with self.assertRaises(UserError):
            ack.with_user(self.employee.user_id).action_acknowledge()
        with self.assertRaises(UserError):
            ack.with_user(self.hr_manager).waive_reason = 'Too late'
        with self.assertRaises(AccessError):
            ack.with_user(self.hr_manager).write({'acknowledged_date': False})
        with self.assertRaises(UserError):
            ack.unlink()

    def test_waive(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        with self.assertRaises(AccessError):
            ack.with_user(self.employee.user_id).action_waive()
        with self.assertRaises(UserError):
            ack.with_user(self.hr_manager).action_waive()
        ack.with_user(self.hr_manager).waive_reason = 'Long-term leave'
        ack.with_user(self.hr_manager).action_waive()
        self.assertEqual(ack.state, 'waived')
        self.assertEqual(ack.waived_by_id, self.hr_manager)

    def test_acknowledgement_rate(self):
        version = self._publish()
        acks = self._acks(version)
        ack = self._ack_of(version, self.employee)
        ack._mark_opened()
        ack.with_user(self.employee.user_id).action_acknowledge()
        self.policy.invalidate_recordset(['ack_rate', 'ack_done', 'ack_total'])
        self.assertEqual(self.policy.ack_total, len(acks))
        self.assertEqual(self.policy.ack_done, 1)
        self.assertAlmostEqual(self.policy.ack_rate, 100.0 / len(acks))

    def test_visibility(self):
        version = self._publish()
        Ack = self.env['hr.policy.acknowledgement']
        own = Ack.with_user(self.employee.user_id).search([('version_id', '=', version.id)])
        self.assertEqual(own.employee_id, self.employee)
        team = Ack.with_user(self.manager.user_id).search([('version_id', '=', version.id)])
        self.assertEqual(team.employee_id, self.manager | self.employee)
        self.assertEqual(len(Ack.with_user(self.hr_manager).search([('version_id', '=', version.id)])),
                         len(self._acks(version)))

    def test_certificate_report(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        ack._mark_opened()
        ack.with_user(self.employee.user_id).action_acknowledge()
        action = ack.action_print_certificate()
        self.assertIn(action['type'], ('ir.actions.report', 'ir.actions.act_window'))  # layout wizard first on new DBs
        html = self.env['ir.actions.report']._render_qweb_html(
            'bxi_hr_policy.report_policy_acknowledgement', ack.ids)[0]
        self.assertIn(b'Policy Employee', html)
        register = self.env['ir.actions.report']._render_qweb_html(
            'bxi_hr_policy.report_policy_register', version.ids)[0]
        self.assertIn(b'Policy Other', register)

    # ── Reminders and escalation ─────────────────────────────────────────
    def _run_cron(self):
        self.env['hr.policy.acknowledgement']._cron_process_acknowledgements()

    def _mails_to(self, user):
        return self.env['mail.mail'].search([('recipient_ids', 'in', user.partner_id.ids)])

    def test_overdue_and_reminder(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        self._run_cron()
        self.assertEqual(ack.state, 'pending')
        self.assertFalse(ack.last_reminder_date, "No reminder before the interval")
        self._shift_dates(ack, 8)
        before = len(self._mails_to(self.employee.user_id))
        self._run_cron()
        self.assertEqual(ack.state, 'overdue')
        self.assertEqual(ack.last_reminder_date, self.today)
        self.assertEqual(len(self._mails_to(self.employee.user_id)), before + 1)
        self._run_cron()
        self.assertEqual(len(self._mails_to(self.employee.user_id)), before + 1, "Next reminder after the interval")

    def test_escalation_to_manager_and_hr(self):
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        self._shift_dates(ack, 7 + 3)  # 3 days overdue
        manager_before = len(self._mails_to(self.manager.user_id))
        self._run_cron()
        self.assertTrue(ack.escalated_manager)
        self.assertFalse(ack.escalated_hr)
        self.assertEqual(len(self._mails_to(self.manager.user_id)), manager_before + 1)
        self._shift_dates(ack, 4)  # 7 days overdue
        hr_before = len(self._mails_to(self.hr_manager))
        self._run_cron()
        self.assertTrue(ack.escalated_hr)
        self.assertGreater(len(self._mails_to(self.hr_manager)), hr_before)

    def test_escalation_disabled(self):
        self.policy.write({'escalate_manager_after_days': 0, 'escalate_hr_after_days': 0, 'reminder_interval_days': 0})
        version = self._publish()
        ack = self._ack_of(version, self.employee)
        self._shift_dates(ack, 30)
        self._run_cron()
        self.assertEqual(ack.state, 'overdue')
        self.assertFalse(ack.escalated_manager or ack.escalated_hr or ack.last_reminder_date)

    def test_grouped_emails(self):
        second_policy = self.env['hr.company.policy'].create({'name': 'Test Gift Policy', 'company_id': False})
        acks = self._ack_of(self._publish(), self.employee) | self._ack_of(self._publish(policy=second_policy), self.employee)
        self._shift_dates(acks, 3)
        before = len(self._mails_to(self.employee.user_id))
        self._run_cron()
        mails = self._mails_to(self.employee.user_id)
        self.assertEqual(len(mails), before + 1, "One email lists both policies")
        self.assertIn('Test Gift Policy', mails[0].body_html)
        self.assertIn('Test Antitrust Policy', mails[0].body_html)

    def test_negative_days_rejected(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.policy.ack_due_days = -1
