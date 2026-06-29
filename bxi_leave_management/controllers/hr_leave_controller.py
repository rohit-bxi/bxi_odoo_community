from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError
from datetime import datetime, time

class HrLeaveAPI(http.Controller):

    @http.route('/leave/apply',type='json',auth='public',methods=['POST'],csrf=False)
    def apply_leave(self, **data):
        try:
            employee_email = data.get('employee_email')
            time_off_code = data.get('time_off_code')
            date_from = data.get('date_from')
            date_to = data.get('date_to')
            reason = data.get('reason')
            if not employee_email:
                return {
                    'status': 'failed',
                    'error': 'employee_email is required'
                }
            if not time_off_code:
                return {
                    'status': 'failed',
                    'error': 'time_off_code is required'
                }
            if not date_from:
                return {
                    'status': 'failed',
                    'error': 'date_from is required'
                }
            if not date_to:
                return {
                    'status': 'failed',
                    'error': 'date_to is required'
                }
            try:
                request_date_from = datetime.strptime(
                    date_from,
                    '%Y-%m-%d'
                ).date()

                request_date_to = datetime.strptime(
                    date_to,
                    '%Y-%m-%d'
                ).date()

            except Exception:
                return {
                    'status': 'failed',
                    'error': 'Invalid date format. Use YYYY-MM-DD'
                }
            if request_date_from > request_date_to:
                return {
                    'status': 'failed',
                    'error': 'date_to cannot be before date_from'
                }
            employee = request.env[
                'hr.employee'
            ].sudo().search([
                ('work_email', '=', employee_email)
            ], limit=1)
            if not employee:
                return {
                    'status': 'failed',
                    'error': 'Employee not found'
                }
            if not employee.resource_calendar_id:
                return {
                    'status': 'failed',
                    'error': (
                        'Employee working schedule is not configured'
                    )
                }
            leave_type = request.env[
                'hr.leave.type'
            ].sudo().search([
                ('time_off_code', '=', time_off_code)
            ], limit=1)
            if not leave_type:
                return {
                    'status': 'failed',
                    'error': 'Invalid leave type'
                }
            overlap_leave = request.env[
                'hr.leave'
            ].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', 'not in', ['cancel', 'refuse']),
                ('request_date_from', '<=', request_date_to),
                ('request_date_to', '>=', request_date_from),
            ], limit=1)
            if overlap_leave:
                return {
                    'status': 'failed',
                    'error': (
                        f'Overlapping leave already exists '
                        f'from {overlap_leave.request_date_from} '
                        f'to {overlap_leave.request_date_to}'
                    )
                }
            remaining_leaves = leave_type.with_context(
                employee_id=employee.id
            ).virtual_remaining_leaves
            requested_days = (
                request_date_to - request_date_from
            ).days + 1
            if (
                not leave_type.allows_negative
                and requested_days > remaining_leaves
            ):
                return {
                    'status': 'failed',
                    'error': (
                        f'Insufficient leave balance. '
                        f'Available: {remaining_leaves} day(s), '
                        f'Requested: {requested_days} day(s)'
                    )
                }
            datetime_from = datetime.combine(
                request_date_from,
                time(9, 0, 0)
            )
            datetime_to = datetime.combine(
                request_date_to,
                time(18, 0, 0)
            )
            leave_vals = {
                'employee_id': employee.id,
                'holiday_status_id': leave_type.id,
                'request_date_from': request_date_from,
                'request_date_to': request_date_to,
                'date_from': datetime_from,
                'date_to': datetime_to,
                'name': reason or 'Leave Request',
            }
            leave = request.env[
                'hr.leave'
            ].sudo().create(leave_vals)
            if hasattr(leave, 'action_submit'):
                leave.action_submit()
            elif hasattr(leave, 'action_confirm'):
                leave.action_confirm()
            try:
                if hasattr(leave, 'action_approve'):
                    leave.action_approve()
                elif hasattr(leave, 'action_validate'):
                    leave.action_validate()
            except Exception:
                pass
            return {
                'status': 'success',
                'message': 'Leave applied successfully',
                'employee': employee.name,
                'employee_email': employee.work_email,
                'leave_type': leave_type.name,
                'request_date_from': str(
                    leave.request_date_from
                ),
                'request_date_to': str(
                    leave.request_date_to
                ),
                'number_of_days': leave.number_of_days,
                'reason': leave.name
            }

        except Exception as e:

            request.env.cr.rollback()

            return {
                'status': 'failed',
                'error': str(e)
            }

    @http.route('/api/leave/balance',type='json',auth='public',methods=['POST'],csrf=False)
    def leave_balance(self, **kwargs):
        employee_email = kwargs.get('employee_email')
        if not employee_email:
            return {
                "status": "error",
                "message": "employee_email is required"
            }

        employee = request.env['hr.employee'].sudo().search([
            ('work_email', '=', employee_email)
        ], limit=1)
        if not employee:
            return {
                "status": "error",
                "message": "Employee not found"
            }
        allocations = request.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate')
        ])
        result = []

        for allocation in allocations:
            leave_type = allocation.holiday_status_id
            allocated = allocation.number_of_days
            used_leaves = request.env[
                'hr.leave'
            ].sudo().search([
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', leave_type.id),
                ('state', '=', 'validate')
            ])
            used = abs(sum(
                used_leaves.mapped('number_of_days')
            ))
            remaining = allocated - used
            result.append({
                "leave_type": leave_type.name,
                "time_off_code": leave_type.time_off_code,
                "allocated": round(allocated, 2),
                "used": round(used, 2),
                "remaining": round(remaining, 2)
            })
        return {
            "status": "success",
            "employee_id": employee.id,
            "employee_name": employee.name,
            "employee_email": employee.work_email,
            "leave_balances": result
        }

    @http.route('/api/leave/history',type='json',auth='public',methods=['POST'],csrf=False)
    def leave_history(self, **kwargs):
        try:
            employee_email = kwargs.get('employee_email')
            state = kwargs.get('state')
            if not employee_email:
                return {
                    'status': 'failed',
                    'error': 'employee_email is required'
                }
            employee = request.env[
                'hr.employee'
            ].sudo().search([
                ('work_email', '=', employee_email)
            ], limit=1)
            if not employee:
                return {
                    'status': 'failed',
                    'error': 'Employee not found'
                }
            domain = [
                ('employee_id', '=', employee.id)
            ]
            if state:
                valid_states = [
                    'confirm',
                    'validate1',
                    'validate',
                    'refuse',
                    'cancel',
                ]
                if state not in valid_states:
                    return {
                        'status': 'failed',
                        'error': (
                            'Invalid state. '
                            'Allowed values: '
                            'draft, confirm, validate1, '
                            'validate, refuse, cancel'
                        )
                    }
                domain.append(('state', '=', state))
            leaves = request.env[
                'hr.leave'
            ].sudo().search(
                domain,
                order='id desc'
            )
            result = []
            for leave in leaves:
                result.append({
                    'leave_id': leave.id,
                    'leave_type': leave.holiday_status_id.name,
                    'time_off_code': leave.holiday_status_id.time_off_code,
                    'date_from': (
                        str(leave.request_date_from)
                        if leave.request_date_from
                        else False
                    ),
                    'date_to': (
                        str(leave.request_date_to)
                        if leave.request_date_to
                        else False
                    ),
                    'days': abs(
                        round(leave.number_of_days, 2)
                    ),
                    'state': leave.state,
                    'reason': leave.name,
                })
            return {
                'status': 'success',
                'employee_id': employee.id,
                'employee_name': employee.name,
                'employee_email': employee.work_email,
                'filter_state': state or 'all',
                'total_records': len(result),
                'leave_history': result
            }
        except Exception as e:
            request.env.cr.rollback()
            return {
                'status': 'failed',
                'error': str(e)
            }

    @http.route('/api/leave/update',type='json',auth='public',methods=['POST'],csrf=False)
    def update_leave(self, **kwargs):
        employee_email = kwargs.get('employee_email')
        time_off_code = kwargs.get('time_off_code')

        request_date_from = kwargs.get('request_date_from')
        request_date_to = kwargs.get('request_date_to')

        update_date_from = kwargs.get('update_date_from')
        update_date_to = kwargs.get('update_date_to')

        reason = kwargs.get('reason')

        if not employee_email:
            return {
                "status": "error",
                "message": "employee_email is required"
            }

        if not time_off_code:
            return {
                "status": "error",
                "message": "time_off_code is required"
            }

        if not request_date_from:
            return {
                "status": "error",
                "message": "request_date_from is required"
            }

        if not request_date_to:
            return {
                "status": "error",
                "message": "request_date_to is required"
            }

        if not update_date_from and not update_date_to and not reason:
            return {
                "status": "error",
                "message": "Nothing to update"
            }
        try:

            request_from = datetime.strptime(
                str(request_date_from),
                '%Y-%m-%d'
            ).date()

            request_to = datetime.strptime(
                str(request_date_to),
                '%Y-%m-%d'
            ).date()

            update_from = False
            update_to = False

            if update_date_from:
                update_from = datetime.strptime(
                    str(update_date_from),
                    '%Y-%m-%d'
                ).date()

            if update_date_to:
                update_to = datetime.strptime(
                    str(update_date_to),
                    '%Y-%m-%d'
                ).date()

            if update_from and update_to:
                if update_from > update_to:
                    return {
                        "status": "error",
                        "message": "update_date_from cannot be greater than update_date_to"
                    }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Date Error: {str(e)}"
            }

        employee = request.env['hr.employee'].sudo().search([
            ('work_email', '=', employee_email)
        ], limit=1)

        if not employee:
            return {
                "status": "error",
                "message": "Employee not found"
            }

        leave_type = request.env['hr.leave.type'].sudo().search([
            ('time_off_code', '=', time_off_code)
        ], limit=1)

        if not leave_type:
            return {
                "status": "error",
                "message": "Time Off type not found"
            }

        leave = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', '=', leave_type.id),
            ('request_date_from', '=', request_from),
            ('request_date_to', '=', request_to),
        ], limit=1, order='id desc')

        if not leave:

            all_leaves = request.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id)
            ])

            return {
                "status": "error",
                "message": "Matching leave request not found",
                "debug": {
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    "searched_from": str(request_from),
                    "searched_to": str(request_to),
                    "available_leaves": [
                        {
                            "leave_id": l.id,
                            "leave_type": l.holiday_status_id.name,
                            "from": str(l.request_date_from),
                            "to": str(l.request_date_to),
                            "state": l.state
                        }
                        for l in all_leaves
                    ]
                }
            }
        if leave.state in ['validate', 'refuse']:
            return {
                "status": "error",
                "message": "Approved or refused leave cannot be updated"
            }

        vals = {}
        if update_from:
            vals['request_date_from'] = update_from

        if update_to:
            vals['request_date_to'] = update_to

        if update_from:
            vals['date_from'] = datetime.combine(
                update_from,
                time.min
            )

        if update_to:
            vals['date_to'] = datetime.combine(
                update_to,
                time.max
            )
        if reason:
            vals['private_name'] = reason

        try:
            request.env.cr.execute("""
                UPDATE hr_leave
                SET
                    request_date_from = %s,
                    request_date_to = %s,
                    date_from = %s,
                    date_to = %s,
                    private_name = %s
                WHERE id = %s
            """, (
                vals.get('request_date_from') or leave.request_date_from,
                vals.get('request_date_to') or leave.request_date_to,
                vals.get('date_from') or leave.date_from,
                vals.get('date_to') or leave.date_to,
                vals.get('private_name') or leave.private_name,
                leave.id
            ))

            request.env.cr.commit()
            leave.invalidate_recordset()
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
        leave = request.env['hr.leave'].sudo().browse(leave.id)
        return {
            "status": "success",
            "message": "Leave updated successfully",
            "leave_id": leave.id,
            "employee_id": employee.id,
            "employee_name": employee.name,
            "employee_email": employee.work_email,
            "leave_type": leave_type.name,
            "time_off_code": leave_type.time_off_code,
            "updated_request_date_from": str(leave.request_date_from),
            "updated_request_date_to": str(leave.request_date_to),
            "updated_date_from": str(leave.date_from),
            "updated_date_to": str(leave.date_to),
            "reason": leave.private_name,
            "state": leave.state
        }
        

    @http.route('/api/leave/action',type='json',auth='public',methods=['POST'],csrf=False)
    def leave_action(self, **kwargs):
        try:
            employee_email = kwargs.get('employee_email')
            time_off_code = kwargs.get('time_off_code')
            request_date_from = kwargs.get(
                'request_date_from'
            )
            request_date_to = kwargs.get(
                'request_date_to'
            )
            action = kwargs.get('action')
            approver_type = kwargs.get(
                'approver_type'
            )
            if not employee_email:
                return {
                    "status": "error",
                    "message": (
                        "employee_email is required"
                    )
                }

            if not time_off_code:
                return {
                    "status": "error",
                    "message": (
                        "time_off_code is required"
                    )
                }

            if not request_date_from:
                return {
                    "status": "error",
                    "message": (
                        "request_date_from is required"
                    )
                }

            if not request_date_to:
                return {
                    "status": "error",
                    "message": (
                        "request_date_to is required"
                    )
                }

            if action not in ['approve', 'reject']:

                return {
                    "status": "error",
                    "message": (
                        "action must be "
                        "approve or reject"
                    )
                }

            if approver_type not in ['manager', 'hr']:

                return {
                    "status": "error",
                    "message": (
                        "approver_type must be "
                        "manager or hr"
                    )
                }
            try:

                request_from = datetime.strptime(
                    str(request_date_from),
                    '%Y-%m-%d'
                ).date()

                request_to = datetime.strptime(
                    str(request_date_to),
                    '%Y-%m-%d'
                ).date()

            except Exception as e:

                return {
                    "status": "error",
                    "message": (
                        f"Date Error: {str(e)}"
                    )
                }
            employee = request.env[
                'hr.employee'
            ].sudo().search([
                ('work_email', '=', employee_email)
            ], limit=1)

            if not employee:

                return {
                    "status": "error",
                    "message": "Employee not found"
                }
            leave_type = request.env[
                'hr.leave.type'
            ].sudo().search([
                ('time_off_code', '=', time_off_code)
            ], limit=1)

            if not leave_type:

                return {
                    "status": "error",
                    "message": (
                        "Time Off type not found"
                    )
                }
            leave = request.env[
                'hr.leave'
            ].sudo().search([
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', leave_type.id),
                ('request_date_from', '=', request_from),
                ('request_date_to', '=', request_to),
            ], limit=1, order='id desc')

            if not leave:

                return {
                    "status": "error",
                    "message": (
                        "Matching leave request "
                        "not found"
                    )
                }
            if action == 'reject':

                leave.sudo().write({
                    'state': 'refuse'
                })

                return {
                    "status": "success",
                    "message": (
                        f"{approver_type.upper()} "
                        f"rejected the leave"
                    ),
                    "leave_id": leave.id,
                    "state": leave.state
                }
            has_manager = bool(employee.leave_manager_id)
            if (
                action == 'approve'
                and approver_type == 'manager'
            ):

                approver_email = kwargs.get(
                    'approver_email'
                )

                if not approver_email:

                    return {
                        "status": "error",
                        "message": (
                            "approver_email is required"
                        )
                    }

                if not employee.leave_manager_id:

                    return {
                        "status": "error",
                        "message": (
                            "Employee leave manager "
                            "is not configured"
                        )
                    }

                manager_email = (
                    employee.leave_manager_id.work_email
                )
                if (
                    manager_email
                    != approver_email
                ):

                    return {
                        "status": "error",
                        "message": (
                            "Only assigned leave "
                            "manager can approve "
                            "this leave"
                        ),
                        "expected_manager_email": (
                            manager_email
                        )
                    }

                if leave.state != 'confirm':

                    return {
                        "status": "error",
                        "message": (
                            "Leave is not waiting "
                            "for manager approval"
                        ),
                        "current_state": leave.state
                    }

                request.env.cr.execute("""
                    UPDATE hr_leave
                    SET state = 'validate1'
                    WHERE id = %s
                """, (leave.id,))

                request.env.cr.commit()

                leave.invalidate_recordset()

                leave = request.env[
                    'hr.leave'
                ].sudo().browse(leave.id)

                return {
                    "status": "success",
                    "message": (
                        "Manager approved the leave"
                    ),
                    "leave_id": leave.id,
                    "employee_name": employee.name,
                    "manager_name": (
                        employee.leave_manager_id.name
                    ),
                    "manager_email": manager_email,
                    "state": leave.state,
                    "next_action": (
                        "Waiting for HR approval"
                    )
                }
            if (
                action == 'approve'
                and approver_type == 'hr'
            ):
                approver_email = kwargs.get(
                    'approver_email'
                )
                if not approver_email:

                    return {
                        "status": "error",
                        "message": (
                            "approver_email is required"
                        )
                    }
                hr_emails = leave_type.responsible_ids.mapped(
                    'work_email'
                )
                if approver_email not in hr_emails:
                    return {
                        "status": "error",
                        "message": (
                            "Only configured HR can "
                            "approve this leave"
                        ),
                        "allowed_hr_emails": hr_emails
                    }
                if employee.leave_manager_id:
                    if leave.state != 'validate1':
                        return {
                            "status": "error",
                            "message": (
                                "Manager approval "
                                "pending first"
                            ),
                            "current_state": leave.state
                        }
                else:
                    if leave.state != 'confirm':

                        return {
                            "status": "error",
                            "message": (
                                "Leave is not waiting "
                                "for HR approval"
                            ),
                            "current_state": leave.state
                        }
                request.env.cr.execute("""
                    UPDATE hr_leave
                    SET state = 'validate'
                    WHERE id = %s
                """, (leave.id,))
                request.env.cr.commit()
                leave.invalidate_recordset()
                leave = request.env[
                    'hr.leave'
                ].sudo().browse(leave.id)

                return {
                    "status": "success",
                    "message": (
                        "HR approved the leave"
                    ),
                    "leave_id": leave.id,
                    "employee_name": employee.name,
                    "hr_email": approver_email,
                    "state": leave.state
                }
        except Exception as e:
            request.env.cr.rollback()
            return {
                "status": "error",
                "message": str(e)
            }