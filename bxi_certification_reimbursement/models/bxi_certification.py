from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class BxiCertification(models.Model):
    _name = 'bxi.certification'
    _description = 'Approved Certification'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Certification Name',
        required=True,
        tracking=True,
        help="Expanded name exactly as on the certifying body's site.",
    )
    code = fields.Char(
        string='Code',
        tracking=True,
        help="Code employees select when raising the claim in My Claims.",
    )
    version_exam_no = fields.Char(string='Version / Exam #')
    certifying_body = fields.Char(string='Certifying Body', required=True, tracking=True)
    area = fields.Char(string='Area of Certification')
    lob_id = fields.Many2one('bxi.line.of.business', string='Line of Business', tracking=True)
    cost = fields.Monetary(string='Cost', currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    website = fields.Char(string='Website', required=True)
    is_udemy = fields.Boolean(
        string='Udemy Course',
        help="Needs prior written approval from the capability/training academy; "
             "reimbursement is capped at the approved amount.",
    )
    description = fields.Text(string='Information')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True, tracking=True)

    _code_uniq = models.Constraint(
        'unique(code, company_id)',
        'The certification code must be unique per company.',
    )

    @api.constrains('name', 'version_exam_no', 'certifying_body', 'company_id')
    def _check_duplicate(self):
        for rec in self:
            duplicate = self.sudo().with_context(active_test=False).search_count([
                ('id', '!=', rec.id),
                ('name', '=ilike', rec.name),
                ('version_exam_no', '=', rec.version_exam_no or False),
                ('certifying_body', '=ilike', rec.certifying_body),
                ('company_id', '=', rec.company_id.id),
            ])
            if duplicate:
                raise ValidationError(_("%(name)s already exists in the approved list.", name=rec.name))

    @api.depends('name', 'code', 'version_exam_no')
    def _compute_display_name(self):
        for rec in self:
            name = rec.name or ''
            if rec.version_exam_no:
                name = f"{name} ({rec.version_exam_no})"
            if rec.code:
                name = f"[{rec.code}] {name}"
            rec.display_name = name
