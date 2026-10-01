# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api
from odoo.exceptions import AccessError

TREND_SERIES = [
    # key, model, label, colour
    ('queries', 'antitrust.query', 'Legal Queries', '#4f6bed'),
    ('incidents', 'antitrust.incident', 'Meeting Incidents', '#e8833a'),
    ('interactions', 'antitrust.interaction', 'Competitor Interactions', '#14a38b'),
    ('cases', 'antitrust.case', 'Compliance Cases', '#d64545'),
]


class AntitrustDashboard(models.TransientModel):
    """Compliance overview for the CPO.

    The backend client action (``bxi_compliance_dashboard``) reads everything through
    :meth:`get_dashboard_data` and opens every number through :meth:`open_kpi`, so the
    domains below are the single definition of what each figure counts.
    """
    _name = 'antitrust.dashboard'
    _description = 'Compliance Dashboard'

    ack_rate = fields.Float(string='Policies Acknowledged (%)', digits=(16, 2), compute='_compute_counts')
    ack_overdue = fields.Integer(string='Overdue Acknowledgements', compute='_compute_counts')
    open_queries = fields.Integer(string='Open Queries', compute='_compute_counts')
    open_incidents = fields.Integer(string='Open Incidents', compute='_compute_counts')
    interactions_to_review = fields.Integer(string='Interactions to Review', compute='_compute_counts')
    interactions_without_confirmation = fields.Integer(string='Awaiting Post-event Confirmation',
                                                       compute='_compute_counts')
    rfp_without_declaration = fields.Integer(string='RFPs Without Valid Declaration', compute='_compute_counts')
    declarations_to_approve = fields.Integer(string='Bid Declarations to Approve', compute='_compute_counts')
    open_cases = fields.Integer(string='Open Cases', compute='_compute_counts')

    def _compute_display_name(self):
        for dashboard in self:
            dashboard.display_name = self.env._('Compliance Dashboard')

    # ------------------------------------------------------------------
    # Definitions
    # ------------------------------------------------------------------
    @api.model
    def _check_cpo(self):
        if not self.env.su and not self.env.user.has_group('bxi_hr_policy.group_policy_cpo'):
            raise AccessError(self.env._("The compliance dashboard is reserved to the Compliance / CPO team."))

    @api.model
    def _rfp_ids(self, states=('missing', 'outdated')):
        leads = self.env['crm.lead'].sudo().search([
            ('is_tender_rfp', '=', True), ('active', '=', True), ('stage_id.is_won', '=', False)])
        return leads.filtered(lambda lead: lead.bid_compliance_state in states).ids

    @api.model
    def _kpi_domains(self):
        """key -> (model, domain, list title) of every clickable figure."""
        _ = self.env._
        today = fields.Date.context_today(self)
        current = [('is_current_version', '=', True), ('state', '!=', 'cancelled')]
        return {
            'acks': ('hr.policy.acknowledgement', current, _("Policy Acknowledgements")),
            'acks_pending': ('hr.policy.acknowledgement', current + [('state', '=', 'pending')],
                             _("Pending Acknowledgements")),
            'acks_overdue': ('hr.policy.acknowledgement', [('state', '=', 'overdue')], _("Overdue")),
            'queries': ('antitrust.query', [('state', '=', 'submitted')], _("Open Queries")),
            'queries_urgent': ('antitrust.query', [('state', '=', 'submitted'), ('urgency', '=', 'urgent')],
                               _("Urgent Queries")),
            'incidents': ('antitrust.incident', [('state', 'in', ('reported', 'under_review'))],
                          _("Open Incidents")),
            'incidents_new': ('antitrust.incident', [('state', '=', 'reported')], _("Incidents Not Yet Reviewed")),
            'interactions': ('antitrust.interaction', [('state', '=', 'cpo_review')], _("Interactions to Review")),
            'interactions_high': ('antitrust.interaction', [('state', '=', 'cpo_review'), ('risk_level', '=', 'high')],
                                  _("High-Risk Interactions to Review")),
            'interactions_unconfirmed': ('antitrust.interaction',
                                         [('state', '=', 'cleared'), ('event_date', '<', today)],
                                         _("Awaiting Confirmation")),
            'rfps': ('crm.lead', [('id', 'in', self._rfp_ids())], _("RFPs Without Declaration")),
            'rfps_missing': ('crm.lead', [('id', 'in', self._rfp_ids(('missing',)))], _("Declaration Missing")),
            'rfps_outdated': ('crm.lead', [('id', 'in', self._rfp_ids(('outdated',)))], _("Declaration Outdated")),
            'declarations': ('antitrust.bid.declaration', [('state', '=', 'to_approve')],
                             _("Declarations to Approve")),
            'cases': ('antitrust.case', [('state', '=', 'open')], _("Open Cases")),
            'cases_followup': ('antitrust.case', [('state', '=', 'open'), ('follow_up_date', '<', today)],
                               _("Cases With an Overdue Follow-up")),
        }

    @api.model
    def _count(self, key, domains=None):
        model, domain, _title = (domains or self._kpi_domains())[key]
        return self.env[model].sudo().search_count(domain)

    @api.depends_context('uid')
    def _compute_counts(self):
        domains = self._kpi_domains()
        acks = self._count('acks', domains)
        done = self.env['hr.policy.acknowledgement'].sudo().search_count(
            domains['acks'][1] + [('state', 'in', ('acknowledged', 'waived'))])
        values = {
            'ack_rate': 100.0 * done / acks if acks else 0.0,
            'ack_overdue': self._count('acks_overdue', domains),
            'open_queries': self._count('queries', domains),
            'open_incidents': self._count('incidents', domains),
            'interactions_to_review': self._count('interactions', domains),
            'interactions_without_confirmation': self._count('interactions_unconfirmed', domains),
            'rfp_without_declaration': self._count('rfps', domains),
            'declarations_to_approve': self._count('declarations', domains),
            'open_cases': self._count('cases', domains),
        }
        for rec in self:
            rec.update(values)

    # ------------------------------------------------------------------
    # Client action API
    # ------------------------------------------------------------------
    @api.model
    def _action(self, model, domain, name, views='list,form'):
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': views, 'views': [(False, view) for view in views.split(',')], 'domain': domain}

    @api.model
    def open_kpi(self, key):
        self._check_cpo()
        model, domain, title = self._kpi_domains()[key]
        return self._action(model, domain, title)

    @api.model
    def open_trend(self, series_key, month_start):
        """Records of one series created in the month starting on ``month_start`` (YYYY-MM-DD)."""
        self._check_cpo()
        series = {key: (model, label) for key, model, label, _colour in TREND_SERIES}
        model, label = series[series_key]
        start = fields.Date.to_date(month_start)
        domain = [('create_date', '>=', start), ('create_date', '<', start + relativedelta(months=1))]
        if model != 'antitrust.case':
            domain.append(('state', '!=', 'draft'))
        return self._action(model, domain, '%s - %s' % (self.env._(label), start.strftime('%B %Y')))

    @api.model
    def open_policy(self, policy_id, state=False):
        self._check_cpo()
        domain = self._kpi_domains()['acks'][1] + [('policy_id', '=', policy_id)]
        if state:
            domain.append(('state', '=', state))
        policy = self.env['hr.company.policy'].sudo().browse(policy_id)
        return self._action('hr.policy.acknowledgement', domain, policy.display_name)

    @api.model
    def get_dashboard_data(self, months=6):
        """Everything the dashboard shows, in one call."""
        self._check_cpo()
        _ = self.env._
        months = max(1, min(int(months or 6), 24))
        domains = self._kpi_domains()
        count = {key: self._count(key, domains) for key in domains}
        Ack = self.env['hr.policy.acknowledgement'].sudo()
        acks_done = Ack.search_count(domains['acks'][1] + [('state', 'in', ('acknowledged', 'waived'))])
        ack_rate = round(100.0 * acks_done / count['acks'], 1) if count['acks'] else 0.0

        def tone(value, danger=False):
            return 'success' if not value else ('danger' if danger else 'warning')

        kpis = [
            {
                'key': 'acks', 'title': _("Policy Acknowledgement"), 'icon': 'fa-check-square-o',
                'value': ack_rate if count['acks'] else None, 'is_rate': True,
                'caption': _("%(done)s of %(total)s current acknowledgements", done=acks_done, total=count['acks'])
                if count['acks'] else _("No acknowledgement requested yet"),
                'tone': 'success' if ack_rate >= 90 or not count['acks'] else ('warning' if ack_rate >= 60 else 'danger'),
                'chips': [
                    {'key': 'acks_pending', 'label': _("pending"), 'value': count['acks_pending'], 'tone': 'info'},
                    {'key': 'acks_overdue', 'label': _("overdue"), 'value': count['acks_overdue'],
                     'tone': tone(count['acks_overdue'], True)},
                ],
            },
            {
                'key': 'queries', 'title': _("Legal Queries Waiting"), 'icon': 'fa-question-circle',
                'value': count['queries'], 'caption': _("Questions waiting for an answer from Legal"),
                'tone': tone(count['queries'], count['queries_urgent']),
                'chips': [{'key': 'queries_urgent', 'label': _("urgent"), 'value': count['queries_urgent'],
                           'tone': tone(count['queries_urgent'], True)}],
            },
            {
                'key': 'incidents', 'title': _("Open Meeting Incidents"), 'icon': 'fa-exclamation-triangle',
                'value': count['incidents'], 'caption': _("Reported or under review"),
                'tone': tone(count['incidents'], True),
                'chips': [{'key': 'incidents_new', 'label': _("not yet reviewed"), 'value': count['incidents_new'],
                           'tone': tone(count['incidents_new'], True)}],
            },
            {
                'key': 'interactions', 'title': _("Competitor Interactions"), 'icon': 'fa-handshake-o',
                'value': count['interactions'], 'caption': _("Declarations waiting for CPO review"),
                'tone': tone(count['interactions'], count['interactions_high']),
                'chips': [
                    {'key': 'interactions_high', 'label': _("high risk"), 'value': count['interactions_high'],
                     'tone': tone(count['interactions_high'], True)},
                    {'key': 'interactions_unconfirmed', 'label': _("awaiting post-event confirmation"),
                     'value': count['interactions_unconfirmed'], 'tone': tone(count['interactions_unconfirmed'])},
                ],
            },
            {
                'key': 'rfps', 'title': _("RFP / Tender Compliance"), 'icon': 'fa-file-text-o',
                'value': count['rfps'], 'caption': _("Open opportunities without a valid bid declaration"),
                'tone': tone(count['rfps'], True),
                'chips': [
                    {'key': 'rfps_missing', 'label': _("missing"), 'value': count['rfps_missing'],
                     'tone': tone(count['rfps_missing'], True)},
                    {'key': 'rfps_outdated', 'label': _("outdated"), 'value': count['rfps_outdated'],
                     'tone': tone(count['rfps_outdated'])},
                    {'key': 'declarations', 'label': _("to approve"), 'value': count['declarations'],
                     'tone': tone(count['declarations'])},
                ],
            },
            {
                'key': 'cases', 'title': _("Open Compliance Cases"), 'icon': 'fa-gavel',
                'value': count['cases'], 'caption': _("Investigations in progress"),
                'tone': tone(count['cases'], count['cases_followup']),
                'chips': [{'key': 'cases_followup', 'label': _("follow-up overdue"), 'value': count['cases_followup'],
                           'tone': tone(count['cases_followup'], True)}],
            },
        ]
        attention = (count['acks_overdue'] + count['queries'] + count['incidents'] + count['interactions']
                     + count['interactions_unconfirmed'] + count['rfps'] + count['declarations']
                     + count['cases_followup'])
        return {
            'kpis': kpis,
            'attention': attention,
            'urgent': count['queries_urgent'] + count['interactions_high'] + count['incidents_new']
                      + count['acks_overdue'] + count['cases_followup'],
            'trend': self._trend_data(months),
            'policies': self._policy_data(),
            'worklist': self._worklist(),
            'outcomes': self._outcome_data(months),
            'months': months,
            'refreshed': fields.Datetime.to_string(fields.Datetime.now()),
        }

    @api.model
    def _trend_data(self, months):
        today = fields.Date.context_today(self)
        first = today.replace(day=1) - relativedelta(months=months - 1)
        starts = [first + relativedelta(months=i) for i in range(months)]
        series = []
        for key, model, label, colour in TREND_SERIES:
            domain = [('create_date', '>=', first)]
            if model != 'antitrust.case':
                domain.append(('state', '!=', 'draft'))
            groups = self.env[model].sudo()._read_group(domain, ['create_date:month'], ['__count'])
            by_month = {month.date().replace(day=1) if hasattr(month, 'date') else month: total
                        for month, total in groups if month}
            series.append({'key': key, 'label': self.env._(label), 'colour': colour,
                           'values': [by_month.get(start, 0) for start in starts]})
        return {
            'months': [{'start': fields.Date.to_string(start), 'label': start.strftime('%b %y')} for start in starts],
            'series': series,
        }

    @api.model
    def _policy_data(self, limit=6):
        Ack = self.env['hr.policy.acknowledgement'].sudo()
        base = self._kpi_domains()['acks'][1]
        totals = {policy.id: (policy, total) for policy, total in Ack._read_group(base, ['policy_id'], ['__count'])
                  if policy}
        done = dict(Ack._read_group(base + [('state', 'in', ('acknowledged', 'waived'))], ['policy_id'], ['__count']))
        overdue = dict(Ack._read_group(base + [('state', '=', 'overdue')], ['policy_id'], ['__count']))
        rows = []
        for policy, total in totals.values():
            acknowledged = done.get(policy, 0)
            rows.append({'id': policy.id, 'name': policy.display_name, 'total': total, 'done': acknowledged,
                         'overdue': overdue.get(policy, 0), 'rate': round(100.0 * acknowledged / total, 1)})
        return sorted(rows, key=lambda row: row['rate'])[:limit]

    @api.model
    def _outcome_data(self, months):
        since = fields.Date.context_today(self).replace(day=1) - relativedelta(months=months - 1)
        Case = self.env['antitrust.case'].sudo()
        labels = dict(Case._fields['outcome']._description_selection(self.env))
        groups = Case._read_group([('state', '=', 'closed'), ('closed_date', '>=', since)], ['outcome'], ['__count'])
        return [{'key': outcome or 'none', 'label': labels.get(outcome, self.env._("Not Set")), 'count': total}
                for outcome, total in sorted(groups, key=lambda g: -g[1])]

    @api.model
    def _worklist(self, limit=12):
        """The oldest / most critical open items, across every compliance flow."""
        _ = self.env._
        today = fields.Date.context_today(self)
        items = []

        def add(records, kind, title, priority, when):
            for rec in records:
                day = when(rec)
                day = day.date() if hasattr(day, 'date') else day
                text = (title(rec) or '').strip()
                items.append({
                    'model': rec._name, 'id': rec.id, 'kind': kind, 'reference': rec.display_name,
                    'title': text.splitlines()[0][:90] if text else '',
                    'employee': rec.employee_id.name if 'employee_id' in rec._fields
                    else rec.declared_by_id.name if 'declared_by_id' in rec._fields else '',
                    'date': fields.Date.to_string(day) if day else False,
                    'age': (today - day).days if day else 0,
                    'priority': priority(rec),
                })

        env = self.env
        add(env['antitrust.query'].sudo().search([('state', '=', 'submitted')], order='create_date', limit=limit),
            _("Legal Query"), lambda r: r.subject, lambda r: 'high' if r.urgency == 'urgent' else 'normal',
            lambda r: r.create_date)
        add(env['antitrust.interaction'].sudo().search([('state', '=', 'cpo_review')], order='event_date', limit=limit),
            _("Interaction"), lambda r: r.organisations,
            lambda r: 'high' if r.risk_level == 'high' else 'normal', lambda r: r.create_date)
        add(env['antitrust.incident'].sudo().search([('state', 'in', ('reported', 'under_review'))],
                                                    order='incident_date', limit=limit),
            _("Incident"), lambda r: r.meeting_title, lambda r: 'high' if r.state == 'reported' else 'normal',
            lambda r: r.incident_date)
        add(env['antitrust.bid.declaration'].sudo().search([('state', '=', 'to_approve')], order='create_date',
                                                           limit=limit),
            _("Bid Declaration"), lambda r: r.lead_id.name, lambda r: 'normal', lambda r: r.create_date)
        add(env['antitrust.case'].sudo().search([('state', '=', 'open'), ('follow_up_date', '<', today)],
                                                order='follow_up_date', limit=limit),
            _("Case Follow-up"), lambda r: r.summary, lambda r: 'high', lambda r: r.follow_up_date)
        items.sort(key=lambda item: (item['priority'] != 'high', -item['age']))
        return items[:limit]

    # ------------------------------------------------------------------
    # Buttons (kept for the form view API and existing integrations)
    # ------------------------------------------------------------------
    def _open(self, key):
        model, domain, title = self._kpi_domains()[key]
        return self._action(model, domain, title)

    def action_open_overdue(self):
        return self._open('acks_overdue')

    def action_open_queries(self):
        return self._open('queries')

    def action_open_incidents(self):
        return self._open('incidents')

    def action_open_interactions(self):
        return self._open('interactions')

    def action_open_unconfirmed(self):
        return self._open('interactions_unconfirmed')

    def action_open_rfps(self):
        return self._open('rfps')

    def action_open_declarations(self):
        return self._open('declarations')

    def action_open_cases(self):
        return self._open('cases')
