import { lazy } from "react";

// These tools are not needed for the public landing page. Splitting them out
// keeps a first visit focused on the market rather than downloading internal
// administration and account-editor code up front.
const AdminPanel = lazy(() => import("../admin/ControlPanel.jsx"));

const SectorMonitorPage = lazy(() => import("../admin/AnalysisMonitor.jsx").then((module) => ({ default: module.SectorMonitorPage })));

export { AdminPanel, SectorMonitorPage };
