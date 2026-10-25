// Public interface for this feature.
import { lazy } from "react";
export const CompanyPage = lazy(() => import("./CompanyPage.jsx").then(module => ({ default: module.CompanyPage })));
// The Финансы and Дивиденды views with their own data, for the catalog terminal.
export const IssuerFinancials = lazy(() => import("./IssuerFinancials.jsx").then(module => ({ default: module.IssuerFinancials })));
export const InvestorView = lazy(() => import("./investor/InvestorView.jsx").then(module => ({ default: module.InvestorView })));
export const FinancialColumns = lazy(() => import("./FinancialColumns.jsx").then(module => ({ default: module.FinancialColumns })));
export const IssuerDividends = lazy(() => import("./IssuerDividends.jsx").then(module => ({ default: module.IssuerDividends })));
