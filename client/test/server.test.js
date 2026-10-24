import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,readFile,rm,stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import nacl from 'tweetnacl';
import {Transport} from '../lib/transport.js';
import {Vault,matchesOrigin} from '../lib/vault.js';
import {controller} from '../lib/controller.js';
import {b64,unb64,utf8,random,seal,open,totp} from '../lib/crypto.js';

const executable=process.env.CREDLET_SERVER || path.resolve('server/build-v3/credlet-server'+(process.platform==='win32'?'.exe':''));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function port() { const server=net.createServer(); await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve)); const value=server.address().port; await new Promise(resolve=>server.close(resolve)); return value; }
async function fixture(t) {
  const folder=await mkdtemp(path.join(tmpdir(),'credlet c server ')), state=path.join(folder,'state');
  const init=spawnSync(executable,['init','--state',state,'--owner','owner@example.com'],{encoding:'utf8'});
  assert.equal(init.status,0,init.stderr);
  const pairing=JSON.parse(init.stdout), number=await port(), server='http://127.0.0.1:'+number;
  let logs='';
  const child=spawn(executable,['serve','--state',state,'--port',String(number)],{stdio:['ignore','pipe','pipe']});
  child.stderr.on('data',chunk=>{logs+=chunk;});
  t.after(async()=>{
    child.kill('SIGTERM'); await new Promise(resolve=>{if(child.exitCode!==null)resolve();else child.once('exit',resolve);});
    assert.doesNotMatch(logs,/AddressSanitizer|runtime error:|LeakSanitizer/);
    await rm(folder,{recursive:true,force:true});
  });
  for(let i=0;i<100;i++) {
    try { if((await fetch(server+'/health')).ok) return {folder,state,server,...pairing,child}; } catch {}
    if(child.exitCode!==null) throw Error(logs);
    await pause(30);
  }
  throw Error('Server did not start: '+logs);
}
function packet(serverKey,{id=crypto.randomUUID(),issuedAt=Math.floor(Date.now()/1000),action='config',data={},token=null,direction='request'}={}) {
  const pair=nacl.box.keyPair(), nonce=random(24);
  const plain=utf8(JSON.stringify({v:1,id,issuedAt,action,data,token,direction}));
  return {pair,id,envelope:{v:1,key:b64(pair.publicKey),nonce:b64(nonce),box:b64(nacl.box(plain,nonce,unb64(serverKey,32),pair.secretKey))}};
}
async function send(server,envelope) { return fetch(server+'/v1/exchange',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(envelope)}); }

test('C server and unified client: encrypted HTTP, enrollment, two clients, conflicts, backup and deletion',async t=>{
  const f=await fixture(t), wire=[];
  const exchange=async(origin,envelope)=>{
    wire.push(JSON.stringify(envelope));
    const response=await send(origin,envelope); assert.equal(response.status,200); const value=await response.json();wire.push(JSON.stringify(value));return value;
  };
  const a=new Vault({exchange}), b=new Vault();
  const login={server:f.server,serverKey:f.serverKey,email:'owner@example.com',password:'my disposable master secret 892!'};
  await a.login({...login,enrollmentToken:f.enrollmentToken});
  assert.equal(a.items.length,0);assert.ok(a.key);
  await a.saveLogin({name:'Private fixture name',username:'secret-owner',password:'fixture-vault-password-6628',uri:'https://example.com/login',notes:'encrypted private notes',totp:'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'});
  await b.login(login); assert.equal(b.items[0].login.password,'fixture-vault-password-6628');
  assert.notEqual(b.key,a.key);assert.deepEqual(b.key,a.key);
  const id=a.items[0].id;
  await a.saveLogin({name:'Renamed fixture',username:'changed',password:'changed password',uri:'https://example.com/login'},id);
  await assert.rejects(b.saveLogin({name:'stale update',uri:''},id),/changed on another client/);
  await b.sync();assert.equal(b.items[0].name,'Renamed fixture');
  await a.savePasskey({rpName:'Example',userName:'alice',keyValue:'secret-passkey-material',credentialId:'test-passkey'},'https://example.com');
  await b.sync();assert.equal(b.items[1].login.fido2Credentials?.[0]?.keyValue || b.items[0].login.fido2Credentials?.[0]?.keyValue,'secret-passkey-material');
  const transport=new Transport(login);
  await assert.rejects(transport.request('enroll',{email:login.email,authKey:b64(random(32)),enrollmentToken:f.enrollmentToken,wrappedKey:seal('key',random(32),'vault-key:v1')}),e=>e.status===401);
  await assert.rejects(transport.request('sync'),e=>e.status===401);
  const backup=path.join(f.folder,'private backup.sqlite3');
  const result=spawnSync(executable,['backup','--state',f.state,'--output',backup],{encoding:'utf8'});assert.equal(result.status,0,result.stderr);
  assert.equal(spawnSync(executable,['backup','--state',f.state,'--output',backup]).status,1);
  const disk=Buffer.concat(await Promise.all([readFile(path.join(f.state,'vault.sqlite3')),readFile(backup)]));
  const observed=wire.join('\n');
  for(const secret of [login.password,'fixture-vault-password-6628','Private fixture name','secret-owner','encrypted private notes','secret-passkey-material',f.enrollmentToken]) {
    assert.ok(!disk.includes(Buffer.from(secret)),secret+' leaked to database');assert.ok(!observed.includes(secret),secret+' leaked to HTTP');
  }
  if(process.platform!=='win32') { assert.equal((await stat(f.state)).mode&0o777,0o700);assert.equal((await stat(backup)).mode&0o777,0o600); }
  await a.deleteLogin(id); await b.sync(); assert.ok(!b.items.some(i=>i.id===id));
  const token=a.token; await a.logout();assert.equal(a.key,null);
  await assert.rejects(transport.request('sync',{},token),e=>e.status===401);
  const repeat=spawnSync(executable,['init','--state',f.state,'--owner',login.email]);assert.equal(repeat.status,1);
  const restored=path.join(f.folder,'restored');
  const recovery=spawnSync(executable,['restore','--state',restored,'--input',backup],{encoding:'utf8'});assert.equal(recovery.status,0,recovery.stderr);
  assert.equal(JSON.parse(spawnSync(executable,['pair','--state',restored],{encoding:'utf8'}).stdout).serverKey,f.serverKey);
  assert.equal(spawnSync(executable,['restore','--state',restored,'--input',backup]).status,1);
  const recoveredPort=await port();
  const recovered=spawn(executable,['serve','--state',restored,'--port',String(recoveredPort)],{stdio:['ignore','ignore','pipe']});
  let recoveryLog=''; recovered.stderr.on('data',chunk=>{recoveryLog+=chunk;});
  try {
    const server='http://127.0.0.1:'+recoveredPort;
    for(let i=0;i<100;i++) { try { if((await fetch(server+'/health')).ok) break; } catch {} await pause(30); }
    const restoredTransport=new Transport({...login,server});
    await assert.rejects(restoredTransport.request('sync',{},token),e=>e.status===401);
    const client=new Vault();await client.login({...login,server});
    assert.ok(client.items.some(i=>i.id===id),'Backup did not restore the pre-deletion record');
    assert.ok(client.items.some(i=>i.login.fido2Credentials?.[0]?.keyValue==='secret-passkey-material'));
  } finally {
    recovered.kill('SIGTERM');await new Promise(resolve=>{if(recovered.exitCode!==null)resolve();else recovered.once('exit',resolve);});
    assert.doesNotMatch(recoveryLog,/AddressSanitizer|runtime error:|LeakSanitizer/);
  }
});

test('channel rejects tampering, wrong pins, stale/replayed requests, reflection, and unauthenticated plaintext',async t=>{
  const f=await fixture(t);
  const transport=new Transport({server:f.server,serverKey:f.serverKey});
  assert.ok((await transport.request('config')).salt);
  await assert.rejects(new Transport({server:f.server,serverKey:b64(nacl.box.keyPair().publicKey)}).request('config'),/rejected/);
  const p=packet(f.serverKey), first=await send(f.server,p.envelope);assert.equal(first.status,200);
  const duplicate=await (await send(f.server,p.envelope)).json();
  const decoded=nacl.box.open(unb64(duplicate.box),unb64(duplicate.nonce),unb64(f.serverKey),p.pair.secretKey);
  assert.equal(JSON.parse(new TextDecoder().decode(decoded)).status,409);
  const expired=packet(f.serverKey,{issuedAt:1}), expiry=await (await send(f.server,expired.envelope)).json();
  assert.equal(JSON.parse(new TextDecoder().decode(nacl.box.open(unb64(expiry.box),unb64(expiry.nonce),unb64(f.serverKey),expired.pair.secretKey))).status,408);
  const modified=structuredClone(p.envelope); const raw=unb64(modified.box);raw[0]^=1;modified.box=b64(raw);
  assert.equal((await send(f.server,modified)).status,400);
  assert.equal((await send(f.server,packet(f.serverKey,{direction:'response'}).envelope)).status,400);
  assert.equal((await send(f.server,{action:'login',password:'plaintext'})).status,400);
  assert.equal((await fetch(f.server+'/identity/connect/token',{method:'POST',body:'password=plaintext'})).status,404);
  assert.equal((await fetch(f.server+'/')).status,404);
  const reflected=new Transport({server:f.server,serverKey:f.serverKey,exchange:async(_origin,envelope)=>envelope});
  await assert.rejects(reflected.request('config'),/replayed server response/);
  for(const body of ['null','[]','{"v":1}','{"v":1}junk','"hello"']) {
    const response=await fetch(f.server+'/v1/exchange',{method:'POST',body});assert.equal(response.status,400);
  }
});

test('record authentication binds context and rejects substitution; exact origin matching and RFC TOTP survive',async()=>{
  const key=random(32), envelope=seal({password:'private'},key,'item:v1:first');
  assert.deepEqual(open(envelope,key,'item:v1:first'),{password:'private'});
  assert.throws(()=>open(envelope,key,'item:v1:second'),/authenticated/);
  assert.throws(()=>open(envelope,random(32),'item:v1:first'),/authenticated/);
  assert.equal(matchesOrigin({uris:[{uri:'https://example.com/path',match:3}]},'https://example.com/else'),false);
  assert.equal(matchesOrigin({uris:[{uri:'https://example.com/path',match:1}]},'https://example.com/else'),true);
  assert.equal(matchesOrigin({uris:[{uri:'https://example.com',match:1}]},'http://example.com'),false);
  assert.equal((await totp('otpauth://totp/fixture?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8',59000)).code,'94287082');
});

test('paginated sync retains all records and an interrupted login cannot unlock a new session',async t=>{
  const f=await fixture(t);
  const login={server:f.server,serverKey:f.serverKey,email:'owner@example.com',password:'long disposable pagination password'};
  const vault=new Vault();await vault.login({...login,enrollmentToken:f.enrollmentToken});
  const transport=new Transport(login);
  for(let i=0;i<70;i++) {
    const id=crypto.randomUUID();
    const item={id,name:'Page fixture '+i,login:{username:'fixture',password:'encrypted',uris:[],fido2Credentials:[]}};
    await transport.request('put',{id,revision:0,payload:seal(item,vault.key,'item:v1:'+id)},vault.token);
  }
  await vault.sync(); assert.equal(vault.items.length,70);assert.equal(new Set(vault.items.map(i=>i.id)).size,70);
  let release,entered;
  const pending=new Promise(resolve=>{release=resolve;}), started=new Promise(resolve=>{entered=resolve;});
  const delayed=new Vault({exchange:async(origin,envelope)=>{entered();await pending;return (await send(origin,envelope)).json();}});
  const attempt=delayed.login(login);
  await started;delayed.lock();release();
  await assert.rejects(attempt,/locked/);assert.equal(delayed.key,null);
  const savedToken=vault.token;await vault.logout();
  await assert.rejects(transport.request('sync',{},savedToken),e=>e.status===401);
});

test('reading status during an in-flight unlock does not cancel its key derivation',async t=>{
  const f=await fixture(t);
  let release,entered;
  const pending=new Promise(resolve=>{release=resolve;}), started=new Promise(resolve=>{entered=resolve;});
  let first=true;
  const vault=new Vault({exchange:async(origin,envelope)=>{
    if(first) { first=false; entered(); await pending; }
    return (await send(origin,envelope)).json();
  }});
  const core=controller({vault});
  const attempt=core.dispatch({type:'login',server:f.server,serverKey:f.serverKey,email:'owner@example.com',
    password:'disposable status race master',enrollmentToken:f.enrollmentToken});
  await started;
  try { assert.equal((await core.status()).unlocked,false); }
  finally { release(); }
  assert.equal((await attempt).unlocked,true);
  await vault.logout();
});
