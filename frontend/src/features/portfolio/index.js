// Public interface for this feature.
import { lazy } from "react";
export const PortfolioView = lazy(() => import("./PortfolioView.jsx").then(module => ({ default: module.PortfolioView })));
