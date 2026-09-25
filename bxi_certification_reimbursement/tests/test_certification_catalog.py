from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestCertificationCatalog(CertificationCommon):

    def test_display_name(self):
        self.assertEqual(self.certification.display_name, '[TEST-CLOUD] Test Cloud Architect')
        self.certification.version_exam_no = 'CA-01'
        self.assertEqual(self.certification.display_name, '[TEST-CLOUD] Test Cloud Architect (CA-01)')
        self.assertEqual(self.udemy.display_name, 'Test Python Course')

    def test_default_currency(self):
        self.assertEqual(self.certification.currency_id, self.env.company.currency_id)

    def test_duplicate_certification(self):
        values = {'name': 'test cloud architect', 'certifying_body': 'CLOUD INC', 'website': 'https://example.com'}
        with self.assertRaises(ValidationError):
            self.env['bxi.certification'].create(values)
        self.certification.active = False
        with self.assertRaises(ValidationError):
            self.env['bxi.certification'].create(values)

    def test_same_certification_other_version(self):
        other = self.env['bxi.certification'].create({
            'name': 'Test Cloud Architect', 'certifying_body': 'Cloud Inc', 'website': 'https://example.com',
            'version_exam_no': 'V2',
        })
        self.assertTrue(other)

    @mute_logger('odoo.sql_db')
    def test_duplicate_certification_code(self):
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env['bxi.certification'].create({
                'name': 'Other', 'certifying_body': 'Other', 'website': 'https://example.com', 'code': 'TEST-CLOUD',
            })

    @mute_logger('odoo.sql_db')
    def test_duplicate_lob_code(self):
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env['bxi.line.of.business'].create({'name': 'Other', 'code': self.lob.code})

    def test_employee_reads_but_cannot_edit_list(self):
        Certification = self.env['bxi.certification'].with_user(self.engineer.user_id)
        self.assertIn(self.certification, Certification.search([]))
        with self.assertRaises(AccessError):
            Certification.create({'name': 'Mine', 'certifying_body': 'Me', 'website': 'https://me.com'})
        with self.assertRaises(AccessError):
            self.certification.with_user(self.engineer.user_id).cost = 1

    def test_academy_maintains_list(self):
        Certification = self.env['bxi.certification'].with_user(self.academy_head.user_id)
        new = Certification.create({'name': 'New', 'certifying_body': 'Body', 'website': 'https://new.com'})
        new.cost = 500
        self.assertEqual(new.cost, 500)

    def test_only_administrators_manage_lines_of_business(self):
        with self.assertRaises(AccessError):
            self.env['bxi.line.of.business'].with_user(self.academy_head.user_id).create({'name': 'X', 'code': 'TEST-X1'})
        hr_manager = self.env['res.users'].create({
            'name': 'HR Manager', 'login': 'cert_test_hr_manager',
            'group_ids': [(6, 0, self.env.ref('hr.group_hr_manager').ids)],
        })
        lob = self.env['bxi.line.of.business'].with_user(hr_manager).create({'name': 'X', 'code': 'TEST-X2'})
        self.assertTrue(lob)
