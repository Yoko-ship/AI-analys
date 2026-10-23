"""Read the active governed terminal configuration."""
from server.terminal.valuation import REFERENCE, REFERENCE_DATE

def parameters():
    from admin_control.rules import active
    rule=next((r for r in active() if r.get('category')=='valuation' and r.get('config',{}).get('code')=='terminal_fv'),None)
    return {'values':{k:rule['config'][k] for k in REFERENCE} if rule else REFERENCE.copy(),
            'as_of':rule['config']['as_of'] if rule else REFERENCE_DATE,
            'version':rule['id'] if rule else 'tz-reference-2026-10-15', 'reference_only':rule is None}
