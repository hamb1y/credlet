import { Vault, matchesOrigin } from './vault.js';
import { totp, generatePassword } from './crypto.js';
import { passkeyBroker } from './passkey-broker.js';

const api = globalThis.browser || globalThis.chrome;
let vault;
const ready = api.storage.local.get(['deviceId']).then(async ({deviceId}) => {
  deviceId ||= crypto.randomUUID();
  await api.storage.local.set({deviceId});
  vault = new Vault({deviceId});
});
const passkeys = passkeyBroker(api, () => vault);
let queue = Promise.resolve();
const ownPage = sender => sender.id === api.runtime.id && !sender.tab?.url?.startsWith('https:') &&
  typeof sender.url === 'string' && sender.url.startsWith(api.runtime.getURL(''));
async function status() {
  const settings = await api.storage.local.get(['server', 'email']);
  try { vault.requireUnlocked(); } catch { /* status also reports locked state */ }
  return {...settings, unlocked: !!vault.key, deadline: vault.deadline,
    items: vault.items.map(({id, name, login, reprompt}) => ({id, name, username: login.username, reprompt,
      uris:login.uris, hasTotp:!!login.totp, hasPasskey:!!login.fido2Credentials?.length}))};
}
async function dispatch(message) {
  await ready;
  if (!message || typeof message.type !== 'string') throw Error('Invalid request.');
  if (message.type.startsWith('passkey-')) return passkeys.dispatch(message);
  if (message.type === 'status') return status();
  if (message.type === 'lock') { vault.lock(); await api.alarms.clear('lock'); return status(); }
  if (message.type === 'login') {
    await api.alarms.clear('lock');
    await vault.login(message);
    await api.storage.local.set({server: vault.server, email: message.email.trim().toLowerCase()});
    await api.alarms.create('lock', {when: vault.deadline});
    return status();
  }
  if (message.type === 'generate') return generatePassword();
  vault.requireUnlocked();
  if (message.type === 'sync') { await vault.sync(); return status(); }
  if (message.type === 'save') { await vault.saveLogin(message.login,message.id); return status(); }
  const item = vault.items.find(i => i.id === message.id);
  if (!item) throw Error('The login could not be found. Sync and try again.');
  if (item.reprompt) throw Error('This item requires a master password prompt. Manage it in the web vault.');
  if (message.type === 'details') { const {fido2Credentials, ...login}=item.login; return {...item,login}; }
  if (message.type === 'totp') return totp(item.login.totp);
  if (message.type === 'delete') { await vault.deleteLogin(item.id); return status(); }
  if (message.type === 'fill' || message.type === 'fill-code') {
    const tab = await api.tabs.get(message.tabId);
    if (!matchesOrigin(item.login, tab.url)) throw Error('This login does not match the active HTTPS page.');
    if (api.scripting) {
      await api.scripting.executeScript({target: {tabId: tab.id, frameIds: [0]}, files: ['content.js']});
    } else {
      await api.tabs.executeScript(tab.id, {file: '/content.js', allFrames: false});
    }
    vault.requireUnlocked();
    const payload = message.type === 'fill-code' ? {type:'credlet-fill-code',code:(await totp(item.login.totp)).code} :
      {type:'credlet-fill',username:item.login.username,password:item.login.password};
    const result = await api.tabs.sendMessage(tab.id, {...payload,origin:new URL(tab.url).origin}, {frameId:0});
    if (!result?.filled) throw Error(message.type === 'fill-code' ? 'No visible authenticator code field was found on this page.' : 'No visible login fields were found on this page.');
    return {filled: true};
  }
  throw Error('Unknown request.');
}
api.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type === 'passkey-request') {
    ready.then(() => passkeys.begin(message,sender,respond)).catch(() => respond({error:'Vault unavailable.',name:'NotAllowedError'}));
    return true;
  }
  if (message?.type === 'passkey-source-cancel') { passkeys.cancel(message,sender); return false; }
  if (!ownPage(sender)) return false; // Web pages and content scripts cannot query the vault.
  queue = queue.catch(() => {}).then(() => dispatch(message)).then(
    value => respond({ok: true, value}),
    error => {
      try { vault?.requireUnlocked(); } catch { /* include actual lock state in failures */ }
      respond({ok: false, error: error.message, providers: error.providers, locked: !vault?.key});
    });
  return true;
});
api.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'lock') vault?.lock(); });
api.runtime.onInstalled.addListener(({reason}) => {
  if (reason === 'install') api.tabs.create({url: api.runtime.getURL('vault.html')});
});
