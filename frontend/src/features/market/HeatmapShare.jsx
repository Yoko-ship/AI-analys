import React, {useState} from 'react';
import * as Popover from '@radix-ui/react-popover';
import {ShareIcon, SharePanel} from '../../shared/Share.jsx';
import {localizedPath} from '../../lib/languagePath.js';

export function HeatmapShare({lang, portalContainer}) {
  const [open, setOpen] = useState(false);
  const label = lang === 'ru' ? 'Поделиться' : lang === 'uz' ? 'Ulashish' : 'Share';
  const title = lang === 'ru' ? 'Карта рынка' : lang === 'uz' ? 'Bozor xaritasi' : 'Market map';
  const url = `${window.location.origin}${localizedPath('/heatmap', lang)}`;
  return <Popover.Root open={open} onOpenChange={setOpen}>
    <Popover.Trigger asChild>
      <button type="button" className="heatmap-share-toggle" aria-label={label} title={label}><ShareIcon /></button>
    </Popover.Trigger>
    <Popover.Portal container={portalContainer}>
      <Popover.Content className="heatmap-share-menu" aria-label={label} align="end" sideOffset={8} collisionPadding={8}
        onKeyDownCapture={event => {
          // Dismiss sharing before Escape reaches the map's fullscreen handler.
          if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); }
        }}>
        <SharePanel url={url} title={`${title} | UZStock`} text={title} lang={lang} />
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
