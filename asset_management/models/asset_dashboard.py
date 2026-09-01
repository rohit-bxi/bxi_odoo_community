# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date
from dateutil.relativedelta import relativedelta


class AssetDashboard(models.AbstractModel):
    """
    Backend Data Provider for the Custom PowerBI-Style Asset Management Dashboard.
    Provides aggregated KPIs, multi-tab chart datasets, filter options, and summary lists.
    """
    _name = 'asset.dashboard'
    _description = 'Asset Management Dashboard'

    @api.model
    def get_dashboard_data(self, filters=None):
        """
        Return filtered KPI metrics, multi-tab chart series, filter dropdown options,
        and asset summaries based on applied filters.
        """
        if filters is None:
            filters = {}

        today = fields.Date.today()
        Asset = self.env['asset.management']
        DepEntry = self.env['asset.depreciation.entry']
        MaintEntry = self.env['asset.maintenance.entry']
        company = self.env.company
        currency = company.currency_id

        # ─── Build Domain from Filters ────────────────────────────────────────
        domain = []

        if filters.get('department_id'):
            domain.append(('department_id', '=', int(filters['department_id'])))
        if filters.get('asset_type_id'):
            domain.append(('asset_type_id', '=', int(filters['asset_type_id'])))
        if filters.get('employee_id'):
            domain.append(('employee_id', '=', int(filters['employee_id'])))
        if filters.get('location'):
            domain.append(('location_description', 'ilike', filters['location']))
        if filters.get('vendor_id'):
            domain.append(('vendor_id', '=', int(filters['vendor_id'])))
        if filters.get('status') and filters['status'] != 'all':
            domain.append(('status', '=', filters['status']))
        if filters.get('state') and filters['state'] != 'all':
            domain.append(('state', '=', filters['state']))

        # Search assets based on filter domain
        all_matched_assets = Asset.search(domain)
        active_assets = all_matched_assets.filtered(lambda a: a.state != 'disposed')
        confirmed_assets = all_matched_assets.filtered(lambda a: a.state == 'confirmed')
        disposed_assets = all_matched_assets.filtered(lambda a: a.state == 'disposed')

        # ─── 1. Primary Top 5 KPI Metrics ─────────────────────────────────────
        total_count = len(all_matched_assets)
        active_count = len(all_matched_assets.filtered(lambda a: a.status == 'assign'))
        total_cost = sum(all_matched_assets.mapped('amount'))
        total_accumulated_dep = sum(confirmed_assets.mapped('total_depreciation_amount'))
        total_nbv = sum(confirmed_assets.mapped('current_amount'))

        # ─── 2. Filter Dropdown Options (Global) ──────────────────────────────
        all_assets_global = Asset.search([])

        # Unique Departments
        dept_ids = all_assets_global.mapped('department_id')
        department_options = [{'id': d.id, 'name': d.name} for d in dept_ids if d]

        # Unique Asset Types
        type_ids = all_assets_global.mapped('asset_type_id')
        type_options = [{'id': t.id, 'name': t.name} for t in type_ids if t]

        # Unique Assigned Employees
        emp_ids = all_assets_global.mapped('employee_id')
        employee_options = [{'id': e.id, 'name': e.name} for e in emp_ids if e]

        # Unique Vendors
        vendor_ids = all_assets_global.mapped('vendor_id')
        vendor_options = [{'id': v.id, 'name': v.name} for v in vendor_ids if v]

        # Unique Locations
        locations = sorted(list({a.location_description for a in all_assets_global if a.location_description}))
        location_options = [{'id': loc, 'name': loc} for loc in locations]

        # Status Options
        status_options = [
            {'id': 'all', 'name': 'All Statuses'},
            {'id': 'assign', 'name': 'In Use / Assigned'},
            {'id': 'in_warehouse', 'name': 'In Stock / Warehouse'},
            {'id': 'return', 'name': 'Returned'},
            {'id': 'on_hold', 'name': 'On Hold'},
            {'id': 'repair', 'name': 'Under Repair'},
            {'id': 'destroyed', 'name': 'Disposed / Destroyed'},
        ]

        # ─── 3. OVERVIEW CHARTS ───────────────────────────────────────────────
        # Vendor NBV
        vendor_nbv_map = {}
        for a in confirmed_assets:
            v_name = a.vendor_id.name if a.vendor_id else _('Unassigned Vendor')
            vendor_nbv_map[v_name] = vendor_nbv_map.get(v_name, 0.0) + a.current_amount

        sorted_vendor_nbv = sorted(vendor_nbv_map.items(), key=lambda x: x[1], reverse=True)[:8]
        vendor_nbv_chart = {
            'labels': [item[0] for item in sorted_vendor_nbv] or [_('No Data')],
            'data': [round(item[1], 2) for item in sorted_vendor_nbv] or [0],
        }

        # Vendor Warranty Days
        vendor_warranty_map = {}
        vendor_warranty_counts = {}
        for a in active_assets:
            if a.expired_warranty_date:
                v_name = a.vendor_id.name if a.vendor_id else _('Other')
                days_left = max(0, (a.expired_warranty_date - today).days)
                vendor_warranty_map[v_name] = vendor_warranty_map.get(v_name, 0) + days_left
                vendor_warranty_counts[v_name] = vendor_warranty_counts.get(v_name, 0) + 1

        avg_warranty_list = []
        for v_name, total_days in vendor_warranty_map.items():
            count = vendor_warranty_counts.get(v_name, 1)
            avg_warranty_list.append((v_name, round(total_days / count)))

        avg_warranty_list = sorted(avg_warranty_list, key=lambda x: x[1], reverse=True)[:8]
        vendor_warranty_chart = {
            'labels': [item[0] for item in avg_warranty_list] or [_('No Warranty Data')],
            'data': [item[1] for item in avg_warranty_list] or [0],
        }

        # Department Status Breakdown
        active_depts = list({a.department_id for a in all_matched_assets if a.department_id})
        dept_names = [d.name for d in active_depts] or [_('All Departments')]

        status_keys = [
            ('assign', 'In Use', '#8b5cf6'),
            ('in_warehouse', 'In Stock', '#3b82f6'),
            ('repair', 'Under Repair', '#f59e0b'),
            ('destroyed', 'Disposed', '#ef4444'),
            ('return', 'Returned', '#06b6d4'),
        ]

        dept_status_datasets = []
        for skey, slabel, scolor in status_keys:
            data_points = []
            for d in active_depts:
                c = len(all_matched_assets.filtered(lambda a: a.department_id.id == d.id and a.status == skey))
                data_points.append(c)
            if not active_depts:
                c = len(all_matched_assets.filtered(lambda a: a.status == skey))
                data_points = [c]

            dept_status_datasets.append({
                'label': slabel,
                'data': data_points,
                'backgroundColor': scolor,
            })

        dept_status_chart = {
            'labels': dept_names,
            'datasets': dept_status_datasets,
        }

        # Asset Condition Breakdown
        cond_map = {'new': 0, 'good': 0, 'fair': 0, 'poor': 0, 'damaged': 0}
        for a in all_matched_assets:
            if a.asset_condition in cond_map:
                cond_map[a.asset_condition] += 1
            else:
                cond_map['good'] += 1

        condition_chart = {
            'labels': ['New', 'Good', 'Fair', 'Poor', 'Damaged'],
            'data': [cond_map['new'], cond_map['good'], cond_map['fair'], cond_map['poor'], cond_map['damaged']],
            'colors': ['#10b981', '#3b82f6', '#f59e0b', '#f97316', '#ef4444'],
        }

        # ─── 4. ASSET SUMMARY TAB DATA ────────────────────────────────────────
        single_assets_count = len(all_matched_assets.filtered(lambda a: a.model_type == 'single'))
        multiple_assets_count = len(all_matched_assets.filtered(lambda a: a.model_type == 'multiple'))
        total_initial_stock = sum(all_matched_assets.mapped('initial_stock'))
        total_current_stock = sum(all_matched_assets.mapped('current_stock'))

        # Asset Type Breakdown Chart
        type_count_map = {}
        type_val_map = {}
        for a in all_matched_assets:
            t_name = a.asset_type_id.name if a.asset_type_id else _('Standard')
            type_count_map[t_name] = type_count_map.get(t_name, 0) + 1
            type_val_map[t_name] = type_val_map.get(t_name, 0.0) + a.amount

        type_labels = list(type_count_map.keys()) or [_('General')]
        type_chart = {
            'labels': type_labels,
            'counts': [type_count_map[k] for k in type_labels],
            'values': [round(type_val_map[k], 2) for k in type_labels],
        }

        # Summary Table Rows (all matched or top 100)
        asset_summary_rows = []
        for a in all_matched_assets[:100]:
            asset_summary_rows.append({
                'id': a.id,
                'name': a.name,
                'asset_name': a.asset_name or a.name,
                'type': a.asset_type_id.name or '—',
                'department': a.department_id.name or '—',
                'employee': a.employee_id.name or '—',
                'vendor': a.vendor_id.name or '—',
                'condition': dict(a._fields['asset_condition'].selection).get(a.asset_condition, a.asset_condition),
                'cost': round(a.amount, 2),
                'nbv': round(a.current_amount, 2),
                'dep_pct': round(a.depreciation_percentage, 1),
                'status': a.status,
                'status_label': dict(a._fields['status'].selection).get(a.status, a.status),
                'state': a.state,
                'warranty_date': a.expired_warranty_date.strftime('%Y-%m-%d') if a.expired_warranty_date else '—',
            })

        # ─── 5. DEPARTMENT ANALYSIS TAB DATA ──────────────────────────────────
        dept_rows = []
        all_depts = self.env['hr.department'].search([])
        for d in all_depts:
            d_assets = all_matched_assets.filtered(lambda a: a.department_id.id == d.id)
            if d_assets:
                d_cost = sum(d_assets.mapped('amount'))
                d_nbv = sum(d_assets.filtered(lambda a: a.state == 'confirmed').mapped('current_amount'))
                d_dep = sum(d_assets.filtered(lambda a: a.state == 'confirmed').mapped('total_depreciation_amount'))
                d_maint = sum(d_assets.mapped('total_maintenance_amount'))
                dept_rows.append({
                    'id': d.id,
                    'name': d.name,
                    'count': len(d_assets),
                    'active_count': len(d_assets.filtered(lambda a: a.status == 'assign')),
                    'cost': round(d_cost, 2),
                    'nbv': round(d_nbv, 2),
                    'dep': round(d_dep, 2),
                    'maint': round(d_maint, 2),
                    'utilization': round(len(d_assets.filtered(lambda a: a.status == 'assign')) / len(d_assets) * 100, 1) if len(d_assets) else 0,
                })

        dept_rows = sorted(dept_rows, key=lambda x: x['nbv'], reverse=True)
        dept_chart = {
            'labels': [r['name'] for r in dept_rows[:8]] or [_('No Data')],
            'nbv': [r['nbv'] for r in dept_rows[:8]] or [0],
            'cost': [r['cost'] for r in dept_rows[:8]] or [0],
            'counts': [r['count'] for r in dept_rows[:8]] or [0],
        }

        # ─── 6. VENDOR ANALYSIS TAB DATA ──────────────────────────────────────
        vendor_rows = []
        all_vendors = self.env['asset.vendor'].search([])
        for v in all_vendors:
            v_assets = all_matched_assets.filtered(lambda a: a.vendor_id.id == v.id)
            if v_assets:
                v_cost = sum(v_assets.mapped('amount'))
                v_nbv = sum(v_assets.filtered(lambda a: a.state == 'confirmed').mapped('current_amount'))
                v_maint = sum(v_assets.mapped('total_maintenance_amount'))
                w_assets = v_assets.filtered(lambda a: a.expired_warranty_date)
                w_days = [max(0, (a.expired_warranty_date - today).days) for a in w_assets]
                avg_w = round(sum(w_days) / len(w_days)) if w_days else 0

                vendor_rows.append({
                    'id': v.id,
                    'name': v.name,
                    'count': len(v_assets),
                    'cost': round(v_cost, 2),
                    'nbv': round(v_nbv, 2),
                    'maint': round(v_maint, 2),
                    'avg_warranty_days': avg_w,
                })

        vendor_rows = sorted(vendor_rows, key=lambda x: x['cost'], reverse=True)
        vendor_maint_chart = {
            'labels': [r['name'] for r in vendor_rows[:8]] or [_('No Data')],
            'maint': [r['maint'] for r in vendor_rows[:8]] or [0],
            'cost': [r['cost'] for r in vendor_rows[:8]] or [0],
        }

        # ─── 7. MONTHLY TRENDS TAB DATA ───────────────────────────────────────
        months_labels = []
        acq_series = []
        dep_series = []
        maint_series = []
        cum_nbv_series = []
        monthly_table_rows = []

        running_nbv = 0.0
        for i in range(11, -1, -1):
            m_date = today - relativedelta(months=i)
            m_start = m_date.replace(day=1)
            next_m = m_start + relativedelta(months=1)
            m_end = next_m - relativedelta(days=1)
            m_label = m_start.strftime('%b %Y')
            months_labels.append(m_label)

            # Acquisitions
            m_acq = sum(all_matched_assets.filtered(
                lambda a: a.invoice_date and m_start <= a.invoice_date <= m_end
            ).mapped('amount'))
            acq_series.append(round(m_acq, 2))

            # Depreciation
            asset_ids = all_matched_assets.ids
            m_dep = sum(DepEntry.search([
                ('asset_id', 'in', asset_ids),
                ('state', '=', 'posted'),
                ('entry_date', '>=', m_start),
                ('entry_date', '<=', m_end),
            ]).mapped('depreciation_amount')) if asset_ids else 0.0
            dep_series.append(round(m_dep, 2))

            # Maintenance
            m_maint = sum(MaintEntry.search([
                ('asset_id', 'in', asset_ids),
                ('assign_date', '>=', m_start),
                ('assign_date', '<=', m_end),
            ]).mapped('maintenance_amount')) if asset_ids else 0.0
            maint_series.append(round(m_maint, 2))

            running_nbv = max(0, running_nbv + m_acq - m_dep)
            cum_nbv_series.append(round(running_nbv, 2))

            monthly_table_rows.append({
                'month': m_label,
                'acquisitions': round(m_acq, 2),
                'depreciation': round(m_dep, 2),
                'maintenance': round(m_maint, 2),
                'nbv': round(running_nbv, 2),
            })

        # Month totals
        first_of_month = today.replace(day=1)
        acq_this_month = sum(all_matched_assets.filtered(
            lambda a: a.invoice_date and a.invoice_date >= first_of_month
        ).mapped('amount'))
        dep_this_month = sum(DepEntry.search([
            ('asset_id', 'in', all_matched_assets.ids),
            ('state', '=', 'posted'),
            ('entry_date', '>=', first_of_month),
        ]).mapped('depreciation_amount')) if all_matched_assets else 0.0

        # ─── 8. Auxiliary Global KPIs ─────────────────────────────────────────
        in_warehouse_count = len(all_matched_assets.filtered(lambda a: a.status == 'in_warehouse'))
        in_repair_count = len(all_matched_assets.filtered(lambda a: a.status == 'repair'))
        warranty_expiring_30 = len(all_matched_assets.filtered(
            lambda a: a.expired_warranty_date and 0 <= (a.expired_warranty_date - today).days <= 30
        ))
        fully_depreciated_count = len(confirmed_assets.filtered(
            lambda a: a.current_amount <= a.salvage_value + 0.01 and a.amount > 0
        ))
        utilization_rate = round((active_count / total_count * 100) if total_count else 0.0, 1)

        return {
            # Company Details
            'company_id': company.id,
            'company_name': company.name or 'Asset Management',
            'currency_symbol': currency.symbol or '$',
            'currency_position': currency.position or 'before',

            # Primary KPIs (Overview & Global)
            'total_count': total_count,
            'active_count': active_count,
            'total_cost': round(total_cost, 2),
            'total_depreciation': round(total_accumulated_dep, 2),
            'total_nbv': round(total_nbv, 2),

            # Auxiliary Numbers
            'in_warehouse_count': in_warehouse_count,
            'in_repair_count': in_repair_count,
            'disposed_count': len(disposed_assets),
            'warranty_expiring_30': warranty_expiring_30,
            'fully_depreciated_count': fully_depreciated_count,
            'utilization_rate': utilization_rate,
            'single_assets_count': single_assets_count,
            'multiple_assets_count': multiple_assets_count,
            'total_initial_stock': total_initial_stock,
            'total_current_stock': total_current_stock,

            # Monthly Specifics
            'acq_this_month': round(acq_this_month, 2),
            'dep_this_month': round(dep_this_month, 2),

            # Filter Options
            'filters': {
                'departments': department_options,
                'asset_types': type_options,
                'employees': employee_options,
                'vendors': vendor_options,
                'locations': location_options,
                'statuses': status_options,
            },

            # Chart Datasets
            'charts': {
                'vendor_nbv': vendor_nbv_chart,
                'vendor_warranty': vendor_warranty_chart,
                'dept_status': dept_status_chart,
                'condition': condition_chart,
                'asset_type': type_chart,
                'dept_analysis': dept_chart,
                'vendor_maint': vendor_maint_chart,
                'monthly_trends': {
                    'labels': months_labels,
                    'acquisitions': acq_series,
                    'depreciation': dep_series,
                    'maintenance': maint_series,
                    'cum_nbv': cum_nbv_series,
                },
            },

            # Tab Detail Lists
            'asset_summary': asset_summary_rows,
            'department_summary': dept_rows,
            'vendor_summary': vendor_rows,
            'monthly_summary': list(reversed(monthly_table_rows)),
        }
