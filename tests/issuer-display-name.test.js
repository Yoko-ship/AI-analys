import {test} from 'node:test';
import assert from 'node:assert/strict';
import {issuerDisplayName} from '../frontend/src/lib/issuerDisplayName.js';

test('issuer identity uses published short names and preserves full-name fallbacks',()=>{
  assert.equal(issuerDisplayName({company_name:'Full legal issuer',short_name:'Published short name'}),'Published short name');
  assert.equal(issuerDisplayName({company_name:'Full legal issuer',name:'Short issuer'}),'Short issuer');
  assert.equal(issuerDisplayName({name:'Universal Bank'}),'Universal Bank');
  assert.equal(issuerDisplayName({},'HMKB'),'HMKB');
});

test('quoted Uzbek legal names expose the issuer without splitting apostrophes',()=>{
  assert.equal(issuerDisplayName({name:'Chet el kapitali ishtirokidagi "Hamkorbank" aksiyadorlik tijorat banki'}),'Hamkorbank');
  assert.equal(issuerDisplayName({name:'“O‘zbekiston metallurgiya kombinati” aksiyadorlik jamiyati'}),'O‘zbekiston metallurgiya kombinati');
  assert.equal(issuerDisplayName({name:'"O\'zpartamponaj" aksiyadorlik jamiyati'}),"O'zpartamponaj");
  assert.equal(issuerDisplayName({name:"O'zbekiston pochtasi"}),"O'zbekiston pochtasi");
});
