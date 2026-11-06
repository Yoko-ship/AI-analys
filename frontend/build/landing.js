import { readFile, writeFile } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { createServer } from 'vite';
import react from '@vitejs/plugin-react';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

export function landingShells() {
  let root;
  return {
    name: 'landing-shells',
    apply: 'build',
    configResolved(config) { root = config.root; },
    async writeBundle(options, bundle) {
      const server = await createServer({
        configFile: false, root, plugins: [react()], appType: 'custom',
        server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true },
      });
      try {
        const { StaticLanding } = await server.ssrLoadModule('/src/features/landing/StaticLanding.jsx');
        const assets = new Map(Object.values(bundle).filter(item => item.type === 'asset')
          .flatMap(item => item.names.map(name => [basename(name), `/${item.fileName}`])));
        const shells = ['ru', 'uz', 'en'].map(language => {
          const markup = renderToStaticMarkup(createElement(StaticLanding, { language }))
            .replace(/\/src\/assets\/[^"\s]+/g, source => {
              const asset = assets.get(basename(source));
              if (!asset) throw new Error(`Landing asset was not emitted: ${source}`);
              return asset;
            });
          return `<template id="landing-${language}">${markup}</template>`;
        }).join('\n');
        const file = resolve(options.dir, 'index.html');
        const html = await readFile(file, 'utf8');
        if (!html.includes('<!-- landing-shells -->')) throw new Error('Missing landing shells placeholder');
        await writeFile(file, html.replace('<!-- landing-shells -->', shells));
      } finally { await server.close(); }
    },
  };
}
