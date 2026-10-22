from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare
from datetime import date
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
    project_allocation_ids = fields.One2many(
        'project.allocation',
        'contract_id',
        string="Project Allocations",
    )
    project_allocation_count = fields.Integer(compute="_compute_counts", string="Allocations Count")

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

    @api.depends('project_ids', 'client_ids', 'project_allocation_ids')
    def _compute_counts(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)
            rec.client_count = len(rec.client_ids)
            rec.project_allocation_count = len(rec.project_allocation_ids)

    def action_view_project_allocations(self):
        self.ensure_one()
        context = {
            'default_contract_id': self.id,
            'default_partner_id': self.client_ids[0].id if self.client_ids else False,
            'default_name': self.name,
            'default_billing_amount': self.contract_amount,
            'default_currency_id': self.currency_id.id if self.currency_id else False,
            'default_date_start': self.contract_start_date,
            'default_date': self.contract_end_date,
            'default_company_id': self.company_id.id if self.company_id else False,
        }
        if self.sale_order_ids:
            context['default_sale_order_id'] = self.sale_order_ids[0].id

        return {
            'name': _('Project Allocations'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.allocation',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': context,
        }

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
        string="Account Lead",
        tracking=True,
    )
    delivery_lead_id = fields.Many2one(
        'hr.employee',
        string="Delivery Lead",
        tracking=True,
    )
    practice_lead_id = fields.Many2one(
        'hr.employee',
        string="Practice Lead",
        tracking=True,
    )
    allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_id',
        string="Allocated Resources",
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

    @api.depends('allocation_ids.amount')
    def _compute_total_allocation_amount(self):
        for rec in self:
            rec.total_allocation_amount = sum(rec.allocation_ids.mapped('amount'))

    @api.depends('allocation_ids.margin')
    def _compute_total_margin(self):
        for rec in self:
            rec.total_margin = sum(rec.allocation_ids.mapped('margin'))

    @api.constrains('allocation_ids', 'billing_amount')
    def _check_total_allocation_amount(self):
        for rec in self:
            if rec.billing_amount and rec.allocation_ids:
                total = sum(rec.allocation_ids.mapped('amount'))
                if float_compare(total, rec.billing_amount, precision_digits=2) > 0:
                    raise ValidationError(
                        _("The total allocated amount (%(total)s) cannot exceed the project's Billing Amount (%(billing)s).",
                          total=f"{total:,.2f}", billing=f"{rec.billing_amount:,.2f}")
                    )

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


class ProjectAllocation(models.Model):
    _name = 'project.allocation'
    _description = 'Project Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string="Allocation / Project Title", required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer Name",
        required=True,
        tracking=True,
    )
    contract_id = fields.Many2one(
        'project.contract.management',
        string="Contract",
        required=True,
        tracking=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string="Project",
        tracking=True,
    )
    project_code = fields.Char(
        string="Project Code",
        related='project_id.project_code',
        readonly=True,
        store=True,
    )
    billing_amount = fields.Monetary(
        string="Billing Amount",
        currency_field='currency_id',
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    label_tasks = fields.Char(
        string="Name of the Tasks",
        default="Tasks",
        help="Label used for tasks of this project",
    )
    tag_ids = fields.Many2many(
        'project.tags',
        string="Tags",
    )
    user_id = fields.Many2one(
        'res.users',
        string="Project Manager",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    account_lead_id = fields.Many2one(
        'hr.employee',
        string="Account Lead",
        required=True,
        tracking=True,
    )
    delivery_lead_id = fields.Many2one(
        'hr.employee',
        string="Delivery Lead",
        required=True,
        tracking=True,
    )
    practice_lead_id = fields.Many2one(
        'hr.employee',
        string="Practice Lead",
        required=True,
        tracking=True,
    )
    date_start = fields.Date(
        string="Planned Start Date",
        required=True,
        tracking=True,
    )
    date = fields.Date(
        string="Planned End Date",
        required=True,
        tracking=True,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string="Status", default='draft', required=True, tracking=True, copy=False)

    # Notebook Tabs
    description = fields.Html(string="Description")

    # Settings Tab
    allow_milestones = fields.Boolean(string="Milestones", default=False)
    allow_timesheets = fields.Boolean(string="Timesheets", default=True)
    allow_billable = fields.Boolean(string="Billable", default=True)
    billing_type = fields.Selection([
        ('manually', 'Billed Manually'),
        ('timesheet', 'Billed on Timesheets'),
    ], string="Billing Type", default='manually')

    # Invoicing Tab
    sale_order_id = fields.Many2one(
        'sale.order',
        string="Sales Order",
        tracking=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string="Sales Order Item",
    )

    # Allocations Tab
    allocation_ids = fields.One2many(
        'project.resource.allocation',
        'project_allocation_id',
        string="Allocated Resources",
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

    @api.depends('allocation_ids.amount')
    def _compute_total_allocation_amount(self):
        for rec in self:
            rec.total_allocation_amount = sum(rec.allocation_ids.mapped('amount'))

    @api.depends('allocation_ids.margin')
    def _compute_total_margin(self):
        for rec in self:
            rec.total_margin = sum(rec.allocation_ids.mapped('margin'))

    @api.constrains('date_start', 'date')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date and rec.date < rec.date_start:
                raise ValidationError(_("The Planned End Date cannot be earlier than the Planned Start Date."))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract_id = self.env.context.get('default_contract_id')
        if not contract_id and self.env.context.get('active_model') == 'project.contract.management':
            contract_id = self.env.context.get('active_id')

        if contract_id:
            contract = self.env['project.contract.management'].browse(contract_id)
            if contract.exists():
                res['contract_id'] = contract.id
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
            res = self._onchange_check_contract_consistency()
            if res:
                return res

    @api.constrains('contract_id', 'billing_amount', 'company_id', 'partner_id')
    def _check_contract_consistency(self):
        for rec in self:
            if not rec.contract_id:
                continue
            contract = rec.contract_id
            messages = []
            if rec.billing_amount and contract.contract_amount:
                contract_amt = contract.contract_amount
                if rec.currency_id and contract.currency_id and rec.currency_id != contract.currency_id:
                    contract_amt = contract.currency_id._convert(
                        contract_amt, rec.currency_id, rec.company_id or self.env.company, fields.Date.today()
                    )
                if float_compare(rec.billing_amount, contract_amt, precision_digits=2) > 0:
                    messages.append(
                        _("Billing amount (%(billing)s) cannot be more than the contract amount (%(contract_amt)s).",
                          billing=f"{rec.billing_amount:,.2f}", contract_amt=f"{contract_amt:,.2f}")
                    )
            if rec.company_id and contract.company_id and rec.company_id != contract.company_id:
                messages.append(
                    _("Company of project allocation ('%(p_comp)s') and contract ('%(c_comp)s') must be the same.",
                      p_comp=rec.company_id.name, c_comp=contract.company_id.name)
                )
            if rec.partner_id and contract.client_ids:
                contract_partners = contract.client_ids | contract.client_ids.commercial_partner_id
                proj_partners = rec.partner_id | rec.partner_id.commercial_partner_id
                if not (proj_partners & contract_partners):
                    client_names = ", ".join(contract.client_ids.mapped('name'))
                    messages.append(
                        _("Customer ('%(partner)s') and contract ('%(clients)s') must be the same.",
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
        if self.billing_amount and contract.contract_amount:
            contract_amt = contract.contract_amount
            if self.currency_id and contract.currency_id and self.currency_id != contract.currency_id:
                contract_amt = contract.currency_id._convert(
                    contract_amt, self.currency_id, self.company_id or self.env.company, fields.Date.today()
                )
            if float_compare(self.billing_amount, contract_amt, precision_digits=2) > 0:
                messages.append(
                    _("Billing amount (%(billing)s) cannot be more than the contract amount (%(contract_amt)s).",
                      billing=f"{self.billing_amount:,.2f}", contract_amt=f"{contract_amt:,.2f}")
                )
        if self.company_id and contract.company_id and self.company_id != contract.company_id:
            messages.append(
                _("Company ('%(p_comp)s') and contract ('%(c_comp)s') must be the same.",
                  p_comp=self.company_id.name, c_comp=contract.company_id.name)
            )
        if self.partner_id and contract.client_ids:
            contract_partners = contract.client_ids | contract.client_ids.commercial_partner_id
            proj_partners = self.partner_id | self.partner_id.commercial_partner_id
            if not (proj_partners & contract_partners):
                client_names = ", ".join(contract.client_ids.mapped('name'))
                messages.append(
                    _("Customer ('%(partner)s') and contract ('%(clients)s') must be the same.",
                      partner=self.partner_id.name, clients=client_names)
                )
        if messages:
            return {
                'warning': {
                    'title': _("Contract Validation Warning"),
                    'message': "\n".join(f"• {m}" for m in messages)
                }
            }

    @api.constrains('allocation_ids', 'billing_amount')
    def _check_total_allocation_amount(self):
        for rec in self:
            if rec.billing_amount and rec.allocation_ids:
                total = sum(rec.allocation_ids.mapped('amount'))
                if float_compare(total, rec.billing_amount, precision_digits=2) > 0:
                    raise ValidationError(
                        _("The total allocated amount (%(total)s) cannot exceed the Billing Amount (%(billing)s).",
                          total=f"{total:,.2f}", billing=f"{rec.billing_amount:,.2f}")
                    )

    def action_submit_for_approval(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_("Only draft allocations can be submitted for approval."))
            if not rec.allocation_ids:
                raise ValidationError(_("Please add at least one allocated resource line before submitting."))
            rec.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise ValidationError(_("Only submitted allocations can be approved."))
            rec.write({'state': 'approved'})

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted':
                raise ValidationError(_("Only submitted allocations can be rejected."))
            rec.write({'state': 'rejected'})

    def action_reset_draft(self):
        for rec in self:
            if rec.project_id:
                raise ValidationError(_("Cannot reset to draft because a project has already been created for this allocation."))
            rec.write({'state': 'draft'})

    def action_create_project(self):
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_("A project can only be created when the allocation is in 'Approved' stage."))
        if self.project_id:
            return self.action_view_project()

        Project = self.env['project.project']
        project_vals = {
            'name': self.name,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'contract_id': self.contract_id.id if self.contract_id else False,
            'contract_ids': [(4, self.contract_id.id)] if self.contract_id else [],
            'billing_amount': self.billing_amount,
            'currency_id': self.currency_id.id if self.currency_id else False,
            'company_id': self.company_id.id if self.company_id else False,
            'user_id': self.user_id.id if self.user_id else False,
            'account_lead_id': self.account_lead_id.id if self.account_lead_id else False,
            'delivery_lead_id': self.delivery_lead_id.id if self.delivery_lead_id else False,
            'practice_lead_id': self.practice_lead_id.id if self.practice_lead_id else False,
            'date_start': self.date_start,
            'date': self.date,
            'description': self.description,
            'label_tasks': self.label_tasks or 'Tasks',
        }
        if self.tag_ids:
            project_vals['tag_ids'] = [(6, 0, self.tag_ids.ids)]
        if self.sale_order_id:
            project_vals['sale_order_id'] = self.sale_order_id.id
        if 'sale_line_id' in Project._fields and self.sale_line_id:
            project_vals['sale_line_id'] = self.sale_line_id.id
        if 'allow_milestones' in Project._fields:
            project_vals['allow_milestones'] = self.allow_milestones
        if 'allow_timesheets' in Project._fields:
            project_vals['allow_timesheets'] = self.allow_timesheets
        if 'allow_billable' in Project._fields:
            project_vals['allow_billable'] = self.allow_billable

        # project_code is intentionally omitted so project.project automatically generates it
        project = Project.create(project_vals)
        self.project_id = project.id
        for alloc in self.allocation_ids:
            alloc.project_id = project.id

        return {
            'type': 'ir.actions.act_window',
            'name': project.name,
            'res_model': 'project.project',
            'res_id': project.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_project(self):
        self.ensure_one()
        if not self.project_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': self.project_id.name,
            'res_model': 'project.project',
            'res_id': self.project_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ProjectResourceAllocation(models.Model):
    _name = 'project.resource.allocation'
    _description = 'Project Resource Allocation'
    _order = 'id asc'

    project_id = fields.Many2one(
        'project.project',
        string="Project",
        required=False,
        ondelete='cascade',
    )
    project_allocation_id = fields.Many2one(
        'project.allocation',
        string="Project Allocation",
        required=False,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string="Currency",
        store=True,
        readonly=False,
    )

    @api.depends('project_id.currency_id', 'project_allocation_id.currency_id')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.project_id.currency_id or rec.project_allocation_id.currency_id or self.env.company.currency_id

    resource_type = fields.Selection([
        ('licenses', 'Licenses'),
        ('employee', 'Employee'),
        ('hardwares', 'Hardwares'),
        ('others', 'Others'),
    ], string="Type", required=True, default='employee')

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
    )
    name = fields.Char(
        string="Based On Type",
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

    @api.depends('allocation_percentage', 'project_id.billing_amount', 'project_allocation_id.billing_amount')
    def _compute_amount(self):
        for rec in self:
            billing = 0.0
            if rec.project_id:
                billing = rec.project_id.billing_amount or 0.0
            elif rec.project_allocation_id:
                billing = rec.project_allocation_id.billing_amount or 0.0
            rec.amount = billing * (rec.allocation_percentage / 100.0)

    @api.depends('resource_type', 'allocation_percentage', 'amount', 'customer_price', 'vendor_price', 'employee_id')
    def _compute_margin(self):
        for rec in self:
            if rec.resource_type in ('hardwares', 'licenses'):
                rec.margin = (rec.customer_price or 0.0) - (rec.vendor_price or 0.0)
            elif rec.resource_type == 'employee':
                wage = 0.0
                if rec.employee_id:
                    emp_sudo = rec.employee_id.sudo()
                    wage = getattr(emp_sudo, 'contract_wage', 0.0) or getattr(emp_sudo, 'wage', 0.0) or 0.0
                allocated_cost = wage * (rec.allocation_percentage / 100.0)
                rec.margin = (rec.amount or 0.0) - allocated_cost
            else:
                rec.margin = 0.0

    @api.onchange('allocation_percentage', 'resource_type', 'customer_price', 'vendor_price', 'employee_id')
    def _onchange_allocation_percentage(self):
        billing = 0.0
        if self.project_id:
            billing = self.project_id.billing_amount or 0.0
        elif self.project_allocation_id:
            billing = self.project_allocation_id.billing_amount or 0.0

        if self.allocation_percentage > 100:
            warning = {
                'title': _("Invalid Allocation %"),
                'message': _("Allocation % cannot be more than 100%.")
            }
            self.allocation_percentage = 100.0
            self.amount = billing * (self.allocation_percentage / 100.0)
            self._compute_margin()
            return {'warning': warning}
        if self.allocation_percentage < 0:
            self.allocation_percentage = 0.0

        self.amount = billing * (self.allocation_percentage / 100.0)
        self._compute_margin()

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("The End Date cannot be earlier than the Start Date."))

    @api.constrains('allocation_percentage', 'amount', 'project_id', 'project_allocation_id')
    def _check_allocation_percentage(self):
        for rec in self:
            if rec.allocation_percentage < 0 or rec.allocation_percentage > 100:
                raise ValidationError(_("Allocation % cannot be more than 100%."))
            if rec.project_id and rec.project_id.billing_amount:
                total = sum(rec.project_id.allocation_ids.mapped('amount'))
                if float_compare(total, rec.project_id.billing_amount, precision_digits=2) > 0:
                    raise ValidationError(
                        _("The total allocated amount (%(total)s) cannot exceed the project's Billing Amount (%(billing)s).",
                          total=f"{total:,.2f}", billing=f"{rec.project_id.billing_amount:,.2f}")
                    )
            if rec.project_allocation_id and rec.project_allocation_id.billing_amount:
                total = sum(rec.project_allocation_id.allocation_ids.mapped('amount'))
                if float_compare(total, rec.project_allocation_id.billing_amount, precision_digits=2) > 0:
                    raise ValidationError(
                        _("The total allocated amount (%(total)s) cannot exceed the project allocation's Billing Amount (%(billing)s).",
                          total=f"{total:,.2f}", billing=f"{rec.project_allocation_id.billing_amount:,.2f}")
                    )

    @api.constrains('project_id', 'project_allocation_id')
    def _check_parent(self):
        for rec in self:
            if not rec.project_id and not rec.project_allocation_id:
                raise ValidationError(_("Resource allocation must be linked to either a Project or a Project Allocation."))

    @api.onchange('resource_type')
    def _onchange_resource_type(self):
        if self.resource_type != 'employee':
            self.employee_id = False
        elif self.employee_id:
            self.name = self.employee_id.name

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.name = self.employee_id.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('resource_type') == 'employee' and vals.get('employee_id') and not vals.get('name'):
                employee = self.env['hr.employee'].browse(vals['employee_id'])
                vals['name'] = employee.name
            if not vals.get('project_id') and vals.get('project_allocation_id'):
                parent_alloc = self.env['project.allocation'].browse(vals['project_allocation_id'])
                if parent_alloc.project_id:
                    vals['project_id'] = parent_alloc.project_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('resource_type') == 'employee' and vals.get('employee_id') and not vals.get('name'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['name'] = employee.name
        return super().write(vals)



