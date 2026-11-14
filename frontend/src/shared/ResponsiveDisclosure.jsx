import {useEffect, useState} from 'react';
import {useMediaQuery} from './useMediaQuery.js';
import './responsiveDisclosure.css';

// One set of controls: always expanded on desktop, reader-controlled on phones.
export function ResponsiveDisclosure({label, className = '', mediaQuery = '(max-width: 760px)', collapsible = true, children}) {
  const compact = useMediaQuery(mediaQuery);
  const phone = compact && collapsible;
  const [open, setOpen] = useState(!phone);
  useEffect(() => setOpen(!phone), [phone]);
  return <details className={`responsive-disclosure ${className}${collapsible ? '' : ' is-static'}`} open={!phone || open}
    onToggle={event => {
      if (phone && event.target === event.currentTarget) setOpen(event.currentTarget.open);
    }}>
    <summary>{label}</summary>
    <div className="responsive-disclosure-body">{children}</div>
  </details>;
}
