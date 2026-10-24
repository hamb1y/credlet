// Independent relying-party checks using Node's crypto implementation.
import assert from 'node:assert/strict';
import {createHash,createPublicKey,verify} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const bin=s=>Buffer.from(s,'base64url');
const hash=b=>createHash('sha256').update(b).digest();
function decodeCbor(buffer,start=0) {
  let pos=start;
  function read() {
    const tag=buffer[pos++],major=tag>>5,ai=tag&31;
    let n=ai;
    if (ai===24) n=buffer[pos++];
    else if (ai===25) {n=buffer.readUInt16BE(pos);pos+=2;}
    else if (ai>=26) throw Error('Unexpected CBOR length');
    if (major===0) return n;
    if (major===1) return -1-n;
    if (major===2||major===3) {const b=buffer.subarray(pos,pos+n);pos+=n;return major===3?b.toString():b;}
    if (major===5) {const m=new Map();for(let i=0;i<n;i++)m.set(read(),read());return m;}
    throw Error('Unexpected CBOR type');
  }
  const value=read();return {value,end:pos};
}
function client(value,kind,challenge,origin) {
  const data=JSON.parse(bin(value.response.clientDataJSON));
  assert.equal(data.type,'webauthn.'+kind);assert.equal(data.challenge,challenge);assert.equal(data.origin,origin);assert.equal(data.crossOrigin,false);
  assert.equal(value.type,'public-key');assert.equal(value.id,value.rawId);
}
function auth(b,rpId,attested,backedUp=true,counter=0) {
  assert.deepEqual(b.subarray(0,32),hash(rpId));
  assert.equal(b[32],(attested?0x45:0x05)+(backedUp?0x18:0)); // user present, user verified, backed up, backup eligible; registration includes credential
  assert.equal(b.readUInt32BE(33),counter);
}
export function verifyRegistration(value,{challenge,origin,rpId,backedUp=true,registrationCounter=0,aaguid='00000000000000000000000000000000',credProps=true}) {
  client(value,'create',challenge,origin);
  const {value:att,end}=decodeCbor(bin(value.response.attestationObject));
  assert.equal(end,bin(value.response.attestationObject).length);assert.equal(att.get('fmt'),'none');assert.equal(att.get('attStmt').size,0);
  const data=att.get('authData');auth(data,rpId,true,backedUp,registrationCounter);
  assert.deepEqual(data.subarray(37,53),Buffer.from(aaguid,'hex'));
  const length=data.readUInt16BE(53);assert.deepEqual(data.subarray(55,55+length),bin(value.rawId));
  const {value:cose,end:coseEnd}=decodeCbor(data,55+length);assert.equal(coseEnd,data.length);
  assert.equal(cose.get(1),2);assert.equal(cose.get(3),-7);assert.equal(cose.get(-1),1);
  const key=createPublicKey({format:'jwk',key:{kty:'EC',crv:'P-256',x:cose.get(-2).toString('base64url'),y:cose.get(-3).toString('base64url')}});
  assert.deepEqual(key.export({format:'der',type:'spki'}),bin(value.response.publicKey));
  assert.equal(value.response.publicKeyAlgorithm,-7);
  assert.deepEqual(data,bin(value.response.authenticatorData));
  if(credProps)assert.equal(value.clientExtensionResults.credProps.rk,true);
  else assert.equal(value.clientExtensionResults.credProps,undefined);
  return key;
}
export function verifyAssertion(value,{key,challenge,origin,rpId,id,userHandle,backedUp=true,counter=0}) {
  client(value,'get',challenge,origin);assert.equal(value.id,id);assert.equal(value.response.userHandle,userHandle);
  const data=bin(value.response.authenticatorData);auth(data,rpId,false,backedUp,counter);assert.equal(data.length,37);
  assert(verify('sha256',Buffer.concat([data,hash(bin(value.response.clientDataJSON))]),key,bin(value.response.signature)),'Relying party rejected the assertion signature');
}
export function verifyCeremony(fixture) {
  const key=verifyRegistration(fixture.registration,fixture);
  verifyAssertion(fixture.assertion,{...fixture,key,challenge:fixture.assertionChallenge,id:fixture.registration.id,counter:fixture.assertionCounter || 0});
}
if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  let data='';for await (const chunk of process.stdin) data+=chunk;
  if(process.argv.includes('--registration-only'))verifyRegistration(JSON.parse(data).registration,JSON.parse(data));
  else verifyCeremony(JSON.parse(data));
  process.stdout.write('PASS independent relying-party checks\n');
}
