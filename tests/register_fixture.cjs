(async () => {
const c = require('node:crypto');
const email = process.env.TEST_EMAIL;
const password = process.env.TEST_PASSWORD;
const argon = process.env.TEST_KDF === 'argon2';
const master = argon ? Buffer.from(await require('hash-wasm').argon2id({password, salt:c.createHash('sha256').update(email).digest(),iterations:3,parallelism:4,memorySize:65536,hashLength:32,outputType:'binary'})) : c.pbkdf2Sync(password, email, 600000, 32, 'sha256');
const enc = c.createHmac('sha256', master).update(Buffer.concat([Buffer.from('enc'),Buffer.from([1])])).digest();
const macKey = c.createHmac('sha256', master).update(Buffer.concat([Buffer.from('mac'),Buffer.from([1])])).digest();
const iv = c.randomBytes(16);
const cipher = c.createCipheriv('aes-256-cbc', enc, iv);
const userKey = c.randomBytes(64);
const ct = Buffer.concat([cipher.update(userKey),cipher.final()]);
const mac = c.createHmac('sha256', macKey).update(Buffer.concat([iv,ct])).digest();
const payload = {email, kdf:0, kdfIterations:600000, key:'2.'+[iv,ct,mac].map(x=>x.toString('base64')).join('|'),masterPasswordHash:c.pbkdf2Sync(master,password,1,32,'sha256').toString('base64')};
if (argon) Object.assign(payload,{kdf:1,kdfIterations:3,kdfMemory:64,kdfParallelism:4});
const rsa = c.generateKeyPairSync('rsa', {modulusLength:2048,publicKeyEncoding:{type:'spki',format:'der'},privateKeyEncoding:{type:'pkcs8',format:'der'}});
const piv=c.randomBytes(16), pc=c.createCipheriv('aes-256-cbc',userKey.subarray(0,32),piv);
const pct=Buffer.concat([pc.update(rsa.privateKey),pc.final()]);
const pmac=c.createHmac('sha256',userKey.subarray(32)).update(Buffer.concat([piv,pct])).digest();
payload.keys={publicKey:rsa.publicKey.toString('base64'),encryptedPrivateKey:'2.'+[piv,pct,pmac].map(x=>x.toString('base64')).join('|')};
await (async()=>{
 let r=await fetch(process.env.TEST_SERVER+'/identity/accounts/register/send-verification-email',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({email,name:'Integration Test'})});
 if(!r.ok) throw Error('token: '+await r.text());
 payload.emailVerificationToken=await r.json();
 r=await fetch(process.env.TEST_SERVER+'/identity/accounts/register/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 if(!r.ok) throw Error('register: '+await r.text());
 console.log('registered');
})();

})().catch(error => { console.error(error); process.exitCode=1; });
