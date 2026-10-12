# -*- coding: utf-8 -*-
import logging

import requests

from odoo import fields, models

_logger = logging.getLogger(__name__)

# ADJUST: real Etimad endpoint that lists activities/sectors, once known.
DEFAULT_ACTIVITIES_ENDPOINT = 'https://tenders.etimad.sa/Tender/AllActivitiesForVisitor'


class EtimadActivity(models.Model):
    """Activity/sector classification for tenders (model name confirmed as
    etimad.activity). The real Etimad platform exposes ~19 fixed activities;
    this is a plain master-data model (seeded with a placeholder list in
    data/etimad_activity_data.xml) rather than a hardcoded selection, so it
    stays correct once synced for real via sync_from_api().
    """
    _name = 'etimad.activity'
    _description = 'Etimad Activity / Sector'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    ext_id = fields.Char(
        string='Etimad Activity ID', index=True,
        help='External activity/sector id on the Etimad platform, used to filter a sync to '
             'specific activities. Leave empty if unknown.',
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'An activity with this name already exists.'),
    ]

    def sync_from_api(self):
        """Pull the real activity/sector list from Etimad and upsert it here.

        ADJUST: the real activities endpoint/response shape is unknown; this
        is a best-effort placeholder mirroring etimad.tender's HTTP client,
        kept isolated here so wiring in the real endpoint later is a small,
        contained change.
        """
        from .etimad_tender import DEFAULT_USER_AGENT, REQUEST_TIMEOUT  # local import to avoid a hard cycle

        icp = self.env['ir.config_parameter'].sudo()
        warmup_url = icp.get_param('etimad_tenders.warmup_url')
        session_cookie = icp.get_param('etimad_tenders.session_cookie')

        session = requests.Session()
        session.headers.update({'User-Agent': DEFAULT_USER_AGENT, 'Accept': 'application/json'})
        if session_cookie:
            session.headers['Cookie'] = session_cookie
        if warmup_url:
            try:
                session.get(warmup_url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                _logger.warning('Etimad Activities: warm-up GET failed: %s', exc)

        try:
            response = session.get(DEFAULT_ACTIVITIES_ENDPOINT, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            _logger.warning('Etimad Activities: sync_from_api failed (endpoint unconfirmed): %s', exc)
            return {'created': 0, 'updated': 0, 'errors': [str(exc)]}

        records = payload if isinstance(payload, list) else payload.get('data', [])
        created = updated = 0
        for rec in records:
            ext_id = str(rec.get('id') or rec.get('activityId') or '')
            name = rec.get('name') or rec.get('activityName')
            if not ext_id or not name:
                continue
            existing = self.search([('ext_id', '=', ext_id)], limit=1)
            if existing:
                existing.write({'name': name})
                updated += 1
            else:
                self.create({'ext_id': ext_id, 'name': name})
                created += 1
        return {'created': created, 'updated': updated, 'errors': []}
