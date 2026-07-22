from odoo import models, fields, api
from datetime import date


class ProjectContract(models.Model):
    _name = 'project.contract.management'
    _description = 'Project Contract Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char("Contract Name", required=True, tracking=True)

    lead_id = fields.Many2one(
        'crm.lead',
        string='Opportunity',
        tracking=True
    )
    service_line_id = fields.Many2one(
        'project.contract.service.line',
        string='Service Line',
        tracking=True
    )




    sale_order_ids = fields.Many2many(
        'sale.order',
        'contract_sale_order_rel',
        'contract_id',
        'sale_order_id',
        string="Sales Orders",
        tracking=True
    )

    
    project_ids = fields.Many2many(
        'project.project',
        'contract_project_rel',
        'contract_id',
        'project_id',
        string="Projects",
        tracking=True
    )


    client_ids = fields.Many2many(
        'res.partner',
        'contract_partner_rel',
        'contract_id',
        'partner_id',
        string="Clients",
        tracking=True
    )



    project_count = fields.Integer(compute="_compute_counts")
    client_count = fields.Integer(compute="_compute_counts")

    contract_start_date = fields.Date("Start Date", tracking=True)

    contract_end_date = fields.Date("End Date", tracking=True)

    invoice_ids = fields.Many2many(
        'account.move',
        'contract_invoice_rel',
        'contract_id',
        'invoice_id',
        string="Linked Invoices",
        domain="[('move_type', '=', 'out_invoice')]",
        tracking=True
    )

    invoice_count = fields.Integer(compute="_compute_invoice_count", string="Invoice Count")

    def _compute_invoice_count(self):
        for rec in self:
            direct_invoices = self.env['account.move'].search([('contract_id', '=', rec.id)])
            so_invoices = rec.sale_order_ids.invoice_ids
            m2m_invoices = rec.invoice_ids
            rec.invoice_count = len(direct_invoices | so_invoices | m2m_invoices)

    def action_view_invoices(self):
        self.ensure_one()
        direct_invoices = self.env['account.move'].search([('contract_id', '=', self.id)])
        so_invoices = self.sale_order_ids.invoice_ids
        m2m_invoices = self.invoice_ids
        all_invoices = direct_invoices | so_invoices | m2m_invoices
        return {
            'name': 'Invoices',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_invoices.ids)],
            'context': {
                'default_move_type': 'out_invoice',
                'default_contract_id': self.id,
                'default_partner_id': self.client_ids[0].id if self.client_ids else False,
                'default_currency_id': self.currency_id.id if self.currency_id else False,
            }
        }




    contract_tenure = fields.Float("Tenure (Years)", compute="_compute_tenure", store=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        tracking=True
    )


    contract_amount = fields.Monetary("Contract Amount", currency_field='currency_id', tracking=True)
    industry_id = fields.Many2one('res.partner.industry', string="Industry", tracking=True)

    milestone_no = fields.Integer("No. Of Milestones", tracking=True)

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )

    contract_type = fields.Selection([
        ('fixed', 'Fixed Price (Lump Sum)'),
        ('tnm', 'Time & Material (T&M)'),
        ('retainer', 'Retainer / Support (SLA)'),
        ('staff_aug', 'Staff Augmentation'),
        ('cost_plus', 'Cost Plus / Reimbursable'),
        ('saas', 'SaaS / Subscription')
    ], string="Contract Type", tracking=True)


    billing_cycle = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
        ('milestone', 'Milestone'),
        ('bi_weekly', 'Bi-weekly'),
        ('one_time', 'One-time / Upfront')
    ], string="Billing Cycle", tracking=True)

    @api.onchange('contract_type')
    def _onchange_contract_type(self):
        if self.contract_type:
            if self.contract_type == 'fixed':
                self.billing_cycle = 'milestone'
            elif self.contract_type == 'saas':
                self.billing_cycle = 'yearly'
            elif self.contract_type in ('tnm', 'staff_aug', 'cost_plus', 'retainer'):
                self.billing_cycle = 'monthly'





    stage_id = fields.Many2one(
        'project.contract.stage',
        string="Stage",
        group_expand='_read_group_stage_ids',
        tracking=True
    )

    contract_attachment_ids = fields.Many2many(
        'ir.attachment',
        'contract_attachment_rel',
        'contract_id',
        'attachment_id',
        string="Attachments"
    )

    probability = fields.Float(
        related="stage_id.probability",
        store=True
    )


    def _read_group_stage_ids(self, stages, domain, order=None):
        Stage = self.env['project.contract.stage']
        return Stage.search([], order=order or 'sequence, id')

    @api.model_create_multi
    def create(self, vals_list):

        stage = self.env['project.contract.stage'].search(
            [],
            order='sequence asc',
            limit=1
        )

        for vals in vals_list:

            if not vals.get('stage_id') and stage:
                vals['stage_id'] = stage.id

        return super().create(vals_list)

    @api.depends('project_ids', 'client_ids')
    def _compute_counts(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)
            rec.client_count = len(rec.client_ids)

    def action_view_projects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Projects',
            'res_model': 'project.project',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.project_ids.ids)],
        }


    def action_view_clients(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Clients',
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.client_ids.ids)],
        }

    # =========================
    # TENURE CALCULATION (DAY BASED)
    # =========================
    @api.depends('contract_start_date', 'contract_end_date')
    def _compute_tenure(self):
        for rec in self:
            if rec.contract_start_date and rec.contract_end_date:
                days = (rec.contract_end_date - rec.contract_start_date).days + 1
                rec.contract_tenure = round(days / 365, 2)
            else:
                rec.contract_tenure = 0

    # =========================
    # CREATE PROJECT ACTION
    # =========================
    def action_create_project(self):
        self.ensure_one()
        return {
            'name': 'Create Project',
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_name': self.name,
                'default_partner_id': self.client_ids[0].id if self.client_ids else False,
                'default_contract_ids': [(4, self.id)],
            }
        }


class ProjectProject(models.Model):
    _inherit = 'project.project'

    contract_ids = fields.Many2many(
        'project.contract.management',
        'contract_project_rel',
        'project_id',
        'contract_id',
        string="Contracts"
    )


class AccountMove(models.Model):
    _inherit = 'account.move'

    contract_id = fields.Many2one(
        'project.contract.management',
        string="Contract"
    )

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        if self.contract_id:
            if self.contract_id.client_ids:
                self.partner_id = self.contract_id.client_ids[0]
            if self.contract_id.currency_id:
                self.currency_id = self.contract_id.currency_id


class ProjectContractServiceLine(models.Model):
    _name = 'project.contract.service.line'
    _description = 'Contract Service Line'
    _order = 'sequence, id'

    name = fields.Char("Service Line", required=True)
    active = fields.Boolean("Active", default=True)
    sequence = fields.Integer("Sequence", default=10)
