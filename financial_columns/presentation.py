"""The supplied terminal's field lists, independent of full source retention.

Selectors are (source form, optional source code, verified semantic metric).
They do not infer values, merge components, or substitute a different standard.
Multiple explicitly listed components (e.g. loans and leases) retain their own
rows and passports. An undisclosed field is not fabricated from a similar one.
"""
import json
from pathlib import Path
import re


FIELDS = json.loads(Path(__file__).with_name('reference_fields.json').read_text(encoding='utf-8'))
RATIOS = {
    'bank': {'NSBU': 'roe roa nim cir cost_of_risk loans_to_deposits',
             'MSFO': 'roe roa nim cir cost_of_risk stage3_to_gross_loans'},
    'insurance': {'NSBU': 'roe roa loss_ratio reinsurance_share premium_retention reserves_to_equity',
                  'MSFO': 'roe roa loss_ratio expense_ratio combined_ratio insurance_service_margin'},
    'leasing': {'NSBU': 'roe roa liabilities_to_equity lease_yield current_ratio',
                'MSFO': 'roe roa lease_nim funding_cost cost_of_risk lease_ecl_ratio'},
    'general': {'NSBU': 'roe roa roce gross_margin current_ratio asset_turnover',
                'MSFO': 'roe roa roce ebitda_margin current_ratio net_debt_to_ebitda'},
    'telecom': {'NSBU': 'roe roa roce current_ratio asset_turnover',
                'MSFO': 'roe roa roce ebitda_margin capex_to_revenue net_debt_to_ebitda'},
    'fund': {'NSBU': 'roe equity_to_assets',
             'MSFO': 'nav_per_share nav_per_share_growth portfolio_revaluation dividends_to_investments'},
}


def template_for(kind, name=''):
    if kind in {'bank', 'insurance', 'fund', 'leasing', 'telecom'}:
        return kind
    if kind == 'financial' and re.search(r'lizing|лизинг|leasing', name or '', re.I):
        return 'leasing'
    if re.search(r'telecom|telekom|телеком|telecommunication|телекоммуникац', name or '', re.I):
        return 'telecom'
    return 'general'


def project(payload):
    template = template_for(payload['template'], payload.get('issuer_name'))
    standard = payload['standard']
    selected, used = [], set()
    for group in FIELDS[template]['nsbu' if standard == 'NSBU' else 'ifrs']:
        for field in group['fields']:
            for form, code, metric in field['selectors']:
                for row in payload['rows']:
                    if (row['id'] not in used and row['source_form'] == form
                            and row.get('metric_id') == metric
                            and (code is None or row.get('source_code') == code)):
                        selected.append({**row, 'label': field['label'],
                                         'source_label': row.get('source_label') or row.get('label') or row.get('raw_label'),
                                         'display_field': field['field_id'], 'display_group': group['label']})
                        used.add(row['id'])
    allowed_ratios = set(RATIOS[template][standard].split())
    return {**payload, 'presentation': 'template', 'display_template': template,
            'rows': selected, 'ratios': [r for r in payload.get('ratios', []) if r['metric_id'] in allowed_ratios],
            'published_ratios': [r for r in payload.get('published_ratios', []) if r['field'] in allowed_ratios]}
