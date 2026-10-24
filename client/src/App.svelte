<script>
  import {onMount} from 'svelte';
  import {makePlatform,extension} from '../lib/platform.js';
  import {matchesOrigin} from '../lib/vault.js';
  let platform, state={unlocked:false,items:[]}, server='', serverKey='', email='', password='', enrollmentToken='';
  let creating=false, showMaster=false, busy=false, error='', notice='', query='', page='list', selected=null, editor={}, showPassword=false;
  let activeTab=null, remaining=0, code=null, request=null, approvalPassword='', generation=0;
  $: visible=state.items.filter(i=>[i.name,i.username,...(i.uris||[]).map(u=>u.uri)].join(' ').toLowerCase().includes(query.toLowerCase())).sort((a,b)=>Number(matchesOrigin(b,activeTab?.url))-Number(matchesOrigin(a,activeTab?.url))||a.name.localeCompare(b.name));
  $: matched=selected && matchesOrigin(selected.login,activeTab?.url);
  function wipe() { generation++; state={unlocked:false,items:[]}; selected=null; editor={}; code=null; password=''; approvalPassword=''; enrollmentToken=''; page='list'; query=''; showPassword=false; showMaster=false; creating=false; }
  async function work(action,success='') {
    if(busy || !platform) return;
    busy=true; error=''; notice=''; const started=generation;
    try { await action(); if(started===generation) notice=success; }
    catch(e) { if(started===generation) { if(e.locked) wipe(); error=e.message; } }
    finally { busy=false; }
  }
  async function refresh() {
    const started=generation;
    const value=await platform.request({type:'status'});
    if(started!==generation) return;
    if(!value.unlocked && state.unlocked) wipe();
    state=value;
    if(!server) { server=value.server||''; serverKey=value.serverKey||''; email=value.email||''; }
    remaining=Math.max(0,Math.ceil((value.deadline-Date.now())/1000));
  }
  async function loadApproval() {
    const started=generation;
    const requestId=new URL(location.href).searchParams.get('passkey');
    const value=requestId ? {id:requestId,...await platform.request({type:'passkey-info',requestId})} : null;
    if(started===generation) request=value;
  }
  async function unlock(event) {
    event.preventDefault();
    await work(async()=>{
      const message={type:'login',server,serverKey:serverKey.trim(),email,password,...(creating?{enrollmentToken}:{})}; password=''; enrollmentToken='';
      const started=generation;
      const value=await platform.request(message);
      if(started!==generation) return;
      state=value; remaining=Math.max(0,Math.ceil((value.deadline-Date.now())/1000)); await loadApproval();
    });
  }
  async function lock() {
    wipe(); error=''; notice='Vault locked.';
    try { await platform.request({type:'lock'}); } catch { /* The local view is already locked. */ }
  }
  async function details(id) {
    await work(async()=>{ const started=generation; const value=await platform.request({type:'details',id}); if(started!==generation) return; selected=value; page='detail'; showPassword=false; code=null; if(value.login.totp) { const fresh=await platform.request({type:'totp',id}); if(started===generation) code=fresh; } });
  }
  function edit() {
    const login=selected?.login;
    editor={name:selected?.name||'',username:login?.username||'',password:login?.password||'',uri:login?.uris.find(u=>u.uri?.startsWith('https://'))?.uri||'',totp:login?.totp||'',notes:selected?.notes||''};
    showPassword=false; page='edit';
  }
  async function save(event) {
    event.preventDefault();
    await work(async()=>{ const started=generation; const value=await platform.request({type:'save',login:editor,id:selected?.id}); if(started!==generation) return; state=value; selected=null; editor={}; page='list'; },'Login saved and synced.');
  }
  async function remove() {
    if(!confirm('Delete this login from every synced client? This cannot be undone in v0.3.0.')) return;
    await work(async()=>{const started=generation;const value=await platform.request({type:'delete',id:selected.id});if(started!==generation)return;state=value;selected=null;page='list';},'Login deleted.');
  }
  async function syncVault() {
    await work(async()=>{const started=generation;const value=await platform.request({type:'sync'});if(started===generation)state=value;},'Vault synced.');
  }
  async function generate() {
    await work(async()=>{const started=generation;const value=await platform.request({type:'generate'});if(started===generation){editor={...editor,password:value};showPassword=true;}});
  }
  async function copy(field) {
    await work(async()=>{
      const fresh=await platform.request({type:'details',id:selected.id});
      const value=field==='code' ? (await platform.request({type:'totp',id:selected.id})).code : fresh.login[field];
      if(!state.unlocked || remaining<=0) throw Error('Vault is locked.');
      await platform.copy(value);
    },'Copied to clipboard.');
  }
  async function fill(type) { await work(async()=>{await platform.request({type,id:selected.id,tabId:activeTab.id});},'Field filled. Review and submit on the website.'); }
  async function approval(action) {
    await work(async()=>{
      const data={type:'passkey-'+action,requestId:request.id,password:approvalPassword,credentialId:request.selectedId||request.choices?.[0]?.id}; approvalPassword='';
      await platform.request(data); request=null; notice=action==='approve'?'Passkey request completed.':'Passkey request closed.';
    });
  }
  onMount(()=>{
    let timer, disposed=false, ticks=0;
    (async()=>{
      try { platform=await makePlatform(); await refresh(); activeTab=await platform.activeTab(); await loadApproval(); }
      catch(e) { error=e.message; }
      if(disposed) return;
      timer=setInterval(async()=>{
        if(state.unlocked) {
          remaining=Math.max(0,Math.ceil((state.deadline-Date.now())/1000));
          if(!remaining) { await lock(); return; }
        }
        ticks++;
        if(!busy && ticks%5===0) {
          try { await refresh(); if(selected?.login.totp && page==='detail') { const started=generation,id=selected.id; const fresh=await platform.request({type:'totp',id}); if(started===generation && selected?.id===id && page==='detail')code=fresh; } }
          catch(e) { if(e.locked) wipe(); }
        }
      },1000);
    })();
    return ()=>{disposed=true;clearInterval(timer);wipe();};
  });
</script>

<svelte:head><title>Credlet · Your credentials, together</title></svelte:head>
<div class="shell">
  <header>
    <div class="brand"><span class="mark" aria-hidden="true">c</span><div><strong>Credlet</strong><small>Your credentials, together.</small></div></div>
    <div class="header-actions">
      {#if extension}<button class="icon" aria-label="Open Credlet in a tab" onclick={()=>platform?.expand()}>↗</button>{/if}
      {#if state.unlocked}<span class="timer" aria-label="Time until vault locks">{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</span><button onclick={lock}>Lock</button>{/if}
    </div>
  </header>
  <main aria-busy={busy}>
    {#if error}<p class="feedback error" role="alert">{error}</p>{/if}
    {#if notice}<p class="feedback" role="status">{notice}</p>{/if}
    {#if !state.unlocked}
      <section class="welcome"><p class="eyebrow">YOUR VAULT. YOUR SERVER.</p><h1>{creating?'Create your private vault.':'Welcome back.'}</h1><p>One place for your passwords, passkeys and authenticator codes.</p></section>
      <form onsubmit={unlock}>
        <label>Server HTTP address<input type="url" bind:value={server} placeholder="http://vault.example.com:8223" required autocomplete="url" /></label>
        <label>Server public key<input bind:value={serverKey} placeholder="Paste the key from your server terminal" required autocomplete="off" spellcheck="false" /><small>Copy this directly from your server or a trusted channel. It authenticates your encrypted connection.</small></label>
        <label>Owner email<input type="email" bind:value={email} required autocomplete="username" /></label>
        <label>Master password<div class="input-action"><input type={showMaster?'text':'password'} bind:value={password} required autocomplete={creating?'new-password':'current-password'} minlength={creating?12:1} /><button type="button" aria-label={showMaster?'Hide master password':'Show master password'} onclick={()=>showMaster=!showMaster}>{showMaster?'Hide':'Show'}</button></div></label>
        {#if creating}<label>One-time enrollment token<input type="password" bind:value={enrollmentToken} required autocomplete="off" /><small>Shown once when you initialize the C server.</small></label>{/if}
        <button class="primary full" disabled={busy||!platform} type="submit">{busy?'Unlocking…':creating?'Create encrypted vault':'Unlock vault'}</button>
      </form>
      <button class="text full" disabled={busy} onclick={()=>{creating=!creating;error='';}}>{creating?'Already have a vault? Sign in':'First time? Set up your vault'}</button>
      <p class="footnote">Your master password stays on your device. Traffic is encrypted by Credlet over HTTP.</p>
      {#if request}<div class="actions"><button onclick={()=>approval('cancel')} disabled={busy}>Cancel passkey request</button><button onclick={()=>approval('device')} disabled={busy}>Use device instead</button></div>{/if}
    {:else if request}
      <p class="eyebrow">PASSKEY REQUEST</p><h1>{request.kind==='create'?'Create a passkey':'Sign in with a passkey'}</h1>
      <p class="origin">{request.origin}</p><p>Verify the website above, then confirm with your master password.</p>
      <form onsubmit={(event)=>{event.preventDefault();approval('approve');}}><label>Master password<input type="password" bind:value={approvalPassword} required autocomplete="current-password" /></label>{#if request.kind==='get'}<label>Account<select bind:value={request.selectedId}>{#each request.choices as choice}<option value={choice.id}>{choice.userName}</option>{/each}</select></label>{/if}<button class="primary full" disabled={busy||request.kind==='get'&&!request.choices.length}>Approve</button></form>
      <div class="actions"><button onclick={()=>approval('cancel')} disabled={busy}>Cancel</button><button onclick={()=>approval('device')} disabled={busy}>Use device instead</button></div>
    {:else if page==='edit'}
      <button class="text" onclick={()=>page=selected?'detail':'list'} disabled={busy}>← Back</button><h1>{selected?'Edit login':'New login'}</h1>
      <form onsubmit={save}>
        <label>Name<input bind:value={editor.name} required maxlength="200" placeholder="e.g. Personal email" /></label>
        <label>Username<input bind:value={editor.username} autocomplete="off" /></label>
        <label>Password<div class="input-action"><input type={showPassword?'text':'password'} bind:value={editor.password} autocomplete="new-password" /><button type="button" onclick={()=>showPassword=!showPassword}>{showPassword?'Hide':'Show'}</button></div></label>
        <button type="button" class="text" disabled={busy} onclick={generate}>Generate a strong password ↗</button>
        <label>Website <span class="optional">optional</span><input type="url" bind:value={editor.uri} placeholder="https://example.com" /><small>Website matching uses the exact HTTPS origin.</small></label>
        <label>Authenticator secret <span class="optional">optional</span><input type="password" bind:value={editor.totp} autocomplete="off" spellcheck="false" placeholder="Secret key or otpauth:// URL" /></label>
        <label>Encrypted notes<textarea rows="4" bind:value={editor.notes} maxlength="12000"></textarea></label>
        <button type="submit" class="primary full" disabled={busy}>{busy?'Saving…':'Save login'}</button>
      </form>
    {:else if page==='detail' && selected}
      <div class="toolbar"><button class="text" onclick={()=>{page='list';selected=null;code=null;}}>← Logins</button><div><button onclick={edit} disabled={busy}>Edit</button><button class="danger text" onclick={remove} disabled={busy}>Delete</button></div></div>
      <h1>{selected.name}</h1>
      <div class="field"><span class="label">Username</span><div class="secret"><span>{selected.login.username||'—'}</span><button disabled={busy||!selected.login.username} onclick={()=>copy('username')}>Copy</button></div></div>
      <div class="field"><span class="label">Password</span><div class="secret"><span class="password">{showPassword?selected.login.password:'••••••••••••••••'}</span><button onclick={()=>showPassword=!showPassword}>{showPassword?'Hide':'Show'}</button><button disabled={busy||!selected.login.password} onclick={()=>copy('password')}>Copy</button></div></div>
      {#if code}<section class="otp"><p class="eyebrow">AUTHENTICATOR CODE</p><strong>{code.code.slice(0,3)} {code.code.slice(3)}</strong><progress value={code.remaining} max={code.period}></progress><small>Refreshes in {code.remaining}s</small><div class="actions"><button onclick={()=>copy('code')} disabled={busy}>Copy code</button>{#if extension}<button onclick={()=>fill('fill-code')} disabled={busy||!matched}>Fill code</button>{/if}</div></section>{/if}
      {#if extension}<button class="primary full" disabled={busy||!matched} onclick={()=>fill('fill')}>Fill on this website</button>{#if !matched}<p class="footnote">Open the matching HTTPS website to fill this login.</p>{/if}{/if}
      {#if selected.notes}<h2>Notes</h2><p class="notes">{selected.notes}</p>{/if}
      {#if selected.login.uris.length}<h2>Linked websites and apps</h2>{#each selected.login.uris as uri}<p class="origin">{uri.uri}</p>{/each}{/if}
    {:else}
      <div class="toolbar"><div><p class="eyebrow">YOUR PRIVATE SPACE</p><h1>Logins <span class="count">{state.items.length}</span></h1></div><button class="primary" disabled={busy} onclick={()=>{selected=null;edit();}}>+ New login</button></div>
      <label class="search"><span class="sr-only">Search logins</span><input type="search" bind:value={query} placeholder="Search names, usernames or websites" /></label>
      <div class="list-toolbar"><small>{visible.length} {visible.length===1?'login':'logins'}</small><button class="text" disabled={busy} onclick={syncVault}>{busy?'Working…':'↻ Sync'}</button></div>
      {#if visible.length}<ul class="logins">{#each visible as item(item.id)}<li><button disabled={busy} onclick={()=>details(item.id)}><span class="avatar" aria-hidden="true">{item.name.slice(0,1).toUpperCase()}</span><span class="login-name"><strong>{item.name}</strong><small>{item.username||'No username'}</small></span>{#if matchesOrigin(item,activeTab?.url)}<span class="badge">This site</span>{:else if item.hasPasskey}<span class="badge">Passkey</span>{/if}<span aria-hidden="true">›</span></button></li>{/each}</ul>
      {:else}<section class="empty"><span class="empty-mark" aria-hidden="true">◇</span><h2>{query?'No matching logins':'A fresh start.'}</h2><p>{query?'Try another name or website.':'Add your first login. Credlet encrypts it before syncing.'}</p>{#if query}<button onclick={()=>query=''}>Clear search</button>{:else}<button class="primary" onclick={()=>{selected=null;edit();}}>Create your first login</button>{/if}</section>{/if}
      <p class="footnote">Encrypted on your device. Synced to your server.</p>
    {/if}
  </main>
  <footer><span class="status-dot"></span> Credlet 0.3.0 · development</footer>
</div>
