# -*- coding: utf-8 -*-
{
    'name': 'Etimad Tenders',
    'version': '17.0.1.0.0',
    'summary': 'Sync Saudi Etimad government tenders into Odoo and convert them to CRM opportunities',
    'description': """
Etimad Tenders
===============
Pulls government tenders from the Saudi Etimad platform (tenders.etimad.sa)
into Odoo and lets you convert any tender into a CRM opportunity in one click.

Rebuilt for Odoo 17, with the sync structure (endpoint candidates, field
names, cron/wizard shape) confirmed by the module's original author. The
HTTP client still needs a confirmed-working endpoint from this specific
deployment's network (see models/etimad_tender.py, ENDPOINT_CANDIDATES) --
search for "ADJUST" in the code for every remaining best-guess spot.
""",
    'category': 'Sales/CRM',
    'author': 'Abdulkaraim Osman, Bab International Corp For Specialized Services',
    'website': 'https://leapai.ai',
    'support': 'sales@leapai.ai',
    'maintainer': 'LEAP AI',
    'depends': ['crm', 'calendar', 'mail'],
    'images': ['static/description/screenshot1.png'],
    'data': [
        'security/etimad_security.xml',
        'security/ir.model.access.csv',
        'data/etimad_activity_data.xml',
        'data/ir_cron_data.xml',
        'views/etimad_tender_views.xml',
        'views/etimad_activity_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/etimad_fetch_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}
