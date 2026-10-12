# -*- coding: utf-8 -*-
"""
HTTP client for the Saudi Etimad tenders platform.

CONFIRMED against a live response from this container (2026-10-11), endpoint
GET https://tenders.etimad.sa/Tender/AllSupplierTendersForVisitorAsync returns
JSON objects shaped like:
    {
      "tenderId": 1111628, "referenceNumber": "261039003772",
      "tenderName": "...", "agencyName": "...", "branchName": "...",
      "tenderActivityId": 1609, "tenderActivityName": "...",
      "tenderIdString": "Lg4vkDIPy1mgzQoN0 cE4w==",   # used in the STenderId details link
      "lastOfferPresentationDate": "2026-11-10T09:59:00",   # submission deadline
      "offersOpeningDate": "2026-11-11T10:00:00",           # envelope opening
      "createdAt": "0001-01-01T00:00:00",   # .NET sentinel: NOT a real publish date
      ... no estimated/tender value field at all on this listing endpoint ...
    }
No estimated-value field exists on this endpoint's payload (it's a listing
endpoint; the budget estimate, if public at all, would live on the per-tender
details page) - estimated_value stays 0 until/unless that is implemented
separately. Still unconfirmed / best-effort:
  * whether the 3 other candidate endpoints are needed/shaped the same way;
  * the query/body param name used to filter a fetch by activity ("ActivityId").
Search for "ADJUST" for every remaining best-guess spot.
"""
import logging
import re
from urllib.parse import quote

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_WARMUP_URL = 'https://tenders.etimad.sa/Tender/AllTendersForVisitor'
DETAILS_URL_TEMPLATE = 'https://tenders.etimad.sa/Tender/DetailsForVisitor?STenderId=%s'

# Confirmed by the user: try these in order, first one returning valid JSON wins.
ENDPOINT_CANDIDATES = [
    ('GET', 'https://tenders.etimad.sa/Tender/AllSupplierTendersForVisitorAsync'),  # confirmed-working one
    ('GET', 'https://tenders.etimad.sa/Tender/AllTendersForVisitorAsync'),
    ('POST', 'https://tenders.etimad.sa/Tender/AllTendersForVisitorAsync'),
    ('POST', 'https://tenders.etimad.sa/Tender/GetAllTendersForVisitor'),
]

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)
DEFAULT_HEADERS = {
    'User-Agent': DEFAULT_USER_AGENT,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ar,en;q=0.9',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'X-Requested-With': 'XMLHttpRequest',
}
REQUEST_TIMEOUT = 30


class EtimadTender(models.Model):
    _name = 'etimad.tender'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Etimad Tender'
    _order = 'submission_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Tender Title', required=True, tracking=True)
    tender_id_external = fields.Char(
        string='Etimad Tender ID', required=True, index=True, tracking=True,
        help='Unique tender identifier on the Etimad platform, used to avoid duplicates on sync.',
    )
    reference = fields.Char(string='Reference Number', tracking=True)
    agency_name = fields.Char(string='Government Agency', tracking=True)
    branch_name = fields.Char(string='Agency Branch')
    activity_id = fields.Many2one('etimad.activity', string='Activity / Sector')
    estimated_value = fields.Monetary(string='Estimated Value', currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.ref('base.SAR', raise_if_not_found=False)
        or self.env.company.currency_id,
    )
    publish_date = fields.Date(string='Publication Date')
    submission_date = fields.Datetime(string='Submission Deadline', tracking=True)
    envelope_date = fields.Datetime(string='Envelope Opening Date')
    tender_url = fields.Char(string='Link on Etimad')
    state = fields.Selection([
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('converted', 'Converted to Opportunity'),
        ('closed', 'Closed'),
        ('expired', 'Expired'),
    ], string='Status', default='new', tracking=True)
    opportunity_id = fields.Many2one('crm.lead', string='CRM Opportunity', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    raw_data = fields.Text(string='Last Raw API Payload', readonly=True, copy=False)
    last_synced_at = fields.Datetime(string='Last Synced', readonly=True, copy=False)

    _sql_constraints = [
        ('tender_id_external_company_uniq', 'unique(tender_id_external, company_id)',
         'A tender with this Etimad ID already exists for this company.'),
    ]

    # ------------------------------------------------------------------
    # CRM conversion
    # ------------------------------------------------------------------
    def action_convert_to_opportunity(self):
        self.ensure_one()
        if self.opportunity_id:
            return self._open_opportunity_action()
        lead = self.env['crm.lead'].create({
            'name': self.name or self.reference or self.tender_id_external,
            'type': 'opportunity',
            'partner_name': self.agency_name,
            'expected_revenue': self.estimated_value,
            'date_deadline': self.submission_date and fields.Datetime.to_datetime(self.submission_date).date(),
            'description': _(
                'Imported from Etimad tender %(ref)s (%(agency)s).\nLink: %(url)s'
            ) % {
                'ref': self.reference or self.tender_id_external,
                'agency': self.agency_name or '',
                'url': self.tender_url or '',
            },
        })
        self.write({'opportunity_id': lead.id, 'state': 'converted'})
        self.message_post(body=_('Converted to opportunity %s.') % lead.name)
        return self._open_opportunity_action()

    def _open_opportunity_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.opportunity_id.id,
            'target': 'current',
        }

    def action_open_on_etimad(self):
        self.ensure_one()
        if not self.tender_url:
            raise UserError(_('This tender has no Etimad link.'))
        return {
            'type': 'ir.actions.act_url',
            'url': self.tender_url,
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # HTTP client / sync
    # ------------------------------------------------------------------
    def _get_sync_params(self):
        """Read the configurable connection parameters from Settings."""
        icp = self.env['ir.config_parameter'].sudo()
        ext_ids_str = icp.get_param('etimad_tenders.activity_ext_ids', '') or ''
        return {
            'api_url': icp.get_param('etimad_tenders.api_url') or False,
            'warmup_url': icp.get_param('etimad_tenders.warmup_url', DEFAULT_WARMUP_URL),
            'page_size': int(icp.get_param('etimad_tenders.page_size', 50) or 50),
            'cron_pages': int(icp.get_param('etimad_tenders.cron_pages', 5) or 5),
            'session_cookie': icp.get_param('etimad_tenders.session_cookie', False),
            'activity_ext_ids': [x for x in ext_ids_str.split(',') if x],
        }

    def _get_http_session(self, warmup_url=None, session_cookie=None):
        """Build a requests.Session, optionally pre-warmed with a plain GET.

        This is the "smart warm-up GET" bot-protection workaround: a plain
        browser-like GET on the public tenders page first, to pick up any
        F5 TrafficShield cookies, unless a manual session cookie is already
        configured (etimad_tenders.session_cookie) - in which case we skip
        the warm-up and rely on that cookie directly.
        """
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        if session_cookie:
            session.headers['Cookie'] = session_cookie
        elif warmup_url:
            try:
                session.get(warmup_url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                _logger.warning('Etimad Tenders: warm-up GET to %s failed: %s', warmup_url, exc)
        return session

    @staticmethod
    def _extract_records(payload):
        if isinstance(payload, list):
            return payload
        for key in ('data', 'items', 'results', 'tenders', 'list'):
            if isinstance(payload, dict) and isinstance(payload.get(key), list):
                return payload[key]
        return []

    def _call_endpoint(self, session, method, url, page_number, page_size, ext_id=None):
        """Call one candidate endpoint for one page. Raises on HTTP error or
        non-JSON response; returns a (possibly empty) list of raw tender dicts
        otherwise -- an empty list is treated as a VALID response shape, used
        by _resolve_endpoint to decide an endpoint "works".
        """
        query_params = {'PageNumber': page_number, 'PageSize': page_size}
        if ext_id:
            query_params['ActivityId'] = ext_id  # ADJUST: real filter param name, once known
        if method == 'GET':
            response = session.get(url, params=query_params, timeout=REQUEST_TIMEOUT)
        else:
            response = session.post(url, json=query_params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()  # raises ValueError (caught by callers) if not JSON
        return self._extract_records(payload)

    def _resolve_endpoint(self, session, page_size, ext_id=None):
        """Try the configured custom endpoint, or each candidate in order,
        until one returns parseable JSON. Returns (method, url, page_1_records).
        """
        icp = self.env['ir.config_parameter'].sudo()
        custom_url = icp.get_param('etimad_tenders.api_url')
        candidates = [('GET', custom_url)] if custom_url else ENDPOINT_CANDIDATES

        last_exc = None
        for method, url in candidates:
            try:
                records = self._call_endpoint(session, method, url, 1, page_size, ext_id=ext_id)
                _logger.info('Etimad Tenders: using endpoint %s %s', method, url)
                return method, url, records
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                continue
        raise UserError(_('No working Etimad endpoint found (tried %(n)d candidate(s)): %(err)s') % {
            'n': len(candidates), 'err': last_exc,
        })

    def test_connection(self):
        """Used by the Settings 'Test Connection' button."""
        params = self._get_sync_params()
        session = self._get_http_session(params['warmup_url'], params['session_cookie'])
        self._resolve_endpoint(session, page_size=1)
        return True

    @staticmethod
    def _coalesce(rec, *keys):
        for key in keys:
            value = rec.get(key)
            if value not in (None, ''):
                return value
        return False

    @staticmethod
    def _parse_iso_datetime(value):
        """Parse an ISO-ish datetime string (e.g. "2026-11-10T09:59:00",
        optionally with fractional seconds and/or a +HH:MM offset, as seen
        from the real API) into Odoo's 'YYYY-MM-DD HH:MM:SS' string. Returns
        False for an empty value or a .NET default/unset sentinel date
        (0001-01-01), which is not a real date.
        """
        if not value or not isinstance(value, str):
            return False
        value = value.strip()
        if value.startswith('0001-01-01'):
            return False
        value = value.replace('T', ' ')
        value = value.split('.')[0]  # drop fractional seconds
        value = re.sub(r'[+-]\d{2}:\d{2}$', '', value)  # drop a trailing UTC offset like +03:00
        return value[:19] or False

    @classmethod
    def _parse_iso_date(cls, value):
        dt = cls._parse_iso_datetime(value)
        return dt[:10] if dt else False

    def _prepare_vals_from_api(self, rec):
        """Map one raw API tender dict to etimad.tender field values.

        Confirmed field names (from AllSupplierTendersForVisitorAsync) are
        tried first; older best-guess fallbacks are kept after them in case
        a different candidate endpoint is used instead. ADJUST if that
        proves wrong once logged (see the class docstring).
        """
        activity_name = self._coalesce(rec, 'tenderActivityName', 'activityName', 'sectorName', 'activityDescription')
        activity_ext_id = self._coalesce(rec, 'tenderActivityId', 'activityId', 'sectorId')
        activity_id = False
        if activity_name or activity_ext_id:
            domain = [('ext_id', '=', str(activity_ext_id))] if activity_ext_id else [('name', '=', activity_name)]
            activity = self.env['etimad.activity'].search(domain, limit=1)
            if not activity:
                activity = self.env['etimad.activity'].create({
                    'name': activity_name or ('Activity %s' % activity_ext_id),
                    'ext_id': str(activity_ext_id) if activity_ext_id else False,
                })
            activity_id = activity.id

        tender_id_external = self._coalesce(rec, 'tenderId', 'id', 'referenceNumber')
        tender_id_string = self._coalesce(rec, 'tenderIdString')  # the "STenderId" used in the details link
        return {
            'tender_id_external': str(tender_id_external),
            'name': self._coalesce(rec, 'tenderName', 'title', 'name') or str(tender_id_external),
            'reference': self._coalesce(rec, 'referenceNumber', 'tenderNumber', 'reference'),
            'agency_name': self._coalesce(rec, 'agencyName', 'agency', 'organizationName'),
            'branch_name': self._coalesce(rec, 'branchName', 'branch'),
            'activity_id': activity_id,
            # No estimated-value field exists on this listing endpoint's payload - stays 0
            # until/unless a per-tender details fetch is implemented. ADJUST if that changes.
            'estimated_value': self._coalesce(rec, 'tenderValue', 'estimatedValue', 'value') or 0.0,
            'publish_date': self._parse_iso_date(self._coalesce(rec, 'publishDate', 'publicationDate')),
            'submission_date': self._parse_iso_datetime(
                self._coalesce(rec, 'lastOfferPresentationDate', 'submissionDate', 'lastEnqueryDate')),
            'envelope_date': self._parse_iso_datetime(
                self._coalesce(rec, 'offersOpeningDate', 'envelopeDate', 'openingDate')),
            'tender_url': DETAILS_URL_TEMPLATE % quote(str(tender_id_string or tender_id_external), safe='')
            if (tender_id_string or tender_id_external) else False,
            'raw_data': str(rec),
            'last_synced_at': fields.Datetime.now(),
        }

    def _upsert_vals(self, vals):
        if not vals.get('tender_id_external'):
            _logger.warning('Etimad Tenders: skipping record with no identifiable tender id: %s', str(vals)[:300])
            return False, False
        existing = self.search([
            ('tender_id_external', '=', vals['tender_id_external']),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing, 'updated'
        vals['company_id'] = self.env.company.id
        created = self.create(vals)
        return created, 'created'

    def _upsert_from_api(self, rec):
        return self._upsert_vals(self._prepare_vals_from_api(rec))

    def fetch_tenders(self, pages=None, page_size=None, ext_id=None, name_filter=None, agency_filter=None):
        """Fetch tenders page by page and upsert them, optionally restricted to
        one activity (ext_id) and/or filtered by tender name / agency
        (client-side, since server-side filter support is unconfirmed).
        Returns {'created': int, 'updated': int, 'errors': [str, ...]}.
        """
        params = self._get_sync_params()
        page_size = page_size or params['page_size']
        pages = pages or params['cron_pages']
        session = self._get_http_session(params['warmup_url'], params['session_cookie'])

        total = {'created': 0, 'updated': 0, 'errors': []}
        try:
            method, url, records = self._resolve_endpoint(session, page_size, ext_id=ext_id)
        except UserError as exc:
            msg = str(exc)
            _logger.warning('Etimad Tenders: %s', msg)
            total['errors'].append(msg)
            return total

        page_number = 1
        while True:
            if not records:
                break
            for rec in records:
                try:
                    vals = self._prepare_vals_from_api(rec)
                except Exception as exc:  # noqa: BLE001 - never let one bad record break the whole sync
                    msg = 'failed to map record %s: %s' % (str(rec)[:120], exc)
                    _logger.exception('Etimad Tenders: %s', msg)
                    total['errors'].append(msg)
                    continue
                if name_filter and name_filter.lower() not in (vals.get('name') or '').lower():
                    continue
                if agency_filter and agency_filter.lower() not in (vals.get('agency_name') or '').lower():
                    continue
                try:
                    _record, action = self._upsert_vals(vals)
                except Exception as exc:  # noqa: BLE001
                    msg = 'failed to upsert record %s: %s' % (str(vals)[:120], exc)
                    _logger.exception('Etimad Tenders: %s', msg)
                    total['errors'].append(msg)
                    continue
                if action == 'created':
                    total['created'] += 1
                elif action == 'updated':
                    total['updated'] += 1

            if len(records) < page_size or page_number >= pages:
                break
            page_number += 1
            try:
                records = self._call_endpoint(session, method, url, page_number, page_size, ext_id=ext_id)
            except (requests.RequestException, ValueError) as exc:
                msg = 'fetch failed on page %s%s: %s' % (
                    page_number, (' (activity %s)' % ext_id) if ext_id else '', exc)
                _logger.warning('Etimad Tenders: %s', msg)
                total['errors'].append(msg)
                break
        return total

    def action_scheduled_fetch(self):
        try:
            params = self._get_sync_params()
            ext_ids = params['activity_ext_ids']
            pages = params['cron_pages']
            if ext_ids:
                total = {'created': 0, 'updated': 0, 'errors': []}
                for ext_id in ext_ids:
                    result = self.fetch_tenders(pages=pages, ext_id=ext_id)
                    total['created'] += result['created']
                    total['updated'] += result['updated']
                    total['errors'].extend(result['errors'])
                _logger.info(
                    'Etimad scheduled fetch (%d activities) complete: %s',
                    len(ext_ids), total
                )
            else:
                result = self.fetch_tenders(pages=pages)
                _logger.info(
                    'Etimad scheduled fetch (all activities) complete: %s', result
                )
        except Exception:  # noqa: BLE001 - a cron must never hard-crash the scheduler
            _logger.exception('Etimad Tenders: scheduled fetch failed')
