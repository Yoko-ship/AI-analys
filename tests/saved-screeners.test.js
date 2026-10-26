import test from 'node:test';
import assert from 'node:assert/strict';
import { readScreeners, saveScreener, removeScreener, matchesDirection } from '../frontend/src/features/market/savedScreeners.js';
const memory = () => { const map=new Map(); return {getItem:k=>map.get(k),setItem:(k,v)=>map.set(k,v)}; };
test('named filters survive reload and preserve sector, period and direction without market values',()=>{
 const storage=memory();
 saveScreener(storage,'Growing banks',{sector:'banks',direction:'gain',period:'1m',type:'ordinary',query:'',favoriteOnly:false,sortKeys:[{key:'change',dir:'desc'}],price:123});
 const [saved]=readScreeners(storage);
 assert.equal(saved.name,'Growing banks'); assert.equal(saved.filters.period,'1m'); assert.equal(saved.filters.direction,'gain');
 assert.equal(saved.filters.price,undefined);
 removeScreener(storage,saved.id); assert.deepEqual(readScreeners(storage),[]);
});
test('unavailable changes never pass gain/loss and flat is not declining',()=>{
 for(const n of [null,undefined,NaN,0]) { assert.equal(matchesDirection(n,'gain'),false);assert.equal(matchesDirection(n,'loss'),false); }
 assert.equal(matchesDirection(2,'gain'),true);assert.equal(matchesDirection(-2,'loss'),true);
});
test('corrupt storage is ignored and failed writes are not reported as saved',()=>{
 assert.deepEqual(readScreeners({getItem:()=>'{oops'}),[]);
 assert.throws(()=>saveScreener({getItem:()=>null,setItem:()=>{throw Error('full');}},'name',{}));
 assert.throws(()=>saveScreener(memory(),'   ',{}));
});
