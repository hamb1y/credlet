import {Vault} from './vault.js';
import {generatePassword, totp} from './crypto.js';

export function controller({vault=new Vault(),settings={get:async()=>({}),set:async()=>{}}}={}) {
  async function status() {
    try { vault.requireUnlocked(); } catch { /* Locked is a normal state. */ }
    return {...await settings.get(),unlocked:!!vault.key,deadline:vault.deadline,
      items:vault.items.map(({id,name,login})=>({id,name,username:login.username,uris:login.uris,hasTotp:!!login.totp,hasPasskey:!!login.fido2Credentials?.length}))};
  }
  async function dispatch(message) {
    if(!message || typeof message.type!=='string') throw Error('Invalid request.');
    if(message.type==='status') return status();
    if(message.type==='lock') { await vault.logout(); return status(); }
    if(message.type==='login') {
      await vault.login(message);
      await settings.set({server:vault.transport.origin,serverKey:message.serverKey,email:message.email.trim().toLowerCase()});
      return status();
    }
    if(message.type==='generate') return generatePassword();
    vault.requireUnlocked();
    if(message.type==='sync') { await vault.sync(); return status(); }
    if(message.type==='save') { await vault.saveLogin(message.login,message.id); return status(); }
    const item=vault.items.find(i=>i.id===message.id);
    if(!item) throw Error('Login not found. Sync and try again.');
    if(message.type==='details') { const {fido2Credentials,...login}=item.login; return {...item,login}; }
    if(message.type==='totp') return totp(item.login.totp);
    if(message.type==='delete') { await vault.deleteLogin(item.id); return status(); }
    throw Error('Unsupported action on this platform.');
  }
  return {vault,status,dispatch};
}
