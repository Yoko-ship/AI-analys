// Public interface for this feature.
import { lazy } from "react";
export const CatalogView = lazy(() => import("./CatalogView.jsx").then(module => ({ default: module.CatalogView })));
