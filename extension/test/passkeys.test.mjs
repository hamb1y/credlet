import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {validateRp,validateRequest,createPasskey,getPasskey,url64,fromUrl64,matchingPasskeys} from '../src/passkeys.js';
import {verifyRegistration,verifyAssertion} from '../../tests/verify_passkeys.mjs';
const encoded=()=>randomBytes(32).toString('base64url');
const origin='https://login.example.com';
const creation=()=>({rp:{id:'example.com',name:'Test service'},user:{id:encoded(),name:'alice',displayName:'Alice'},challenge:encoded(),
  pubKeyCredParams:[{type:'public-key',alg:-7}],authenticatorSelection:{residentKey:'required',userVerification:'required'},extensions:{credProps:true}});
const asJSON=r=>({id:r.id,rawId:r.rawId,type:'public-key',clientExtensionResults:r.extensions,
  response:{clientDataJSON:r.clientDataJSON,attestationObject:r.attestationObject,publicKey:r.publicKey,publicKeyAlgorithm:-7,
    authenticatorData:r.authenticatorData,signature:r.signature,userHandle:r.userHandle}});
function vault() {
  return {items:[],requireUnlocked(){},async savePasskey(credential){this.items.push({id:encoded(),login:{username:credential.userName,fido2Credentials:[credential]}});}};
}
test('RP ID checks reject public and private suffixes, unrelated domains and IPs',()=>{
  assert.equal(validateRp(origin,'example.com'),'example.com');assert.equal(validateRp(origin,null),'login.example.com');
  assert.equal(validateRp('https://localhost:444',null),'localhost');
  for(const [site,rp] of [[origin,'com'],[origin,'evil.com'],[origin,'example.com.evil.com'],['https://alice.github.io','github.io'],['https://127.0.0.1','127.0.0.1'],[origin,'example.com/'],[origin,'example.com.']]) {
    assert.throws(()=>validateRp(site,rp),e=>e.name==='SecurityError');
  }
  assert.equal(validateRp('https://alice.github.io','alice.github.io'),'alice.github.io');
});
test('real ES256 credentials verify independently; allow lists, exclusion and RP scoping hold',async()=>{
  const v=vault(), options=creation(), r=validateRequest('create',options,origin);
  const registration=await createPasskey(v,r);const json=asJSON(registration);
  const key=verifyRegistration(json,{origin,rpId:r.rpId,challenge:options.challenge});
  assert(!JSON.stringify(json).includes(v.items[0].login.fido2Credentials[0].keyValue));
  const challenge=encoded(), request=validateRequest('get',{challenge,rpId:r.rpId,allowCredentials:[{type:'public-key',id:registration.id}]},origin);
  assert.equal(matchingPasskeys(v,request).length,1);
  const assertion=asJSON(await getPasskey(v,request,registration.id));
  verifyAssertion(assertion,{origin,rpId:r.rpId,challenge,key,id:registration.id,userHandle:options.user.id});
  assert.equal(matchingPasskeys(v,{...request,rpId:'other.example.com'}).length,0);
  assert.equal(matchingPasskeys(v,{...request,credentials:[encoded()]}).length,0);
  assert.equal(matchingPasskeys(v,{...request,credentials:[]}).length,1);
  v.items[0].login.fido2Credentials[0].counter='3';assert.equal(matchingPasskeys(v,request).length,0);
  v.items[0].login.fido2Credentials[0].counter='0';
  await assert.rejects(createPasskey(v,{...r,credentials:[registration.id]}),e=>e.name==='InvalidStateError');
  await assert.rejects(getPasskey(v,request,encoded()),/No matching/);
  assert.deepEqual(fromUrl64(url64(new Uint8Array([0,255,128]))),new Uint8Array([0,255,128]));
});
test('unsupported hardware and algorithms request a native authenticator; expired consent cannot save',async()=>{
  const options=creation();
  assert.throws(()=>validateRequest('create',{...options,pubKeyCredParams:[{type:'public-key',alg:-257}]},origin),e=>e.name==='NotSupportedError');
  assert.throws(()=>validateRequest('create',{...options,attestation:'direct'},origin),e=>e.name==='NotSupportedError');
  const v=vault();await assert.rejects(createPasskey(v,validateRequest('create',options,origin),()=>{throw Error('Expired');}),/Expired/);
  assert.equal(v.items.length,0);
});
