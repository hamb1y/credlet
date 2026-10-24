import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {Vault} from '../src/vault.js';
import {encrypt,decryptText} from '../src/crypto.js';

test('editing an imported cipher uses its item key and preserves passkeys, attachments, fields and extra URIs',async()=>{
  const v=new Vault();v.key=new Uint8Array(randomBytes(64));v.userId='owner';v.deadline=Date.now()+300000;
  const itemKey=new Uint8Array(randomBytes(64)),key=await encrypt(itemKey,v.key);
  const raw={id:'fixture',type:1,key,revisionDate:'2026-10-23T00:00:00Z',reprompt:0,name:await encrypt('Old',itemKey),
    notes:await encrypt('Private notes',itemKey),fields:[{name:'encrypted',value:'also encrypted'}],attachments:[{id:'attachment'}],
    favorite:true,login:{username:await encrypt('Old',itemKey),password:await encrypt('Old',itemKey),
      fido2Credentials:[{keyValue:'existing encrypted private key'}],uris:[{uri:await encrypt('https://old.example.com',itemKey),match:1},
        {uri:await encrypt('androidapp://com.example',itemKey),match:0}]}};
  v.rawItems=[raw];let sent;
  v.request=async(path,options)=>{sent={path,...options};};v.sync=async()=>[];
  await v.saveLogin({name:'Changed',username:'alice',password:'new secret',totp:'GEZDGNBV',uri:'https://new.example.com'},raw.id);
  assert.equal(sent.path,'/api/ciphers/fixture');assert.equal(sent.method,'PUT');
  assert.equal(sent.body.lastKnownRevisionDate,raw.revisionDate);assert.equal(sent.body.encryptedFor,'owner');
  for (const field of ['key','notes','fields','attachments','favorite']) assert.deepEqual(sent.body[field],raw[field]);
  assert.deepEqual(sent.body.login.fido2Credentials,raw.login.fido2Credentials);
  assert.deepEqual(sent.body.login.uris[1],raw.login.uris[1]);
  assert.equal(await decryptText(sent.body.login.password,itemKey),'new secret');
  assert.equal(await decryptText(sent.body.name,itemKey),'Changed');
  await assert.rejects(decryptText(sent.body.login.password,v.key),/authentication failed/);
});
test('trash uses recoverable deletion and protected or missing items cannot be changed',async()=>{
  const v=new Vault();v.key=new Uint8Array(64);v.deadline=Date.now()+300000;
  v.items=[{id:'normal'},{id:'protected',reprompt:1}];let request;
  v.request=async(path,options)=>{request={path,...options};};v.sync=async()=>[];
  await v.deleteLogin('normal');assert.equal(request.path,'/api/ciphers/normal/delete');assert.equal(request.method,'PUT');
  await assert.rejects(v.deleteLogin('protected'),/cannot be deleted/);await assert.rejects(v.deleteLogin('missing'),/cannot be deleted/);
  v.rawItems=[{id:'protected',reprompt:1}];await assert.rejects(v.saveLogin({name:'overwrite'},'protected'),/cannot be edited/);
  await assert.rejects(v.saveLogin({name:'overwrite'},'missing'),/cannot be edited/);
});

test('editing a username preserves exact website rules and app links; clearing a website removes only that website',async()=>{
  const v=new Vault();v.key=new Uint8Array(randomBytes(64));v.userId='owner';v.deadline=Date.now()+300000;
  const addresses=[['lockbox-app://linux/%2Fopt%2Ffixture',3],['https://example.com/account?mode=login',3],['https://other.example.com/',5]];
  const raw={id:'fixture',type:1,reprompt:0,name:await encrypt('Fixture',v.key),login:{uris:await Promise.all(addresses.map(async([uri,match])=>({uri:await encrypt(uri,v.key),match})))}};
  v.rawItems=[raw];let body;v.request=async(path,options)=>{body=options.body;};v.sync=async()=>[];
  await v.saveLogin({name:'Fixture',username:'changed',uri:addresses[1][0]},'fixture');
  assert.deepEqual(body.login.uris,raw.login.uris,'Unchanged exact URI must not broaden to an origin rule');
  await v.saveLogin({name:'Fixture',username:'changed',uri:''},'fixture');
  assert.deepEqual(body.login.uris,[raw.login.uris[0],raw.login.uris[2]]);
});
test('website-free logins are supported and invalid URLs or authenticator secrets cannot be saved',async()=>{
  const v=new Vault();v.key=new Uint8Array(randomBytes(64));v.userId='owner';v.deadline=Date.now()+300000;
  let calls=0;v.request=async()=>{calls++;};v.sync=async()=>[];
  await v.saveLogin({name:'Native app',username:'alice',password:'secret',uri:''});assert.equal(calls,1);
  for(const uri of ['http://example.com','https://user:secret@example.com','not a URL']) await assert.rejects(v.saveLogin({name:'Invalid',uri}),/HTTPS/);
  await assert.rejects(v.saveLogin({name:'Invalid',totp:'invalid0'}),/Invalid authenticator/);
  await assert.rejects(v.saveLogin({name:'  '}),/Give the login a name/);
  assert.equal(calls,1,'Invalid inputs must not reach the server');
});
