import {test} from 'node:test';import assert from 'node:assert/strict';
import {matchesInterests,rankEvent} from '../frontend/src/features/news/eventPersonalization.js';
test('interests match disclosed topics and issuer sectors without matching unrelated stories',()=>{
 const bank={tickers:['HMKB'],category:'governance',title:{en:'Board changed'}};
 assert.equal(matchesInterests(bank,['banks'],{HMKB:{sector:'banks'}}),true);
 assert.equal(matchesInterests(bank,['insurance'],{HMKB:{sector:'banks'}}),false);
 assert.equal(matchesInterests({category:'dividends'},['dividends'],{}),true);
 assert.equal(matchesInterests({category:'reference'},['dividends'],{}),false);
});
test('personal ranking prioritizes holdings and confirmed approaching dates without changing the risk label',()=>{
 const near={priority:2,tickers:['HMKB'],event_date:'2026-10-27'};
 const distant={...near,event_date:'2026-12-01'};
 assert.ok(rankEvent(near,new Set(['HMKB']),'2026-10-26')>rankEvent(distant,new Set(),'2026-10-26'));
 assert.equal(near.priority,2);
});
