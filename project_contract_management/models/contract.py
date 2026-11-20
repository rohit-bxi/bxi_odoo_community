from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare
from datetime import date, timedelta
import re


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

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids)

    def action_view_invoices(self):
        self.ensure_one()
        context = {
            'default_move_type': 'out_invoice',
            'default_contract_id': self.id,
            'default_partner_id': self.client_ids[0].id if self.client_ids else False,
            'default_currency_id': self.currency_id.id if self.currency_id else False,
        }
        if self.sale_order_ids:
            context['default_sale_order_id'] = self.sale_order_ids[0].id
            context['default_invoice_origin'] = self.sale_order_ids[0].name

        return {
            'name': 'Invoices',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
            'context': context,
        }

    @api.onchange('sale_order_ids')
    def _onchange_sale_order_ids(self):
        if self.sale_order_ids:
            so_invoices = self.sale_order_ids.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
            new_invoices = so_invoices - self.invoice_ids
            if new_invoices:
                self.invoice_ids = [(4, inv.id) for inv in new_invoices]




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

    def _convert_usd_to_target_currency(self, usd_amount, target_currency, target_date=None):
        if not usd_amount or not target_currency:
            return usd_amount or 0.0

        currency_code = target_currency.name or ""
        d = target_date or fields.Date.context_today(self)
        year = d.year if hasattr(d, "year") else fields.Date.today().year

        if year >= 2027:
            rate_usd_inr = 93.0
            rate_aed_inr = 25.6
        else:
            rate_usd_inr = 90.0
            rate_aed_inr = 24.5

        if currency_code == "USD":
            converted = usd_amount
        elif currency_code == "INR":
            converted = usd_amount * rate_usd_inr
        elif currency_code == "AED":
            converted = (usd_amount * rate_usd_inr) / rate_aed_inr
        else:
            usd_curr = (
                self.env.ref("base.USD", raise_if_not_found=False)
                or self.env["res.currency"].search([("name", "=", "USD")], limit=1)
            )
            if usd_curr and usd_curr != target_currency:
                converted = usd_curr._convert(
                    usd_amount,
                    target_currency,
                    self.company_id or self.env.company,
                    d,
                )
            else:
                converted = usd_amount

        return target_currency.round(converted) if hasattr(target_currency, "round") else round(converted, 2)

    @api.onchange('lead_id', 'currency_id', 'contract_start_date')
    def _onchange_lead_currency_for_amount(self):
        if self.lead_id and getattr(self.lead_id, 'expected_revenue', False) and self.currency_id:
            self.contract_amount = self._convert_usd_to_target_currency(
                self.lead_id.expected_revenue,
                self.currency_id,
                self.contract_start_date,
            )

    stage_id = fields.Many2one(
        'project.contract.stage',
        string="Stage",
        group_expand='_read_group_stage_ids',
        tracking=True
    )
    is_draft = fields.Boolean(
        string="Is Draft",
        compute="_compute_is_draft",
        store=True,
    )

    @api.depends('stage_id', 'stage_id.name', 'stage_id.sequence')
    def _compute_is_draft(self):
        for rec in self:
            if not rec.stage_id:
                rec.is_draft = True
            else:
                stage_name = (rec.stage_id.name or '').strip().lower()
                rec.is_draft = bool(stage_name == 'draft' or rec.stage_id.sequence == 0)
    is_draft = fields.Boolean(
        string="Is Draft",
        compute="_compute_is_draft",
        store=True,
    )

    @api.depends('stage_id', 'stage_id.name', 'stage_id.sequence')
    def _compute_is_draft(self):
        for rec in self:
            if not rec.stage_id:
                rec.is_draft = True
            else:
                stage_name = (rec.stage_id.name or '').strip().lower()
                rec.is_draft = bool(stage_name == 'draft' or rec.stage_id.sequence == 0)

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

    @api.constrains('project_ids')
    def _check_project_ids_single_contract(self):
        for rec in self:
            for project in rec.project_ids:
                proj_id = project._origin.id if project._origin else (project.id if isinstance(project.id, int) else False)
                if not proj_id:
                    continue
                # 1. Check if another contract in current batch already has this project
                other_in_batch = self.filtered(lambda c: c.id != rec.id and project in c.project_ids)
                if other_in_batch:
                    raise ValidationError(_(
                        "The project '%(project)s' cannot be attached to multiple contracts (found on '%(contract)s' and '%(other)s'). "
                        "One project can only be attached to one contract.",
                        project=project.display_name,
                        contract=rec.display_name,
                        other=other_in_batch[0].display_name
                    ))
                # 2. Check in database for any other contract containing this project
                other_contracts = self.search([
                    ('id', '!=', rec.id),
                    ('project_ids', 'in', [proj_id])
                ], limit=1)
                if other_contracts:
                    raise ValidationError(_(
                        "The project '%(project)s' is already attached to contract '%(contract)s'. "
                        "One project can only be attached to one contract.",
                        project=project.display_name,
                        contract=other_contracts.display_name
                    ))

    @api.constrains('project_ids', 'contract_amount', 'company_id', 'client_ids')
    def _check_projects_contract_consistency(self):
        for rec in self:
            messages = []
            for project in rec.project_ids:
                # 1. Billing amount check
                if project.billing_amount and rec.contract_amount:
                    contract_amt = rec.contract_amount
                    if project.currency_id and rec.currency_id and project.currency_id != rec.currency_id:
                        contract_amt = rec.currency_id._convert(
                            contract_amt, project.currency_id, project.company_id or self.env.company, fields.Date.today()
                        )
                    if float_compare(project.billing_amount, contract_amt, precision_digits=2) > 0:
                        messages.append(
                            _("Billing amount of project '%(proj)s' (%(billing)s) cannot be more than the contract amount (%(contract_amt)s).",
                              proj=project.name, billing=f"{project.billing_amount:,.2f}", contract_amt=f"{contract_amt:,.2f}")
                        )

                # 2. Company check
                if project.company_id and rec.company_id and project.company_id != rec.company_id:
                    messages.append(
                        _("Company of project '%(proj)s' ('%(p_comp)s') and contract ('%(c_comp)s') must be the same.",
                          proj=project.name, p_comp=project.company_id.name, c_comp=rec.company_id.name)
                    )

                # 3. Customer check
                if project.partner_id and rec.client_ids:
                    contract_partners = rec.client_ids | rec.client_ids.commercial_partner_id
                    project_partners = project.partner_id | project.partner_id.commercial_partner_id
                    if not (project_partners & contract_partners):
                        client_names = ", ".join(rec.client_ids.mapped('name'))
                        messages.append(
                            _("Customer of project '%(proj)s' ('%(partner)s') and contract ('%(clients)s') must be the same.",
                              proj=project.name, partner=project.partner_id.name, clients=client_names)
                        )

            if messages:
                raise ValidationError("\n".join(messages))

    @api.onchange('project_ids', 'contract_amount', 'company_id', 'client_ids')
    def _onchange_project_ids_single_contract(self):
        for rec in self:
            rec_id = rec._origin.id if rec._origin else False
            messages = []
            for project in rec.project_ids:
                proj_id = project._origin.id if project._origin else (project.id if isinstance(project.id, int) else False)
                if not proj_id:
                    continue
                # Single contract check
                if project.contract_id and project.contract_id.id != rec_id:
                    messages.append(
                        _("The project '%(project)s' is already attached to contract '%(contract)s'. One project can only be attached to one contract.",
                          project=project.display_name, contract=project.contract_id.display_name)
                    )
                else:
                    other = self.search([
                        ('id', '!=', rec_id),
                        ('project_ids', 'in', [proj_id])
                    ], limit=1)
                    if other:
                        messages.append(
                            _("The project '%(project)s' is already attached to contract '%(contract)s'. One project can only be attached to one contract.",
                              project=project.display_name, contract=other.display_name)
                        )

                # 1. Billing amount check
                if project.billing_amount and rec.contract_amount:
                    contract_amt = rec.contract_amount
                    if project.currency_id and rec.currency_id and project.currency_id != rec.currency_id:
                        contract_amt = rec.currency_id._convert(
                            contract_amt, project.currency_id, project.company_id or self.env.company, fields.Date.today()
                        )
                    if float_compare(project.billing_amount, contract_amt, precision_digits=2) > 0:
                        messages.append(
                            _("Billing amount of project '%(proj)s' (%(billing)s) cannot be more than the contract amount (%(contract_amt)s).",
                              proj=project.name, billing=f"{project.billing_amount:,.2f}", contract_amt=f"{contract_amt:,.2f}")
                        )

                # 2. Company check
                if project.company_id and rec.company_id and project.company_id != rec.company_id:
                    messages.append(
                        _("Company of project '%(proj)s' ('%(p_comp)s') and contract ('%(c_comp)s') must be the same.",
                          proj=project.name, p_comp=project.company_id.name, c_comp=rec.company_id.name)
                    )

                # 3. Customer check
                if project.partner_id and rec.client_ids:
                    contract_partners = rec.client_ids | rec.client_ids.commercial_partner_id
                    project_partners = project.partner_id | project.partner_id.commercial_partner_id
                    if not (project_partners & contract_partners):
                        client_names = ", ".join(rec.client_ids.mapped('name'))
                        messages.append(
                            _("Customer of project '%(proj)s' ('%(partner)s') and contract ('%(clients)s') must be the same.",
                              proj=project.name, partner=project.partner_id.name, clients=client_names)
                        )

            if messages:
                return {
                    'warning': {
                        'title': _("Contract Validation Warning"),
                        'message': "\n".join(f"• {m}" for m in messages)
                    }
                }

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

        records = super().create(vals_list)
        records._update_client_customer_type()
        for rec in records:
            if rec.project_ids:
                for proj in rec.project_ids:
                    proj.with_context(from_contract_sync=True).write({'contract_id': rec.id})
            if rec.sale_order_ids:
                so_invoices = rec.sale_order_ids.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
                for inv in so_invoices:
                    if inv not in rec.invoice_ids:
                        rec.with_context(from_invoice_sync=True).write({'invoice_ids': [(4, inv.id)]})
                    if not inv.contract_id:
                        inv.with_context(from_contract_sync=True).write({'contract_id': rec.id})
                    if not inv.sale_order_id and rec.sale_order_ids:
                        inv.with_context(from_contract_sync=True).write({'sale_order_id': rec.sale_order_ids[0].id})
        return records

    def write(self, vals):
        old_project_ids = {rec.id: set(rec.project_ids.ids) for rec in self} if 'project_ids' in vals else {}
        old_so_ids = {rec.id: set(rec.sale_order_ids.ids) for rec in self} if 'sale_order_ids' in vals else {}
        old_invoice_ids = {rec.id: set(rec.invoice_ids.ids) for rec in self} if 'invoice_ids' in vals else {}

        res = super().write(vals)
        self._update_client_customer_type()

        # Project synchronization
        if 'project_ids' in vals and not self.env.context.get('from_project_sync'):
            for rec in self:
                old_ids = old_project_ids.get(rec.id, set())
                new_ids = set(rec.project_ids.ids)
                removed_ids = old_ids - new_ids
                added_ids = new_ids - old_ids
                if removed_ids:
                    removed_projs = self.env['project.project'].browse(removed_ids)
                    for proj in removed_projs:
                        if proj.contract_id == rec:
                            proj.with_context(from_contract_sync=True).write({'contract_id': False})
                if added_ids:
                    added_projs = self.env['project.project'].browse(added_ids)
                    for proj in added_projs:
                        proj.with_context(from_contract_sync=True).write({'contract_id': rec.id})

        # Sale Orders synchronization (Requirement 1 & 3)
        if 'sale_order_ids' in vals and not self.env.context.get('from_so_sync'):
            for rec in self:
                old_sos = self.env['sale.order'].browse(old_so_ids.get(rec.id, set()))
                new_sos = rec.sale_order_ids
                added_sos = new_sos - old_sos
                removed_sos = old_sos - new_sos

                if added_sos:
                    added_so_invoices = added_sos.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
                    for inv in added_so_invoices:
                        if inv not in rec.invoice_ids:
                            rec.with_context(from_invoice_sync=True).write({'invoice_ids': [(4, inv.id)]})
                        if not inv.contract_id:
                            inv.with_context(from_contract_sync=True).write({'contract_id': rec.id})
                        if not inv.sale_order_id:
                            inv.with_context(from_contract_sync=True).write({'sale_order_id': added_sos[0].id})

                if removed_sos:
                    remaining_invoices = new_sos.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
                    removed_invoices = removed_sos.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice') - remaining_invoices
                    for inv in removed_invoices:
                        if inv in rec.invoice_ids:
                            rec.with_context(from_invoice_sync=True).write({'invoice_ids': [(3, inv.id)]})
                        if inv.contract_id == rec:
                            inv.with_context(from_contract_sync=True).write({'contract_id': False})

        # Invoices manual update in one2many (Requirement 2 & 3)
        if 'invoice_ids' in vals and not self.env.context.get('from_invoice_sync'):
            for rec in self:
                old_inv_ids = old_invoice_ids.get(rec.id, set())
                new_inv_ids = set(rec.invoice_ids.ids)
                added_inv_ids = new_inv_ids - old_inv_ids
                removed_inv_ids = old_inv_ids - new_inv_ids

                if added_inv_ids:
                    added_invoices = self.env['account.move'].browse(added_inv_ids)
                    for inv in added_invoices:
                        vals_to_update = {}
                        if not inv.contract_id:
                            vals_to_update['contract_id'] = rec.id
                        if rec.sale_order_ids:
                            if not inv.sale_order_id:
                                vals_to_update['sale_order_id'] = rec.sale_order_ids[0].id
                            if not inv.invoice_origin:
                                vals_to_update['invoice_origin'] = rec.sale_order_ids[0].name
                        if vals_to_update:
                            inv.with_context(from_contract_sync=True).write(vals_to_update)

                if removed_inv_ids:
                    removed_invoices = self.env['account.move'].browse(removed_inv_ids)
                    for inv in removed_invoices:
                        if inv.contract_id == rec:
                            inv.with_context(from_contract_sync=True).write({'contract_id': False})

        return res

    @api.depends('project_ids', 'client_ids')
    def _compute_counts(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)
            rec.client_count = len(rec.client_ids)

    def action_view_projects(self):
        self.ensure_one()
        context = {
            'default_contract_id': self.id,
            'default_contract_ids': [(4, self.id)],
            'default_partner_id': self.client_ids[0].id if self.client_ids else False,
            'default_name': self.name,
            'default_billing_amount': self.contract_amount,
            'default_currency_id': self.currency_id.id if self.currency_id else False,
            'default_date_start': self.contract_start_date,
            'default_date': self.contract_end_date,
            'default_company_id': self.company_id.id if self.company_id else False,
        }
        if 'sale_order_ids' in self._fields and self.sale_order_ids:
            context['default_sale_order_id'] = self.sale_order_ids[0].id

        if len(self.project_ids) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': self.project_ids[0].display_name or 'Project',
                'res_model': 'project.project',
                'view_mode': 'form',
                'res_id': self.project_ids[0].id,
                'context': context,
            }
        elif len(self.project_ids) == 0:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Create Project',
                'res_model': 'project.project',
                'view_mode': 'form',
                'target': 'current',
                'context': context,
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Projects',
                'res_model': 'project.project',
                'view_mode': 'list,form',
                'domain': [('id', 'in', self.project_ids.ids)],
                'context': context,
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
                'default_contract_id': self.id,
                'default_contract_ids': [(4, self.id)],
                'default_billing_amount': self.contract_amount,
                'default_currency_id': self.currency_id.id if self.currency_id else False,
                'default_date_start': self.contract_start_date,
                'default_date': self.contract_end_date,
                'default_company_id': self.company_id.id if self.company_id else False,
            }
        }

    # =========================================================================
    # AUTO-CONVERT PROSPECT TO CUSTOMER ON CREATE / UPDATE
    # =========================================================================


    def _update_client_customer_type(self):
        for rec in self:
            for partner in rec.client_ids:
                partners = partner | partner.commercial_partner_id
                for p in partners:
                    if 'customer_type' in p._fields and p.customer_type == 'prospect':
                        p.sudo().write({'customer_type': 'customer'})


class ProjectProject(models.Model):
    _inherit = 'project.project'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract_id = self.env.context.get('default_contract_id')
        if not contract_id and self.env.context.get('default_contract_ids'):
            cids = self.env.context.get('default_contract_ids')
            if isinstance(cids, list) and cids:
                if isinstance(cids[0], (list, tuple)) and len(cids[0]) > 1:
                    contract_id = cids[0][1]
                elif isinstance(cids[0], int):
                    contract_id = cids[0]
        if not contract_id and self.env.context.get('active_model') == 'project.contract.management':
            contract_id = self.env.context.get('active_id')

        if contract_id:
            contract = self.env['project.contract.management'].browse(contract_id)
            if contract.exists():
                res['contract_id'] = contract.id
                res['contract_ids'] = [(6, 0, [contract.id])]
                if not res.get('name'):
                    res['name'] = contract.name
                if not res.get('partner_id') and contract.client_ids:
                    res['partner_id'] = contract.client_ids[0].id
                if not res.get('billing_amount'):
                    res['billing_amount'] = contract.contract_amount
                if not res.get('currency_id') and contract.currency_id:
                    res['currency_id'] = contract.currency_id.id
                if not res.get('date_start') and contract.contract_start_date:
                    res['date_start'] = contract.contract_start_date
                if not res.get('date') and contract.contract_end_date:
                    res['date'] = contract.contract_end_date
                if not res.get('company_id') and contract.company_id:
                    res['company_id'] = contract.company_id.id
                if 'sale_order_ids' in contract._fields and contract.sale_order_ids:
                    res['sale_order_id'] = contract.sale_order_ids[0].id
        return res

    contract_id = fields.Many2one(
        'project.contract.management',
        string="Contract",
        tracking=True,
    )
    project_code = fields.Char(
        string="Project Code",
        tracking=True,
        copy=False,
    )
    billing_amount = fields.Monetary(
        string="Billing Amount",
        currency_field='currency_id',
        tracking=True,
    )
    contract_ids = fields.Many2many(
        'project.contract.management',
        'contract_project_rel',
        'project_id',
        'contract_id',
        string="Contracts"
    )
    account_lead_id = fields.Many2one(
        'hr.employee',
        string="Account Head",
        tracking=True,
    )
    delivery_lead_id = fields.Many2one(
        'hr.employee',
        string="Delivery Head",
        tracking=True,
    )
    practice_lead_id = fields.Many2one(
        'hr.employee',
        string="Practice Head",
        tracking=True,
    )
    allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="Allocated Resources",
    )
    employee_allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="Employee Allocations",
        domain=[('resource_type', '=', 'employee')],
    )
    hardware_allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="Hardware Allocations",
        domain=[('resource_type', '=', 'hardwares')],
    )
    license_allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="License Allocations",
        domain=[('resource_type', '=', 'licenses')],
    )
    ssd_allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="SSD Allocations",
        domain=[('resource_type', '=', 'ssd')],
    )
    other_allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="Other Allocations",
        domain=[('resource_type', '=', 'others')],
    )
    total_allocation_amount = fields.Monetary(
        string="Total Allocated Amount",
        compute='_compute_total_allocation_amount',
        store=True,
        currency_field='currency_id',
    )
    total_margin = fields.Monetary(
        string="Total Margin",
        compute='_compute_total_margin',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('allocation_ids.amount',
                 'employee_allocation_ids.amount',
                 'hardware_allocation_ids.amount',
                 'license_allocation_ids.amount',
                 'ssd_allocation_ids.amount',
                 'other_allocation_ids.amount')
    def _compute_total_allocation_amount(self):
        for rec in self:
            all_allocs = (
                rec.employee_allocation_ids |
                rec.hardware_allocation_ids |
                rec.license_allocation_ids |
                rec.ssd_allocation_ids |
                rec.other_allocation_ids |
                rec.allocation_ids
            )
            rec.total_allocation_amount = sum(all_allocs.mapped('amount'))

    @api.depends('billing_amount', 'total_allocation_amount',
                 'allocation_ids.amount',
                 'employee_allocation_ids.amount',
                 'hardware_allocation_ids.amount',
                 'license_allocation_ids.amount',
                 'ssd_allocation_ids.amount',
                 'other_allocation_ids.amount')
    def _compute_total_margin(self):
        for rec in self:
            rec.total_margin = (rec.billing_amount or 0.0) - (rec.total_allocation_amount or 0.0)

    @api.onchange('employee_allocation_ids', 'hardware_allocation_ids',
                  'license_allocation_ids', 'ssd_allocation_ids',
                  'other_allocation_ids', 'billing_amount', 'currency_id')
    def _onchange_resequence_allocations_and_margins(self):
        all_allocs = (
            self.employee_allocation_ids |
            self.hardware_allocation_ids |
            self.license_allocation_ids |
            self.ssd_allocation_ids |
            self.other_allocation_ids
        )
        if not all_allocs:
            self.total_allocation_amount = 0.0
            self.total_margin = self.billing_amount or 0.0
            return

        # Assign sequence to unsequenced lines
        existing_seqs = [a.sequence for a in all_allocs if a.sequence]
        max_seq = max(existing_seqs) if existing_seqs else 0
        for alloc in all_allocs:
            if not alloc.sequence:
                max_seq += 1
                alloc.sequence = max_seq

        # Sort allocations by sequence, then id
        sorted_allocs = all_allocs.sorted(
            key=lambda r: (r.sequence or 0, r.id if isinstance(r.id, int) else 9999999)
        )

        running_margin = self.billing_amount or 0.0
        total_alloc = 0.0
        target_curr = self.currency_id or self.company_id.currency_id or self.env.company.currency_id
        for alloc in sorted_allocs:
            if alloc.resource_type in ('hardwares', 'licenses'):
                alloc.amount = (alloc.vendor_price or 0.0) * (alloc.qty or 0.0)
            elif alloc.resource_type == 'ssd':
                target_date = alloc.start_date or self.date_start
                ssd_amt = self.env['project.resource.allocation']._convert_inr_to_target_currency(
                    2500.0, target_curr, target_date, self.company_id
                )
                alloc.amount = ssd_amt
                alloc.vendor_price = ssd_amt
                alloc.allocation_percentage = 0.0
            else:
                billing = self.billing_amount or 0.0
                alloc.amount = billing * ((alloc.allocation_percentage or 0.0) / 100.0)

            total_alloc += (alloc.amount or 0.0)
            running_margin -= (alloc.amount or 0.0)
            alloc.margin = running_margin

        self.total_allocation_amount = total_alloc
        self.total_margin = (self.billing_amount or 0.0) - total_alloc

    @api.constrains('contract_ids')
    def _check_contract_ids_single(self):
        for rec in self:
            if len(rec.contract_ids) > 1:
                contracts = ", ".join(rec.contract_ids.mapped('display_name'))
                raise ValidationError(_(
                    "The project '%(project)s' cannot be attached to multiple contracts (%(contracts)s). "
                    "One project can only be attached to one contract.",
                    project=rec.display_name,
                    contracts=contracts
                ))

    @api.constrains('contract_id', 'billing_amount', 'company_id', 'partner_id')
    def _check_contract_consistency(self):
        for rec in self:
            if not rec.contract_id:
                continue
            contract = rec.contract_id
            messages = []
            # 1. Billing amount check
            if rec.billing_amount and contract.contract_amount:
                contract_amt = contract.contract_amount
                if rec.currency_id and contract.currency_id and rec.currency_id != contract.currency_id:
                    contract_amt = contract.currency_id._convert(
                        contract_amt, rec.currency_id, rec.company_id or self.env.company, fields.Date.today()
                    )
                if float_compare(rec.billing_amount, contract_amt, precision_digits=2) > 0:
                    messages.append(
                        _("Billing amount of project (%(billing)s) cannot be more than the contract amount (%(contract_amt)s).",
                          billing=f"{rec.billing_amount:,.2f}", contract_amt=f"{contract_amt:,.2f}")
                    )

            # 2. Company check
            if rec.company_id and contract.company_id and rec.company_id != contract.company_id:
                messages.append(
                    _("Company of project ('%(p_comp)s') and contract ('%(c_comp)s') must be the same.",
                      p_comp=rec.company_id.name, c_comp=contract.company_id.name)
                )

            # 3. Customer check
            if rec.partner_id and contract.client_ids:
                contract_partners = contract.client_ids | contract.client_ids.commercial_partner_id
                project_partners = rec.partner_id | rec.partner_id.commercial_partner_id
                if not (project_partners & contract_partners):
                    client_names = ", ".join(contract.client_ids.mapped('name'))
                    messages.append(
                        _("Customer of project ('%(partner)s') and contract ('%(clients)s') must be the same.",
                          partner=rec.partner_id.name, clients=client_names)
                    )

            if messages:
                raise ValidationError("\n".join(messages))

    @api.onchange('billing_amount', 'company_id', 'partner_id')
    def _onchange_check_contract_consistency(self):
        if not self.contract_id:
            return
        contract = self.contract_id
        messages = []
        # 1. Billing amount check
        if self.billing_amount and contract.contract_amount:
            contract_amt = contract.contract_amount
            if self.currency_id and contract.currency_id and self.currency_id != contract.currency_id:
                contract_amt = contract.currency_id._convert(
                    contract_amt, self.currency_id, self.company_id or self.env.company, fields.Date.today()
                )
            if float_compare(self.billing_amount, contract_amt, precision_digits=2) > 0:
                messages.append(
                    _("Billing amount of project (%(billing)s) cannot be more than the contract amount (%(contract_amt)s).",
                      billing=f"{self.billing_amount:,.2f}", contract_amt=f"{contract_amt:,.2f}")
                )

        # 2. Company check
        if self.company_id and contract.company_id and self.company_id != contract.company_id:
            messages.append(
                _("Company of project ('%(p_comp)s') and contract ('%(c_comp)s') must be the same.",
                  p_comp=self.company_id.name, c_comp=contract.company_id.name)
            )

        # 3. Customer check
        if self.partner_id and contract.client_ids:
            contract_partners = contract.client_ids | contract.client_ids.commercial_partner_id
            project_partners = self.partner_id | self.partner_id.commercial_partner_id
            if not (project_partners & contract_partners):
                client_names = ", ".join(contract.client_ids.mapped('name'))
                messages.append(
                    _("Customer of project ('%(partner)s') and contract ('%(clients)s') must be the same.",
                      partner=self.partner_id.name, clients=client_names)
                )

        if messages:
            return {
                'warning': {
                    'title': _("Contract Validation Warning"),
                    'message': "\n".join(f"• {m}" for m in messages)
                }
            }

    @api.model
    def _generate_project_code(self, project_name, partner=None, date_ref=None):
        def _get_initials(text, fallback='PRJ'):
            if not text:
                return fallback
            words = re.findall(r'[a-zA-Z0-9]+', text)
            initials = ''.join(w[0].upper() for w in words if w)
            return initials if initials else fallback

        proj_initials = _get_initials(project_name, fallback='PRJ')
        cust_name = partner.name if partner else ''
        cust_initials = _get_initials(cust_name, fallback='CUST')

        d = fields.Date.to_date(date_ref) if date_ref else fields.Date.today()
        year = str(d.year)

        seq_num = self.env['ir.sequence'].next_by_code('project.project.code') or '0000001'
        return f"{proj_initials}/{cust_initials}/{year}/{seq_num}"

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        if self.contract_id:
            if not self.name:
                self.name = self.contract_id.name
            if self.contract_id.client_ids:
                self.partner_id = self.contract_id.client_ids[0]
            if self.contract_id.contract_amount:
                self.billing_amount = self.contract_id.contract_amount
            if self.contract_id.currency_id:
                self.currency_id = self.contract_id.currency_id
            if self.contract_id.contract_start_date:
                self.date_start = self.contract_id.contract_start_date
            if self.contract_id.contract_end_date:
                self.date = self.contract_id.contract_end_date
            if self.contract_id.company_id:
                self.company_id = self.contract_id.company_id
            if 'sale_order_id' in self._fields and self.contract_id.sale_order_ids:
                self.sale_order_id = self.contract_id.sale_order_ids[0]
            if self.contract_id:
                self.contract_ids = [(6, 0, [self.contract_id.id])]
            res = self._onchange_check_contract_consistency()
            if res:
                return res
        else:
            self.contract_ids = [(5, 0, 0)]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('contract_id'):
                contract_ids = vals.get('contract_ids', [])
                if not any(isinstance(cmd, (list, tuple)) and cmd[0] == 4 and cmd[1] == vals['contract_id'] for cmd in contract_ids):
                    contract_ids.append((4, vals['contract_id']))
                    vals['contract_ids'] = contract_ids

            if not vals.get('project_code'):
                project_name = vals.get('name') or ''
                partner = False
                if vals.get('partner_id'):
                    partner = self.env['res.partner'].browse(vals['partner_id'])
                elif vals.get('contract_id'):
                    contract = self.env['project.contract.management'].browse(vals['contract_id'])
                    if contract.client_ids:
                        partner = contract.client_ids[0]
                date_ref = vals.get('date_start') or vals.get('date')
                vals['project_code'] = self._generate_project_code(project_name, partner, date_ref)

        records = super().create(vals_list)
        for rec in records:
            if rec.contract_id:
                if rec not in rec.contract_id.project_ids:
                    rec.contract_id.with_context(from_project_sync=True).write({'project_ids': [(4, rec.id)]})
                if rec.contract_id not in rec.contract_ids:
                    rec.contract_ids = [(4, rec.contract_id.id)]
        return records

    def write(self, vals):
        old_contract_ids = {rec.id: rec.contract_id.id for rec in self} if 'contract_id' in vals else {}
        res = super().write(vals)
        if 'contract_id' in vals and not self.env.context.get('from_contract_sync'):
            for rec in self:
                old_cid = old_contract_ids.get(rec.id)
                new_cid = rec.contract_id.id
                if old_cid and old_cid != new_cid:
                    old_contract = self.env['project.contract.management'].browse(old_cid)
                    if rec in old_contract.project_ids:
                        old_contract.with_context(from_project_sync=True).write({'project_ids': [(3, rec.id)]})
                    if old_contract in rec.contract_ids:
                        rec.contract_ids = [(3, old_contract.id)]
                if new_cid:
                    new_contract = rec.contract_id
                    if rec not in new_contract.project_ids:
                        new_contract.with_context(from_project_sync=True).write({'project_ids': [(4, rec.id)]})
                    if new_contract not in rec.contract_ids:
                        rec.contract_ids = [(4, new_contract.id)]
        return res


class AccountMove(models.Model):
    _inherit = 'account.move'

    contract_id = fields.Many2one(
        'project.contract.management',
        string="Contract",
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string="Sales Order",
        copy=False,
        tracking=True,
    )

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        if self.contract_id:
            if self.contract_id.client_ids:
                self.partner_id = self.contract_id.client_ids[0]
            if self.contract_id.currency_id:
                self.currency_id = self.contract_id.currency_id
            if self.contract_id.sale_order_ids and not self.sale_order_id:
                self.sale_order_id = self.contract_id.sale_order_ids[0]
                if not self.invoice_origin:
                    self.invoice_origin = self.contract_id.sale_order_ids[0].name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            contract_id = vals.get('contract_id')
            if contract_id and not vals.get('sale_order_id'):
                contract = self.env['project.contract.management'].browse(contract_id)
                if contract.sale_order_ids:
                    vals['sale_order_id'] = contract.sale_order_ids[0].id
                    if not vals.get('invoice_origin'):
                        vals['invoice_origin'] = contract.sale_order_ids[0].name

        records = super().create(vals_list)
        for rec in records:
            if rec.contract_id and rec.move_type == 'out_invoice':
                if rec not in rec.contract_id.invoice_ids:
                    rec.contract_id.with_context(from_invoice_sync=True).write({'invoice_ids': [(4, rec.id)]})
        return records

    def write(self, vals):
        old_contract_ids = {rec.id: rec.contract_id.id for rec in self} if 'contract_id' in vals else {}
        if 'contract_id' in vals and vals.get('contract_id') and not vals.get('sale_order_id'):
            contract = self.env['project.contract.management'].browse(vals['contract_id'])
            if contract.sale_order_ids:
                vals['sale_order_id'] = contract.sale_order_ids[0].id
                if not vals.get('invoice_origin'):
                    vals['invoice_origin'] = contract.sale_order_ids[0].name

        res = super().write(vals)
        if 'contract_id' in vals and not self.env.context.get('from_contract_sync'):
            for rec in self:
                old_cid = old_contract_ids.get(rec.id)
                new_cid = rec.contract_id.id
                if old_cid and old_cid != new_cid:
                    old_c = self.env['project.contract.management'].browse(old_cid)
                    if rec in old_c.invoice_ids:
                        old_c.with_context(from_invoice_sync=True).write({'invoice_ids': [(3, rec.id)]})
                if new_cid and rec.move_type == 'out_invoice':
                    if rec not in rec.contract_id.invoice_ids:
                        rec.contract_id.with_context(from_invoice_sync=True).write({'invoice_ids': [(4, rec.id)]})
        return res


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    contract_ids = fields.Many2many(
        'project.contract.management',
        'contract_sale_order_rel',
        'sale_order_id',
        'contract_id',
        string="Contracts",
    )

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for order in self:
            if order.contract_ids:
                contract = order.contract_ids[0]
                for move in moves:
                    vals_to_write = {}
                    if not move.contract_id:
                        vals_to_write['contract_id'] = contract.id
                    if not move.sale_order_id:
                        vals_to_write['sale_order_id'] = order.id
                    if vals_to_write:
                        move.with_context(from_contract_sync=True).write(vals_to_write)
                    if move not in contract.invoice_ids:
                        contract.with_context(from_invoice_sync=True).write({'invoice_ids': [(4, move.id)]})
        return moves

    @api.depends('order_line.invoice_lines', 'order_line.invoice_lines.move_id')
    def _get_invoiced(self):
        super()._get_invoiced()
        for order in self:
            extra_invoices = self.env['account.move'].search([
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                '|',
                ('sale_order_id', '=', order.id),
                ('id', 'in', order.contract_ids.invoice_ids.ids),
            ])
            if extra_invoices:
                all_invoices = order.invoice_ids | extra_invoices
                order.invoice_ids = all_invoices
                order.invoice_count = len(all_invoices)


class ProjectContractServiceLine(models.Model):
    _name = 'project.contract.service.line'
    _description = 'Contract Service Line'
    _order = 'sequence, id'

    name = fields.Char("Service Line", required=True)
    active = fields.Boolean("Active", default=True)
    sequence = fields.Integer("Sequence", default=10)


class ProjectResourceAllocation(models.Model):
    _name = 'project.resource.allocation'
    _description = 'Project Resource Allocation'
    _order = 'sequence asc, id asc'

    sequence = fields.Integer(
        string="Sequence",
        default=0,
    )
    project_id = fields.Many2one(
        'project.project',
        string="Project",
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string="Currency",
        store=True,
        readonly=False,
    )

    @api.depends('project_id.currency_id')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.project_id.currency_id or self.env.company.currency_id

    resource_type = fields.Selection([
        ('employee', 'Employee'),
        ('hardwares', 'Hardwares'),
        ('licenses', 'Licenses'),
        ('ssd', 'SSD'),
        ('others', 'Others'),
    ], string="Type", required=True, default='employee')

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
    )
    ssd_id = fields.Many2one(
        'hr.employee',
        string="SSD",
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
    )
    name = fields.Char(
        string="Based On Type",
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string="Vendor",
    )
    service_line_id = fields.Many2one(
        'project.contract.service.line',
        string="Service Line",
    )
    start_date = fields.Date(
        string="Start Date",
        required=True,
    )
    end_date = fields.Date(
        string="End Date",
        required=True,
    )
    qty = fields.Float(
        string="QTY",
        default=1.0,
    )
    allocation_percentage = fields.Float(
        string="Allocation %",
        default=100.0,
    )
    vendor_price = fields.Monetary(
        string="Vendor Price",
        currency_field='currency_id',
    )
    customer_price = fields.Monetary(
        string="Customer Price",
        currency_field='currency_id',
    )
    amount = fields.Monetary(
        string="Amount",
        currency_field='currency_id',
        compute='_compute_amount',
        store=True,
        readonly=True,
    )
    margin = fields.Monetary(
        string="Margin",
        currency_field='currency_id',
        compute='_compute_margin',
        store=True,
        readonly=True,
    )
    allocation_days = fields.Integer(
        string="Allocation Days",
        compute='_compute_allocation_days_and_hours',
        store=True,
    )
    allocated_hours = fields.Float(
        string="Allocated Hours",
        compute='_compute_allocation_days_and_hours',
        store=True,
    )

    @api.model
    def _convert_inr_to_target_currency(self, inr_amount, target_currency, target_date=None, company=None):
        """Convert INR amount to target currency according to the rates defined in Financial Books:
           AED - INR: FY (<2027): 24.5, CY (>=2027): 25.6
           USD - INR: FY (<2027): 90.0, CY (>=2027): 93.0
        """
        if not inr_amount or not target_currency:
            return inr_amount or 0.0

        currency_code = (target_currency.name or "").upper().strip()
        if currency_code == "INR":
            return inr_amount

        d = target_date or fields.Date.context_today(self)
        if isinstance(d, str):
            d = fields.Date.from_string(d)
        year = d.year if hasattr(d, "year") else fields.Date.today().year

        if year >= 2027:
            rate_usd_inr = 93.0
            rate_aed_inr = 25.6
        else:
            rate_usd_inr = 90.0
            rate_aed_inr = 24.5

        if currency_code == "USD":
            converted = inr_amount / rate_usd_inr
        elif currency_code == "AED":
            converted = inr_amount / rate_aed_inr
        else:
            inr_curr = (
                self.env.ref("base.INR", raise_if_not_found=False)
                or self.env["res.currency"].search([("name", "=", "INR")], limit=1)
            )
            if inr_curr and inr_curr != target_currency:
                converted = inr_curr._convert(
                    inr_amount,
                    target_currency,
                    company or self.env.company,
                    d or fields.Date.today(),
                )
            else:
                converted = inr_amount

        return target_currency.round(converted) if hasattr(target_currency, "round") else round(converted, 2)

    @api.depends('resource_type', 'qty', 'vendor_price', 'allocation_percentage',
                 'project_id.billing_amount', 'currency_id', 'start_date', 'end_date',
                 'employee_id', 'employee_id.l10n_in_basic_salary_amount', 'employee_id.l10n_in_fixed_allowance')
    def _compute_amount(self):
        for rec in self:
            if rec.resource_type == 'employee':
                rec.amount = rec._get_employee_allocated_cost()
            elif rec.resource_type in ('hardwares', 'licenses'):
                rec.amount = (rec.vendor_price or 0.0) * (rec.qty or 0.0)
            elif rec.resource_type == 'ssd':
                target_curr = rec.currency_id or (rec.project_id.currency_id if rec.project_id else False) or self.env.company.currency_id
                target_date = rec.start_date or (rec.project_id.date_start if rec.project_id else False)
                comp = rec.project_id.company_id if rec.project_id else self.env.company
                ssd_amt = self._convert_inr_to_target_currency(2500.0, target_curr, target_date, comp)
                rec.amount = ssd_amt
                if not rec.vendor_price:
                    rec.vendor_price = ssd_amt
            else:
                billing = rec.project_id.billing_amount or 0.0 if rec.project_id else 0.0
                rec.amount = rec.vendor_price if rec.vendor_price else billing * ((rec.allocation_percentage or 0.0) / 100.0)

    @api.depends(
        'sequence', 'amount', 'project_id.billing_amount',
        'project_id.allocation_ids.amount', 'project_id.allocation_ids.sequence'
    )
    def _compute_margin(self):
        for project in self.mapped('project_id'):
            all_allocs = project.allocation_ids.sorted(
                key=lambda r: (r.sequence or 0, r.id if isinstance(r.id, int) else 9999999)
            )
            running_margin = project.billing_amount or 0.0
            for alloc in all_allocs:
                running_margin -= (alloc.amount or 0.0)
                if alloc in self:
                    alloc.margin = running_margin
        for rec in self.filtered(lambda r: not r.project_id):
            rec.margin = 0.0

    def _get_working_days(self):
        """Calculate working days between start_date and end_date (inclusive) based on employee shift calendar."""
        self.ensure_one()
        if not (self.start_date and self.end_date and self.start_date <= self.end_date):
            return 0
        emp = (self.employee_id or self.ssd_id).sudo()
        cal = (emp.resource_calendar_id if emp else False) or (self.project_id.company_id.resource_calendar_id if self.project_id else False) or self.env.company.resource_calendar_id
        work_days = {0, 1, 2, 3, 4}  # Monday to Friday default
        if cal and cal.attendance_ids:
            cal_days = {int(att.dayofweek) for att in cal.attendance_ids if str(att.dayofweek).isdigit()}
            if cal_days:
                work_days = cal_days

        cur_date = self.start_date
        working_days = 0
        while cur_date <= self.end_date:
            if cur_date.weekday() in work_days:
                working_days += 1
            cur_date += timedelta(days=1)
        return working_days

    @api.depends('start_date', 'end_date', 'employee_id.resource_calendar_id', 'ssd_id.resource_calendar_id')
    def _compute_allocation_days_and_hours(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.start_date <= rec.end_date:
                rec.allocation_days = (rec.end_date - rec.start_date).days + 1
                working_days = rec._get_working_days()
                rec.allocated_hours = working_days * 9.0
            else:
                rec.allocation_days = 0
                rec.allocated_hours = 0.0

    def _get_employee_allocated_cost(self):
        """Salary cost of the employee for the allocation period based on working days."""
        self.ensure_one()
        emp = self.employee_id
        if not (emp and self.start_date and self.end_date):
            return 0.0
        if self.start_date > self.end_date:
            return 0.0

        emp_sudo = emp.sudo()
        basic = getattr(emp_sudo, 'l10n_in_basic_salary_amount', 0.0) or 0.0
        fixed_allowance = getattr(emp_sudo, 'l10n_in_fixed_allowance', 0.0) or 0.0
        if not basic and getattr(emp_sudo, 'contract_id', False):
            basic = emp_sudo.contract_id.wage or 0.0
        if not basic and getattr(emp_sudo, 'version_id', False):
            basic = emp_sudo.version_id.wage or 0.0

        monthly_pay = basic + fixed_allowance
        if not monthly_pay:
            return 0.0

        # Per day cost based on 22 working days in a month
        per_day_cost = monthly_pay / 22.0

        # Number of working days between start_date and end_date (inclusive)
        working_days = self._get_working_days()

        amount_inr = per_day_cost * working_days * ((self.allocation_percentage or 0.0) / 100.0)

        # Convert to project currency if different from INR
        target_curr = self.currency_id or (self.project_id.currency_id if self.project_id else False) or self.env.company.currency_id
        target_date = self.start_date or (self.project_id.date_start if self.project_id else False)
        comp = self.project_id.company_id if self.project_id else self.env.company
        return self._convert_inr_to_target_currency(amount_inr, target_curr, target_date, comp)

    def _update_in_memory_margins(self):
        if not self.project_id:
            return
        all_allocs = (
            self.project_id.employee_allocation_ids |
            self.project_id.hardware_allocation_ids |
            self.project_id.license_allocation_ids |
            self.project_id.ssd_allocation_ids |
            self.project_id.other_allocation_ids
        )
        if not self.sequence:
            existing_seqs = [a.sequence for a in all_allocs if a != self and a.sequence]
            self.sequence = (max(existing_seqs) + 1) if existing_seqs else 1

        sorted_allocs = all_allocs.sorted(
            key=lambda r: (r.sequence or 0, r.id if isinstance(r.id, int) else 9999999)
        )
        running = self.project_id.billing_amount or 0.0
        for alloc in sorted_allocs:
            running -= (alloc.amount or 0.0)
            alloc.margin = running

    @api.onchange('qty', 'vendor_price')
    def _onchange_qty_vendor_price(self):
        if self.resource_type in ('hardwares', 'licenses'):
            self.amount = (self.vendor_price or 0.0) * (self.qty or 0.0)
            self._update_in_memory_margins()

    @api.onchange('allocation_percentage', 'start_date', 'end_date', 'employee_id', 'ssd_id')
    def _onchange_allocation_dates_percentage(self):
        if self.start_date and self.end_date and self.start_date <= self.end_date:
            self.allocation_days = (self.end_date - self.start_date).days + 1
            self.allocated_hours = self._get_working_days() * 9.0
        else:
            self.allocation_days = 0
            self.allocated_hours = 0.0

        if self.allocation_percentage > 100:
            warning = {
                'title': _("Invalid Allocation %"),
                'message': _("Allocation % cannot be more than 100%.")
            }
            self.allocation_percentage = 100.0
            if self.resource_type == 'employee':
                self.amount = self._get_employee_allocated_cost()
            else:
                billing = self.project_id.billing_amount or 0.0 if self.project_id else 0.0
                self.amount = billing * (self.allocation_percentage / 100.0)
            self._update_in_memory_margins()
            return {'warning': warning}
        if self.allocation_percentage < 0:
            self.allocation_percentage = 0.0

        if self.resource_type == 'employee':
            self.amount = self._get_employee_allocated_cost()
        elif self.resource_type == 'others':
            billing = self.project_id.billing_amount or 0.0 if self.project_id else 0.0
            self.amount = self.vendor_price if self.vendor_price else billing * (self.allocation_percentage / 100.0)
        self._update_in_memory_margins()

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("The End Date cannot be earlier than the Start Date."))

    @api.constrains('allocation_percentage', 'resource_type')
    def _check_allocation_percentage(self):
        for rec in self:
            if rec.resource_type in ('employee', 'others'):
                if rec.allocation_percentage < 0 or rec.allocation_percentage > 100:
                    raise ValidationError(_("Allocation % cannot be more than 100%."))

    @api.constrains('project_id')
    def _check_parent(self):
        for rec in self:
            if not rec.project_id:
                raise ValidationError(_("Resource allocation must be linked to a Project."))

    @api.onchange('resource_type')
    def _onchange_resource_type(self):
        if self.resource_type == 'employee':
            self.vendor_id = False
            self.product_id = False
            self.ssd_id = False
            if self.employee_id:
                self.name = self.employee_id.name
            self.amount = self._get_employee_allocated_cost()
        elif self.resource_type == 'ssd':
            self.vendor_id = False
            self.product_id = False
            self.customer_price = 0.0
            target_curr = self.currency_id or (self.project_id.currency_id if self.project_id else False) or self.env.company.currency_id
            target_date = self.start_date or (self.project_id.date_start if self.project_id else False)
            comp = self.project_id.company_id if self.project_id else self.env.company
            ssd_amt = self._convert_inr_to_target_currency(2500.0, target_curr, target_date, comp)
            self.amount = ssd_amt
            self.vendor_price = ssd_amt
            if self.ssd_id:
                self.name = self.ssd_id.name
                self.employee_id = self.ssd_id
        elif self.resource_type in ('hardwares', 'licenses'):
            self.employee_id = False
            self.ssd_id = False
            if not self.qty:
                self.qty = 1.0
            self.amount = (self.vendor_price or 0.0) * (self.qty or 0.0)
            if self.product_id:
                self.name = self.product_id.display_name
        else:
            self.employee_id = False
            self.ssd_id = False
        self._update_in_memory_margins()

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.name = self.employee_id.name
            if self.resource_type == 'employee':
                self.amount = self._get_employee_allocated_cost()
        self._update_in_memory_margins()

    @api.onchange('ssd_id')
    def _onchange_ssd_id(self):
        if self.ssd_id:
            self.name = self.ssd_id.name
            self.employee_id = self.ssd_id
            self.vendor_id = False
            self.customer_price = 0.0
            target_curr = self.currency_id or (self.project_id.currency_id if self.project_id else False) or self.env.company.currency_id
            target_date = self.start_date or (self.project_id.date_start if self.project_id else False)
            comp = self.project_id.company_id if self.project_id else self.env.company
            ssd_amt = self._convert_inr_to_target_currency(2500.0, target_curr, target_date, comp)
            self.amount = ssd_amt
            self.vendor_price = ssd_amt
        self._update_in_memory_margins()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            if not self.vendor_price and self.product_id.standard_price:
                self.vendor_price = self.product_id.standard_price
            if not self.customer_price and self.product_id.lst_price:
                self.customer_price = self.product_id.lst_price
            if self.resource_type in ('hardwares', 'licenses'):
                if not self.qty:
                    self.qty = 1.0
                self.amount = (self.vendor_price or 0.0) * (self.qty or 0.0)
        self._update_in_memory_margins()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get('resource_type') == 'ssd':
            target_curr = False
            if 'currency_id' in res and res['currency_id']:
                target_curr = self.env['res.currency'].browse(res['currency_id'])
            elif self._context.get('default_project_id'):
                proj = self.env['project.project'].browse(self._context['default_project_id'])
                target_curr = proj.currency_id
            if not target_curr:
                target_curr = self.env.company.currency_id
            ssd_amt = self._convert_inr_to_target_currency(2500.0, target_curr)
            res['amount'] = ssd_amt
            res['vendor_price'] = ssd_amt
        elif res.get('resource_type') in ('hardwares', 'licenses'):
            if 'qty' in fields_list:
                res['qty'] = 1.0
        return res

    @api.model_create_multi
    def create(self, vals_list):
        max_seq_cache = {}
        for vals in vals_list:
            if vals.get('resource_type') == 'employee' and vals.get('employee_id') and not vals.get('name'):
                employee = self.env['hr.employee'].browse(vals['employee_id'])
                vals['name'] = employee.name
            elif vals.get('resource_type') == 'ssd':
                if vals.get('ssd_id'):
                    if not vals.get('employee_id'):
                        vals['employee_id'] = vals['ssd_id']
                    if not vals.get('name'):
                        employee = self.env['hr.employee'].browse(vals['ssd_id'])
                        vals['name'] = employee.name
                proj = self.env['project.project'].browse(vals['project_id']) if vals.get('project_id') else False
                target_curr = (
                    self.env['res.currency'].browse(vals['currency_id']) if vals.get('currency_id')
                    else (proj.currency_id if proj else self.env.company.currency_id)
                )
                target_date = vals.get('start_date') or (proj.date_start if proj else False)
                comp = proj.company_id if proj else self.env.company
                ssd_amt = self._convert_inr_to_target_currency(2500.0, target_curr, target_date, comp)
                vals['amount'] = ssd_amt
                vals['vendor_price'] = ssd_amt
                vals['customer_price'] = 0.0
                vals['vendor_id'] = False
                vals['allocation_percentage'] = 0.0
            elif vals.get('resource_type') in ('hardwares', 'licenses'):
                qty = vals.get('qty', 1.0)
                vprice = vals.get('vendor_price', 0.0)
                vals['amount'] = qty * vprice
                if vals.get('product_id') and not vals.get('name'):
                    product = self.env['product.product'].browse(vals['product_id'])
                    vals['name'] = product.display_name
            elif vals.get('product_id') and not vals.get('name'):
                product = self.env['product.product'].browse(vals['product_id'])
                vals['name'] = product.display_name

            # Sequence assignment
            proj_id = vals.get('project_id')
            if not vals.get('sequence') and proj_id:
                if proj_id not in max_seq_cache:
                    existing = self.search([('project_id', '=', proj_id)])
                    max_seq_cache[proj_id] = max(existing.mapped('sequence') or [0])
                max_seq_cache[proj_id] += 1
                vals['sequence'] = max_seq_cache[proj_id]

        return super().create(vals_list)

    def write(self, vals):
        if vals.get('resource_type') == 'employee' and vals.get('employee_id') and not vals.get('name'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['name'] = employee.name
        elif vals.get('resource_type') == 'ssd' or (len(self) == 1 and self.resource_type == 'ssd'):
            if vals.get('ssd_id'):
                if not vals.get('employee_id'):
                    vals['employee_id'] = vals['ssd_id']
                if not vals.get('name'):
                    employee = self.env['hr.employee'].browse(vals['ssd_id'])
                    vals['name'] = employee.name
            if vals.get('resource_type') == 'ssd' or 'currency_id' in vals:
                for rec in self:
                    target_curr = (
                        self.env['res.currency'].browse(vals['currency_id']) if vals.get('currency_id')
                        else (rec.currency_id or (rec.project_id.currency_id if rec.project_id else self.env.company.currency_id))
                    )
                    target_date = vals.get('start_date') or rec.start_date or (rec.project_id.date_start if rec.project_id else False)
                    comp = rec.project_id.company_id if rec.project_id else self.env.company
                    ssd_amt = self._convert_inr_to_target_currency(2500.0, target_curr, target_date, comp)
                    vals['amount'] = ssd_amt
                    if 'vendor_price' not in vals:
                        vals['vendor_price'] = ssd_amt
        elif vals.get('product_id') and not vals.get('name'):
            product = self.env['product.product'].browse(vals['product_id'])
            vals['name'] = product.display_name
        return super().write(vals)



