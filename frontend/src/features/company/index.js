// Public interface for this feature.
import { lazy } from "react";
export const CompanyPage = lazy(() => import("./CompanyPage.jsx").then(module => ({ default: module.CompanyPage })));
