import { lazy } from 'react';

export const CompanyComparison = lazy(() => import('./CompanyComparison.jsx').then(module => ({
  default: module.CompanyComparison,
})));
