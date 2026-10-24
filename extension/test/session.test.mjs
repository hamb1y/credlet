import test from 'node:test';
import assert from 'node:assert/strict';
import {Vault} from '../src/vault.js';
import {deriveMaster,stretchMaster,encrypt} from '../src/crypto.js';

test('locking during a pending network request rejects its response',async()=>{
  let complete,started;const waiting=new Promise(resolve=>started=resolve);
  const v=new Vault({fetcher:()=>new Promise(resolve=>{complete=resolve;started();})});
  v.server='https://vault.example.com';v.key=new Uint8Array(64);v.token='fixture';v.deadline=Date.now()+300000;
  const pending=v.sync();await waiting;v.lock();
  complete(new Response(JSON.stringify({profile:{id:'owner'},ciphers:[]})));
  await assert.rejects(pending,/locked/);assert.equal(v.key,null);assert.equal(v.userId,null);assert.deepEqual(v.items,[]);
});
test('a login interrupted during key derivation cannot unlock or replace a later session',async()=>{
  const email='fixture@example.com',password='disposable fixture',config={kdf:0,kdfIterations:600000};
  let signal;const tokenRequested=new Promise(resolve=>signal=resolve);let finish;
  const master=await deriveMaster(password,email,config),stretched=await stretchMaster(master);
  const wrapped=await encrypt(new Uint8Array(64).fill(9),stretched);master.fill(0);stretched.fill(0);
  const v=new Vault({fetcher:async url=>{
    if(url.endsWith('/prelogin'))return new Response(JSON.stringify(config));
    if(url.endsWith('/token')) {signal();return new Promise(resolve=>finish=()=>resolve(new Response(JSON.stringify({key:wrapped,access_token:'old-token',expires_in:300}))));}
    throw Error('Unexpected request');
  }});
  const pending=v.login({server:'https://vault.example.com',email,password});
  await tokenRequested;v.lock();
  // A newer session must survive the old login's eventual rejection.
  const key=new Uint8Array(64).fill(4);v.key=key;v.token='new-token';v.server='https://new.example.com';v.deadline=Date.now()+300000;
  finish();await assert.rejects(pending,/locked/);
  assert.equal(v.key,key);assert.equal(v.token,'new-token');assert.equal(v.server,'https://new.example.com');
});

test('successful empty-body mutation responses are accepted while malformed JSON is rejected',async()=>{
  const v=new Vault({fetcher:async()=>new Response('',{status:200})});
  v.server='https://vault.example.com';v.key=new Uint8Array(64);v.token='fixture';v.deadline=Date.now()+300000;
  assert.deepEqual(await v.request('/api/ciphers/fixture/delete',{method:'PUT',authenticated:true}),{});
  v.fetcher=async()=>new Response('<html>Not a vault</html>',{status:200});
  await assert.rejects(v.request('/api/sync',{method:'GET',authenticated:true}),/invalid response/);
});
