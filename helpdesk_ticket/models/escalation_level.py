from odoo import models, fields

class HelpdeskEscalationLevel(models.Model):
    _name = "helpdesk.escalation.level"
    _description = "Helpdesk Escalation Level"
    _order = "name asc"


    team_id = fields.Many2one(
        "helpdesk.team",
        string="Helpdesk Team",
        required=True,
        ondelete="cascade"
    )

    name = fields.Integer(
        string="Escalation Level",
        required=True,
        help="Level number like 1, 2, 3"
    )

    # assignee_ids = fields.Many2many(
    #     "res.users",
    #     string="Level Assignees",
    #     help="Users responsible for this escalation level"
    # )
    assignees_ids = fields.Many2many(
        "hr.employee",
        string="Level Assignees",
        help="Users responsible for this escalation level"
    )

