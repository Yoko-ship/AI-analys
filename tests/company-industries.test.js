import assert from 'node:assert/strict';
import {test} from 'node:test';
import {industryOf, buildIssuerTree} from '../frontend/src/lib/companyIndustries.js';
import {sectorOf} from '../frontend/src/lib/sectors.js';
import {groupMarketIndustries, matchesMarketIndustry} from '../frontend/src/lib/marketIndustries.js';

test('market hierarchy includes only present securities, keeps share classes and unknown listings', () => {
  const rows = ['IPTB', 'IPTBP', 'UZNF', 'DORI', 'CBSK', 'UZGFP', 'NEW'].map(ticker => ({ticker}));
  const securities = {DORI: {sector: 'manufacturing'}, UZGFP: {sector: 'mining'}, NEW: {sector: 'agriculture'}};
  const sections = groupMarketIndustries(rows, securities);
  assert.deepEqual(sections.find(s => s.sector === 'finance').groups.map(g => g.id), ['banks', 'funds']);
  assert.deepEqual(sections.find(s => s.sector === 'trade').groups.map(g => g.id), ['trading-complexes', 'pharma-wholesale']);
  assert.deepEqual(sections.find(s => s.sector === 'professional').groups[0].rows, [{ticker: 'UZGFP'}]);
  assert.deepEqual(sections.find(s => s.sector === 'agriculture').groups[0].rows, [{ticker: 'NEW'}]);
  assert.equal(sections.flatMap(s => s.groups.flatMap(g => g.rows)).length, rows.length);
  assert.deepEqual(groupMarketIndustries([], securities), []);
});

test('sector and subgroup selection share one rule, including aliases and unreviewed fallbacks', () => {
  for (const ticker of ['IPTB', 'IPTBP', 'TNGB']) assert.equal(matchesMarketIndustry(ticker, 'group:banks'), true);
  assert.equal(matchesMarketIndustry('UZNF', 'finance'), true);
  assert.equal(matchesMarketIndustry('UZNF', 'group:banks'), false);
  assert.equal(matchesMarketIndustry('UZNF', 'group:funds'), true);
  assert.equal(matchesMarketIndustry('BNGP', 'group:well-services'), true);
  assert.equal(matchesMarketIndustry('BNGPP', 'group:well-services'), true);
  assert.equal(matchesMarketIndustry('BNG', 'group:well-services'), false);
  assert.equal(matchesMarketIndustry('NEW', 'mining', {NEW: {sector: 'mining'}}), true);
  assert.equal(matchesMarketIndustry('NEW', 'group:nonexistent'), false);
  assert.equal(matchesMarketIndustry('NEW', null), true);
});

test('curated industry wins over stale catalogs without losing future sectors', () => {
  assert.equal(sectorOf('DORI', {DORI: {sector: 'manufacturing'}}), 'trade');
  assert.equal(sectorOf('PLSTP', {PLSTP: {sector: 'mining'}}), 'manufacturing');
  assert.equal(sectorOf('UZGF', {UZGF: {sector: 'mining'}}), 'professional');
  assert.equal(sectorOf('METQ', {METQ: {sector: 'other'}}), 'construction');
  assert.equal(sectorOf('NEW', {NEW: {sector: 'agriculture'}}), 'agriculture');
  assert.equal(industryOf('bngp').issuer_id, industryOf('BNGPP').issuer_id);
  assert.equal(industryOf('BNG'), null);
});

test('search by preferred ISIN keeps one issuer and both distinct share prices', () => {
  const tree = buildIssuerTree({securitiesMap: {IPTB: {isin: 'ordinary'}, IPTBP: {isin: 'preferred-isin'}}, query: 'preferred-isin'});
  assert.equal(tree.length, 1);
  assert.equal(tree[0].sector, 'finance');
  const issuers = tree[0].groups[0].issuers;
  assert.equal(issuers.length, 1);
  assert.deepEqual(issuers[0].securities.map(s => s.ticker), ['IPTB', 'IPTBP']);
});

test('directory includes the document, preserves unknown issuers and excludes bonds from every source', () => {
  const tree = buildIssuerTree({companies: [{ticker: 'NEW', company_name: 'New issuer'}, {ticker: 'BOND', type: 'bond'}], securitiesMap: {BOND2: {type: 'bond'}}});
  const issuers = tree.flatMap(s => s.groups.flatMap(g => g.issuers));
  assert.equal(issuers.length, 70);
  assert.equal(issuers.flatMap(i => i.securities).length, 103);
  assert.equal(issuers.find(i => i.id === 'NEW').status, 'unclassified');
  assert.equal(issuers.find(i => i.id === 'CBSK').oked, null);
  assert.equal(issuers.find(i => i.id === 'ORGS').status, 'conflict');
});

test('Tenge catalog alias joins its listed security without duplicating an issuer or security', () => {
  const tree = buildIssuerTree({companies: [{ticker: 'TNGB', company_name: '"Tenge Bank" ATB'}],
    securitiesMap: {TGBK: {isin: 'UZ7056730011'}}, query: 'TNGB'});
  const issuers = tree.flatMap(s => s.groups.flatMap(g => g.issuers));
  assert.equal(issuers.length, 1);
  assert.equal(issuers[0].id, 'TGBK');
  assert.deepEqual(issuers[0].securities.map(s => s.ticker), ['TGBK']);
  assert.equal(issuers[0].securities[0].isin, 'UZ7056730011');
});
