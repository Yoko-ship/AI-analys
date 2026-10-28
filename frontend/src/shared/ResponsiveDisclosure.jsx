import {useEffect, useState} from 'react';
import {useMediaQuery} from './useMediaQuery.js';
import './responsiveDisclosure.css';

// One set of controls: always expanded on desktop, reader-controlled on phones.
export function ResponsiveDisclosure({label, className = '', children}) {
  const phone = useMediaQuery('(max-width: 760px)');
  const [open, setOpen] = useState(!phone);
  useEffect(() => setOpen(!phone), [phone]);
  return <details className={`responsive-disclosure ${className}`} open={open}
    onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{label}</summary>
    <div className="responsive-disclosure-body">{children}</div>
  </details>;
}
