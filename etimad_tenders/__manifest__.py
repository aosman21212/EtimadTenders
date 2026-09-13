{
    'name': 'Etimad Tenders',
    'version': '19.0.1.2.1',
    'summary': 'Fetch Saudi government tenders from the Etimad platform',
    'description': """
        Fetches public government tenders from the Saudi Etimad platform
        (https://tenders.etimad.sa) and stores them in Odoo.

        Features:
        - Automatic daily fetch via scheduled action
        - Manual fetch wizard with keyword / agency filters
        - Convert any tender to a CRM opportunity in one click
        - Smart session warm-up to bypass bot-protection
        - Configurable session cookie, page size, and API endpoint
    """,
    'category': 'Sales/CRM',
    'author': 'Custom',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/etimad_activity_views.xml',
        'views/etimad_tender_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/fetch_wizard_views.xml',
        'views/menu.xml',
    ],
    'images': [
        'images/main_screenshot.png',
        'static/description/screen_list.png',
        'static/description/screen_form.png',
        'static/description/screen_wizard.png',
        'static/description/screen_config.png',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
