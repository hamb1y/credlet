import {validateRequest, matchingPasskeys, createPasskey, getPasskey} from './passkeys.js';

export function passkeyBroker(api, getVault) {
  const pending = new Map();
  const failure = (error='Passkey request cancelled.',name='NotAllowedError')=>({error,name});
  const source = sender => sender.id === api.runtime.id && sender.frameId === 0 && sender.tab?.id != null && sender.url?.startsWith('https://');
  function finish(id, result, close = false) {
    const p=pending.get(id); if (!p) return;
    pending.delete(id); clearTimeout(p.timer); p.respond(result);
    if (close && p.approvalTab != null) api.tabs.remove(p.approvalTab).catch(()=>{});
  }
  function live(id) {
    const p=pending.get(id);
    if (!p || Date.now() >= p.deadline) throw Error('Passkey request expired. Retry on the website.');
    return p;
  }
  async function check(id) {
    const p=live(id), tab=await api.tabs.get(p.tabId);
    if (tab.url !== p.url) { finish(id,failure('The requesting page changed.'),true); throw Error('The requesting page changed.'); }
    return live(id);
  }
  async function begin(message,sender,respond) {
    if (!source(sender)) { respond(failure('Passkeys require the top-level HTTPS page.','SecurityError')); return; }
    try {
      if (typeof message.id !== 'string' || message.id.length > 64) throw Error('Invalid request.');
      const request=validateRequest(message.kind,message.publicKey,new URL(sender.url).origin);
      const tab=await api.tabs.get(sender.tab.id);
      if (!tab.active) throw Error('Request a passkey from the active page.');
      if (tab.url !== sender.url) throw Error('The requesting page address changed.');
      if (pending.size >= 8 || [...pending.values()].some(p=>p.tabId===tab.id)) throw Error('A passkey request is already open.');
      const id=crypto.randomUUID(), p={request,tabId:tab.id,url:tab.url,sourceId:message.id,respond,deadline:Date.now()+request.timeout};
      pending.set(id,p);
      p.timer=setTimeout(()=>finish(id,failure('Passkey request expired.'),true),request.timeout);
      try {
        const approval=await api.tabs.create({url:api.runtime.getURL('vault.html')+'?passkey='+id});
        if (pending.has(id)) p.approvalTab=approval.id;
        else api.tabs.remove(approval.id).catch(()=>{});
      } catch (error) { finish(id,failure(error.message)); }
    } catch (error) { respond(error.name === 'NotSupportedError' ? {fallback:true} : failure(error.message,error.name)); }
  }
  async function dispatch(message) {
    const p=await check(message.requestId), vault=getVault();
    if (message.type === 'passkey-info') {
      try { vault.requireUnlocked(); } catch { /* approval first offers the normal unlock form */ }
      return {kind:p.request.kind,origin:p.request.origin,rpId:p.request.rpId,
        userName:p.request.user?.name,displayName:p.request.user?.displayName,
        choices:vault.key && p.request.kind === 'get' ? matchingPasskeys(vault,p.request).map(c=>({id:c.id,userName:c.userName})) : []};
    }
    if (message.type === 'passkey-cancel' || message.type === 'passkey-device') {
      if (message.type === 'passkey-device') await api.tabs.update(p.tabId,{active:true});
      live(message.requestId);
      finish(message.requestId,message.type === 'passkey-device' ? {fallback:true} : failure()); return {done:true};
    }
    if (message.type !== 'passkey-approve') throw Error('Unknown passkey action.');
    vault.requireUnlocked();
    await vault.verifyPassword(message.password);
    await vault.sync();
    await check(message.requestId);
    const assertLive=()=>{live(message.requestId);vault.requireUnlocked();};
    const result=p.request.kind === 'create' ? await createPasskey(vault,p.request,assertLive) : await getPasskey(vault,p.request,message.credentialId,assertLive);
    await check(message.requestId); assertLive();
    finish(message.requestId,{value:result}); return {done:true};
  }
  function cancel(message,sender) {
    if (!source(sender)) return;
    for (const [id,p] of pending) if (p.tabId === sender.tab.id && p.sourceId === message.id && p.url === sender.url) finish(id,failure(),true);
  }
  api.tabs.onRemoved.addListener(tabId=>{
    for (const [id,p] of pending) if (p.tabId === tabId || p.approvalTab === tabId) finish(id,failure(),p.tabId === tabId);
  });
  api.tabs.onUpdated.addListener((tabId,change)=>{
    if (change.url || change.status === 'loading') for (const [id,p] of pending) {
      if (p.tabId === tabId && (change.status === 'loading' || change.url !== p.url)) finish(id,failure('The requesting page changed.'),true);
    }
  });
  return {begin,cancel,dispatch};
}
