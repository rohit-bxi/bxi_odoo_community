# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from datetime import date, datetime

# -----------------------------------------------------------------------
# Field type exclusions
# -----------------------------------------------------------------------
# -----------------------------------------------------------------------
# Field exclusion rules
# -----------------------------------------------------------------------
_SKIP_TYPES = {'binary'}
_M2O_TYPES  = {'many2one'}
_X2M_TYPES  = {'many2many', 'one2many'}

# Prefixes — any field starting with these is excluded
_EXCLUDED_PREFIXES = (
    'activity_',        # Odoo activity/chatter
    'message_',         # mail.thread chatter
    'allocation_',      # leave allocation counts
    'allowed_',         # allowed_country_state_ids etc.
    'leave_',           # leave computed flags
    'l10n_in_',         # India payroll localization (wages, PF, ESIC amounts)
    'payslip',          # payslip_count, payslips_count
    'onboarding_',      # onboarding count/ids
    'timesheet_',       # timesheet_manager_id
    'equipment_',       # equipment_count, equipment_ids
    'goal_',            # goal_ids
    'version_',         # version_id, version_ids, versions_count
    'subordinate_',     # subordinate_ids
    'subscribed_',      # subscribed_courses
    'work_entry_',      # work_entry_source_calendar_invalid
    'work_location_',   # work_location_id/name/type
    'work_permit_',     # work_permit_name/expiration
    'salary_',          # salary_attachment_*, salary_distribution
    'last_',            # last_activity, last_generation_date, last_modified_*
    'im_',              # im_status (instant messaging)
    'has_',             # has_badges, has_timesheet, has_work_entries, etc.
    'is_',              # computed boolean flags (is_absent, is_fulltime, etc.)
)

# Suffixes — any field ending with these is excluded
_EXCLUDED_SUFFIXES = (
    '_location_id',     # monday_location_id, friday_location_id, etc.
)

# Specific field names to always exclude
_EXCLUDED_FIELDS = {
    'website_message_ids',
    'hr_presence_state',
    'allocations_count',
    # Equipment / expense
    'expense_manager_id',
    'filter_for_expense',
    # Payroll / salary
    'hourly_cost',
    'hourly_wage',
    'nps_contribution',
    'schedule_pay',
    'structure_id',
    'structure_type_id',
    'standard_calendar_id',
    'wage',
    'wage_type',
    'work_time_rate',
    'full_time_required_hours',
    'hours_per_week',
    # Folders & versioning
    'hr_employee_contract_folder_id',
    'hr_employee_folder_id',
    'template_company_id',
    # HR computed display
    'hr_icon_display',
    'newly_hired',
    'today_location_name',
    'exceptional_location_id',
    # Misc computed / counters
    'script_qty',
    'script_rate',
    'video_qty',
    'video_rate',
    'total_amount',
    'permit_no',
    # Audit fields
    'write_date',
    'write_uid',
    # Work permit (specific)
    'work_permit_name',
} 


def _is_excluded(fname):
    """Return True if this field should be excluded from the response."""
    if fname in _EXCLUDED_FIELDS:
        return True
    for prefix in _EXCLUDED_PREFIXES:
        if fname.startswith(prefix):
            return True
    for suffix in _EXCLUDED_SUFFIXES:
        if fname.endswith(suffix):
            return True
    return False


def _serialize_value(value, field_type):
    """Convert an Odoo field value to a JSON-safe type."""
    if value is None or value is False:
        return None
    if field_type in _M2O_TYPES:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return {'id': value[0], 'name': value[1]}
        return None
    if field_type in _X2M_TYPES:
        return list(value) if isinstance(value, (list, tuple)) else []
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, date):
        return value.strftime('%Y-%m-%d')
    return value


class EmployeeAPIController(http.Controller):

    @http.route(
        '/api/employee/all',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def get_all_employees(self, **kwargs):
        """
        Return all hr.employee records keyed by "employee_code - employee_name".

        Optional POST params (inside "params" key):
            active_only  (bool)  : true = only active, false = all incl. archived  [default: false]
            limit        (int)   : max records, 0 = all                            [default: 0]
            offset       (int)   : pagination offset                               [default: 0]

        Postman body (raw JSON):
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "active_only": false,
                "limit": 0,
                "offset": 0
            }
        }

        Response shape:
        {
            "status": true,
            "total": 120,
            "count": 120,
            "data": {
                "EMP001 - John Doe": { ...all fields... },
                "EMP002 - Jane Smith": { ...all fields... },
                ...
            }
        }
        """
        try:
            active_only = kwargs.get('active_only', False)
            limit       = int(kwargs.get('limit', 0))
            offset      = int(kwargs.get('offset', 0))

            domain = [('active', '=', True)] if active_only else []

            # All company IDs so records from every company are accessible
            all_company_ids = request.env['res.company'].sudo().search([]).ids

            ctx = dict(
                request.env.context,
                active_test=bool(active_only),
                allowed_company_ids=all_company_ids,
            )

            Employee = request.env['hr.employee'].sudo().with_context(ctx)

            # ------------------------------------------------------------------
            # Discover fields — exclude:
            #   1. Binary fields (too large)
            #   2. Non-stored computed fields (cause multi-company singleton error)
            #   3. Activity / chatter / allocation / leave meta fields (unwanted)
            # ------------------------------------------------------------------
            all_fields_meta = Employee.fields_get(attributes=['type', 'store', 'compute'])

            field_names = sorted(
                fname for fname, fmeta in all_fields_meta.items()
                if fmeta.get('type') not in _SKIP_TYPES
                and not (fmeta.get('compute') and not fmeta.get('store', False))
                and not _is_excluded(fname)
            )

            # Always keep these core fields
            for f in ('id', 'name', 'active', 'employee_code'):
                if f in all_fields_meta and f not in field_names:
                    field_names.insert(0, f)

            # ------------------------------------------------------------------
            # Fetch records
            # ------------------------------------------------------------------
            total   = Employee.search_count(domain)
            records = Employee.search(domain, limit=limit or 0, offset=offset)

            # Bulk read — fall back to per-employee if any field errors
            try:
                rows = records.read(field_names)
            except Exception:
                rows = []
                for emp in records:
                    row = {'id': emp.id}
                    for fname in field_names:
                        try:
                            val = emp.read([fname])
                            row[fname] = val[0].get(fname) if val else None
                        except Exception:
                            row[fname] = None
                    rows.append(row)

            # ------------------------------------------------------------------
            # Serialise + key by "employee_code - name"
            # ------------------------------------------------------------------
            data = {}
            for rec in rows:
                row = {}
                for fname in field_names:
                    ftype      = all_fields_meta.get(fname, {}).get('type', 'char')
                    row[fname] = _serialize_value(rec.get(fname), ftype)

                # Build the dict key: "EMP001 - John Doe"
                emp_code = rec.get('employee_code') or ''
                emp_name = rec.get('name') or f"id_{rec.get('id')}"
                key = f"{emp_code} - {emp_name}" if emp_code else emp_name

                data[key] = row

            return {
                'status'  : True,
                'message' : 'Employee data fetched successfully',
                'total'   : total,
                'count'   : len(data),
                'limit'   : limit,
                'offset'  : offset,
                'data'    : data,
            }

        except Exception as e:
            return {
                'status'  : False,
                'message' : str(e),
            }