// Public interface for this feature.
export { CatalogAccessNotice } from "./CatalogAccessNotice.jsx";
import { lazy } from "react";
export const CatalogView = lazy(() => import("./CatalogView.jsx").then(module => ({ default: module.CatalogView })));
