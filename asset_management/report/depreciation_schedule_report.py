# -*- coding: utf-8 -*-
from odoo import models, api, fields
from dateutil.relativedelta import relativedelta


class DepreciationScheduleReport(models.AbstractModel):
    _name = 'report.asset_management.depreciation_schedule_report'
    _description = 'Asset Depreciation Schedule Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        assets = self.env['asset.management'].browse(docids)
        report_data = []

        for asset in assets:
            schedule = self._compute_schedule(asset)
            report_data.append({
                'asset': asset,
                'schedule': schedule,
            })

        return {
            'doc_ids': docids,
            'doc_model': 'asset.management',
            'docs': assets,
            'report_data': report_data,
        }

    def _compute_schedule(self, asset):
        """Compute future depreciation schedule for an asset."""
        schedule = []
        if not asset.depreciation_apply or not asset.asset_type_id:
            return schedule

        method = asset.asset_type_id.depreciation_method
        freq = asset.asset_type_id.depreciation_frequency
        delay = asset.asset_type_id.depreciation_start_delay or 1
        max_entries = asset.asset_type_id.maximum_depreciation_entries or 999

        current_nbv = asset.current_amount
        salvage = asset.salvage_value or 0.0
        cost = asset.amount

        # Start from last depreciation date or capitalized date
        start_date = (asset.last_depreciation_date or
                      asset.capitalized_date or
                      asset.invoice_date or
                      fields.Date.today())

        posted_count = len(asset.depreciation_ids.filtered(
            lambda d: d.state == 'posted'))

        entry_num = posted_count + 1
        current_date = start_date
        cumulative_dep = asset.total_depreciation_amount

        while entry_num <= max_entries and current_nbv > salvage + 0.01:
            # Next period date
            if freq == 'yearly':
                current_date = current_date + relativedelta(years=delay)
            elif freq == 'monthly':
                current_date = current_date + relativedelta(months=delay)
            elif freq == 'days':
                from datetime import timedelta
                current_date = current_date + timedelta(days=delay)

            # Calculate depreciation
            rate = asset.asset_type_id.depreciation_rate

            if method == 'fix':
                dep_amount = rate
            elif method == 'percentage':
                base = cost if asset.asset_type_id.depreciation_basis == 'real_value' \
                    else current_nbv
                dep_amount = (base * rate) / 100
            elif method == 'straight_line':
                if asset.useful_life_years > 0:
                    annual = asset.depreciable_amount / asset.useful_life_years
                    dep_amount = annual / 12 if freq == 'monthly' else \
                                 annual / 365 if freq == 'days' else annual
                else:
                    dep_amount = 0
            elif method == 'declining_balance':
                dep_amount = (current_nbv * rate) / 100
            else:
                dep_amount = 0

            # Don't exceed NBV - salvage
            if current_nbv - dep_amount < salvage:
                dep_amount = current_nbv - salvage

            if dep_amount <= 0:
                break

            cumulative_dep += dep_amount
            current_nbv -= dep_amount

            schedule.append({
                'period': entry_num,
                'date': current_date,
                'opening_nbv': current_nbv + dep_amount,
                'dep_amount': dep_amount,
                'cumulative_dep': cumulative_dep,
                'closing_nbv': current_nbv,
                'dep_pct': (cumulative_dep / cost * 100) if cost else 0,
            })

            entry_num += 1

        return schedule
