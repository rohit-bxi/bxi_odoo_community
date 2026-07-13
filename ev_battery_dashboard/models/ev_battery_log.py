# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class EvBatteryLog(models.Model):
    _name = 'ev.battery.log'
    _description = 'EV Battery KPI Log'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='EV Vehicle',
        required=True,
        ondelete='cascade',
    )
    device_id = fields.Many2one(
        'ev.device',
        string='Telemetry Device',
        ondelete='set null',
    )
    import_batch_id = fields.Many2one(
        'ev.import.batch',
        string='Import Batch',
        ondelete='set null',
        readonly=True,
    )
    raw_import_source = fields.Char(
        string='Source File',
        readonly=True,
        help='Filename from which this record was imported',
    )
    date = fields.Date(
        string='Log Date',
        required=True,
        default=fields.Date.context_today,
    )
    odometer = fields.Float(
        string='Odometer (km)',
        required=True,
    )
    trip_distance = fields.Float(
        string='Trip Distance (km)',
        required=True,
    )

    # 1. Battery SOH & Degradation Rate
    soh = fields.Float(
        string='State of Health (SOH %)',
        required=True,
        help='State of Health of the battery pack',
    )
    degradation_rate = fields.Float(
        string='Degradation Rate (%/10k km)',
        required=True,
        help='Degradation rate normalized to % loss per 10,000 km',
    )

    # 2. Battery Energy Efficiency (kWh/km)
    energy_efficiency = fields.Float(
        string='Energy Efficiency (kWh/km)',
        required=True,
        help='Energy consumption efficiency of the trip',
    )

    # 3. SOC Drop per Trip
    soc_start = fields.Float(
        string='SOC Start (%)',
        required=True,
    )
    soc_end = fields.Float(
        string='SOC End (%)',
        required=True,
    )
    soc_drop = fields.Float(
        string='SOC Drop (%)',
        compute='_compute_soc_drop',
        store=True,
    )

    # 4. Charging Behaviour & Battery Cycle Stress
    charge_type = fields.Selection(
        [
            ('slow', 'Slow Charge (AC)'),
            ('fast', 'Fast Charge (DC)'),
            ('none', 'No Charge / Discharge Only'),
        ],
        string='Recent Charging Type',
        default='none',
        required=True,
    )
    cycle_stress_score = fields.Float(
        string='Cycle Stress Score',
        required=True,
        help='Battery mechanical & chemical stress score from cycling (0-100)',
    )

    # 5. Battery Temperature Stress
    avg_temperature = fields.Float(
        string='Average Temp (°C)',
        required=True,
    )
    max_temperature = fields.Float(
        string='Max Temp (°C)',
        required=True,
    )
    temperature_stress_score = fields.Float(
        string='Temperature Stress Score',
        required=True,
        help='Score indicating heat-related battery stress (0-100)',
    )

    # Advanced / Predictive KPIs
    regen_efficiency = fields.Float(
        string='Regen Efficiency (%)',
        help='Energy recovered through regenerative braking vs total traction energy',
    )
    cell_imbalance = fields.Float(
        string='Cell Voltage Imbalance (mV)',
        help='Maximum voltage delta between cells (higher indicates cell mismatch)',
    )
    internal_resistance = fields.Float(
        string='Internal Resistance (mΩ)',
        help='Total battery pack internal resistance',
    )
    co2_savings = fields.Float(
        string='CO2 Saved (kg)',
        compute='_compute_co2_savings',
        store=True,
        help='Estimated carbon emissions saved compared to an equivalent internal combustion engine vehicle',
    )

    @api.depends('trip_distance')
    def _compute_co2_savings(self):
        for rec in self:
            # Standard multiplier: 0.22 kg CO2 saved per electric kilometer driven
            rec.co2_savings = rec.trip_distance * 0.22

    @api.depends('soc_start', 'soc_end')
    def _compute_soc_drop(self):
        for rec in self:
            rec.soc_drop = max(0.0, rec.soc_start - rec.soc_end)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('ev.battery.log.sequence') or '/'
        return super(EvBatteryLog, self).create(vals_list)

    @api.model
    def get_dashboard_data(self, vehicle_id=None, date_range=None, charge_type=None, soh_status=None):
        """Compiles and returns aggregated KPIs for custom EV Fleet Battery Dashboard."""
        domain = []
        if vehicle_id:
            domain.append(('vehicle_id', '=', int(vehicle_id)))

        # Date Range Filter
        if date_range and date_range != 'all':
            from datetime import timedelta
            today = fields.Date.context_today(self)
            if date_range == '7days':
                domain.append(('date', '>=', today - timedelta(days=7)))
            elif date_range == '30days':
                domain.append(('date', '>=', today - timedelta(days=30)))
            elif date_range == '90days':
                domain.append(('date', '>=', today - timedelta(days=90)))

        # Charge Type Filter
        if charge_type and charge_type != 'all':
            domain.append(('charge_type', '=', charge_type))

        # SOH Status Filter
        if soh_status and soh_status != 'all':
            if soh_status == 'healthy':
                domain.append(('soh', '>=', 90.0))
            elif soh_status == 'warning':
                domain.append(('soh', '>=', 80.0))
                domain.append(('soh', '<', 90.0))
            elif soh_status == 'critical':
                domain.append(('soh', '<', 80.0))

        logs = self.search(domain, order='date asc')
        all_vehicles = self.env['fleet.vehicle'].search([])
        vehicles = all_vehicles

        # Calculate standard fleet aggregations
        total_logs = len(logs)
        avg_soh = sum(l.soh for l in logs) / total_logs if total_logs else 0
        avg_degradation = sum(l.degradation_rate for l in logs) / total_logs if total_logs else 0
        avg_efficiency = sum(l.energy_efficiency for l in logs) / total_logs if total_logs else 0
        avg_soc_drop = sum(l.soc_drop for l in logs) / total_logs if total_logs else 0
        avg_cycle_stress = sum(l.cycle_stress_score for l in logs) / total_logs if total_logs else 0
        avg_temp_stress = sum(l.temperature_stress_score for l in logs) / total_logs if total_logs else 0

        # Advanced aggregates
        total_co2 = sum(l.trip_distance * 0.22 for l in logs)
        avg_regen = sum(l.regen_efficiency or max(10.0, min(35.0, 24.5 - (l.energy_efficiency - 0.15) * 45)) for l in logs) / total_logs if total_logs else 0
        avg_imbalance = sum(l.cell_imbalance or max(5.0, min(80.0, 11.5 + (l.cycle_stress_score * 0.28))) for l in logs) / total_logs if total_logs else 0
        avg_resistance = sum(l.internal_resistance or max(15.0, min(95.0, 22.0 + (100.0 - l.soh) * 1.8)) for l in logs) / total_logs if total_logs else 0

        # Charging split counts
        fast_charge_count = sum(1 for l in logs if l.charge_type == 'fast')
        slow_charge_count = sum(1 for l in logs if l.charge_type == 'slow')
        discharge_only_count = sum(1 for l in logs if l.charge_type == 'none')

        # Chart datasets preparation
        chart_soh_dates = []
        chart_soh_values = []
        chart_degradation_values = []
        chart_efficiency_values = []
        chart_temp_avg = []
        chart_temp_max = []
        chart_regen = []
        chart_imbalance = []
        chart_resistance = []

        for log in logs:
            date_str = log.date.strftime('%Y-%m-%d')
            chart_soh_dates.append(date_str)
            chart_soh_values.append(log.soh)
            chart_degradation_values.append(log.degradation_rate)
            chart_efficiency_values.append(log.energy_efficiency)
            chart_temp_avg.append(log.avg_temperature)
            chart_temp_max.append(log.max_temperature)
            
            # Fallbacks for advanced charts
            chart_regen.append(log.regen_efficiency or max(10.0, min(35.0, 24.5 - (log.energy_efficiency - 0.15) * 45)))
            chart_imbalance.append(log.cell_imbalance or max(5.0, min(80.0, 11.5 + (log.cycle_stress_score * 0.28))))
            chart_resistance.append(log.internal_resistance or max(15.0, min(95.0, 22.0 + (100.0 - log.soh) * 1.8)))

        # Vehicle list with status summary
        vehicle_summary_list = []
        for veh in vehicles:
            veh_logs = logs.filtered(lambda l: l.vehicle_id == veh) if not vehicle_id else logs
            if not veh_logs:
                veh_logs = self.search([('vehicle_id', '=', veh.id)], order='date asc')
            
            if veh_logs:
                latest_log = veh_logs[-1]
                v_soh = latest_log.soh
                v_degradation = sum(l.degradation_rate for l in veh_logs) / len(veh_logs)
                v_efficiency = sum(l.energy_efficiency for l in veh_logs) / len(veh_logs)
                v_temp_stress = sum(l.temperature_stress_score for l in veh_logs) / len(veh_logs)
                v_cycle_stress = sum(l.cycle_stress_score for l in veh_logs) / len(veh_logs)
                
                # SOH status classification
                if v_soh >= 90:
                    status = 'Optimal'
                    status_class = 'success'
                elif v_soh >= 80:
                    status = 'Attention Required'
                    status_class = 'warning'
                else:
                    status = 'Maintenance Required'
                    status_class = 'danger'

                vehicle_summary_list.append({
                    'id': veh.id,
                    'name': veh.display_name,
                    'model': veh.model_id.name or 'Unknown Model',
                    'license_plate': veh.license_plate or 'Unknown Plate',
                    'latest_soh': round(v_soh, 1),
                    'avg_degradation': round(v_degradation, 2),
                    'avg_efficiency': round(v_efficiency, 3),
                    'avg_temp_stress': round(v_temp_stress, 1),
                    'avg_cycle_stress': round(v_cycle_stress, 1),
                    'avg_imbalance': round(sum(l.cell_imbalance or max(5.0, min(80.0, 11.5 + (l.cycle_stress_score * 0.28))) for l in veh_logs) / len(veh_logs), 1),
                    'avg_resistance': round(sum(l.internal_resistance or max(15.0, min(95.0, 22.0 + (100.0 - l.soh) * 1.8)) for l in veh_logs) / len(veh_logs), 1),
                    'status': status,
                    'status_class': status_class,
                })

        # Fleet comparison arrays
        fleet_comparison = {
            'labels': [s['license_plate'] for s in vehicle_summary_list],
            'soh': [s['latest_soh'] for s in vehicle_summary_list],
            'efficiency': [s['avg_efficiency'] for s in vehicle_summary_list],
            'imbalance': [s['avg_imbalance'] for s in vehicle_summary_list],
            'resistance': [s['avg_resistance'] for s in vehicle_summary_list],
        }

        # Fleet overview aggregations
        healthy = sum(1 for s in vehicle_summary_list if s['status'] == 'Optimal')
        warning = sum(1 for s in vehicle_summary_list if s['status'] == 'Attention Required')
        critical = sum(1 for s in vehicle_summary_list if s['status'] == 'Maintenance Required')
        total_fleet_km = sum(v.odometer for v in all_vehicles if v.odometer)

        # GPS Tracking & Last Trip Analyzer
        map_points = []
        is_route = False
        last_trip_details = None

        if vehicle_id:
            # Selected vehicle: return full last trip route & stop details
            devices = self.env['ev.device'].search([('vehicle_id', '=', vehicle_id)])
            if devices:
                gps_logs = self.env['ev.telemetry.log'].search([
                    ('device_id', 'in', devices.ids),
                    ('latitude', '!=', 0.0),
                    ('longitude', '!=', 0.0)
                ], order='timestamp asc')

                if gps_logs:
                    # Segment logs into trips based on time gap (> 15 mins) or ignition cycles
                    trips = []
                    current_trip = []
                    for log in gps_logs:
                        if not current_trip:
                            current_trip.append(log)
                            continue
                        prev_log = current_trip[-1]
                        time_gap = (log.timestamp - prev_log.timestamp).total_seconds() / 60.0
                        if time_gap > 15.0 or (not prev_log.ignition and log.ignition):
                            trips.append(current_trip)
                            current_trip = [log]
                        else:
                            current_trip.append(log)
                    if current_trip:
                        trips.append(current_trip)

                    if trips:
                        last_trip = trips[-1]
                        is_route = True

                        # Parse stops and device on/off cycles
                        stops = []
                        import math

                        # Haversine distance calculator
                        def get_dist(lat1, lon1, lat2, lon2):
                            R = 6371.0
                            dlat = math.radians(lat2 - lat1)
                            dlon = math.radians(lon2 - lon1)
                            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
                            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                            return R * c

                        i = 0
                        while i < len(last_trip):
                            log = last_trip[i]
                            # Scenario A: Device / Ignition turned OFF
                            if not log.ignition:
                                stop_time = log.timestamp
                                next_on = self.env['ev.telemetry.log'].search([
                                    ('device_id', '=', log.device_id.id),
                                    ('timestamp', '>', log.timestamp),
                                    ('ignition', '=', True)
                                ], order='timestamp asc', limit=1)

                                if next_on:
                                    restart_time = next_on[0].timestamp
                                    duration = round((restart_time - stop_time).total_seconds() / 60.0, 1)
                                else:
                                    duration = 15.0 # default estimated stop length
                                
                                stops.append({
                                    'lat': log.latitude,
                                    'lng': log.longitude,
                                    'time': stop_time.strftime('%H:%M:%S'),
                                    'duration': duration,
                                    'type': 'ignition_off',
                                    'description': f"Ignition Turned OFF (Device Offline) for {duration} mins"
                                })
                            # Scenario B: Speed is 0 but Ignition is ON (Idling Stop)
                            elif log.speed == 0:
                                stop_start = log.timestamp
                                j = i + 1
                                while j < len(last_trip) and last_trip[j].speed == 0 and last_trip[j].ignition:
                                    j += 1
                                stop_end = last_trip[j-1].timestamp
                                duration = round((stop_end - stop_start).total_seconds() / 60.0, 1)
                                if duration >= 1.0:
                                    stops.append({
                                        'lat': log.latitude,
                                        'lng': log.longitude,
                                        'time': stop_start.strftime('%H:%M:%S'),
                                        'duration': duration,
                                        'type': 'idle',
                                        'description': f"Vehicle Idle Stop for {duration} mins"
                                    })
                                i = j - 1
                            i += 1

                        # Calculate total trip distance
                        total_dist = 0.0
                        for idx in range(len(last_trip) - 1):
                            total_dist += get_dist(last_trip[idx].latitude, last_trip[idx].longitude, last_trip[idx+1].latitude, last_trip[idx+1].longitude)
                        
                        if total_dist == 0.0 and len(last_trip) > 1:
                            total_dist = max(0.0, last_trip[-1].odometer - last_trip[0].odometer)
                        if total_dist == 0.0:
                            total_dist = 3.5

                        avg_speed = sum(l.speed for l in last_trip) / len(last_trip)
                        max_speed = max(l.speed for l in last_trip)
                        duration_mins = (last_trip[-1].timestamp - last_trip[0].timestamp).total_seconds() / 60.0

                        last_trip_details = {
                            'start_time': last_trip[0].timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                            'end_time': last_trip[-1].timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                            'duration_mins': round(max(5.0, duration_mins), 1),
                            'distance_km': round(total_dist, 2),
                            'avg_speed': round(avg_speed, 1),
                            'max_speed': round(max_speed, 1),
                            'stops_count': len(stops),
                            'stops': stops
                        }


                        map_points = [{
                            'lat': l.latitude,
                            'lng': l.longitude,
                            'speed': l.speed,
                            'time': l.timestamp.strftime('%H:%M:%S'),
                            'ign': l.ignition,
                        } for l in last_trip]

        else:
            # All vehicles: return latest coordinate for each device
            devices = self.env['ev.device'].search([('vehicle_id', '!=', False)])
            for dev in devices:
                latest_gps = self.env['ev.telemetry.log'].search(
                    [('device_id', '=', dev.id), ('latitude', '!=', 0.0), ('longitude', '!=', 0.0)],
                    order='timestamp desc',
                    limit=1
                )
                if latest_gps:
                    map_points.append({
                        'veh_name': dev.vehicle_id.display_name,
                        'plate': dev.vehicle_id.license_plate or '',
                        'lat': latest_gps.latitude,
                        'lng': latest_gps.longitude,
                        'speed': latest_gps.speed,
                        'time': latest_gps.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        'ign': latest_gps.ignition,
                    })

        return {
            'kpis': {
                'avg_soh': round(avg_soh, 2),
                'avg_degradation': round(avg_degradation, 2),
                'avg_efficiency': round(avg_efficiency, 3),
                'avg_soc_drop': round(avg_soc_drop, 2),
                'avg_cycle_stress': round(avg_cycle_stress, 2),
                'avg_temp_stress': round(avg_temp_stress, 2),
                'avg_regen': round(avg_regen, 1),
                'avg_imbalance': round(avg_imbalance, 1),
                'avg_resistance': round(avg_resistance, 1),
                'total_co2': round(total_co2, 1),
            },
            'charging_split': {
                'fast': fast_charge_count,
                'slow': slow_charge_count,
                'none': discharge_only_count,
            },
            'charts': {
                'dates': chart_soh_dates,
                'soh': chart_soh_values,
                'degradation': chart_degradation_values,
                'efficiency': chart_efficiency_values,
                'temp_avg': chart_temp_avg,
                'temp_max': chart_temp_max,
                'regen': chart_regen,
                'imbalance': chart_imbalance,
                'resistance': chart_resistance,
            },
            'vehicles': [{'id': v.id, 'name': v.display_name} for v in all_vehicles],
            'vehicle_summary': vehicle_summary_list,
            'fleet_overview': {
                'total': len(all_vehicles),
                'healthy': healthy,
                'warning': warning,
                'critical': critical,
                'total_km': round(total_fleet_km, 0),
                'total_logs': total_logs,
            },
            'map_data': {
                'points': map_points,
                'is_route': is_route,
                'last_trip_details': last_trip_details,
                'stops': last_trip_details['stops'] if last_trip_details else [],
            },
            'fleet_comparison': fleet_comparison
        }

