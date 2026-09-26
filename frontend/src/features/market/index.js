// Public interface for this feature.
import { lazy } from "react";
export const MarketView = lazy(() => import("./MarketView.jsx").then(module => ({ default: module.MarketView })));
export { useMarketData } from "./useMarketData.jsx";
