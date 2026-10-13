from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Claims in approval move to the Reporting Manager, Finance, then HR approval.

    The Finance step is added before HR, and HR is added where it was not required. Claims waiting for Finance
    approval go back to Conveyance Approval, at the Finance step.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    claims = env['hr.expense'].search([
        ('conveyance_kind', '!=', False), ('state', 'in', ('conveyance_approval', 'finance_approval')),
    ])
    todo = env.ref('mail.mail_activity_data_todo')
    for claim in claims:
        lines = claim.conveyance_approval_line_ids
        company = claim.company_id
        approvers = lines.approver_user_id
        lines.filtered(lambda line: line.role == 'rm').sequence = 1
        new_lines = []
        if not lines.filtered(lambda line: line.role == 'finance'):
            finance_user = company.conveyance_finance_user_id
            if not finance_user or finance_user not in approvers:
                new_lines.append({'role': 'finance', 'approver_user_id': finance_user.id, 'sequence': 2})
                approvers |= finance_user
        hr_lines = lines.filtered(lambda line: line.role == 'hr')
        hr_lines.sequence = 3
        if not hr_lines:
            hr_user = company.conveyance_hr_user_id
            if not hr_user or hr_user not in approvers:
                new_lines.append({'role': 'hr', 'approver_user_id': hr_user.id, 'sequence': 3})
        if new_lines:
            claim.write({'conveyance_approval_line_ids': [(0, 0, vals) for vals in new_lines]})
        if claim.state == 'finance_approval':
            claim.state = 'conveyance_approval'
        # The step waiting for approval may have changed: notify its approvers again.
        claim.activity_ids.filtered(lambda act: act.activity_type_id == todo).unlink()
        if claim._get_current_conveyance_line():
            claim._notify_conveyance_approver()
        else:
            claim.state = 'approved'
