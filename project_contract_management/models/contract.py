from odoo import models, fields, api
from datetime import date


class ProjectContract(models.Model):
    _name = 'project.contract.management'
    _description = 'Project Contract Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char("Contract Name", required=True, tracking=True)

    lead_id = fields.Many2one(
        'crm.lead',
        string='Opportunity'
    )

    sale_order_ids = fields.Many2many(
        'sale.order',
        'contract_sale_order_rel',
        'contract_id',
        'sale_order_id',
        string="Sales Orders"
    )
    
    project_ids = fields.Many2many(
        'project.project',
        'contract_project_rel',
        'contract_id',
        'project_id',
        string="Projects"
    )

    client_ids = fields.Many2many(
        'res.partner',
        'contract_partner_rel',
        'contract_id',
        'partner_id',
        string="Clients"
    )
    project_count = fields.Integer(compute="_compute_counts")
    client_count = fields.Integer(compute="_compute_counts")

    contract_start_date = fields.Date("Start Date")
    contract_end_date = fields.Date("End Date")

    contract_tenure = fields.Float("Tenure (Years)", compute="_compute_tenure", store=True)

    contract_amount = fields.Float("Contract Amount")
    milestone_no = fields.Integer("No. Of Milestones")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    contract_type = fields.Selection([
        ('fixed', 'Fixed'),
        ('tnm', 'Time & Material')
    ], string="Contract Type")

    billing_cycle = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
        ('milestone', 'Milestone'),
    ], string="Billing Cycle")

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

    contract_quarter_ids = fields.One2many(
        'contract.quarter.line',
        'contract_id',
        string="Quarter Breakdown"
    )

    total_quarter_amount = fields.Float(
        compute="_compute_total",
        store=True
    )

    exceed_warning = fields.Boolean(
        compute="_compute_total",
        store=True
    )

    progress_percent = fields.Float(
        string="Progress %",
        compute="_compute_progress",
        store=True
    )

    probability = fields.Float(
        related="stage_id.probability",
        store=True
    )
    progress_color = fields.Char(
        compute="_compute_progress_color"
    )

    def _compute_progress_color(self):
        for rec in self:
            if rec.progress_percent > 100:
                rec.progress_color = 'bg-danger'
            elif rec.progress_percent > 70:
                rec.progress_color = 'bg-warning'
            else:
                rec.progress_color = 'bg-success'

    def action_auto_split_remaining(self):
        for rec in self:
            if not rec.contract_quarter_ids:
                return

            total = sum(rec.contract_quarter_ids.mapped('amount'))
            remaining = rec.contract_amount - total

            if remaining <= 0:
                return

            count = len(rec.contract_quarter_ids)
            per_line = remaining / count

            for line in rec.contract_quarter_ids:
                line.amount += per_line

    @api.depends('contract_quarter_ids.amount', 'contract_quarter_ids.billed', 'contract_amount')
    def _compute_progress(self):
        for rec in self:
            billed_amount = sum(
                line.amount for line in rec.contract_quarter_ids if line.billed
            )

            if rec.contract_amount:
                rec.progress_percent = (billed_amount / rec.contract_amount) * 100
            else:
                rec.progress_percent = 0

    @api.depends('contract_quarter_ids.amount', 'contract_amount')
    def _compute_total(self):
        for rec in self:
            total = sum(rec.contract_quarter_ids.mapped('amount'))
            rec.total_quarter_amount = total
            rec.exceed_warning = total > rec.contract_amount


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
    # GENERATE QUARTERS
    # =========================
    def action_generate_quarters(self):
        for rec in self:
            rec.contract_quarter_ids.unlink()

            if not rec.contract_start_date or not rec.contract_end_date:
                continue

            total_years = int(rec.contract_tenure)
            if total_years <= 0:
                total_years = 1

            yearly_amount = rec.contract_amount / total_years
            quarterly_amount = yearly_amount / 4

            year = rec.contract_start_date.year

            for y in range(total_years):
                for q in range(1, 5):
                    self.env['contract.quarter.line'].create({
                        'contract_id': rec.id,
                        'year': year + y,
                        'quarter': f'Q{q}',
                        'amount': quarterly_amount,
                    })


class ContractQuarterLine(models.Model):
    _name = 'contract.quarter.line'
    _description = 'Contract Quarter Line'

    contract_id = fields.Many2one('project.contract.management', ondelete='cascade')

    year = fields.Integer("Year")
    quarter = fields.Selection([
        ('Q1', 'Q1'),
        ('Q2', 'Q2'),
        ('Q3', 'Q3'),
        ('Q4', 'Q4'),
    ])

    amount = fields.Float("Amount")
    billed = fields.Boolean("Billed")