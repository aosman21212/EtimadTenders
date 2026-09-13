from odoo import models, fields, api, _
from odoo.exceptions import UserError


class EtimadFetchWizard(models.TransientModel):
    _name        = 'etimad.fetch.wizard'
    _description = 'Fetch Tenders from Etimad'

    # ── Fetch options ──────────────────────────────────────────────────────
    pages = fields.Integer(
        string='Pages to Fetch',
        default=1,
        help='Each page contains the number of records configured in Settings.',
    )
    activity_ids = fields.Many2many(
        'etimad.activity',
        string='Filter by Activity / Sector',
        help=(
            'Leave empty to fetch all sectors.\n'
            'Select one or more sectors to restrict the fetch. '
            'The wizard will run one API request per selected sector.'
        ),
    )
    tender_name = fields.Char(
        string='Filter by Tender Name',
        help='Leave blank to fetch all tenders.',
    )
    agency_name = fields.Char(
        string='Filter by Agency Name',
    )

    # ── Result display (readonly) ──────────────────────────────────────────
    result_message = fields.Text(string='Result', readonly=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')],
        default='draft',
    )

    # ── Actions ────────────────────────────────────────────────────────────
    def action_sync_activities(self):
        """Sync the activity list from Etimad, then re-open the wizard."""
        self.env['etimad.activity'].sync_from_api()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_fetch(self):
        self.ensure_one()
        if self.pages < 1:
            raise UserError(_('Number of pages must be at least 1.'))

        Tender = self.env['etimad.tender']
        activities = self.activity_ids

        if activities:
            # One fetch per selected activity — aggregate results
            total = {'created': 0, 'updated': 0, 'total_fetched': 0, 'errors': []}
            for act in activities:
                result = Tender.fetch_tenders(
                    pages=self.pages,
                    tender_name=self.tender_name or '',
                    agency_name=self.agency_name or '',
                    activity_id=act.activity_id_external,
                )
                total['created']       += result['created']
                total['updated']       += result['updated']
                total['total_fetched'] += result['total_fetched']
                total['errors'].extend(result['errors'])
        else:
            # No activity filter — fetch everything
            total = Tender.fetch_tenders(
                pages=self.pages,
                tender_name=self.tender_name or '',
                agency_name=self.agency_name or '',
            )

        sector_info = (
            ', '.join(a.name for a in activities)
            if activities
            else _('all sectors')
        )

        lines = [
            _('✅ Fetch complete!  (%s)') % sector_info,
            _('• New tenders created  : %d') % total['created'],
            _('• Existing updated     : %d') % total['updated'],
            _('• Total records fetched: %d') % total['total_fetched'],
        ]
        if total.get('errors'):
            lines.append(_('\n⚠️  Errors:'))
            lines.extend(total['errors'])

        self.write({
            'result_message': '\n'.join(lines),
            'state': 'done',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
