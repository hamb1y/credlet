import {Vault} from '../extension/src/vault.js';
const vault = new Vault();
await vault.login({server:process.env.TEST_SERVER,email:process.env.TEST_EMAIL,password:process.env.TEST_PASSWORD});
await vault.saveLogin({name:'Integration fixture',username:'test-user',password:process.env.TEST_ITEM_PASSWORD,uri:'https://example.com',totp:'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'});
vault.lock();
