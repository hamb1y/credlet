// Runs in the website's world. Only public WebAuthn requests and signed responses cross the bridge.
(() => {
  if (window !== top || !navigator.credentials || !globalThis.PublicKeyCredential) return;
  const credentials = navigator.credentials;
  const native = {create:credentials.create.bind(credentials), get:credentials.get.bind(credentials)};
  const encode = value => {
    const b = value instanceof ArrayBuffer ? new Uint8Array(value) : new Uint8Array(value.buffer,value.byteOffset,value.byteLength);
    let s=''; for (const n of b) s+=String.fromCharCode(n);
    return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  };
  const decode = value => Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0)).buffer;
  // Master-password verification supplies user verification even without OS biometrics.
  PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable=async()=>true;
  const pending = new Map();
  const send = message => window.postMessage({credletWebAuthn:1,...message},location.origin);
  function pack(pk) {
    const out = {...pk,challenge:encode(pk.challenge)};
    if (pk.user) out.user = {...pk.user,id:encode(pk.user.id)};
    for (const field of ['allowCredentials','excludeCredentials']) if (pk[field]) out[field]=pk[field].map(c=>({...c,id:encode(c.id)}));
    // No buffers from unsupported extensions cross into extension code.
    out.extensions = {credProps:!!pk.extensions?.credProps};
    return out;
  }
  function unpack(value) {
    const create = value.kind === 'create';
    const response = Object.create(create ? AuthenticatorAttestationResponse.prototype : AuthenticatorAssertionResponse.prototype);
    const fields={clientDataJSON:decode(value.clientDataJSON)};
    if (create) Object.assign(fields,{attestationObject:decode(value.attestationObject),
      getTransports:()=>['internal'],getAuthenticatorData:()=>decode(value.authenticatorData),
      getPublicKey:()=>decode(value.publicKey),getPublicKeyAlgorithm:()=>-7});
    else Object.assign(fields,{authenticatorData:decode(value.authenticatorData),signature:decode(value.signature),userHandle:value.userHandle ? decode(value.userHandle):null});
    for (const [key,v] of Object.entries(fields)) Object.defineProperty(response,key,{value:v,enumerable:true});
    const result=Object.create(PublicKeyCredential.prototype);
    const json=()=>({id:value.id,rawId:value.rawId,type:'public-key',authenticatorAttachment:value.authenticatorAttachment,
      clientExtensionResults:value.extensions,response:create ? {clientDataJSON:value.clientDataJSON,attestationObject:value.attestationObject,
        transports:['internal'],publicKeyAlgorithm:-7,publicKey:value.publicKey,authenticatorData:value.authenticatorData} :
        {clientDataJSON:value.clientDataJSON,authenticatorData:value.authenticatorData,signature:value.signature,userHandle:value.userHandle}});
    for (const [key,v] of Object.entries({id:value.id,rawId:decode(value.rawId),type:'public-key',response,
      authenticatorAttachment:value.authenticatorAttachment,getClientExtensionResults:()=>value.extensions,toJSON:json})) {
      Object.defineProperty(result,key,{value:v,enumerable:true});
    }
    return result;
  }
  window.addEventListener('message',event=>{
    if (event.source !== window || event.origin !== location.origin || event.data?.credletWebAuthnResponse !== 1) return;
    const message=event.data, entry=pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id); entry.cleanup();
    if (message.fallback) entry.fallback();
    else if (message.error) entry.reject(new DOMException(message.error,message.name || 'NotAllowedError'));
    else { try { entry.resolve(unpack(message.value)); } catch { entry.reject(new DOMException('Invalid authenticator response.','UnknownError')); } }
  });
  for (const kind of ['create','get']) {
    credentials[kind] = function(options) {
      if (!options?.publicKey || options.mediation === 'conditional') return native[kind](options);
      if (options.signal?.aborted) return Promise.reject(options.signal.reason || new DOMException('Request aborted.','AbortError'));
      let publicKey; try { publicKey=pack(options.publicKey); } catch (error) { return Promise.reject(error); }
      return new Promise((resolve,reject)=>{
        const id=crypto.randomUUID();
        const abort=()=>{
          if (!pending.delete(id)) return;
          cleanup(); send({type:'cancel',id}); reject(options.signal.reason || new DOMException('Request aborted.','AbortError'));
        };
        const cleanup=()=>{clearTimeout(timer);options.signal?.removeEventListener('abort',abort);};
        const timer=setTimeout(()=>{
          if (!pending.delete(id)) return;
          cleanup();send({type:'cancel',id});reject(new DOMException('Passkey request expired.','NotAllowedError'));
        },Math.min(125000,Math.max(20000,Number(publicKey.timeout)||65000)));
        pending.set(id,{resolve,reject,cleanup,fallback:()=>native[kind](options).then(resolve,reject)});
        options.signal?.addEventListener('abort',abort,{once:true});
        send({type:'request',id,kind,publicKey});
      });
    };
  }
})();
