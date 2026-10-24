import { argon2id } from 'hash-wasm';

export const utf8 = value => new TextEncoder().encode(value);
export const text = value => new TextDecoder('utf-8', { fatal: true }).decode(value);
export const bytes = value => value instanceof Uint8Array ? value : new Uint8Array(value);
export function concat(...arrays) {
  const out = new Uint8Array(arrays.reduce((n, a) => n + a.length, 0));
  let i = 0;
  for (const a of arrays) { out.set(a, i); i += a.length; }
  return out;
}
export function b64(value) {
  let s = '';
  for (const b of bytes(value)) s += String.fromCharCode(b);
  return btoa(s);
}
export const unb64 = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
export const random = n => crypto.getRandomValues(new Uint8Array(n));
export async function hmac(key, data, hash = 'SHA-256') {
  const k = await crypto.subtle.importKey('raw', key, {name: 'HMAC', hash}, false, ['sign']);
  return bytes(await crypto.subtle.sign('HMAC', k, data));
}
async function pbkdf(password, salt, iterations) {
  const key = await crypto.subtle.importKey('raw', password, 'PBKDF2', false, ['deriveBits']);
  return bytes(await crypto.subtle.deriveBits({name: 'PBKDF2', hash: 'SHA-256', salt, iterations}, key, 256));
}
function integer(value, min, max, label) {
  if (!Number.isSafeInteger(value) || value < min || value > max) throw Error(`Invalid ${label} setting.`);
  return value;
}
export async function deriveMaster(password, email, config) {
  const salt = utf8(email.trim().toLowerCase());
  const iterations = integer(config.kdfIterations, 1, 20000000, 'KDF iteration');
  if (config.kdf === 0) return pbkdf(utf8(password), salt, iterations);
  if (config.kdf !== 1) throw Error('This vault uses an unsupported key derivation method.');
  const memorySize = integer(config.kdfMemory, 8, 1024, 'Argon2 memory') * 1024;
  const parallelism = integer(config.kdfParallelism, 1, 16, 'Argon2 parallelism');
  integer(iterations, 1, 100, 'Argon2 iteration');
  const hashedSalt = bytes(await crypto.subtle.digest('SHA-256', salt));
  return argon2id({password: utf8(password), salt: hashedSalt, iterations, parallelism, memorySize, hashLength: 32, outputType: 'binary'});
}
export const authHash = (master, password) => pbkdf(master, utf8(password), 1).then(b64);
export async function stretchMaster(master) {
  return concat(await hmac(master, concat(utf8('enc'), new Uint8Array([1]))),
                await hmac(master, concat(utf8('mac'), new Uint8Array([1]))));
}
export async function encrypt(value, key) {
  if (key.length !== 64) throw Error('Invalid vault key.');
  const iv = random(16);
  const aes = await crypto.subtle.importKey('raw', key.subarray(0, 32), 'AES-CBC', false, ['encrypt']);
  const ct = bytes(await crypto.subtle.encrypt({name: 'AES-CBC', iv}, aes, typeof value === 'string' ? utf8(value) : value));
  const mac = await hmac(key.subarray(32), concat(iv, ct));
  return '2.' + [iv, ct, mac].map(b64).join('|');
}
export async function decrypt(value, key) {
  if (typeof value !== 'string' || !value.startsWith('2.') || key.length !== 64) throw Error('Unsupported encrypted field.');
  const parts = value.slice(2).split('|');
  if (parts.length !== 3) throw Error('Invalid encrypted field.');
  const [iv, ct, mac] = parts.map(unb64);
  if (iv.length !== 16 || mac.length !== 32 || !ct.length || ct.length % 16) throw Error('Invalid encrypted field.');
  const k = await crypto.subtle.importKey('raw', key.subarray(32), {name: 'HMAC', hash: 'SHA-256'}, false, ['verify']);
  if (!await crypto.subtle.verify('HMAC', k, mac, concat(iv, ct))) throw Error('Vault authentication failed.');
  const aes = await crypto.subtle.importKey('raw', key.subarray(0, 32), 'AES-CBC', false, ['decrypt']);
  return bytes(await crypto.subtle.decrypt({name: 'AES-CBC', iv}, aes, ct));
}
export const decryptText = async (value, key) => value == null ? '' : text(await decrypt(value, key));

function base32(value) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const result = []; let bits = 0, buffer = 0;
  for (const c of value.toUpperCase().replace(/[\s=-]/g, '')) {
    const n = alphabet.indexOf(c);
    if (n < 0) throw Error('Invalid authenticator secret.');
    buffer = (buffer << 5) | n; bits += 5;
    if (bits >= 8) { bits -= 8; result.push((buffer >>> bits) & 255); }
  }
  if (!result.length) throw Error('Empty authenticator secret.');
  return new Uint8Array(result);
}
export async function totp(value, time = Date.now()) {
  let secret = value, algorithm = 'SHA1', digits = 6, period = 30;
  if (value.startsWith('otpauth://')) {
    const uri = new URL(value);
    if (uri.hostname !== 'totp') throw Error('Only time-based authenticator codes are supported.');
    secret = uri.searchParams.get('secret') || '';
    algorithm = (uri.searchParams.get('algorithm') || 'SHA1').toUpperCase();
    digits = Number(uri.searchParams.get('digits') || 6);
    period = Number(uri.searchParams.get('period') || 30);
  }
  if (![6, 8].includes(digits) || !['SHA1', 'SHA256', 'SHA512'].includes(algorithm)) throw Error('Unsupported authenticator settings.');
  integer(period, 1, 3600, 'authenticator period');
  const counter = new Uint8Array(8);
  new DataView(counter.buffer).setBigUint64(0, BigInt(Math.floor(time / 1000 / period)));
  const digest = await hmac(base32(secret), counter, algorithm.replace('SHA', 'SHA-'));
  const offset = digest[digest.length - 1] & 15;
  const n = new DataView(digest.buffer, digest.byteOffset + offset, 4).getUint32(0) & 0x7fffffff;
  return {code: String(n % 10 ** digits).padStart(digits, '0'), remaining: period - Math.floor(time / 1000) % period, period};
}
export function generatePassword(length = 24) {
  integer(length, 12, 128, 'password length');
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()-_=+';
  let value = '';
  while (value.length < length) {
    const n = random(1)[0];
    if (n < Math.floor(256 / alphabet.length) * alphabet.length) value += alphabet[n % alphabet.length];
  }
  return value;
}
