from odoo import models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Simple scalar settings (auto-stored via config_parameter) ──────────
    etimad_session_cookie = fields.Char(
        string='Etimad Session Cookie',
        help=(
            'Paste the full Cookie header value from your Etimad browser '
            'session. Open https://tenders.etimad.sa in your browser, '
            'open DevTools (F12) → Network tab → any request → copy the '
            'Cookie request header and paste it here. Required when the '
            'public API blocks automated access.'
        ),
        config_parameter='etimad_tenders.session_cookie',
    )
    etimad_api_url = fields.Char(
        string='Custom API Endpoint URL (optional)',
        help=(
            'Override the default Etimad API endpoint. Leave blank to use '
            'the auto-detected endpoint.\n'
            'Example: https://tenders.etimad.sa/Tender/AllTendersForVisitorAsync'
        ),
        config_parameter='etimad_tenders.api_url',
    )
    etimad_page_size = fields.Integer(
        string='Page Size (records per request)',
        default=50,
        config_parameter='etimad_tenders.page_size',
        help='Number of tenders to retrieve per API page (max 100).',
    )
    etimad_cron_pages = fields.Integer(
        string='Pages per Scheduled Fetch',
        default=5,
        config_parameter='etimad_tenders.cron_pages',
        help='How many pages (× Page Size) to pull on each scheduled run.',
    )

    # ── Activity / sector filter for scheduled cron ────────────────────────
    # Stored as comma-separated Etimad activity IDs in ir.config_parameter.
    # We use get_values / set_values because Many2many can't use config_parameter.
    etimad_cron_activity_ids = fields.Many2many(
        'etimad.activity',
        string='Sectors to Fetch (Scheduled)',
        help=(
            'Leave empty to fetch all sectors.\n'
            'Select one or more sectors to limit the daily scheduled fetch '
            'to only those activity categories.'
        ),
    )

    # ── get / set values ──────────────────────────────────────────────────
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ids_str = ICP.get_param('etimad_tenders.cron_activity_ids', '')
        if ids_str:
            ext_ids = [
                int(x) for x in ids_str.split(',') if x.strip().isdigit()
            ]
            activities = self.env['etimad.activity'].search(
                [('activity_id_external', 'in', ext_ids)]
            )
            res['etimad_cron_activity_ids'] = [(6, 0, activities.ids)]
        else:
            res['etimad_cron_activity_ids'] = [(5,)]
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        activities = self.etimad_cron_activity_ids
        if activities:
            ids_str = ','.join(
                str(a.activity_id_external) for a in activities
            )
        else:
            ids_str = ''
        ICP.set_param('etimad_tenders.cron_activity_ids', ids_str)

    # ── Button handlers ───────────────────────────────────────────────────
    def action_test_etimad_connection(self):
        """Test the Etimad API connection from the Settings page."""
        return self.env['etimad.tender'].action_test_connection()

    def action_sync_etimad_activities(self):
        """Sync the activity / sector list from the Etimad API."""
        return self.env['etimad.activity'].sync_from_api()
