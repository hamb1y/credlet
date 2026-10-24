import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import readline from 'node:readline';
import {randomBytes} from 'node:crypto';
import {deriveMaster,stretchMaster,encrypt} from '../src/crypto.js';

test('desktop unlock survives the auto-lock timer during a slow prelogin',async()=>{
  const email='fixture@example.com',password='disposable bridge fixture';
  const config={kdf:0,kdfIterations:600000};
  const master=await deriveMaster(password,email,config),stretched=await stretchMaster(master);
  let wrapped;const userKey=randomBytes(64);
  try {wrapped=await encrypt(userKey,stretched);}
  finally {master.fill(0);stretched.fill(0);}
  const cipher={id:'legacy-app',type:1,name:await encrypt('Legacy app',userKey),login:{
    username:await encrypt('alice',userKey),password:await encrypt('legacy-secret',userKey),
    uris:[{uri:await encrypt('lockbox-app://linux/%2Fopt%2Ffixture',userKey),match:3}]}};
  userKey.fill(0);
  // Keep the real Vault and bridge, replacing only the network boundary. The
  // delay guarantees a timer tick while no decrypted vault key exists yet.
  const shim=`globalThis.fetch=async(input)=>{
    const url=new URL(input);
    if(url.origin!=='https://vault.example.com')throw Error('Unexpected server');
    let value;
    if(url.pathname==='/identity/accounts/prelogin'){
      await new Promise(resolve=>setTimeout(resolve,1250));value=${JSON.stringify(config)};
    }else if(url.pathname==='/identity/connect/token'){
      value={key:${JSON.stringify(wrapped)},access_token:'fixture-token',expires_in:300};
    }else if(url.pathname==='/api/sync')value={profile:{id:'fixture-owner'},ciphers:[${JSON.stringify(cipher)}]};
    else throw Error('Unexpected request');
    return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
  };`;
  const child=spawn(process.execPath,['--import','data:text/javascript,'+encodeURIComponent(shim),
    fileURLToPath(new URL('../../desktop/bridge.mjs',import.meta.url))],{stdio:['pipe','pipe','pipe']});
  let errors='';child.stderr.on('data',data=>errors+=data);
  const lines=readline.createInterface({input:child.stdout})[Symbol.asyncIterator]();
  const timer=setTimeout(()=>child.kill(),10000);
  try {
    child.stdin.write(JSON.stringify({id:1,type:'login',server:'https://vault.example.com',email,password})+'\n');
    const response=await lines.next();assert.equal(response.done,false,errors);
    const result=JSON.parse(response.value);
    assert.equal(result.ok,true,result.error);assert.equal(result.value.unlocked,true);
    for(const [id,uri] of [[2,'credlet-app://linux/%2Fopt%2Ffixture'],[3,'lockbox-app://linux/%2Fopt%2Ffixture']]) {
      child.stdin.write(JSON.stringify({id,type:'fill',itemId:'legacy-app',appUri:uri,field:'password'})+'\n');
      const fill=JSON.parse((await lines.next()).value);assert.equal(fill.ok,true,fill.error);assert.equal(fill.value.value,'legacy-secret');
    }
    child.stdin.write(JSON.stringify({id:4,type:'link',itemId:'legacy-app',appUri:'credlet-app://linux/%2Fopt%2Ffixture'})+'\n');
    const linked=JSON.parse((await lines.next()).value);assert.equal(linked.ok,true,linked.error);
    assert.equal(linked.value.items[0].uris.length,1,'Renaming must not duplicate an existing native app link');
    child.stdin.write(JSON.stringify({id:5,type:'lock'})+'\n');
    const locked=JSON.parse((await lines.next()).value);
    assert.equal(locked.ok,true);assert.equal(locked.value.unlocked,false);assert.deepEqual(locked.value.items,[]);
    child.stdin.end();
    const [code]=await once(child,'exit');assert.equal(code,0,errors);
  }finally {clearTimeout(timer);if(child.exitCode===null)child.kill();}
});
