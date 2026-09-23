import re

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # role_band is stored as text such as "1.1", "2.2", "4.1", "10".
    # The part before the dot is the band; a higher band is more senior.
    band_level = fields.Integer(
        string='Band Level',
        compute='_compute_band_level',
        store=True,
        groups='hr.group_hr_user',
    )
    is_band_set = fields.Boolean(
        string='Band Set',
        compute='_compute_band_level',
        store=True,
        groups='hr.group_hr_user',
    )
    lob_id = fields.Many2one(
        'bxi.line.of.business',
        string='Line of Business',
        groups='hr.group_hr_user',
    )
    cost_center_id = fields.Many2one(
        'account.analytic.account',
        string='Cost Centre',
        groups='hr.group_hr_user',
        help="Certification reimbursements approved by this Band 4 head "
             "are charged to this cost centre.",
    )
    is_india_payroll = fields.Boolean(
        string='India Payroll',
        compute='_compute_is_india_payroll',
        store=True,
        readonly=False,
        groups='hr.group_hr_user',
        help="Only employees on the India payroll are covered by the Certification Policy.",
    )
    has_active_resignation = fields.Boolean(
        string='Resignation Submitted',
        compute='_compute_has_active_resignation',
        groups='hr.group_hr_user',
    )

    @api.model
    def _parse_band_level(self, role_band):
        """Return the band number of a role band ("4.1" -> 4), or None."""
        match = re.match(r'\s*(\d+)', role_band or '')
        return int(match.group(1)) if match else None

    @api.depends('role_band')
    def _compute_band_level(self):
        for rec in self:
            level = self._parse_band_level(rec.role_band)
            rec.is_band_set = level is not None
            rec.band_level = level or 0

    @api.depends('company_id.country_id')
    def _compute_is_india_payroll(self):
        for rec in self:
            rec.is_india_payroll = rec.company_id.country_id.code == 'IN'

    def _compute_has_active_resignation(self):
        read_group_result = self.env['employee.resignation'].sudo()._read_group(
            [('employee_id', 'in', self.ids), ('state', 'in', ('submitted', 'approved'))],
            ['employee_id'],
            ['__count'],
        )
        resigned = {employee.id for employee, count in read_group_result if count}
        for rec in self:
            rec.has_active_resignation = rec.id in resigned

    def _get_band_head(self, level, raise_if_not_found=True):
        """Return the manager who acts as the given band head for this employee.

        The nearest manager in the reporting line at exactly that band is used.
        Otherwise the nearest more senior manager (higher band number), and
        failing that the head of the reporting line when no band is set on
        them (e.g. the founder).
        """
        self.ensure_one()
        employee = self.sudo()
        fallback = self.env['hr.employee']
        top = self.env['hr.employee']
        seen = {employee.id}
        manager = employee.parent_id
        while manager and manager.id not in seen:
            seen.add(manager.id)
            if manager.is_band_set:
                if manager.band_level == level:
                    return manager
                if not fallback and manager.band_level > level:
                    fallback = manager
            top = manager
            manager = manager.parent_id
        head = fallback or (top if top and not top.is_band_set else self.env['hr.employee'])
        if not head and raise_if_not_found:
            raise UserError(_(
                "No Band %(level)s head found in the reporting line of %(employee)s. "
                "Please check the managers and role bands.",
                level=level, employee=employee.name,
            ))
        return head

    def _get_skip_manager(self):
        """Return the Reporting Manager's Reporting Manager."""
        self.ensure_one()
        manager = self.sudo().parent_id
        return manager.parent_id or manager
