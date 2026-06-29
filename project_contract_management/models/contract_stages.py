from odoo import models, fields, api

class ContractStage(models.Model):
    _name = 'project.contract.stage'
    _description = 'Contract Stage'
    _order = 'sequence'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=1)
    fold = fields.Boolean("Folded in Kanban")
    probability = fields.Float(string="Success Probability (%)")
    color = fields.Integer(string="Color Index")