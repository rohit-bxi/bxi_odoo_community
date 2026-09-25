import base64
import importlib.util

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import PolicyCommon, make_pdf


@tagged('post_install', '-at_install')
class TestPolicyVersion(PolicyCommon):

    def test_version_numbering(self):
        first = self._version()
        second = self._version()
        self.assertEqual((first.version_no, second.version_no), (1, 2))
        self.assertEqual(first.display_name, 'Test Antitrust Policy - v1')

    def test_valid_dates(self):
        with self.assertRaises(ValidationError):
            self._version(valid_to='2000-01-01')

    def test_approval_workflow(self):
        version = self._version()
        with self.assertRaises(AccessError):
            version.with_user(self.employee.user_id).action_submit()
        version.with_user(self.hr_manager).action_submit()
        self.assertEqual(version.state, 'submitted')
        self.assertTrue(version.activity_ids.filtered(lambda a: a.user_id == self.cpo))
        with self.assertRaises(AccessError):
            version.with_user(self.hr_manager).action_approve()
        with self.assertRaises(UserError):
            version.with_user(self.hr_manager).action_publish()  # not approved yet
        version.with_user(self.cpo).action_approve()
        self.assertEqual(version.state, 'approved')
        self.assertEqual(version.approved_by_id, self.cpo)
        self.assertFalse(version.activity_ids)

    def test_reject_requires_reason(self):
        version = self._version()
        version.with_user(self.hr_manager).action_submit()
        with self.assertRaises(UserError):
            version.with_user(self.cpo).action_reject()
        version.with_user(self.cpo).reject_reason = 'Update the version table'
        version.with_user(self.cpo).action_reject()
        self.assertEqual(version.state, 'rejected')
        version.with_user(self.hr_manager).action_submit()
        self.assertFalse(version.reject_reason)

    def test_publish_copies_document_and_supersedes(self):
        first = self._publish()
        self.assertEqual(first.state, 'published')
        self.assertEqual(self.policy.current_version_id, first)
        self.assertEqual(self.policy.policy_filename, 'policy.pdf')
        second = self._version(filename='policy-v2.pdf')
        self._publish(second)
        self.assertEqual(first.state, 'superseded')
        self.assertEqual(self.policy.current_version_id, second)
        self.assertEqual(self.policy.policy_filename, 'policy-v2.pdf')

    def test_published_version_is_locked(self):
        version = self._publish()
        with self.assertRaises(UserError):
            version.with_user(self.hr_manager).write({'document': base64.b64encode(make_pdf('other'))})
        with self.assertRaises(UserError):
            version.with_user(self.hr_manager).unlink()
        version.with_user(self.hr_manager).description = 'Typo fixed'

    def test_employees_only_see_published_versions(self):
        draft = self._version()
        Version = self.env['hr.company.policy.version'].with_user(self.employee.user_id)
        self.assertFalse(Version.search([('id', '=', draft.id)]))
        self._publish(draft)
        self.assertTrue(Version.search([('id', '=', draft.id)]))

    def test_company_rule(self):
        own = self.env['hr.company.policy'].create({'name': 'Own company policy', 'company_id': self.company.id})
        other = self.env['hr.company.policy'].create({'name': 'Other company policy', 'company_id': self.other_company.id})
        Policy = self.env['hr.company.policy'].with_user(self.employee.user_id)
        visible = Policy.search([('id', 'in', (own | other | self.policy).ids)])
        self.assertEqual(visible, own | self.policy)

    def test_migration_creates_published_version(self):
        policy = self.env['hr.company.policy'].create({
            'name': 'Legacy policy', 'policy_document': base64.b64encode(make_pdf('legacy')),
            'policy_filename': 'legacy.pdf',
        })
        path = __file__.replace('tests/test_policy_version.py', 'migrations/19.0.1.1.0/post-migrate.py')
        spec = importlib.util.spec_from_file_location('policy_post_migrate', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, '19.0.1.0.0')
        self.assertEqual(len(policy.version_ids), 1)
        self.assertEqual(policy.version_ids.state, 'published')
        self.assertFalse(policy.requires_acknowledgement, "Existing policies do not ask everyone at once")
        self.assertFalse(policy.version_ids.acknowledgement_ids)
