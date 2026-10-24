import {controller} from '../../client/lib/controller.js';
import {matchesOrigin} from '../../client/lib/vault.js';
import {totp} from '../../client/lib/crypto.js';
import {passkeyBroker} from './passkey-broker.js';
const api=globalThis.browser||globalThis.chrome;
const core=controller({settings:{get:()=>api.storage.local.get(['server','serverKey','email']),set:value=>api.storage.local.set(value)}});
const passkeys=passkeyBroker(api,()=>core.vault);
let queue=Promise.resolve();
const ownPage=sender=>sender.id===api.runtime.id && typeof sender.url==='string' && sender.url.startsWith(api.runtime.getURL(''));
async function dispatch(message) {
  if(message.type.startsWith('passkey-')) return passkeys.dispatch(message);
  if(message.type==='fill' || message.type==='fill-code') {
    core.vault.requireUnlocked();
    const generation=core.vault.generation;
    const item=core.vault.items.find(i=>i.id===message.id);
    const tab=await api.tabs.get(message.tabId);
    if(!item || !matchesOrigin(item.login,tab.url)) throw Error('This login does not match the active HTTPS page.');
    if(api.scripting) await api.scripting.executeScript({target:{tabId:tab.id,frameIds:[0]},files:['content.js']});
    else await api.tabs.executeScript(tab.id,{file:'/content.js',allFrames:false});
    const payload=message.type==='fill-code' ? {type:'credlet-fill-code',code:(await totp(item.login.totp)).code} : {type:'credlet-fill',username:item.login.username,password:item.login.password};
    core.vault.current(generation);core.vault.requireUnlocked();
    const result=await api.tabs.sendMessage(tab.id,{...payload,origin:new URL(tab.url).origin},{frameId:0});
    if(!result?.filled) throw Error('No compatible visible field was found on this page.');
    return result;
  }
  const result=await core.dispatch(message);
  if(message.type==='login') await api.alarms.create('credlet-lock',{when:core.vault.deadline});
  if(message.type==='lock') await api.alarms.clear('credlet-lock');
  return result;
}
api.runtime.onMessage.addListener((message,sender,respond)=>{
  if(message?.type==='passkey-request') { passkeys.begin(message,sender,respond);return true; }
  if(message?.type==='passkey-source-cancel') { passkeys.cancel(message,sender);return false; }
  if(!ownPage(sender) || typeof message?.type!=='string') return false;
  const run=()=>dispatch(message).then(value=>respond({ok:true,value}),error=>respond({ok:false,error:error.message,locked:!core.vault.key}));
  if(message.type==='lock') run();
  else queue=queue.catch(()=>{}).then(run);
  return true;
});
api.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='credlet-lock')core.vault.logout();});
api.runtime.onInstalled.addListener(({reason})=>{if(reason==='install')api.tabs.create({url:api.runtime.getURL('vault.html')});});
