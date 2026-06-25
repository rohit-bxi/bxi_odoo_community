# -*- coding: utf-8 -*-
{
    'name': 'Aura Backend Theme - Free',
    'version': '19.0.1.0.0',
    'category': 'Themes/Backend',
    'summary': 'Free backend theme for Odoo 19',
    'description': """
Aura Backend Theme - Free
=========================
A clean, modern backend theme for Odoo 19.

Covers:
- Login page
- Top navigation bar
- App menu
- Form views
- List views
- Kanban views
- Buttons, badges, alerts
- Typography
    """,
    'author': 'LATI',
    'website': 'https://latitibabu.com',
    'support': 'support@latitibabu.com',
    'depends': ['web', 'base_setup', 'mail', 'auth_signup'],
    'data': [
        'views/web_assets.xml',
        'views/login_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'aura_backend_theme_free/static/src/scss/navbar.scss',

            'aura_backend_theme_free/static/src/webclient/navbar/navbar.js',
            'aura_backend_theme_free/static/src/webclient/navbar/navbar.xml',

            'aura_backend_theme_free/static/src/webclient/loading/loading_style.js',

            'aura_backend_theme_free/static/src/webclient/home_menu/apps_menu.xml',
            'aura_backend_theme_free/static/src/webclient/switch_company_menu/switch_company_menu.xml',

            'aura_backend_theme_free/static/src/scss/views.scss',

            'aura_backend_theme_free/static/src/views/discuss/discuss.xml',
            'aura_backend_theme_free/static/src/views/chatter/chatter.xml',
            'aura_backend_theme_free/static/src/views/activity_view/activity_view.scss',
            'aura_backend_theme_free/static/src/views/search_panel/search_panel.scss',
            'aura_backend_theme_free/static/src/views/discuss/discuss.scss',
            'aura_backend_theme_free/static/src/views/chatter/chatter.scss',
            'aura_backend_theme_free/static/src/views/others/others.scss',
            'aura_backend_theme_free/static/src/views/calendar_view/calendar_view.scss',
            'aura_backend_theme_free/static/src/views/chatter/chatter.js',

            'aura_backend_theme_free/static/src/scss/buttons.scss',
            'aura_backend_theme_free/static/src/scss/misc.scss',
            'aura_backend_theme_free/static/src/scss/rtl.scss',
        ],

        'web.assets_frontend': [
            'aura_backend_theme_free/static/src/scss/login.scss',
            'aura_backend_theme_free/static/src/scss/signup.scss',
            'aura_backend_theme_free/static/src/scss/rtl.scss',
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/theme_screenshot.png',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
