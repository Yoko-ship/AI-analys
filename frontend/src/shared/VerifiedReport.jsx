import { lazy } from "react";

const VerifiedReport = lazy(() => import("../analysis/VerifiedReport.jsx"));

const ReportAvailability = lazy(() => import("../analysis/VerifiedReport.jsx").then((module) => ({ default: module.ReportAvailability })));

export { ReportAvailability, VerifiedReport };
