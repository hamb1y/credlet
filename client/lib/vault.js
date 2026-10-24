import {b64, unb64, random, derive, seal, open, totp} from './crypto.js';
import {Transport} from './transport.js';

export function matchesOrigin(login,page) {
  try {
    const target=new URL(page); if(target.protocol!=='https:') return false;
    return (login.uris||[]).some(({uri,match})=>{
      if(!uri || match===5 || match===4) return false;
      try { const saved=new URL(uri); return saved.protocol==='https:' && saved.origin===target.origin && (match===3 ? saved.href===target.href : match===2 ? target.href.startsWith(saved.href) : true); } catch { return false; }
    });
  } catch { return false; }
}

export class Vault {
  constructor({exchange,now=Date.now}={}) { this.exchange=exchange; this.now=now; this.lock(); }
  lock() {
    this.generation=(this.generation||0)+1;
    this.key?.fill(0); this.key=null; this.items=[]; this.records=[]; this.token=null; this.deadline=0; this.transport=null; this.verification=null;
  }
  requireUnlocked() { if(!this.key || this.now()>=this.deadline) { this.lock(); throw Error('Vault is locked. Sign in again.'); } }
  current(generation) { if(generation!==this.generation) throw Error('Vault is locked. Sign in again.'); }
  async request(action,data={}) {
    this.requireUnlocked(); const generation=this.generation;
    let result;
    try { result=await this.transport.request(action,data,this.token); }
    catch(error) { this.current(generation); if(error.status===401) this.lock(); throw error; }
    this.current(generation); this.requireUnlocked(); return result;
  }
  async login({server,serverKey,email,password,enrollmentToken}) {
    this.lock(); const generation=this.generation;
    const transport=new Transport({server,serverKey,exchange:this.exchange,now:this.now});
    let derived, key;
    try {
      const config=await transport.request('config'); this.current(generation);
      derived=await derive(password,config); this.current(generation);
      const body={email:email.trim().toLowerCase(),authKey:b64(derived.auth)};
      let auth;
      if (enrollmentToken) {
        if(!config.enrollmentOpen) throw Error('Enrollment is closed. Sign in with your existing master password.');
        if(password.length<12) throw Error('Choose a master password of at least 12 characters.');
        key=random(32);
        Object.assign(body,{enrollmentToken:enrollmentToken.trim(),wrappedKey:seal(b64(key),derived.wrap,'vault-key:v1')});
        auth=await transport.request('enroll',body);
      } else auth=await transport.request('login',body);
      this.current(generation);
      key?.fill(0); key=unb64(open(auth.wrappedKey,derived.wrap,'vault-key:v1'),32);
      if(!Number.isSafeInteger(auth.expiresAt) || auth.expiresAt*1000<=this.now()) throw Error('Invalid session expiry. Check your device clock.');
      this.key=key; key=null; this.token=auth.token; this.deadline=Math.min(auth.expiresAt*1000,this.now()+300000);
      this.transport=transport; this.verification={config,wrapped:auth.wrappedKey};
      await this.sync();
    } catch(error) { if(generation===this.generation) this.lock(); throw error; }
    finally { derived?.auth.fill(0); derived?.wrap.fill(0); key?.fill(0); }
  }
  async sync() {
    const generation=this.generation;
    const records=[]; let cursor=null;
    do {
      const data=await this.request('sync',cursor ? {after:cursor} : {});
      if(!Array.isArray(data.items) || data.items.length>32 || (data.cursor && (typeof data.cursor!=='string' || data.cursor<=String(cursor||'')))) throw Error('Invalid vault response.');
      records.push(...data.items); cursor=data.cursor;
      if(records.length>4096) throw Error('Vault item limit exceeded.');
    } while(cursor);
    const items=[];
    for(const record of records) {
      if(record.deleted) continue;
      const item=open(record.payload,this.key,'item:v1:'+record.id);
      if(item.id!==record.id || typeof item.name!=='string' || !item.login || !Array.isArray(item.login.uris)) throw Error('Invalid encrypted login.');
      items.push(item);
    }
    this.current(generation); this.requireUnlocked(); this.records=records; this.items=items; return items;
  }
  async verifyPassword(password) {
    this.requireUnlocked(); const generation=this.generation; let derived,key;
    try {
      derived=await derive(password,this.verification.config); this.current(generation); this.requireUnlocked();
      key=unb64(open(this.verification.wrapped,derived.wrap,'vault-key:v1'),32);
      if(key.some((n,i)=>n!==this.key[i])) throw Error();
    } catch { throw Error('Master password verification failed.'); }
    finally { derived?.auth.fill(0); derived?.wrap.fill(0); key?.fill(0); }
  }
  async put(item) {
    this.requireUnlocked(); const id=item.id, record=this.records.find(r=>r.id===id);
    const payload=seal(item,this.key,'item:v1:'+id);
    if(payload.length>65536) throw Error('This login is too large. Shorten its notes.');
    await this.request('put',{id,revision:record?.revision||0,payload});
    return this.sync();
  }
  async saveLogin(login,id) {
    this.requireUnlocked(); const generation=this.generation;
    const existing=id ? this.items.find(i=>i.id===id) : null;
    if(id && !existing) throw Error('Login not found. Sync and try again.');
    const name=login.name?.trim(); if(!name || name.length>200) throw Error('Give this login a name of up to 200 characters.');
    const website=login.uri?.trim()||'';
    if(website) { let url; try { url=new URL(website); } catch { throw Error('Use a valid HTTPS website address.'); } if(url.protocol!=='https:' || url.username || url.password) throw Error('Use an HTTPS website address without credentials.'); }
    if(login.totp) await totp(login.totp);
    this.current(generation); this.requireUnlocked();
    const uris=structuredClone(existing?.login.uris||[]), web=uris.findIndex(u=>u.uri?.startsWith('https://'));
    if(web>=0) { if(!website) uris.splice(web,1); else if(uris[web].uri!==website) uris[web]={uri:website,match:1}; }
    else if(website) uris.unshift({uri:website,match:1});
    const item={...existing,id:id||crypto.randomUUID(),name,notes:login.notes||'',reprompt:0,
      login:{...existing?.login,username:login.username||'',password:login.password||'',totp:login.totp||'',uris,fido2Credentials:existing?.login.fido2Credentials||[]}};
    return this.put(item);
  }
  async savePasskey(credential,origin) {
    this.requireUnlocked();
    return this.put({id:crypto.randomUUID(),name:credential.rpName+' — '+credential.userName,notes:'',reprompt:0,
      login:{username:credential.userName,password:'',totp:'',uris:[{uri:origin,match:1}],fido2Credentials:[credential]}});
  }
  async deleteLogin(id) {
    const record=this.records.find(r=>r.id===id);
    if(!record || record.deleted) throw Error('Login not found. Sync and try again.');
    await this.request('delete',{id,revision:record.revision}); return this.sync();
  }
  async logout() {
    const transport=this.transport, token=this.token; this.lock();
    if(transport && token) { try { await transport.request('logout',{},token); } catch { /* A disconnected session expires on the server within five minutes. */ } }
  }
}
