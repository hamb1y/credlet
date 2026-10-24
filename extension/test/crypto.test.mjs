import test from 'node:test';
import assert from 'node:assert/strict';
import * as c from 'node:crypto';
import {deriveMaster, stretchMaster, authHash, encrypt, decrypt, utf8, text, b64, unb64, totp, generatePassword} from '../src/crypto.js';
import {serverOrigin, matchesOrigin, Vault} from '../src/vault.js';

test('Bitwarden PBKDF2, expanded master key and server authentication hash match independent Node primitives', async () => {
  const config = {kdf:0,kdfIterations:600000};
  const master = await deriveMaster('an example password', ' OWNER@example.com ', config);
  const expected = c.pbkdf2Sync('an example password','owner@example.com',600000,32,'sha256');
  assert.equal(b64(master), expected.toString('base64'));
  const expanded = Buffer.concat(['enc','mac'].map(s => c.createHmac('sha256',expected).update(Buffer.concat([Buffer.from(s),Buffer.from([1])])).digest()));
  assert.equal(b64(await stretchMaster(master)),expanded.toString('base64'));
  assert.equal(await authHash(master,'an example password'),c.pbkdf2Sync(expected,'an example password',1,32,'sha256').toString('base64'));
});
test('AES-256 CBC + HMAC ciphertext interoperates with Node and rejects tampering before decryption', async () => {
  const key = new Uint8Array(c.randomBytes(64));
  const encrypted = await encrypt('Unicode secret 🔑', key);
  const [iv,ct,mac] = encrypted.slice(2).split('|').map(s=>Buffer.from(s,'base64'));
  assert.deepEqual(mac,c.createHmac('sha256',key.subarray(32)).update(Buffer.concat([iv,ct])).digest());
  const decipher = c.createDecipheriv('aes-256-cbc',key.subarray(0,32),iv);
  assert.equal(Buffer.concat([decipher.update(ct),decipher.final()]).toString(),'Unicode secret 🔑');
  assert.equal(text(await decrypt(encrypted,key)),'Unicode secret 🔑');
  const damaged=unb64(encrypted.slice(2).split('|')[1]); damaged[0]^=1;
  await assert.rejects(decrypt('2.'+[b64(iv),b64(damaged),b64(mac)].join('|'),key),/authentication failed/);
  await assert.rejects(decrypt(encrypted,new Uint8Array(c.randomBytes(64))),/authentication failed/);
});
test('RFC 6238 TOTP vectors and six-digit default', async () => {
  const secret='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';
  const uri='otpauth://totp/test?secret='+secret+'&digits=8';
  for(const [time,expected] of [[59,'94287082'],[1111111109,'07081804'],[1111111111,'14050471'],[1234567890,'89005924'],[2000000000,'69279037'],[20000000000,'65353130']]) {
    assert.equal((await totp(uri,time*1000)).code,expected);
  }
  assert.equal((await totp(secret,59000)).code,'287082');
  await assert.rejects(totp('otpauth://hotp/test?secret='+secret),/time-based/);
  await assert.rejects(totp('invalid0'),/Invalid/);
});
test('URL and imported URI rules cannot release credentials to other origins', () => {
  assert.equal(serverOrigin('https://vault.example.com/'),'https://vault.example.com');
  for(const u of ['http://example.com','https://a:b@example.com','https://example.com/path','https://example.com/?redirect=evil']) assert.throws(()=>serverOrigin(u));
  const login={uris:[{uri:'https://example.com/login',match:0}]};
  assert(matchesOrigin(login,'https://example.com/account'));
  for(const u of ['https://evil.example.com','https://example.com.evil.test','http://example.com','https://example.com:8443','file:///login']) assert(!matchesOrigin(login,u));
  assert(!matchesOrigin({uris:[{uri:'https://example.com/login',match:3}]},'https://example.com/other'));
  assert(!matchesOrigin({uris:[{uri:'https://example.com',match:5}]},'https://example.com'));
  assert(!matchesOrigin({uris:[{uri:'https://example.com',match:4}]},'https://example.com'));
});
test('auto-lock wipes the vault key and cached secret references', () => {
  let now=0; const vault=new Vault({now:()=>now});
  const key=new Uint8Array(64).fill(7); vault.key=key;vault.token='secret';vault.items=[{login:{password:'secret'}}];vault.deadline=10;
  now=11;assert.throws(()=>vault.requireUnlocked(),/locked/);
  assert(key.every(x=>x===0));assert.equal(vault.token,null);assert.deepEqual(vault.items,[]);
});
test('password generator uses requested length and rejects weak sizes', () => {
  assert.equal(generatePassword().length,24);assert.equal(generatePassword(128).length,128);
  assert.throws(()=>generatePassword(4));
});
