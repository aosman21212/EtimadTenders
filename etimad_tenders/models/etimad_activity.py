import logging
import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ETIMAD_BASE_URL = 'https://tenders.etimad.sa'
ACTIVITIES_URL  = f'{ETIMAD_BASE_URL}/Tender/GetMainActivitiesAsync'

# English labels for the 21 known Arabic sector IDs (for UI readability)
_SECTOR_LABELS = {
    1:  'Trade / Commerce',
    2:  'Construction & Contracting',
    3:  'Facilities O&M / Cleaning',
    4:  'Real Estate & Land',
    5:  'Industry, Mining & Recycling',
    6:  'Gas, Water & Energy',
    7:  'Mines, Petroleum & Quarries',
    8:  'Media, Publishing & Distribution',
    9:  'ICT / Telecommunications',
    10: 'Agriculture & Fishing',
    11: 'Healthcare',
    12: 'Education & Training',
    13: 'Employment & Recruitment',
    14: 'Security & Safety',
    15: 'Transport, Postal & Storage',
    16: 'Consulting Services',
    17: 'Tourism, Restaurants & Hotels',
    18: 'Finance, Insurance',
    19: 'Other Services',
}


class EtimadActivity(models.Model):
    _name        = 'etimad.activity'
    _description = 'Etimad Activity / Sector'
    _order       = 'activity_id_external'
    _rec_name    = 'display_name'

    # ── Fields ────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Arabic Name', required=True,
        help='Sector name as returned by the Etimad API (Arabic)'
    )
    name_en = fields.Char(
        string='English Label',
        help='English translation / hint for this sector'
    )
    activity_id_external = fields.Integer(
        string='Etimad Activity ID', index=True, required=True,
        help='Numeric ID used as TenderActivityId in API calls'
    )
    display_name = fields.Char(
        string='Activity', compute='_compute_display_name', store=True
    )

    # ── Unique constraint ─────────────────────────────────────────────────
    _activity_unique = models.Constraint(
        'UNIQUE(activity_id_external)',
        'An activity with this Etimad ID already exists.',
    )

    # ── Computed ──────────────────────────────────────────────────────────
    @api.depends('name', 'name_en', 'activity_id_external')
    def _compute_display_name(self):
        for rec in self:
            if rec.name_en:
                rec.display_name = f'[{rec.activity_id_external}] {rec.name_en} — {rec.name}'
            else:
                rec.display_name = f'[{rec.activity_id_external}] {rec.name}'

    # ── API sync ──────────────────────────────────────────────────────────
    @api.model
    def sync_from_api(self):
        """
        Fetch the sector list from Etimad and upsert into this model.
        Returns an ir.actions.client notification dict.
        """
        try:
            sess = requests.Session()
            sess.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'application/json, text/plain, */*',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'{ETIMAD_BASE_URL}/Tender/AllTendersForVisitor',
            })
            # warm-up to get anti-bot cookies
            sess.get(
                f'{ETIMAD_BASE_URL}/Tender/AllTendersForVisitor',
                timeout=15
            )
            resp = sess.get(ACTIVITIES_URL, timeout=15)
            resp.raise_for_status()
            activities = resp.json()
        except Exception as exc:
            raise UserError(
                _('Failed to fetch activity list from Etimad: %s') % exc
            )

        created = updated = 0
        for item in activities:
            raw_val  = item.get('value') or item.get('Value')
            raw_text = (item.get('text') or item.get('Text') or '').strip()
            if not raw_val or not raw_text:
                continue
            try:
                ext_id = int(raw_val)
            except (ValueError, TypeError):
                continue

            vals = {
                'name':                 raw_text,
                'activity_id_external': ext_id,
                'name_en':              _SECTOR_LABELS.get(ext_id, ''),
            }
            existing = self.search(
                [('activity_id_external', '=', ext_id)], limit=1
            )
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.create(vals)
                created += 1

        _logger.info(
            'Etimad activities synced: %d created, %d updated', created, updated
        )
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   _('Activities Synced'),
                'message': _(
                    'Synced %d sector(s) from Etimad '
                    '(%d new, %d updated).'
                ) % (created + updated, created, updated),
                'type':    'success',
            },
        }

    @api.model
    def action_sync_activities(self):
        """Button handler — wrapper around sync_from_api."""
        return self.sync_from_api()
