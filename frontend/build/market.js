import { startMarketStartup } from '../src/lib/marketStartup.js';

export function marketStartup() {
  return {
    name: 'market-startup',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html, {bundle}) {
        const market = Object.values(bundle).find(chunk => chunk.type === 'chunk'
          && chunk.facadeModuleId?.endsWith('/features/market/MarketView.jsx'));
        if (!market) throw new Error('Missing market entry for startup preloads');
        const files = new Set();
        const visit = chunk => {
          if (files.has(chunk.fileName)) return;
          files.add(chunk.fileName);
          for (const imported of chunk.imports) {
            const dependency = bundle[imported];
            if (dependency?.type === 'chunk') visit(dependency);
          }
        };
        visit(market);
        const marker = '<!-- market-startup -->';
        if (!html.includes(marker)) throw new Error('Missing market startup placeholder');
        const script = `(${startMarketStartup.toString()})(window, ${JSON.stringify([...files].map(file => '/' + file))});`;
        // Attribute-less scripts are hashed by the existing production CSP.
        return html.replace(marker, `<script>${script}</script>`);
      },
    },
  };
}
