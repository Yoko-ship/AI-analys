// Public interface for this feature.
import { lazy } from "react";
export const AdvancedChart = lazy(() => import("./AdvancedChart.jsx").then(module => ({ default: module.AdvancedChart })));
