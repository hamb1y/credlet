// New client instance must decrypt and use a passkey created in the browser.
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {Vault} from '../extension/src/vault.js';
import {validateRequest,matchingPasskeys,getPasskey} from '../extension/src/passkeys.js';
import {verifyRegistration,verifyAssertion} from './verify_passkeys.mjs';
let input='';for await (const chunk of process.stdin) input+=chunk;
const fixture=JSON.parse(input),vault=new Vault();
try {
  await vault.login({server:process.env.TEST_SERVER,email:process.env.TEST_EMAIL,password:process.env.TEST_PASSWORD});
  await vault.verifyPassword(process.env.TEST_PASSWORD);
  const challenge=randomBytes(32).toString('base64url');
  const request=validateRequest('get',{challenge,rpId:fixture.rpId,allowCredentials:[]},fixture.origin);
  const found=matchingPasskeys(vault,request).find(c=>c.id===fixture.registration.id);
  assert(found,'New client cannot find the browser-created discoverable passkey');
  const r=await getPasskey(vault,request,found.id);
  const key=verifyRegistration(fixture.registration,fixture);
  verifyAssertion({id:r.id,rawId:r.rawId,type:'public-key',response:r},
    {...fixture,key,challenge,id:fixture.registration.id});
  process.stdout.write(JSON.stringify({id:found.itemId,passed:true}));
} finally {vault.lock();}
