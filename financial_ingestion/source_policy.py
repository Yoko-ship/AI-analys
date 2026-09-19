"""Source eligibility for new work; archived publications remain readable."""
import os
from urllib.parse import urlparse


def name():
    value = os.environ.get('FINANCIAL_SOURCE_POLICY', 'openinfo')
    if value not in {'openinfo', 'reviewed_issuers'}:
        raise ValueError('Unknown FINANCIAL_SOURCE_POLICY')
    return value


def allows(url):
    if name() == 'reviewed_issuers':
        return True  # Existing issuer attribution/download checks still apply.
    try:
        parsed = urlparse(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'openinfo.uz'
                and parsed.port in {None, 443} and not parsed.username and not parsed.password
                and parsed.path.startswith('/media/'))
    except ValueError:
        return False


def require(url):
    if not allows(url):
        raise ValueError('OpenInfo-only sourcing: new work requires an OpenInfo media document')
