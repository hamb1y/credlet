// Private stdin/stdout RPC for the desktop UI. No listening socket or persistent session keys.
import readline from 'node:readline';
import {Vault} from '../extension/src/vault.js';
import {totp,encrypt,decrypt} from '../extension/src/crypto.js';
const vault=new Vault({deviceId:process.env.CREDLET_DEVICE_ID || process.env.LOCKBOX_DEVICE_ID});
const status=()=>{
  try{vault.requireUnlocked();}catch{}
  return {unlocked:!!vault.key,deadline:vault.deadline,items:vault.items.map(i=>({id:i.id,name:i.name,username:i.login.username,
    uris:i.login.uris.map(u=>({uri:u.uri,match:u.match})),reprompt:i.reprompt}))};
};
function appUri(uri) {
  if(typeof uri!=='string' || uri.length>8192 || !/^(credlet|lockbox)-app:\/\/(linux|windows|macos)\/[^/]+$/.test(uri))throw Error('Invalid application identity.');
  return uri.replace(/^lockbox-app:/,'credlet-app:');
}
async function dispatch(m) {
  if(m.type==='status')return status();
  if(m.type==='lock'){vault.lock();return status();}
  if(m.type==='login'){await vault.login(m);return status();}
  vault.requireUnlocked();
  if(m.type==='sync'){await vault.sync();return status();}
  const item=vault.items.find(i=>i.id===m.itemId);
  if(!item)throw Error('Select a login and sync again.');
  if(item.reprompt)await vault.verifyPassword(m.password);
  const uri=appUri(m.appUri);
  if(m.type==='link') {
    const raw=vault.rawItems.find(i=>i.id===item.id);
    let key=vault.key,ownKey;
    try {
      if(raw.key)key=ownKey=await decrypt(raw.key,vault.key);
      if(!item.login.uris.some(u=>u.uri && appIdentity(u.uri)===uri && u.match!==5)) {
        const body={...raw,encryptedFor:vault.userId,lastKnownRevisionDate:raw.revisionDate,
          login:{...raw.login,uris:[...(raw.login.uris||[]),{uri:await encrypt(uri,key),match:3}]}};
        await vault.request('/api/ciphers/'+encodeURIComponent(item.id),{method:'PUT',body,authenticated:true});
        await vault.sync();
      }
      return status();
    } finally {ownKey?.fill(0);}
  }
  if(m.type==='fill') {
    if(!item.login.uris.some(u=>u.uri && appIdentity(u.uri)===uri && u.match!==5))throw Error('Link this login to the captured application before filling.');
    if(m.field==='username')return {value:item.login.username};
    if(m.field==='password')return {value:item.login.password};
    if(m.field==='code')return {value:(await totp(item.login.totp)).code};
    throw Error('Choose username, password or authenticator code.');
  }
  throw Error('Unknown desktop operation.');
}
function appIdentity(uri) {return uri.replace(/^lockbox-app:/,'credlet-app:');}
let queue=Promise.resolve();
readline.createInterface({input:process.stdin,crlfDelay:Infinity}).on('line',line=>{
  if(line.length>1048576){vault.lock();process.exit(1);}
  queue=queue.then(async()=>{
    let message;
    try {message=JSON.parse(line);const value=await dispatch(message);process.stdout.write(JSON.stringify({id:message.id,ok:true,value})+'\n');}
    catch(error){
      try{vault.requireUnlocked();}catch{}
      process.stdout.write(JSON.stringify({id:message?.id,ok:false,error:error.message,locked:!vault.key})+'\n');
    }
  });
}).on('close',()=>{vault.lock();process.exit();});
// Login derives its key asynchronously. A locked vault can be in the middle of
// that derivation; checking it here would clear its server and abort login.
setInterval(()=>{if(vault.key){try{vault.requireUnlocked();}catch{}}},1000).unref();
process.on('SIGTERM',()=>{vault.lock();process.exit();});
