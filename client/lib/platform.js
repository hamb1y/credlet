import {controller} from './controller.js';
import {Vault} from './vault.js';

const api=globalThis.browser||globalThis.chrome;
export const extension=!!api?.runtime?.id;
export async function makePlatform() {
  if(extension) return {
    async request(message) {
      const result=await api.runtime.sendMessage(message);
      if(!result?.ok) { const error=Error(result?.error||'Credlet is unavailable.'); error.locked=result?.locked; throw error; }
      return result.value;
    },
    async activeTab() { const [tab]=await api.tabs.query({active:true,currentWindow:true}); return tab; },
    async copy(value) { await navigator.clipboard.writeText(value); },
    async expand() { await api.tabs.create({url:api.runtime.getURL('vault.html')}); }
  };
  const native=!!globalThis.__TAURI_INTERNALS__;
  let exchange;
  if(native) {
    const {invoke}=await import('@tauri-apps/api/core');
    exchange=(origin,envelope)=>invoke('encrypted_exchange',{origin,envelope});
  }
  const settings={
    async get() { try { return JSON.parse(localStorage.getItem('credlet.settings.v3')||'{}'); } catch { return {}; } },
    async set(value) { localStorage.setItem('credlet.settings.v3',JSON.stringify(value)); }
  };
  const core=controller({vault:new Vault({exchange}),settings});
  let queue=Promise.resolve();
  return {
    request(message) {
      if(message.type==='lock') return core.dispatch(message);
      const run=()=>core.dispatch(message).catch(error=>{error.locked=!core.vault.key;throw error;});
      const result=queue.catch(()=>{}).then(run); queue=result; return result;
    },
    activeTab:async()=>null, expand:async()=>{},
    async copy(value) {
      if(native) { const {writeText}=await import('@tauri-apps/plugin-clipboard-manager'); await writeText(value); }
      else await navigator.clipboard.writeText(value);
    }
  };
}
