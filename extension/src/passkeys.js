import {parse} from 'tldts';
import {b64, unb64, bytes, utf8, concat, random} from './crypto.js';

export const url64 = value => b64(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
export function fromUrl64(value) {
  if (typeof value !== 'string' || !/^[\w+/=-]*$/.test(value)) throw Error('Invalid encoded credential data.');
  return unb64(value.replace(/-/g, '+').replace(/_/g, '/'));
}
function fail(message, name = 'NotAllowedError') { const e = Error(message); e.name = name; throw e; }
function encoded(value, min, max) {
  let decoded;try { decoded=fromUrl64(value); } catch { fail('Invalid public-key request.','TypeError'); }
  if (decoded.length < min || decoded.length > max) fail('Invalid public-key request.', 'TypeError');
  return url64(decoded);
}
function label(value, fallback = '') {
  if (value == null) return fallback;
  if (typeof value !== 'string' || value.length > 1024) fail('Invalid account name.', 'TypeError');
  return value;
}
export function validateRp(origin, value) {
  const site = new URL(origin);
  if (site.protocol !== 'https:' || site.username || site.password) fail('Passkeys require an HTTPS page.', 'SecurityError');
  const host = site.hostname;
  const rp = value == null ? host : value;
  if (typeof rp !== 'string' || !rp || rp.length > 253 || rp.endsWith('.') || /[\s/:@?#\\]/.test(rp)) fail('Invalid relying party.', 'SecurityError');
  let canonical;try { canonical=new URL('https://'+rp).hostname; } catch { fail('Invalid relying party.','SecurityError'); }
  if (canonical !== host && !host.endsWith('.' + canonical)) fail('The relying party does not match this page.', 'SecurityError');
  const parsed = parse(canonical, {allowPrivateDomains:true});
  if (canonical !== 'localhost' && (!parsed.domain || parsed.isIp || canonical === parsed.publicSuffix)) {
    fail('A public suffix or IP address cannot be a relying party.', 'SecurityError');
  }
  return canonical;
}
export function validateRequest(kind, options, origin) {
  if (!['create','get'].includes(kind) || !options || typeof options !== 'object') fail('Invalid public-key request.', 'TypeError');
  const rpId = validateRp(origin, kind === 'create' ? options.rp?.id : options.rpId);
  const result = {kind, origin:new URL(origin).origin, rpId, challenge:encoded(options.challenge, 16, 1024),
    timeout:Math.min(120000, Math.max(15000, Number(options.timeout) || 60000)),
    credProps:!!options.extensions?.credProps};
  const descriptors = kind === 'create' ? options.excludeCredentials : options.allowCredentials;
  if (descriptors != null && (!Array.isArray(descriptors) || descriptors.length > 128)) fail('Too many credential descriptors.', 'TypeError');
  result.credentials = (descriptors || []).filter(d => d.type === 'public-key').map(d => encoded(d.id, 1, 1024));
  if (kind === 'create') {
    if (!options.pubKeyCredParams?.some(p => p.type === 'public-key' && p.alg === -7)) fail('Use your device for this public-key algorithm.', 'NotSupportedError');
    if (options.authenticatorSelection?.authenticatorAttachment === 'cross-platform' || ['direct','enterprise'].includes(options.attestation)) {
      fail('Use your device for hardware attestation or an external authenticator.', 'NotSupportedError');
    }
    result.user = {id:encoded(options.user?.id, 1, 64), name:label(options.user?.name), displayName:label(options.user?.displayName)};
    result.rpName = label(options.rp?.name, rpId);
    const choice = options.authenticatorSelection;
    result.discoverable = choice?.residentKey !== 'discouraged' || !!choice?.requireResidentKey;
  }
  return result;
}
// Small deterministic CBOR encoder for WebAuthn's attestation and EC2 public-key maps.
export function cbor(value) {
  const head = (major, n) => n < 24 ? new Uint8Array([major*32+n]) : n < 256 ? new Uint8Array([major*32+24,n]) :
    n < 65536 ? new Uint8Array([major*32+25,n>>8,n&255]) : fail('CBOR value too large.');
  if (Number.isSafeInteger(value)) return value >= 0 ? head(0,value) : head(1,-1-value);
  if (typeof value === 'string') { const b=utf8(value); return concat(head(3,b.length),b); }
  if (value instanceof Uint8Array) return concat(head(2,value.length),value);
  if (value instanceof Map) return concat(head(5,value.size),...Array.from(value,([k,v])=>concat(cbor(k),cbor(v))));
  if (Array.isArray(value)) return concat(head(4,value.length),...value.map(cbor));
  if (typeof value === 'boolean') return new Uint8Array([value ? 245 : 244]);
  fail('Unsupported CBOR value.');
}
const sha256 = async value => bytes(await crypto.subtle.digest('SHA-256',value));
const clientData = r => utf8(JSON.stringify({type:'webauthn.'+(r.kind==='create'?'create':'get'),challenge:r.challenge,origin:r.origin,crossOrigin:false}));
export function credentialBytes(id) {
  if (id.startsWith('b64.')) return fromUrl64(id.slice(4));
  if (!/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(id)) fail('Unsupported credential identifier.');
  return Uint8Array.from(id.replace(/-/g,'' ).match(/../g), n=>parseInt(n,16));
}
export function matchingPasskeys(vault, request) {
  const result=[];
  for (const item of vault.items) {
    for (const credential of item.login.fido2Credentials || []) {
      if (credential.rpId !== request.rpId || credential.keyAlgorithm !== 'ECDSA' || credential.keyCurve !== 'P-256' || String(credential.counter) !== '0') continue;
      let id; try { id=url64(credentialBytes(credential.credentialId)); } catch { continue; }
      if (request.kind === 'create' ? request.credentials.includes(id) : request.credentials.length ? request.credentials.includes(id) : credential.discoverable === 'true') {
        result.push({itemId:item.id, id, userName:credential.userName || item.login.username, credential});
      }
    }
  }
  return result;
}
export function derSignature(raw) {
  if (raw.length !== 64) fail('Invalid ECDSA signature.');
  const integer = b => {
    let i=0; while (i < b.length-1 && b[i] === 0) i++;
    b=b.subarray(i); if (b[0] & 128) b=concat(new Uint8Array([0]),b);
    return concat(new Uint8Array([2,b.length]),b);
  };
  const pair=concat(integer(raw.subarray(0,32)),integer(raw.subarray(32)));
  return concat(new Uint8Array([48,pair.length]),pair);
}
export async function createPasskey(vault, request, assertLive = () => {}) {
  if (matchingPasskeys(vault, request).length) fail('This account already has an excluded passkey.', 'InvalidStateError');
  const pair=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
  const jwk=await crypto.subtle.exportKey('jwk',pair.publicKey);
  const spki=bytes(await crypto.subtle.exportKey('spki',pair.publicKey));
  const secret=bytes(await crypto.subtle.exportKey('pkcs8',pair.privateKey));
  const id=random(32), handle=fromUrl64(request.user.id);
  const credential={credentialId:'b64.'+url64(id),keyType:'public-key',keyAlgorithm:'ECDSA',keyCurve:'P-256',
    keyValue:url64(secret),rpId:request.rpId,userHandle:url64(handle),userName:request.user.name,
    userDisplayName:request.user.displayName,rpName:request.rpName,counter:'0',discoverable:String(request.discoverable),creationDate:new Date().toISOString()};
  try {
    assertLive(); vault.requireUnlocked();
    await vault.savePasskey(credential,request.origin);
  } finally { secret.fill(0); }
  assertLive();
  const cose=cbor(new Map([[1,2],[3,-7],[-1,1],[-2,fromUrl64(jwk.x)],[-3,fromUrl64(jwk.y)]]));
  const authData=concat(await sha256(utf8(request.rpId)),new Uint8Array([0x5d,0,0,0,0]),new Uint8Array(16),new Uint8Array([0,id.length]),id,cose);
  const attestation=cbor(new Map([['fmt','none'],['attStmt',new Map()],['authData',authData]]));
  return {kind:'create',id:url64(id),rawId:url64(id),authenticatorAttachment:'platform',
    clientDataJSON:url64(clientData(request)),attestationObject:url64(attestation),authenticatorData:url64(authData),publicKey:url64(spki),
    extensions:request.credProps?{credProps:{rk:request.discoverable}}:{}};
}
export async function getPasskey(vault, request, id, assertLive = () => {}) {
  const match=matchingPasskeys(vault,request).find(c=>c.id===id);
  if (!match) fail('No matching passkey was selected.');
  const c=match.credential;
  const secret=fromUrl64(c.keyValue);
  let key;
  try { key=await crypto.subtle.importKey('pkcs8',secret,{name:'ECDSA',namedCurve:'P-256'},false,['sign']); }
  finally { secret.fill(0); }
  const authData=concat(await sha256(utf8(request.rpId)),new Uint8Array([0x1d,0,0,0,0]));
  const data=clientData(request);
  assertLive(); vault.requireUnlocked();
  const signature=derSignature(bytes(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},key,concat(authData,await sha256(data)))));
  assertLive();
  return {kind:'get',id:match.id,rawId:match.id,authenticatorAttachment:'platform',clientDataJSON:url64(data),
    authenticatorData:url64(authData),signature:url64(signature),userHandle:c.userHandle || null,extensions:{}};
}
