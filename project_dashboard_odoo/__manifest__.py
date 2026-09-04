# -*- coding: utf-8 -*-
##############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: AYANA KP @cybrosys(odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
{
    'name': 'Project Dashboard',
    'version': '19.0.3.0.0',
    'category': 'Extra Tools',
    'summary': """Access level aware project dashboard plus CXO, PMO, Manager and User PMO dashboards.""",
    'description': """A project dashboard that shows the projects,
     milestones, tasks and sub-tasks the connected user is allowed to see,
     according to the Administrator / Manager / User access levels defined by
     the Advanced Project Management System module.""",
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['project', 'hr_timesheet',
                'advanced_project_management_system'],
    'data': ['views/dashboard_views.xml'],
    'assets': {
        'web.assets_backend': [
            'project_dashboard_odoo/static/src/js/dashboard.js',
            'project_dashboard_odoo/static/src/js/pmo_dashboard.js',
            'project_dashboard_odoo/static/src/css/dashboard.css',
            'project_dashboard_odoo/static/src/xml/dashboard_templates.xml',
            'project_dashboard_odoo/static/src/xml/pmo_dashboard_templates.xml',
            'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/2.9.4/Chart.js'
        ]},
    'images': ['static/description/banner.png'],
    'license': 'AGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}

