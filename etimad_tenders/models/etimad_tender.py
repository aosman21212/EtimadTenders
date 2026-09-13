import re
import json
import logging
import requests
from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ETIMAD_BASE_URL = 'https://tenders.etimad.sa'

# Confirmed working endpoint (verified 2026-09-12):
#   GET https://tenders.etimad.sa/Tender/AllSupplierTendersForVisitorAsync
# The list below is tried in order; first 200+JSON response wins.
ETIMAD_ENDPOINTS = [
    ('GET',  f'{ETIMAD_BASE_URL}/Tender/AllSupplierTendersForVisitorAsync'),  # ✅ confirmed
    ('GET',  f'{ETIMAD_BASE_URL}/Tender/AllTendersForVisitorAsync'),
    ('POST', f'{ETIMAD_BASE_URL}/Tender/AllTendersForVisitorAsync'),
    ('POST', f'{ETIMAD_BASE_URL}/Tender/GetAllTendersForVisitor'),
]

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ar-SA,ar;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://tenders.etimad.sa/Tender/AllTendersForVisitor',
    'Origin': 'https://tenders.etimad.sa',
    'sec-ch-ua': '"Chromium";v="120", "Not(A:Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'Connection': 'keep-alive',
}


def _parse_date(value):
    """Parse Etimad date fields which may be:
       - ISO string  : '2024-03-15T00:00:00'
       - MS JSON date: '/Date(1710460800000)/'
       - None / empty
    """
    if not value:
        return False
    if isinstance(value, str) and value.startswith('/Date('):
        match = re.search(r'/Date\((-?\d+)', value)
        if match:
            ts = int(match.group(1)) / 1000
            try:
                return datetime.utcfromtimestamp(ts)
            except (OSError, OverflowError, ValueError):
                return False
    try:
        return datetime.fromisoformat(str(value).replace('Z', ''))
    except (ValueError, TypeError):
        return False


class EtimadTender(models.Model):
    _name = 'etimad.tender'
    _description = 'Etimad Government Tender'
    _order = 'publish_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Tender Name', required=True, tracking=True,
        help='Arabic name of the tender as published on Etimad'
    )
    tender_id_external = fields.Char(
        string='Etimad ID', index=True, copy=False,
        help='Internal numeric ID on the Etimad platform'
    )
    tender_number = fields.Char(
        string='Tender Reference', index=True,
        help='Official tender reference number e.g. 2024/12345'
    )

    # ── Agency / Classification ────────────────────────────────────────────────
    agency_name = fields.Char(string='Government Agency', tracking=True)
    agency_id_external = fields.Char(string='Agency ID (Etimad)')
    branch_name = fields.Char(string='Branch / Department')
    tender_type = fields.Char(string='Tender Type')
    tender_activity = fields.Char(string='Activity / Sector')
    purpose = fields.Char(string='Purpose')

    # ── Status ─────────────────────────────────────────────────────────────────
    status = fields.Char(string='Tender Status', tracking=True)
    state = fields.Selection([
        ('new', 'New'),
        ('open', 'Open'),
        ('closed', 'Closed / Awarded'),
        ('cancelled', 'Cancelled'),
        ('converted', 'Converted to Opportunity'),
    ], string='State', default='new', tracking=True)

    # ── Dates ──────────────────────────────────────────────────────────────────
    publish_date = fields.Datetime(string='Published On')
    last_apply_date = fields.Datetime(string='Last Application Date')
    last_envelope_date = fields.Datetime(
        string='Submission Deadline', tracking=True,
        help='Last date to submit offers / envelopes'
    )
    offers_opening_date = fields.Datetime(string='Offers Opening Date')

    # ── Financials ─────────────────────────────────────────────────────────────
    estimated_value = fields.Float(
        string='Estimated Value (SAR)', digits=(16, 2),
        help='Estimated contract value in Saudi Riyals'
    )
    booklet_price = fields.Float(
        string='Tender Booklet Price (SAR)', digits=(16, 2)
    )

    # ── Links ──────────────────────────────────────────────────────────────────
    tender_url = fields.Char(
        string='Tender URL',
        compute='_compute_tender_url', store=True
    )

    # ── CRM Integration ────────────────────────────────────────────────────────
    opportunity_id = fields.Many2one(
        'crm.lead', string='Opportunity',
        domain=[('type', '=', 'opportunity')],
        copy=False, tracking=True
    )
    opportunity_count = fields.Integer(
        compute='_compute_opportunity_count'
    )

    # ── Raw data ───────────────────────────────────────────────────────────────
    raw_data = fields.Text(
        string='Raw JSON', help='Original JSON payload from Etimad'
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Constraints (Odoo 19 class-attribute style)
    # ──────────────────────────────────────────────────────────────────────────

    _tender_id_external_unique = models.Constraint(
        'UNIQUE(tender_id_external)',
        'A tender with this Etimad ID already exists.',
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ──────────────────────────────────────────────────────────────────────────

    @api.depends('tender_id_external')
    def _compute_tender_url(self):
        for rec in self:
            if rec.tender_id_external:
                rec.tender_url = (
                    f'{ETIMAD_BASE_URL}/Tender/DetailsForVisitor'
                    f'?STenderId={rec.tender_id_external}'
                )
            else:
                rec.tender_url = False

    def _compute_opportunity_count(self):
        for rec in self:
            rec.opportunity_count = 1 if rec.opportunity_id else 0

    # ──────────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────────

    def action_view_opportunity(self):
        self.ensure_one()
        if not self.opportunity_id:
            raise UserError(_('No opportunity linked to this tender yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': self.opportunity_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_opportunity(self):
        """Create a CRM opportunity from this tender."""
        self.ensure_one()
        if self.opportunity_id:
            raise UserError(
                _('An opportunity is already linked to this tender.')
            )
        Lead = self.env['crm.lead']
        opp = Lead.create({
            'type': 'opportunity',
            'name': self.name,
            'description': (
                f'Tender Reference: {self.tender_number or ""}\n'
                f'Agency: {self.agency_name or ""}\n'
                f'Type: {self.tender_type or ""}\n'
                f'Status: {self.status or ""}\n'
                f'Estimated Value: {self.estimated_value:,.2f} SAR\n'
                f'Submission Deadline: {self.last_envelope_date or ""}\n'
                f'URL: {self.tender_url or ""}'
            ),
            'expected_revenue': self.estimated_value,
            'date_deadline': (
                self.last_envelope_date.date()
                if self.last_envelope_date else False
            ),
        })
        self.write({
            'opportunity_id': opp.id,
            'state': 'converted',
        })
        self.message_post(
            body=_('Converted to opportunity: <a href="#" data-oe-model="crm.lead" '
                   'data-oe-id="%d">%s</a>') % (opp.id, opp.name)
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': opp.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_url(self):
        self.ensure_one()
        if not self.tender_url:
            raise UserError(_('No URL available for this tender.'))
        return {
            'type': 'ir.actions.act_url',
            'url': self.tender_url,
            'target': 'new',
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Fetch helpers
    # ──────────────────────────────────────────────────────────────────────────

    @api.model
    def _get_session(self):
        """
        Build a requests.Session with browser-like headers and any stored
        session cookie.  Also performs a warm-up GET to the listing page
        so the F5 TrafficShield anti-bot cookie (TS…) is properly set,
        unless the user has already provided one.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        cookie_str = ICP.get_param('etimad_tenders.session_cookie', '')

        sess = requests.Session()
        sess.headers.update(DEFAULT_HEADERS)

        if cookie_str:
            # User supplied a full Cookie header string — inject directly
            sess.headers['Cookie'] = cookie_str
        else:
            # Warm-up: load the listing page to receive anti-bot cookies
            try:
                warm = sess.get(
                    f'{ETIMAD_BASE_URL}/Tender/AllTendersForVisitor',
                    headers={
                        'Accept': 'text/html,application/xhtml+xml,*/*',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                    },
                    timeout=20,
                )
                _logger.debug('Etimad warm-up: %s', warm.status_code)
            except Exception as exc:
                _logger.warning('Etimad warm-up failed: %s', exc)

        return sess

    @api.model
    def _build_params(self, page_number=1, page_size=None,
                      tender_name='', agency_name='',
                      activity_id=None,
                      tender_type_id=None, tender_status_id=None):
        """Build the query / body parameters for the Etimad API."""
        if page_size is None:
            page_size = int(
                self.env['ir.config_parameter']
                .sudo()
                .get_param('etimad_tenders.page_size', 50)
            )
        params = {
            'PageNumber': page_number,
            'PageSize': page_size,
        }
        if tender_name:
            params['TenderName'] = tender_name
        if agency_name:
            params['AgencyName'] = agency_name
        if activity_id:
            params['TenderActivityId'] = activity_id
        if tender_type_id:
            params['TenderTypeId'] = tender_type_id
        if tender_status_id:
            params['TenderStatusId'] = tender_status_id
        return params

    # Keep old name as alias for backwards compat
    _build_payload = _build_params

    @api.model
    def _fetch_page(self, params, timeout=30, session=None):
        """
        Try each candidate endpoint in ETIMAD_ENDPOINTS until one returns
        valid JSON.  Returns the parsed dict/list.
        Raises UserError if all attempts fail.
        """
        sess = session or self._get_session()

        # Allow a user-configured override endpoint
        custom_url = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('etimad_tenders.api_url', '')
        )
        candidates = (
            [('GET', custom_url)] if custom_url else list(ETIMAD_ENDPOINTS)
        )

        last_error = ''
        for method, url in candidates:
            try:
                if method == 'GET':
                    resp = sess.get(url, params=params, timeout=timeout)
                else:
                    sess.headers['Content-Type'] = 'application/json'
                    resp = sess.post(url, json=params, timeout=timeout)

                if resp.status_code == 404:
                    _logger.debug('Etimad 404 on %s %s', method, url)
                    continue
                if resp.status_code == 403:
                    last_error = _(
                        'Etimad returned 403 Forbidden on %s %s — '
                        'the site requires a valid browser session cookie. '
                        'Please open https://tenders.etimad.sa in your browser, '
                        'copy the Cookie request header from DevTools → Network, '
                        'and paste it in Settings → Etimad Tenders → Session Cookie.'
                    ) % (method, url)
                    continue

                resp.raise_for_status()
                ct = resp.headers.get('Content-Type', '')
                if 'json' not in ct and resp.text.strip().startswith('<'):
                    _logger.debug(
                        'Etimad %s %s returned HTML (bot check?)', method, url
                    )
                    last_error = _(
                        'Etimad returned HTML instead of JSON on %s %s. '
                        'The site may have triggered a CAPTCHA or bot check. '
                        'Provide a valid Session Cookie in the settings.'
                    ) % (method, url)
                    continue

                data = resp.json()
                _logger.info('Etimad: success with %s %s', method, url)
                return data

            except requests.exceptions.Timeout:
                last_error = _('Etimad request timed out (%s %s).') % (method, url)
            except requests.exceptions.ConnectionError as exc:
                last_error = _('Connection error on %s %s: %s') % (method, url, exc)
            except requests.exceptions.HTTPError as exc:
                last_error = _('HTTP error on %s %s: %s') % (method, url, exc)
            except ValueError:
                last_error = _(
                    'Non-JSON response from %s %s.'
                ) % (method, url)

        raise UserError(
            _('Could not retrieve data from Etimad after trying all endpoints.\n\n'
              'Last error: %s\n\n'
              'Tip: Copy your Cookie header from a logged-in browser session '
              'and paste it in Settings → Etimad Tenders → Session Cookie.')
            % last_error
        )

    @api.model
    def _parse_tender_row(self, row):
        """
        Map a single raw API dict to an etimad.tender field dict.
        Handles both camelCase and PascalCase field naming conventions.
        """
        def g(row, *keys):
            """Get first matching key (case-insensitive fallback)."""
            for k in keys:
                if k in row:
                    return row[k]
            # case-insensitive last resort
            low = {x.lower(): v for x, v in row.items()}
            for k in keys:
                v = low.get(k.lower())
                if v is not None:
                    return v
            return None

        tender_id = str(g(row, 'TenderId', 'tenderId') or '')
        return {
            'name': (
                g(row, 'TenderName', 'tenderName') or
                g(row, 'TenderIdString', 'tenderIdString') or
                tender_id or _('Unknown Tender')
            ),
            'tender_id_external': tender_id,
            'tender_number': str(
                g(row, 'TenderIdString', 'tenderIdString') or ''
            ),
            'agency_name': g(row, 'AgencyName', 'agencyName') or '',
            'agency_id_external': str(
                g(row, 'AgencyId', 'agencyId') or ''
            ),
            'branch_name': g(row, 'BranchName', 'branchName') or '',
            'tender_type': g(row, 'TenderTypeName', 'tenderTypeName') or '',
            'tender_activity': (
                g(row, 'TenderActivityName', 'tenderActivityName') or ''
            ),
            'purpose': g(row, 'Purpose', 'purpose') or '',
            'status': (
                g(row, 'TenderStatusName', 'tenderStatusName') or ''
            ),
            'publish_date': _parse_date(
                g(row, 'PublishDate', 'publishDate')
            ),
            'last_apply_date': _parse_date(
                g(row, 'LastApplyDate', 'lastApplyDate')
            ),
            'last_envelope_date': _parse_date(
                g(row, 'LastEnvelopeDate', 'lastEnvelopeDate')
            ),
            'offers_opening_date': _parse_date(
                g(row, 'OffersOpeningDate', 'offersOpeningDate')
            ),
            'estimated_value': float(
                g(row, 'TenderValue', 'tenderValue',
                  'EstimatedValue', 'estimatedValue') or 0.0
            ),
            'booklet_price': float(
                g(row, 'ConditionalBookletPrice', 'conditionalBookletPrice')
                or 0.0
            ),
            'raw_data': json.dumps(row, ensure_ascii=False),
        }

    @api.model
    def _upsert_tenders(self, rows):
        """
        Create-or-update tenders from a list of raw API dicts.
        Returns (created_count, updated_count).
        """
        created = updated = 0
        for row in rows:
            vals = self._parse_tender_row(row)
            ext_id = vals.get('tender_id_external')
            if not ext_id:
                continue
            existing = self.search(
                [('tender_id_external', '=', ext_id)], limit=1
            )
            if existing:
                # Only update mutable fields, not state/opportunity
                mutable = {
                    k: v for k, v in vals.items()
                    if k not in ('tender_id_external', 'raw_data')
                }
                existing.write(mutable)
                updated += 1
            else:
                self.create(vals)
                created += 1
        return created, updated

    # ──────────────────────────────────────────────────────────────────────────
    # Public fetch entry points
    # ──────────────────────────────────────────────────────────────────────────

    @api.model
    def fetch_tenders(self, pages=1, page_size=None,
                       tender_name='', agency_name='',
                       activity_id=None,
                       tender_type_id=None, tender_status_id=None):
        """
        Fetch *pages* pages from Etimad and upsert the results.
        Pass activity_id (int) to filter by sector / activity.
        Reuses a single HTTP session across pages for efficiency.
        Returns a summary dict: {created, updated, total_fetched, errors}.
        Called by the scheduled action and the manual wizard.
        """
        total_created = total_updated = total_fetched = 0
        errors = []
        session = self._get_session()   # shared session for all pages

        for page in range(1, pages + 1):
            params = self._build_params(
                page_number=page,
                page_size=page_size,
                tender_name=tender_name,
                agency_name=agency_name,
                activity_id=activity_id,
                tender_type_id=tender_type_id,
                tender_status_id=tender_status_id,
            )
            try:
                data = self._fetch_page(params, session=session)
            except UserError as exc:
                errors.append(str(exc))
                _logger.warning('Etimad fetch error on page %d: %s', page, exc)
                break

            # Support both wrapped {"data": [...]} and bare list responses
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = (
                    data.get('data') or
                    data.get('Data') or
                    data.get('tenders') or
                    data.get('Tenders') or
                    data.get('result') or
                    data.get('Result') or
                    []
                )
            else:
                rows = []

            if not rows:
                _logger.info(
                    'Etimad: no rows on page %d — stopping.', page
                )
                break

            total_fetched += len(rows)
            created, updated = self._upsert_tenders(rows)
            total_created += created
            total_updated += updated
            _logger.info(
                'Etimad page %d: %d fetched, %d new, %d updated',
                page, len(rows), created, updated
            )

        return {
            'created': total_created,
            'updated': total_updated,
            'total_fetched': total_fetched,
            'errors': errors,
        }

    @api.model
    def action_test_connection(self):
        """
        Test the Etimad API connection and return a user notification.
        Can be called from a button in settings or the list view toolbar.
        """
        try:
            result = self.fetch_tenders(pages=1, page_size=3)
        except UserError as exc:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Etimad Connection Failed'),
                    'message': str(exc),
                    'type': 'danger',
                    'sticky': True,
                },
            }
        if result.get('errors'):
            msg = result['errors'][0]
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Etimad Connection Failed'),
                    'message': msg,
                    'type': 'danger',
                    'sticky': True,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Etimad Connection OK'),
                'message': _(
                    'Successfully fetched %d tender(s) from Etimad.'
                ) % result['total_fetched'],
                'type': 'success',
            },
        }

    @api.model
    def action_scheduled_fetch(self):
        """Entry point for the ir.cron scheduled action."""
        ICP = self.env['ir.config_parameter'].sudo()
        pages = int(ICP.get_param('etimad_tenders.cron_pages', 5))

        # Check for configured activity filters
        ids_str = ICP.get_param('etimad_tenders.cron_activity_ids', '')
        if ids_str:
            ext_ids = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
        else:
            ext_ids = []

        if ext_ids:
            # Fetch once per configured activity and aggregate
            total = {'created': 0, 'updated': 0, 'total_fetched': 0, 'errors': []}
            for ext_id in ext_ids:
                result = self.fetch_tenders(pages=pages, activity_id=ext_id)
                total['created']       += result['created']
                total['updated']       += result['updated']
                total['total_fetched'] += result['total_fetched']
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
