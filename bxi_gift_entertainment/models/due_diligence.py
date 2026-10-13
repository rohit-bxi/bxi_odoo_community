from odoo import _, api, fields, models
from odoo.exceptions import UserError

SCOPES = [('gift', 'Gift / Entertainment'), ('donation', 'Donation'), ('sponsorship', 'Sponsorship')]


class BxiGiftDdQuestion(models.Model):
    _name = 'bxi.gift.dd.question'
    _description = 'Due Diligence Question'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Text(string='Question', required=True, translate=True)
    guidance = fields.Text(translate=True)
    scope = fields.Selection([('all', 'All')] + SCOPES, required=True, default='all')
    risk_answer = fields.Selection([('yes', 'Yes'), ('no', 'No')], required=True, default='yes',
                                   help="The answer that indicates a risk.")
    active = fields.Boolean(default=True)


class BxiGiftDueDiligence(models.Model):
    """LSO due diligence on the counterparty of a gift, donation or sponsorship."""
    _name = 'bxi.gift.due.diligence'
    _description = 'Due Diligence'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    res_model = fields.Char(required=True, readonly=True)
    res_id = fields.Many2oneReference(model_field='res_model', required=True, readonly=True)
    record_name = fields.Char(string='For', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Counterparty', tracking=True)
    scope = fields.Selection(SCOPES, required=True, default='gift')
    answer_ids = fields.One2many('bxi.gift.due.diligence.answer', 'due_diligence_id', string='Questionnaire')
    attachment_ids = fields.Many2many('ir.attachment', 'bxi_gift_dd_attachment_rel', 'dd_id', 'attachment_id',
                                      string='Evidence')
    reviewer_id = fields.Many2one('res.users', string='LSO Reviewer', tracking=True,
                                  default=lambda self: self.env.user)
    risk_count = fields.Integer(compute='_compute_risk', store=True)
    risk_rating = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
                                   compute='_compute_risk', store=True, tracking=True)
    conclusion = fields.Text()
    state = fields.Selection([
        ('draft', 'To Do'),
        ('approved', 'Cleared'),
        ('rejected', 'Not Cleared'),
    ], default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        Question = self.env['bxi.gift.dd.question']
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('bxi.gift.due.diligence') or 'New'
            if 'answer_ids' not in vals:
                scope = vals.get('scope', 'gift')
                vals['answer_ids'] = [(0, 0, {'question_id': q.id})
                                      for q in Question.search([('scope', 'in', ('all', scope))])]
        return super().create(vals_list)

    @api.depends('answer_ids.is_risk')
    def _compute_risk(self):
        for rec in self:
            count = len(rec.answer_ids.filtered('is_risk'))
            rec.risk_count = count
            rec.risk_rating = 'low' if not count else ('medium' if count <= 2 else 'high')

    def _linked_record(self):
        self.ensure_one()
        return self.env[self.res_model].sudo().browse(self.res_id)

    def _check_lso(self):
        if not self.env.user.has_group('bxi_gift_entertainment.group_gift_lso'):
            raise UserError(_("Only the LSO team can conclude a due diligence."))

    def action_approve(self):
        self._check_lso()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("%s is already concluded.", rec.name))
            if rec.answer_ids.filtered(lambda a: not a.answer):
                raise UserError(_("Answer every question before clearing the due diligence."))
            if rec.risk_rating == 'high' and not rec.conclusion:
                raise UserError(_("A high risk rating needs a written conclusion to be cleared."))
            rec.write({'state': 'approved', 'reviewer_id': self.env.user.id})
            record = rec._linked_record()
            line = record.current_approval_line_id
            if line.approver_type == 'due_diligence':
                record._gift_approve_line(line, self.env.user, comment=rec.conclusion)
        return True

    def action_reject(self):
        self._check_lso()
        for rec in self:
            if not rec.conclusion:
                raise UserError(_("Write the conclusion explaining why the counterparty is not cleared."))
            rec.write({'state': 'rejected', 'reviewer_id': self.env.user.id})
            record = rec._linked_record()
            if record.current_approval_line_id.approver_type == 'due_diligence':
                record.with_user(self.env.user).sudo()._gift_reject(
                    _("Due diligence %(name)s not cleared: %(conclusion)s", name=rec.name, conclusion=rec.conclusion))
        return True

    def action_open_record(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
                'view_mode': 'form'}


class BxiGiftDueDiligenceAnswer(models.Model):
    _name = 'bxi.gift.due.diligence.answer'
    _description = 'Due Diligence Answer'
    _order = 'sequence, id'

    due_diligence_id = fields.Many2one('bxi.gift.due.diligence', required=True, ondelete='cascade')
    question_id = fields.Many2one('bxi.gift.dd.question', required=True, ondelete='restrict')
    sequence = fields.Integer(related='question_id.sequence', store=True)
    question = fields.Text(related='question_id.name')
    guidance = fields.Text(related='question_id.guidance')
    answer = fields.Selection([('yes', 'Yes'), ('no', 'No'), ('na', 'Not Applicable')])
    comment = fields.Char()
    is_risk = fields.Boolean(compute='_compute_is_risk', store=True)

    @api.depends('answer', 'question_id.risk_answer')
    def _compute_is_risk(self):
        for rec in self:
            rec.is_risk = rec.answer == rec.question_id.risk_answer
