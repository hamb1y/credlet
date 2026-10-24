import nacl from 'tweetnacl';
import { argon2id } from 'hash-wasm';

export const utf8 = value => new TextEncoder().encode(value);
export const text = value => new TextDecoder('utf-8', {fatal: true}).decode(value);
export const bytes = value => value instanceof Uint8Array ? value : new Uint8Array(value);
export const random = n => crypto.getRandomValues(new Uint8Array(n));
export function concat(...arrays) {
  const out=new Uint8Array(arrays.reduce((n,a)=>n+a.length,0)); let offset=0;
  for(const array of arrays) { out.set(array,offset); offset+=array.length; }
  return out;
}
export function b64(value) { return btoa(Array.from(bytes(value), c => String.fromCharCode(c)).join('')); }
export function unb64(value, length) {
  if (typeof value !== 'string' || value.length > 16 * 1024 * 1024) throw Error('Invalid encrypted data.');
  let out;
  try { out = Uint8Array.from(atob(value), c => c.charCodeAt(0)); } catch { throw Error('Invalid encrypted data.'); }
  if (b64(out) !== value || (length !== undefined && out.length !== length)) throw Error('Invalid encrypted data.');
  return out;
}
export function seal(value, key, context) {
  const nonce = random(nacl.secretbox.nonceLength);
  const plaintext = utf8(JSON.stringify({context, data: value}));
  try { return JSON.stringify({v:1, nonce:b64(nonce), box:b64(nacl.secretbox(plaintext, nonce, key))}); }
  finally { plaintext.fill(0); }
}
export function open(value, key, context) {
  let plain;
  try {
    const envelope = JSON.parse(value);
    if (envelope.v !== 1) throw Error();
    plain = nacl.secretbox.open(unb64(envelope.box), unb64(envelope.nonce,24), key);
    if (!plain) throw Error();
    const decoded = JSON.parse(text(plain));
    if (decoded.context !== context) throw Error();
    return decoded.data;
  } catch { throw Error('The encrypted vault record could not be authenticated.'); }
  finally { plain?.fill(0); }
}
export async function derive(password, config) {
  if (typeof password !== 'string' || password.length < 1 || password.length > 1024 || config.iterations !== 3 || config.memoryKiB !== 65536 || config.parallelism !== 1) throw Error('Unsupported key derivation settings.');
  const root = await argon2id({password, salt:unb64(config.salt,16), iterations:3, memorySize:65536, parallelism:1, hashLength:32, outputType:'binary'});
  try {
    const key = await crypto.subtle.importKey('raw',root,'HKDF',false,['deriveBits']);
    const expand = async label => bytes(await crypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:utf8('Credlet v1'),info:utf8(label)},key,256));
    return {auth:await expand('server authentication'), wrap:await expand('vault key wrapping')};
  } finally { root.fill(0); }
}
export async function totp(value, time = Date.now()) {
  let secret = value, algorithm = 'SHA1', digits = 6, period = 30;
  if (value.startsWith('otpauth://')) {
    const uri = new URL(value);
    if (uri.hostname !== 'totp') throw Error('Only time-based authenticator codes are supported.');
    secret = uri.searchParams.get('secret') || '';
    algorithm = (uri.searchParams.get('algorithm') || 'SHA1').toUpperCase();
    digits = Number(uri.searchParams.get('digits') || 6); period = Number(uri.searchParams.get('period') || 30);
  }
  if (![6,8].includes(digits) || !['SHA1','SHA256','SHA512'].includes(algorithm) || !Number.isSafeInteger(period) || period<1 || period>3600) throw Error('Unsupported authenticator settings.');
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits=0, buffer=0; const decoded=[];
  for (const c of secret.toUpperCase().replace(/[\s=-]/g,'')) {
    const n=alphabet.indexOf(c); if(n<0) throw Error('Invalid authenticator secret.');
    buffer=(buffer<<5)|n; bits+=5;
    if(bits>=8) { bits-=8; decoded.push((buffer>>>bits)&255); }
  }
  if (!decoded.length) throw Error('Empty authenticator secret.');
  const counter=new Uint8Array(8); new DataView(counter.buffer).setBigUint64(0,BigInt(Math.floor(time/1000/period)));
  const key=await crypto.subtle.importKey('raw',new Uint8Array(decoded),{name:'HMAC',hash:algorithm.replace('SHA','SHA-')},false,['sign']);
  const digest=bytes(await crypto.subtle.sign('HMAC',key,counter)), offset=digest.at(-1)&15;
  const n=new DataView(digest.buffer,digest.byteOffset+offset,4).getUint32(0)&0x7fffffff;
  return {code:String(n%10**digits).padStart(digits,'0'),remaining:period-Math.floor(time/1000)%period,period};
}
export function generatePassword(length=24) {
  if (!Number.isSafeInteger(length) || length<12 || length>128) throw Error('Invalid password length.');
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()-_=+'; let result='';
  while(result.length<length) { const n=random(1)[0]; if(n<Math.floor(256/alphabet.length)*alphabet.length) result+=alphabet[n%alphabet.length]; }
  return result;
}
