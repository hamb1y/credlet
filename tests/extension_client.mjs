// Uses the actual extension vault code against the disposable integration server.
import assert from 'node:assert/strict';
import { Vault } from '../extension/src/vault.js';
import { totp } from '../extension/src/crypto.js';
const vault = new Vault();
await vault.login({server:process.env.TEST_SERVER,email:process.env.TEST_EMAIL,password:process.env.TEST_PASSWORD});
const item = vault.items.find(i => i.name === 'Integration fixture');
assert(item, 'Extension must decrypt the cipher created by the official client');
assert.equal(item.login.password, process.env.TEST_ITEM_PASSWORD);
assert.equal(item.login.totp,'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
assert.match((await totp(item.login.totp)).code,/^\d{6}$/);
await vault.saveLogin({name:'Credlet extension fixture',uri:'https://example.com',username:'extension-user',password:process.env.TEST_ITEM_PASSWORD,totp:item.login.totp});
const created = vault.items.find(i=>i.name==='Credlet extension fixture');
assert(created);
const id=created.id;
vault.lock();
assert.equal(vault.key,null);
console.log(JSON.stringify({id}));
