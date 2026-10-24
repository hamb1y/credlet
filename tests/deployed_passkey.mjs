// Exercise encrypted passkey storage against the real container deployment.
// Browser UI ceremonies are tested separately by firefox_client.py.
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {Vault} from '../extension/src/vault.js';
import {validateRequest,createPasskey,getPasskey,matchingPasskeys} from '../extension/src/passkeys.js';
import {verifyCeremony} from './verify_passkeys.mjs';
const encoded=()=>randomBytes(32).toString('base64url');
const json=r=>({id:r.id,rawId:r.rawId,type:'public-key',clientExtensionResults:r.extensions,
  response:{clientDataJSON:r.clientDataJSON,attestationObject:r.attestationObject,publicKey:r.publicKey,
    publicKeyAlgorithm:-7,authenticatorData:r.authenticatorData,signature:r.signature,userHandle:r.userHandle}});
const login={server:process.env.TEST_SERVER,email:process.env.TEST_EMAIL,password:process.env.TEST_PASSWORD};
const vault=new Vault(),fresh=new Vault();
try {
  await vault.login(login);await vault.verifyPassword(login.password);
  const origin='https://login.example.com',rpId='example.com',challenge=encoded(),userHandle=encoded();
  const registration=json(await createPasskey(vault,validateRequest('create',{
    rp:{id:rpId,name:'Container fixture'},user:{id:userHandle,name:'passkey-user',displayName:'Container test'},
    challenge,pubKeyCredParams:[{type:'public-key',alg:-7}],
    authenticatorSelection:{residentKey:'required',userVerification:'required'},extensions:{credProps:true}},origin)));
  vault.lock();await fresh.login(login);await fresh.verifyPassword(login.password);
  const assertionChallenge=encoded();
  const request=validateRequest('get',{challenge:assertionChallenge,rpId,allowCredentials:[]},origin);
  const found=matchingPasskeys(fresh,request).find(c=>c.id===registration.id);assert(found);
  const assertion=json(await getPasskey(fresh,request,found.id));
  const ceremony={origin,rpId,challenge,userHandle,assertionChallenge,registration,assertion};
  verifyCeremony(ceremony);
  process.stdout.write(JSON.stringify({id:found.itemId,ceremony}));
} finally {vault.lock();fresh.lock();}
