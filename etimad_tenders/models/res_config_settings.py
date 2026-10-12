# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .etimad_tender import DEFAULT_WARMUP_URL


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    etimad_api_url = fields.Char(
        string='Custom API Endpoint (optional)',
        config_parameter='etimad_tenders.api_url',
        help='Override the automatic endpoint detection with one specific URL '
             '(always called as GET). Leave empty to let the module try the known '
             'candidate endpoints in order and use whichever responds with valid JSON.',
    )
    etimad_warmup_url = fields.Char(
        string='Etimad Warm-up URL',
        config_parameter='etimad_tenders.warmup_url',
        default=DEFAULT_WARMUP_URL,
        help='A plain public page fetched once before the API call, to pick up any '
             'bot-protection cookies (e.g. F5 TrafficShield) the platform requires. '
             'Skipped if a Session Cookie is configured below.',
    )
    etimad_page_size = fields.Integer(
        string='Page Size',
        config_parameter='etimad_tenders.page_size',
        default=50,
        help='Number of tenders requested per API call. Maximum 100.',
    )
    etimad_cron_pages = fields.Integer(
        string='Pages per Sync',
        config_parameter='etimad_tenders.cron_pages',
        default=5,
        help='Maximum number of pages fetched on each scheduled/manual sync run.',
    )
    etimad_session_cookie = fields.Char(
        string='Session Cookie (optional)',
        config_parameter='etimad_tenders.session_cookie',
        help='Raw Cookie header value to send with every request (e.g. copied from a browser '
             'that already solved the Etimad bot-protection challenge). When set, the warm-up '
             'GET is skipped and this cookie is used directly.',
    )
    etimad_activity_ids = fields.Many2many(
        'etimad.activity', string='Activities to Sync',
        compute='_compute_etimad_activity_ids', inverse='_inverse_etimad_activity_ids',
        help='Restrict the daily sync to specific activities/sectors. Leave empty to fetch all.',
    )

    @api.depends('etimad_api_url')  # dummy dependency: value is read from ir.config_parameter, not a stored field
    def _compute_etimad_activity_ids(self):
        icp = self.env['ir.config_parameter'].sudo()
        ext_ids_str = icp.get_param('etimad_tenders.activity_ext_ids', '') or ''
        ext_ids = [x for x in ext_ids_str.split(',') if x]
        activities = self.env['etimad.activity'].search([('ext_id', 'in', ext_ids)]) if ext_ids \
            else self.env['etimad.activity']
        for record in self:
            record.etimad_activity_ids = activities

    def _inverse_etimad_activity_ids(self):
        icp = self.env['ir.config_parameter'].sudo()
        for record in self:
            ext_ids = [ext_id for ext_id in record.etimad_activity_ids.mapped('ext_id') if ext_id]
            icp.set_param('etimad_tenders.activity_ext_ids', ','.join(ext_ids))

    @api.constrains('etimad_page_size')
    def _check_etimad_page_size(self):
        for record in self:
            if record.etimad_page_size and not (1 <= record.etimad_page_size <= 100):
                raise ValidationError(
                    'Etimad page size must be between 1 and 100.'
                )

    def action_etimad_test_connection(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(
            'etimad_tenders.api_url', self.etimad_api_url or '')
        self.env['ir.config_parameter'].sudo().set_param(
            'etimad_tenders.warmup_url', self.etimad_warmup_url or DEFAULT_WARMUP_URL)
        self.env['ir.config_parameter'].sudo().set_param(
            'etimad_tenders.session_cookie', self.etimad_session_cookie or '')
        self.env['etimad.tender'].test_connection()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Etimad Tenders',
                'message': 'Connection successful.',
                'type': 'success',
                'sticky': False,
            },
        }
