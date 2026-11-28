"""Normalize numeric dates in parsing copies, without changing source evidence."""
from datetime import date
import re


MONTHS = ('January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December')
NUMERIC = re.compile(r'(?<![\w.])(\d{4}|\d{1,2})\s*([./-])\s*(\d{1,2})\s*([./-])\s*(\d{4}|\d{1,2})(?!\d)')


def expand(text):
    """Return a parsing copy, or None when a numeric date is invalid or ambiguous."""
    def replace(match):
        first, separator, middle, second_separator, last = match.groups()
        if separator != second_separator:
            raise ValueError('Inconsistent date separators')
        if len(first) == 4 and len(last) <= 2:
            year, month, day = int(first), int(middle), int(last)
        elif len(last) == 4 and len(first) <= 2:
            year, month, day = int(last), int(middle), int(first)
            if day <= 12 and month > 12:
                day, month = month, day
            elif day <= 12 and day != month:
                raise ValueError('Ambiguous day and month')
        else:
            raise ValueError('A date needs a four-digit year')
        parsed = date(year, month, day)
        return f'{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}'
    try:
        return NUMERIC.sub(replace, text)
    except ValueError:
        return None
