// Public interface for this feature.
import { lazy } from "react";
export const BondCard = lazy(() => import("./Bonds.jsx").then(module => ({ default: module.BondCard })));
export const BondsView = lazy(() => import("./Bonds.jsx").then(module => ({ default: module.BondsView })));
