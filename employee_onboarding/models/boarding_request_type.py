# -*- coding: utf-8 -*-

from odoo import models, fields


class BoardingRequestType(models.Model):
    _name = 'boarding.request.type'
    _description = 'Boarding Request Type'
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char(
        string='Name',
        required=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    task_ids = fields.One2many(
        'boarding.request.type.task',
        'request_type_id',
        string='Tasks',
    )


class BoardingRequestTypeTask(models.Model):
    _name = 'boarding.request.type.task'
    _description = 'Boarding Request Type Task'
    _order = 'sequence, id'

    request_type_id = fields.Many2one(
        'boarding.request.type',
        string='Request Type',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    task = fields.Char(
        string='Task',
        required=True,
    )
    performed_by = fields.Many2one(
        'request.type.team',
        string='Performed By',
        required=True,
    )
