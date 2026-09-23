from odoo import models, fields, api
from odoo.exceptions import UserError


class BxiCertificationInclusion(models.Model):
    """Annexure B: request to include a certification in the approved list."""
    _name = 'bxi.certification.inclusion'
    _description = 'Certification Inclusion Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env._('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Requested By',
        required=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_user_id = fields.Many2one(related='employee_id.user_id', string='Requester User')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    lob_id = fields.Many2one('bxi.line.of.business', string='Line of Business', required=True)
    certification_name = fields.Char(
        string='Certification Name',
        required=True,
        help="Expanded form with version and/or exam number, exactly as on the certifying body's site.",
    )
    version_exam_no = fields.Char(string='Version / Exam #')
    certifying_body = fields.Char(string='Certifying Body', required=True)
    area = fields.Char(string='Area of Certification', required=True)
    cost = fields.Monetary(string='Cost', currency_field='currency_id', required=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    information = fields.Text(string='Information about the Certification')
    website = fields.Char(string='Website', required=True)
    is_du_specific = fields.Selection(
        [('y', 'Y'), ('n', 'N')],
        string="Specific to the Employee's DU",
        required=True,
        default='n',
    )
    business_case = fields.Text(string='Business Case', required=True)
    submit_date = fields.Date(string='Submitted On', readonly=True, copy=False)
    deadline_date = fields.Date(
        string='Respond By',
        readonly=True,
        copy=False,
        help="The academy informs the employee within 10 working days.",
    )
    certification_id = fields.Many2one('bxi.certification', string='Approved Certification', readonly=True, copy=False)
    response = fields.Text(string='Academy Response', tracking=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Included'),
            ('rejected', 'Not Included'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.certification.inclusion') or self.env._('New')
        return super().create(vals_list)

    def _get_deadline(self):
        self.ensure_one()
        days = int(self.env['bxi.certification.request']._get_policy_param('inclusion_sla_days', 10))
        employee = self.employee_id.sudo()
        calendar = employee.resource_calendar_id or self.company_id.resource_calendar_id
        now = fields.Datetime.now()
        if calendar:
            deadline = calendar.plan_days(days, now)
            if deadline:
                return deadline.date()
        return fields.Date.add(now.date(), days=days)

    def _is_academy_user(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group('bxi_certification_reimbursement.group_certification_manager'):
            return True
        lob = self.lob_id.sudo()
        return user.has_group('bxi_certification_reimbursement.group_certification_academy') and (
            user in lob.academy_user_ids or lob.academy_head_id.user_id == user)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft requests can be submitted."))
            rec.sudo().write({
                'state': 'submitted',
                'submit_date': fields.Date.context_today(rec),
                'deadline_date': rec._get_deadline(),
            })
            lob = rec.lob_id.sudo()
            for user in (lob.academy_head_id.user_id | lob.academy_user_ids):
                rec.sudo().activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=rec.deadline_date,
                    user_id=user.id,
                    summary=self.env._("Certification inclusion request: %(name)s", name=rec.certification_name),
                )

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted' or not rec._is_academy_user():
                raise UserError(self.env._("You are not allowed to approve this request."))
            certification = self.env['bxi.certification'].sudo().create({
                'name': rec.certification_name,
                'version_exam_no': rec.version_exam_no,
                'certifying_body': rec.certifying_body,
                'area': rec.area,
                'lob_id': rec.lob_id.id,
                'cost': rec.cost,
                'currency_id': rec.currency_id.id,
                'website': rec.website,
                'description': rec.information,
                'company_id': rec.company_id.id,
            })
            rec.sudo().write({'state': 'approved', 'certification_id': certification.id})
            rec._close_and_notify(self.env._(
                "%(name)s has been included in the approved certification list. You may proceed with "
                "the certification as per the process.",
                name=rec.certification_name,
            ))

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted' or not rec._is_academy_user():
                raise UserError(self.env._("You are not allowed to reject this request."))
            if not rec.response:
                raise UserError(self.env._("Enter the academy response explaining why it is not included."))
            rec.sudo().state = 'rejected'
            rec._close_and_notify(self.env._(
                "%(name)s has not been included in the approved list: %(response)s. Please reach out to "
                "your LoB Academy for further clarifications.",
                name=rec.certification_name, response=rec.response,
            ))

    def action_reset_to_draft(self):
        self.filtered(lambda r: r.state == 'rejected').sudo().write({'state': 'draft'})

    def _close_and_notify(self, body):
        self.ensure_one()
        self.sudo().activity_unlink(['mail.mail_activity_data_todo'])
        partner = self.employee_id.sudo().work_contact_id
        self.sudo().message_post(body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment')

    @api.model
    def _cron_remind_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self.search([('state', '=', 'submitted'), ('deadline_date', '<', today)]):
            rec.message_post(body=self.env._("This inclusion request is past its response date (%(date)s).", date=rec.deadline_date))
