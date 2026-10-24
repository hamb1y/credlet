// Isolated extension world; the background authenticates the actual sender URL and tab.
(() => {
  if (window !== top || location.protocol !== 'https:') return;
  const api=globalThis.browser || globalThis.chrome;
  window.addEventListener('message',async event=>{
    if (event.source !== window || event.origin !== location.origin || event.data?.credletWebAuthn !== 1) return;
    const m=event.data;
    if (typeof m.id !== 'string' || m.id.length > 64) return;
    if (m.type === 'cancel') { api.runtime.sendMessage({type:'passkey-source-cancel',id:m.id}).catch(()=>{}); return; }
    if (m.type !== 'request') return;
    try {
      const result=await api.runtime.sendMessage({type:'passkey-request',id:m.id,kind:m.kind,publicKey:m.publicKey});
      window.postMessage({credletWebAuthnResponse:1,id:m.id,...result},location.origin);
    } catch {
      window.postMessage({credletWebAuthnResponse:1,id:m.id,error:'Credlet is unavailable. Retry with your device.',name:'NotAllowedError'},location.origin);
    }
  });
})();
