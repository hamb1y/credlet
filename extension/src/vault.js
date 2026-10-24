import { deriveMaster, authHash, stretchMaster, decrypt, decryptText, encrypt, totp } from './crypto.js';

export function serverOrigin(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw Error('Enter an HTTPS server address with no path, credentials or query.');
  }
  return url.origin;
}
export function matchesOrigin(login, page) {
  try {
    const target = new URL(page);
    if (target.protocol !== 'https:') return false;
    return (login.uris || []).some(({uri, match}) => {
      if (match === 5 || !uri) return false; // Bitwarden Never match.
      try {
        const saved = new URL(uri);
        // Never broaden imported host/domain/regex rules to a different origin.
        if (saved.protocol !== 'https:' || saved.origin !== target.origin) return false;
        if (match === 2) return target.href.startsWith(saved.href);
        if (match === 3) return target.href === saved.href;
        if (match === 4) return false; // Regex rules require explicit selection in the web vault.
        return true;
      } catch { return false; }
    });
  } catch { return false; }
}
export class Vault {
  constructor({fetcher = globalThis.fetch.bind(globalThis), deviceId = crypto.randomUUID(), now = Date.now} = {}) {
    this.fetcher = fetcher; this.deviceId = deviceId; this.now = now;
    this.lock();
  }
  lock() {
    this.generation = (this.generation || 0) + 1;
    this.key?.fill(0); this.key = null; this.token = null; this.deadline = 0;
    this.items = []; this.rawItems = []; this.server = null; this.userId = null; this.verification = null;
  }
  requireUnlocked() {
    if (!this.key || this.now() >= this.deadline) { this.lock(); throw Error('Vault is locked. Sign in to continue.'); }
  }
  requireSession(generation) {
    if (generation !== this.generation) throw Error('Vault is locked. Sign in to continue.');
  }
  async request(path, {body, authenticated = false, form = false, method = 'POST'} = {}) {
    if (authenticated) this.requireUnlocked();
    const generation = this.generation;
    const headers = {'Accept': 'application/json', 'Bitwarden-Client-Name': 'browser', 'Bitwarden-Client-Version': '2026.6.0'};
    if (authenticated) headers.Authorization = `Bearer ${this.token}`;
    if (body != null) headers['Content-Type'] = form ? 'application/x-www-form-urlencoded' : 'application/json';
    let response;
    try { response = await this.fetcher(this.server + path, {method, headers,
      body: body == null ? undefined : form ? new URLSearchParams(body).toString() : JSON.stringify(body),
      credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(30000)}); }
    catch (error) {
      this.requireSession(generation);
      throw Error(error.name === 'TimeoutError' ? 'The vault server took too long to respond. Try again.' : 'Could not reach the vault server. Check its address, HTTPS certificate and your connection.');
    }
    this.requireSession(generation);
    if (authenticated) this.requireUnlocked();
    let data;
    try { const body = await response.text(); data = body.trim() ? JSON.parse(body) : {}; }
    catch { if (response.ok) throw Error('The server returned an invalid response. Check that this address runs a compatible vault.'); data = {}; }
    this.requireSession(generation);
    if (authenticated) this.requireUnlocked();
    if (!response.ok) {
      if (data.TwoFactorProviders || data.twoFactorProviders) {
        const providers = data.TwoFactorProviders || data.twoFactorProviders;
        const error = Error('Enter the code from your vault login authenticator.');
        error.providers = providers; throw error;
      }
      if (authenticated && response.status === 401) this.lock();
      // Do not surface server-controlled HTML or echo potentially secret request data.
      throw Error(response.status === 401 || response.status === 400 ? 'Sign-in or vault request was rejected.' : `Vault request failed (${response.status}).`);
    }
    return data;
  }
  async login({server, email, password, code}) {
    this.lock(); this.server = serverOrigin(server);
    const generation = this.generation;
    email = email.trim().toLowerCase();
    let master, stretched, unlocked;
    try {
      const config = await this.request('/identity/accounts/prelogin', {body: {email}});
      master = await deriveMaster(password, email, config);
      const hash = await authHash(master, password);
      this.requireSession(generation);
      const body = {grant_type: 'password', username: email, password: hash, scope: 'api offline_access',
        client_id: 'browser', deviceType: '2', deviceIdentifier: this.deviceId, deviceName: 'Credlet extension'};
      if (code) Object.assign(body, {twoFactorProvider: '0', twoFactorToken: code.replace(/\s/g, ''), twoFactorRemember: '0'});
      const auth = await this.request('/identity/connect/token', {body, form: true});
      stretched = await stretchMaster(master);
      const wrapped = auth.Key || auth.key || auth.masterPasswordUnlock?.masterKeyEncryptedUserKey;
      unlocked = await decrypt(wrapped, stretched);
      this.requireSession(generation);
      if (unlocked.length !== 64) throw Error('Unsupported vault encryption key.');
      this.key = unlocked; unlocked = null;
      this.verification = {email, config, wrapped};
      this.token = auth.access_token;
      if (!this.token) throw Error('Server did not return an access token.');
      this.deadline = this.now() + Math.min(Number(auth.expires_in) * 1000 || 300000, 300000);
      await this.sync();
    } catch (error) { if (generation === this.generation) this.lock(); throw error; }
    finally { master?.fill(0); stretched?.fill(0); unlocked?.fill(0); }
  }
  async sync() {
    const generation = this.generation;
    const data = await this.request('/api/sync?excludeDomains=true', {method: 'GET', authenticated: true});
    this.userId = data.profile?.id;
    if (!this.userId) throw Error('Server did not return the vault owner.');
    const raw = (data.ciphers || []).filter(item => item.type === 1 && !item.organizationId && !item.deletedDate);
    const items = [];
    for (const item of raw) {
      let key = this.key, ownKey;
      try {
        if (item.key) key = ownKey = await decrypt(item.key, this.key);
        const d = value => decryptText(value, key);
        const login = item.login || {};
        items.push({id: item.id, name: await d(item.name), notes: await d(item.notes), reprompt: item.reprompt || 0,
          login: {username: await d(login.username), password: await d(login.password), totp: await d(login.totp),
            fido2Credentials: await Promise.all((login.fido2Credentials || []).map(async c => Object.fromEntries(await Promise.all(Object.entries(c).map(async ([k,v]) => [k, k === 'creationDate' || v == null ? v : await d(v)]))))),
            uris: await Promise.all((login.uris || []).map(async u => ({uri: await d(u.uri), match: u.match})))}});
      } finally { ownKey?.fill(0); }
    }
    this.requireUnlocked();
    this.requireSession(generation);
    this.rawItems = raw; this.items = items;
    return items;
  }
  async verifyPassword(password) {
    this.requireUnlocked();
    let master, stretched, key;
    try {
      master = await deriveMaster(password, this.verification.email, this.verification.config);
      stretched = await stretchMaster(master);
      key = await decrypt(this.verification.wrapped, stretched);
      this.requireUnlocked();
      if (key.length !== this.key.length || key.some((b,i) => b !== this.key[i])) throw Error('Wrong master password.');
    } catch { throw Error('Master password verification failed.'); }
    finally { master?.fill(0); stretched?.fill(0); key?.fill(0); }
  }
  async savePasskey(credential, origin) {
    this.requireUnlocked();
    const e = value => value ? encrypt(value, this.key) : null;
    const fido2 = Object.fromEntries(await Promise.all(Object.entries(credential).map(async ([k,v]) => [k,k === 'creationDate' ? v : await e(v)])));
    const body = {type:1,encryptedFor:this.userId,organizationId:null,folderId:null,reprompt:0,favorite:false,
      name:await e(credential.rpName + ' — ' + credential.userName),
      login:{username:await e(credential.userName),password:null,totp:null,uris:[{uri:await e(origin),match:1}],fido2Credentials:[fido2]}};
    await this.request('/api/ciphers',{body,authenticated:true});
    await this.sync();
  }
  async deleteLogin(id) {
    this.requireUnlocked();
    const item=this.items.find(i=>i.id===id);
    if (!item || item.reprompt) throw Error('This login cannot be deleted here.');
    await this.request('/api/ciphers/'+encodeURIComponent(id)+'/delete',{method:'PUT',authenticated:true});
    return this.sync(); // Move to the server's trash; recovery remains available in the web vault.
  }
  async saveLogin(login,id) {
    this.requireUnlocked();
    const raw=id ? this.rawItems.find(i=>i.id===id) : null;
    if (id && (!raw || raw.reprompt)) throw Error('This login cannot be edited here. Sync and try again.');
    if (typeof login.name !== 'string' || !login.name.trim() || login.name.trim().length > 200) throw Error('Give the login a name of up to 200 characters.');
    let website = login.uri?.trim() || '';
    if (website) {
      let url;
      try { url = new URL(website); } catch { throw Error('Use an HTTPS website address.'); }
      if (url.protocol !== 'https:' || url.username || url.password) throw Error('Use an HTTPS website address.');
      website = url.href;
    }
    const previous = this.items.find(item => item.id === id);
    if (login.totp && login.totp !== previous?.login.totp) await totp(login.totp);
    let key=this.key,ownKey;
    try {
      if (raw?.key) key=ownKey=await decrypt(raw.key,this.key);
      const e=value=>value ? encrypt(value,key) : null;
      const body=raw ? {...raw,lastKnownRevisionDate:raw.revisionDate} :
        {type:1,encryptedFor:this.userId,organizationId:null,folderId:null,reprompt:0,favorite:false};
      body.encryptedFor=this.userId;
      body.name=await e(login.name.trim());
      if (!body.name) throw Error('Give the login a name.');
      if (login.notes !== undefined) body.notes=await e(login.notes);
      const uris=raw?.login?.uris ? [...raw.login.uris] : [];
      // Edit the first website, preserving native-app links, other websites and
      // imported exact/prefix/never-match rules when the address is unchanged.
      const decoded = raw ? await Promise.all(uris.map(u => decryptText(u.uri,key))) : [];
      const index = decoded.findIndex(uri => uri.startsWith('https://'));
      if (index >= 0) {
        const sameAddress = website && new URL(decoded[index]).href === website;
        if (!website) uris.splice(index,1);
        else if (!sameAddress) uris[index] = {uri:await e(website),match:1};
      } else if (website) uris.push({uri:await e(website),match:1});
      body.login={...raw?.login,username:await e(login.username),password:await e(login.password),totp:await e(login.totp),uris};
      await this.request('/api/ciphers'+(id?'/'+encodeURIComponent(id):''),{body,method:id?'PUT':'POST',authenticated:true});
      return this.sync();
    } finally {ownKey?.fill(0);}
  }
}
