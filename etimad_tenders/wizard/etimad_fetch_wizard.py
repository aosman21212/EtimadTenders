# -*- coding: utf-8 -*-
from odoo import fields, models


class EtimadFetchWizard(models.TransientModel):
    _name = 'etimad.fetch.wizard'
    _description = 'Fetch Etimad Tenders Now'

    max_pages = fields.Integer(
        string='Pages to Fetch', default=1,
        help='How many pages to pull per activity in this manual run '
             '(overrides the Settings default for this run only).',
    )
    page_size = fields.Integer(
        string='Page Size', default=50,
        help='Number of tenders requested per page (maximum 100).',
    )
    activity_ids = fields.Many2many(
        'etimad.activity', string='Activities',
        help='Restrict this run to specific activities/sectors. Leave empty to fetch all.',
    )
    tender_name = fields.Char(string='Tender Name Contains')
    agency_name = fields.Char(string='Agency Contains')

    def action_fetch_now(self):
        self.ensure_one()
        Tender = self.env['etimad.tender']
        ext_ids = [ext_id for ext_id in self.activity_ids.mapped('ext_id') if ext_id]
        kwargs = {
            'pages': self.max_pages or 1,
            'page_size': self.page_size or 50,
            'name_filter': self.tender_name or None,
            'agency_filter': self.agency_name or None,
        }

        if ext_ids:
            total = {'created': 0, 'updated': 0, 'errors': []}
            for ext_id in ext_ids:
                result = Tender.fetch_tenders(ext_id=ext_id, **kwargs)
                total['created'] += result['created']
                total['updated'] += result['updated']
                total['errors'].extend(result['errors'])
        else:
            total = Tender.fetch_tenders(**kwargs)

        message = 'Sync finished: %s created, %s updated, %s error(s).' % (
            total['created'], total['updated'], len(total['errors']))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Etimad Tenders',
                'message': message,
                'type': 'warning' if total['errors'] else 'success',
                'sticky': True,
            },
        }
