import React from 'react';
import {createCatalogRequestCache, readJson} from '../lib/catalogRequestCache.js';

const uncached = {read:readJson, peek:() => null, version:0};
const CatalogData = React.createContext(uncached);

export function CatalogDataProvider({token, children}) {
  const [cache] = React.useState(() => createCatalogRequestCache({fetcher:(url, options) => fetch(url, {
    ...options, headers:token ? {Authorization:`Bearer ${token}`} : {},
  })}));
  const [version, setVersion] = React.useState(0);
  React.useEffect(() => () => cache.clear(), [cache]);
  const invalidate = React.useCallback(() => {cache.clear(); setVersion(v => v + 1);}, [cache]);
  const value = React.useMemo(() => ({...cache, version, invalidate}), [cache, version, invalidate]);
  return <CatalogData.Provider value={value}>{children}</CatalogData.Provider>;
}

export const useCatalogRequests = () => React.useContext(CatalogData);
