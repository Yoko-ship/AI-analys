import {industryGroups, industrySections, industryLabel} from '../lib/companyIndustries.js';
import {sectorLabel} from './marketCopy.jsx';

export function marketIndustryLabel(language, selection) {
  if (!selection) return sectorLabel(language, 'all');
  const labels = selection.startsWith('group:')
    ? industryGroups[selection.slice(6)]?.label : industrySections[selection]?.label;
  return industryLabel(labels, language) || sectorLabel(language, selection);
}
