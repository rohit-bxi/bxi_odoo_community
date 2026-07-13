# -*- coding: utf-8 -*-

import base64
import io
import csv
import json
import logging
from datetime import date, datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  $NRM Payload – positional field map
#  Format: $NRM,<type_or_imei?>,<date_DDMMYYYY>,<time_HHMMSS>,
#          <lat>,<N/S>,<lon>,<E/W>,<speed>,<heading>,<altitude>,
#          <satellites>,<gps_status>,<battery_voltage>,<ignition>,<odometer>,...
#
#  Positions are 0-indexed from the split(',') on the raw payload.
#  Position 0 is always "$NRM".
# ─────────────────────────────────────────────────────────────────────────────
NRM_POSITIONS = {
    'msg_type':       0,   # $NRM
    'date':           2,   # DDMMYYYY or YYYYMMDD
    'time':           3,   # HHMMSS
    'latitude_raw':   4,   # DDMM.mmmm
    'lat_dir':        5,   # N / S
    'longitude_raw':  6,   # DDDMM.mmmm
    'lon_dir':        7,   # E / W
    'speed':          8,   # km/h
    'heading':        9,   # degrees
    'altitude':       10,  # metres
    'satellites':     11,  # count
    'gps_status':     12,  # A=Active, V=Void
    'battery_voltage':13,  # Volts (float)
    'ignition':       14,  # 0 / 1
    'odometer':       15,  # km (float)
}

# Column aliases for cleaned CSV / Excel format (case-insensitive)
TELEMETRY_CLEAN_COL_MAP = {
    'device_imei':     ['device imei', 'imei', 'device_imei', 'deviceimei', 'device id', 'device_id'],
    'date':            ['date', 'log_date', 'log date'],
    'time':            ['time', 'log_time', 'log time'],
    'latitude':        ['latitude', 'lat', 'gps_lat', 'gps lat'],
    'longitude':       ['longitude', 'lon', 'lng', 'gps_lon', 'gps lon'],
    'speed':           ['speed', 'speed (km/h)', 'vehicle speed', 'spd'],
    'ignition':        ['ignition', 'ignition status', 'ign'],
    'gps_status':      ['gps status', 'gps_status', 'fix status', 'gps fix'],
    'battery_voltage': ['battery voltage', 'battery_voltage', 'bat voltage', 'battery v', 'batt voltage'],
    'odometer':        ['odometer', 'odo', 'mileage', 'km', 'total km'],
    'heading':         ['heading', 'direction', 'course', 'bearing'],
    'altitude':        ['altitude', 'alt', 'elevation'],
    'satellites':      ['satellites', 'sats', 'gps satellites', 'satellite count'],
}

# CSV/legacy fleet column aliases (unchanged from original)
FLEET_COL_MAP = {
    'device_id':     ['device_id', 'device', 'device_code', 'unit_id', 'unit', 'imei'],
    'license_plate': ['license_plate', 'license', 'plate', 'reg_no', 'registration'],
    'brand':         ['brand', 'make', 'manufacturer'],
    'model':         ['model', 'model_name', 'vehicle_model'],
    'year':          ['year', 'model_year', 'manufacture_year'],
    'odometer':      ['odometer', 'mileage', 'km', 'kilometers', 'odo'],
    'vin':           ['vin', 'chassis', 'chassis_no', 'vin_number'],
    'driver':        ['driver', 'driver_name', 'assigned_driver', 'employee'],
    'color':         ['color', 'colour', 'vehicle_color'],
}

CHARGE_TYPE_NORM = {
    'slow': 'slow', 'ac': 'slow', 'slow charge': 'slow', 'ac charge': 'slow',
    'fast': 'fast', 'dc': 'fast', 'fast charge': 'fast', 'dc charge': 'fast',
    'none': 'none', 'discharge': 'none', 'no charge': 'none',
}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _detect_delimiter(raw_text):
    for dlm in ['|', ',', '\t', ';']:
        if dlm in raw_text[:500]:
            return dlm
    return ','


def _map_columns(header_row, col_map):
    mapping = {}
    header_lower = [h.strip().lower() for h in header_row]
    for canonical, aliases in col_map.items():
        for alias in aliases:
            if alias in header_lower:
                mapping[canonical] = header_lower.index(alias)
                break
    return mapping


def _safe_float(val, default=0.0):
    try:
        return float(str(val).strip().replace(',', ''))
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default


def _safe_date(val):
    val = str(val).strip()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%m/%d/%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return date.today()


def _nrm_lat(raw, direction):
    """Convert DDMM.mmmm + N/S to decimal degrees."""
    try:
        raw = str(raw).strip()
        if not raw:
            return 0.0
        dot = raw.index('.')
        degrees = float(raw[:dot - 2])
        minutes = float(raw[dot - 2:])
        decimal = degrees + minutes / 60.0
        if direction.strip().upper() == 'S':
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return _safe_float(raw)


def _nrm_lon(raw, direction):
    """Convert DDDMM.mmmm + E/W to decimal degrees."""
    try:
        raw = str(raw).strip()
        if not raw:
            return 0.0
        dot = raw.index('.')
        degrees = float(raw[:dot - 2])
        minutes = float(raw[dot - 2:])
        decimal = degrees + minutes / 60.0
        if direction.strip().upper() == 'W':
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return _safe_float(raw)


def _parse_nrm_datetime(date_str, time_str):
    """Parse NRM date (DDMMYYYY or YYYYMMDD) + time (HHMMSS) into datetime."""
    date_str = str(date_str).strip().zfill(8)
    time_str = str(time_str).strip().zfill(6)
    for fmt in ('%d%m%Y', '%Y%m%d', '%d%m%y'):
        try:
            dt = datetime.strptime(date_str + time_str, fmt + '%H%M%S')
            return dt
        except ValueError:
            pass
    return datetime.now()


def _nrm_gps_status(val):
    v = str(val).strip().upper()
    return v if v in ('A', 'V', 'D') else 'unknown'


def _nrm_ignition(val):
    v = str(val).strip()
    return v in ('1', 'true', 'True', 'on', 'ON', 'yes')


def _get_nrm_field(fields_list, pos, default=''):
    try:
        return fields_list[pos] if pos < len(fields_list) else default
    except (IndexError, TypeError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
#  Wizard
# ─────────────────────────────────────────────────────────────────────────────
class EvImportWizard(models.TransientModel):
    _name = 'ev.import.wizard'
    _description = 'EV Fleet / Telemetry .dat Import Wizard'

    # ── File Uploads ──────────────────────────────────────────────────────────
    fleet_file = fields.Binary(
        string='Fleet .dat File',
        attachment=False,
        help='Fleet master data .dat file (CSV or JSON format)',
    )
    fleet_filename = fields.Char(string='Fleet Filename')

    device_file = fields.Binary(
        string='Telemetry / Device .dat File',
        attachment=False,
        help=(
            'Raw GPS telematics .dat file (JSON with $NRM payload) '
            'OR cleaned CSV with named columns: '
            'Device IMEI, Date, Time, Latitude, Longitude, Speed, Ignition, '
            'GPS Status, Battery Voltage, Odometer, Heading'
        ),
    )
    device_filename = fields.Char(string='Device Filename')

    # ── Options ───────────────────────────────────────────────────────────────
    delimiter = fields.Selection(
        [
            ('auto', 'Auto Detect'),
            (',', 'Comma (,)'),
            ('|', 'Pipe (|)'),
            ('\t', 'Tab'),
            (';', 'Semicolon (;)'),
        ],
        string='Delimiter (for CSV files)',
        default='auto',
        required=True,
    )

    # ── Preview ───────────────────────────────────────────────────────────────
    fleet_preview = fields.Text(string='Fleet File Preview', readonly=True)
    device_preview = fields.Text(string='Device File Preview', readonly=True)
    detected_format = fields.Char(string='Detected Format', readonly=True)

    # ── Result ────────────────────────────────────────────────────────────────
    import_result = fields.Text(string='Import Result', readonly=True)
    batch_id = fields.Many2one('ev.import.batch', string='Import Batch', readonly=True)
    state = fields.Selection(
        [('upload', 'Upload'), ('result', 'Result')],
        default='upload',
    )

    # ─────────────────────────────────────────────────────────────────────────
    def _decode_file(self, file_binary):
        raw = base64.b64decode(file_binary)
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('latin-1')

    def _get_delimiter(self, text):
        return text if self.delimiter != 'auto' else _detect_delimiter(text)

    def _detect_file_format(self, text):
        """Return 'json_nrm', 'json_array', or 'csv'."""
        stripped = text.strip()
        if stripped.startswith('[') or stripped.startswith('{'):
            # Could be JSON array or JSONL (one JSON object per line)
            try:
                json.loads(stripped[:2000] if len(stripped) > 2000 else stripped)
                return 'json_array' if stripped.startswith('[') else 'jsonl'
            except json.JSONDecodeError:
                # Try first line
                first_line = stripped.splitlines()[0]
                try:
                    json.loads(first_line)
                    return 'jsonl'
                except json.JSONDecodeError:
                    pass
        return 'csv'

    def _parse_jsonl_records(self, text):
        """Parse JSONL or JSON array, return list of dicts."""
        text = text.strip()
        records = []
        if text.startswith('['):
            try:
                records = json.loads(text)
            except json.JSONDecodeError:
                pass
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records

    # ─────────────────────────────────────────────────────────────────────────
    def action_preview(self):
        previews = []
        if self.fleet_file:
            text = self._decode_file(self.fleet_file)
            fmt = self._detect_file_format(text)
            self.fleet_preview = f'[Format: {fmt.upper()}]\n' + '\n'.join(text.strip().splitlines()[:4])
            previews.append(fmt)

        if self.device_file:
            text = self._decode_file(self.device_file)
            fmt = self._detect_file_format(text)
            # Show first record nicely if JSON
            if fmt in ('jsonl', 'json_array'):
                records = self._parse_jsonl_records(text)
                if records:
                    first = records[0]
                    payload = first.get('payload', first.get('Payload', ''))
                    preview_parts = [f'[Format: JSON with $NRM payload]']
                    preview_parts.append(f'Total records in preview: {min(len(records), 3)}')
                    preview_parts.append(f'IMEI field: {first.get("imei", first.get("IMEI", first.get("device_id", "not found")))}')
                    if payload:
                        preview_parts.append(f'Payload: {payload[:120]}...')
                        nrm_fields = payload.split(',')
                        preview_parts.append(f'  → $NRM fields count: {len(nrm_fields)}')
                        for i, v in enumerate(nrm_fields[:16]):
                            preview_parts.append(f'  → [{i}] = {v}')
                    self.device_preview = '\n'.join(preview_parts)
                else:
                    self.device_preview = '[JSON detected but no records parsed]\n' + text[:300]
            else:
                self.device_preview = f'[Format: CSV]\n' + '\n'.join(text.strip().splitlines()[:5])
            previews.append(fmt)

        self.detected_format = ', '.join(set(previews)) if previews else 'unknown'

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Main import
    # ─────────────────────────────────────────────────────────────────────────
    def action_import(self):
        if not self.fleet_file and not self.device_file:
            raise UserError(_('Please upload at least one .dat file to import.'))

        batch = self.env['ev.import.batch'].create({
            'fleet_filename': self.fleet_filename or '',
            'device_filename': self.device_filename or '',
        })

        vehicles_created = 0
        vehicles_updated = 0
        devices_created = 0
        telemetry_created = 0
        errors = []

        device_map = {}  # imei/device_code → ev.device record

        # ── 1. Fleet File ─────────────────────────────────────────────────────
        if self.fleet_file:
            try:
                text = self._decode_file(self.fleet_file)
                fmt = self._detect_file_format(text)

                if fmt in ('jsonl', 'json_array'):
                    records = self._parse_jsonl_records(text)
                    for i, rec in enumerate(records, start=1):
                        try:
                            res = self._import_fleet_record_from_dict(rec)
                            vehicles_created += res.get('created', 0)
                            vehicles_updated += res.get('updated', 0)
                            devices_created += res.get('device_created', 0)
                            if res.get('device'):
                                imei = res['imei']
                                if imei:
                                    device_map[imei] = res['device']
                        except Exception as e:
                            errors.append(f'Fleet JSON row {i}: {e}')
                else:
                    dlm = _detect_delimiter(text) if self.delimiter == 'auto' else self.delimiter
                    reader = csv.reader(io.StringIO(text), delimiter=dlm)
                    rows = list(reader)
                    if not rows:
                        raise UserError('Fleet file appears empty.')
                    header, data_rows = rows[0], rows[1:]
                    col = _map_columns(header, FLEET_COL_MAP)
                    for i, row in enumerate(data_rows, start=2):
                        if not any(row):
                            continue
                        try:
                            def get(key, r=row):
                                idx = col.get(key)
                                return r[idx].strip() if idx is not None and idx < len(r) else ''

                            res = self._import_fleet_record_from_csv(get)
                            vehicles_created += res.get('created', 0)
                            vehicles_updated += res.get('updated', 0)
                            devices_created += res.get('device_created', 0)
                            if res.get('device') and res.get('imei'):
                                device_map[res['imei']] = res['device']
                        except Exception as e:
                            errors.append(f'Fleet CSV row {i}: {e}')

            except Exception as e:
                errors.append(f'Fleet file error: {e}')

        # ── 2. Telemetry / Device File ─────────────────────────────────────────
        if self.device_file:
            try:
                text = self._decode_file(self.device_file)
                fmt = self._detect_file_format(text)

                if fmt in ('jsonl', 'json_array'):
                    # Raw .dat format: JSON records with $NRM payload
                    records = self._parse_jsonl_records(text)
                    for i, rec in enumerate(records, start=1):
                        try:
                            telem = self._import_nrm_record(rec, device_map, batch)
                            if telem:
                                telemetry_created += 1
                        except Exception as e:
                            errors.append(f'Telemetry JSON row {i}: {e}')
                else:
                    # Cleaned CSV format with named columns
                    dlm = _detect_delimiter(text) if self.delimiter == 'auto' else self.delimiter
                    reader = csv.reader(io.StringIO(text), delimiter=dlm)
                    rows = list(reader)
                    if not rows:
                        raise UserError('Device file appears empty.')
                    header, data_rows = rows[0], rows[1:]
                    col = _map_columns(header, TELEMETRY_CLEAN_COL_MAP)
                    for i, row in enumerate(data_rows, start=2):
                        if not any(row):
                            continue
                        try:
                            def get(key, r=row):
                                idx = col.get(key)
                                return r[idx].strip() if idx is not None and idx < len(r) else ''

                            telem = self._import_clean_csv_record(get, device_map, batch)
                            if telem:
                                telemetry_created += 1
                        except Exception as e:
                            errors.append(f'Telemetry CSV row {i}: {e}')

            except Exception as e:
                errors.append(f'Telemetry file error: {e}')

        # ── Finalise Batch ────────────────────────────────────────────────────
        status = 'success' if not errors else ('partial' if (vehicles_created + telemetry_created) > 0 else 'failed')
        result_lines = [
            f'✅ Vehicles Created: {vehicles_created}',
            f'🔄 Vehicles Updated: {vehicles_updated}',
            f'📡 Devices Created: {devices_created}',
            f'📍 Telemetry Logs Created: {telemetry_created}',
        ]
        if errors:
            result_lines.append(f'\n⚠️ Warnings / Errors ({len(errors)}):')
            result_lines.extend(errors[:20])

        batch.write({
            'vehicles_created': vehicles_created,
            'vehicles_updated': vehicles_updated,
            'devices_created': devices_created,
            'logs_created': telemetry_created,
            'status': status,
            'notes': '\n'.join(result_lines),
        })

        self.write({
            'import_result': '\n'.join(result_lines),
            'batch_id': batch.id,
            'state': 'result',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Fleet record helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _get_or_create_device(self, imei_or_code, vehicle=None):
        """Find or create ev.device by IMEI/device code."""
        if not imei_or_code:
            return False, False
        device = self.env['ev.device'].search(
            ['|', ('device_id_code', '=', imei_or_code), ('imei', '=', imei_or_code)], limit=1
        )
        created = False
        if not device:
            device = self.env['ev.device'].create({
                'device_id_code': imei_or_code,
                'imei': imei_or_code,
                'name': f'Device {imei_or_code}',
                'device_type': 'telematics',
                'status': 'active',
                'vehicle_id': vehicle.id if vehicle else False,
            })
            created = True
        elif vehicle and not device.vehicle_id:
            device.write({'vehicle_id': vehicle.id})
        return device, created

    def _import_fleet_record_from_dict(self, rec):
        """Handle a fleet record coming from a JSON dict."""
        imei = (
            rec.get('imei') or rec.get('IMEI') or
            rec.get('device_id') or rec.get('deviceId') or ''
        )
        license_plate = rec.get('license_plate') or rec.get('plate') or rec.get('registration') or ''
        brand_name = rec.get('brand') or rec.get('make') or ''
        model_name = rec.get('model') or rec.get('vehicle_model') or ''
        year_val = _safe_int(rec.get('year') or rec.get('model_year') or 0)
        odometer_val = _safe_float(rec.get('odometer') or rec.get('mileage') or 0)
        vin_val = rec.get('vin') or rec.get('chassis') or ''
        color_val = rec.get('color') or rec.get('colour') or ''

        return self._upsert_fleet_vehicle(
            imei, license_plate, brand_name, model_name, year_val, odometer_val, vin_val, color_val
        )

    def _import_fleet_record_from_csv(self, get):
        """Handle a fleet record coming from a CSV row getter."""
        return self._upsert_fleet_vehicle(
            get('device_id'), get('license_plate'), get('brand'), get('model'),
            _safe_int(get('year')), _safe_float(get('odometer')),
            get('vin'), get('color'),
        )

    def _upsert_fleet_vehicle(self, imei, license_plate, brand_name, model_name,
                               year_val, odometer_val, vin_val, color_val):
        result = {'created': 0, 'updated': 0, 'device_created': 0, 'device': False, 'imei': imei}

        if not license_plate and not imei:
            return result

        brand_rec = False
        if brand_name:
            brand_rec = self.env['fleet.vehicle.model.brand'].search(
                [('name', 'ilike', brand_name)], limit=1
            )
            if not brand_rec:
                brand_rec = self.env['fleet.vehicle.model.brand'].create({'name': brand_name})

        model_rec = False
        if model_name and brand_rec:
            model_rec = self.env['fleet.vehicle.model'].search(
                [('name', 'ilike', model_name), ('brand_id', '=', brand_rec.id)], limit=1
            )
            if not model_rec:
                model_rec = self.env['fleet.vehicle.model'].create({
                    'name': model_name, 'brand_id': brand_rec.id, 'vehicle_type': 'car',
                })

        veh_vals = {}
        if license_plate:
            veh_vals['license_plate'] = license_plate
        if model_rec:
            veh_vals['model_id'] = model_rec.id
        if year_val:
            veh_vals['model_year'] = year_val
        if odometer_val:
            veh_vals['odometer'] = odometer_val
        if vin_val:
            veh_vals['vin_sn'] = vin_val
        if color_val:
            veh_vals['color'] = color_val

        vehicle = False
        if license_plate:
            vehicle = self.env['fleet.vehicle'].search([('license_plate', '=', license_plate)], limit=1)
            if vehicle:
                vehicle.write(veh_vals)
                result['updated'] = 1
            else:
                vehicle = self.env['fleet.vehicle'].create(veh_vals)
                result['created'] = 1

        device, dev_created = self._get_or_create_device(imei, vehicle)
        result['device'] = device
        result['device_created'] = 1 if dev_created else 0
        return result

    # ─────────────────────────────────────────────────────────────────────────
    #  Telemetry import helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _resolve_device(self, imei, device_map):
        """Find ev.device by IMEI, using cache then DB."""
        if not imei:
            return False
        if imei in device_map:
            return device_map[imei]
        device = self.env['ev.device'].search(
            ['|', ('imei', '=', imei), ('device_id_code', '=', imei)], limit=1
        )
        if device:
            device_map[imei] = device
        return device or False

    def _import_nrm_record(self, rec, device_map, batch):
        """Parse a JSON record with a $NRM payload field and create ev.telemetry.log."""
        # ── Extract IMEI from JSON wrapper ────────────────────────────────────
        imei = (
            str(rec.get('imei') or rec.get('IMEI') or
                rec.get('device_id') or rec.get('deviceId') or
                rec.get('device') or '').strip()
        )

        # ── Extract payload ───────────────────────────────────────────────────
        raw_payload = str(
            rec.get('payload') or rec.get('Payload') or rec.get('data') or ''
        ).strip()

        if not raw_payload:
            return False

        nrm = raw_payload.split(',')

        def nf(pos, default=''):
            return _get_nrm_field(nrm, pos, default)

        # ── Parse date/time ───────────────────────────────────────────────────
        # Try JSON-level timestamp first
        ts_raw = rec.get('timestamp') or rec.get('time') or rec.get('datetime') or ''
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace('Z', '+00:00').replace('z', ''))
            except (ValueError, AttributeError):
                ts = _parse_nrm_datetime(nf(NRM_POSITIONS['date']), nf(NRM_POSITIONS['time']))
        else:
            ts = _parse_nrm_datetime(nf(NRM_POSITIONS['date']), nf(NRM_POSITIONS['time']))

        # ── GPS coordinates ───────────────────────────────────────────────────
        lat = _nrm_lat(nf(NRM_POSITIONS['latitude_raw']), nf(NRM_POSITIONS['lat_dir']))
        lon = _nrm_lon(nf(NRM_POSITIONS['longitude_raw']), nf(NRM_POSITIONS['lon_dir']))

        # ── Other fields ──────────────────────────────────────────────────────
        speed = _safe_float(nf(NRM_POSITIONS['speed']))
        heading = _safe_float(nf(NRM_POSITIONS['heading']))
        altitude = _safe_float(nf(NRM_POSITIONS['altitude']))
        satellites = _safe_int(nf(NRM_POSITIONS['satellites']))
        gps_status = _nrm_gps_status(nf(NRM_POSITIONS['gps_status'], 'unknown'))
        battery_voltage = _safe_float(nf(NRM_POSITIONS['battery_voltage']))
        ignition = _nrm_ignition(nf(NRM_POSITIONS['ignition']))
        odometer = _safe_float(nf(NRM_POSITIONS['odometer']))

        # ── Resolve device ────────────────────────────────────────────────────
        device = self._resolve_device(imei, device_map)
        if not device:
            # Auto-create a device for this IMEI so data isn't lost
            device = self.env['ev.device'].create({
                'device_id_code': imei or f'UNKNOWN-{batch.id}',
                'imei': imei,
                'name': f'Auto-Imported Device ({imei})',
                'device_type': 'telematics',
                'status': 'active',
            })
            if imei:
                device_map[imei] = device

        return self.env['ev.telemetry.log'].create({
            'device_id': device.id,
            'import_batch_id': batch.id,
            'raw_import_source': self.device_filename or '',
            'timestamp': ts,
            'latitude': lat,
            'longitude': lon,
            'altitude': altitude,
            'heading': heading,
            'gps_status': gps_status,
            'satellites': satellites,
            'speed': speed,
            'odometer': odometer,
            'ignition': ignition,
            'battery_voltage': battery_voltage,
            'raw_payload': raw_payload,
        })

    def _import_clean_csv_record(self, get, device_map, batch):
        """Parse a cleaned CSV row with named columns into ev.telemetry.log."""
        imei = get('device_imei')
        date_str = get('date')
        time_str = get('time') or '000000'

        try:
            ts = _parse_nrm_datetime(
                date_str.replace('-', '').replace('/', ''),
                time_str.replace(':', '').replace('-', '')
            )
        except Exception:
            ts = datetime.now()

        lat_raw = get('latitude')
        lon_raw = get('longitude')
        # Handle DDMM.mmmm format if present
        if lat_raw and ('N' in lat_raw or 'S' in lat_raw or len(lat_raw) > 10):
            lat = _nrm_lat(lat_raw.replace('N', '').replace('S', '').strip(), 'N' if 'S' not in lat_raw else 'S')
        else:
            lat = _safe_float(lat_raw)

        if lon_raw and ('E' in lon_raw or 'W' in lon_raw or len(lon_raw) > 11):
            lon = _nrm_lon(lon_raw.replace('E', '').replace('W', '').strip(), 'E' if 'W' not in lon_raw else 'W')
        else:
            lon = _safe_float(lon_raw)

        gps_raw = get('gps_status').upper()
        gps_status = gps_raw if gps_raw in ('A', 'V', 'D') else 'unknown'

        device = self._resolve_device(imei, device_map)
        if not device:
            device = self.env['ev.device'].create({
                'device_id_code': imei or f'CSV-{batch.id}',
                'imei': imei,
                'name': f'Auto-Imported Device ({imei})',
                'device_type': 'telematics',
                'status': 'active',
            })
            if imei:
                device_map[imei] = device

        return self.env['ev.telemetry.log'].create({
            'device_id': device.id,
            'import_batch_id': batch.id,
            'raw_import_source': self.device_filename or '',
            'timestamp': ts,
            'latitude': lat,
            'longitude': lon,
            'altitude': _safe_float(get('altitude')),
            'heading': _safe_float(get('heading')),
            'gps_status': gps_status,
            'satellites': _safe_int(get('satellites')),
            'speed': _safe_float(get('speed')),
            'odometer': _safe_float(get('odometer')),
            'ignition': get('ignition').strip().lower() in ('1', 'true', 'on', 'yes'),
            'battery_voltage': _safe_float(get('battery_voltage')),
        })
