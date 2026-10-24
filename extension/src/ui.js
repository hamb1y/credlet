const api = globalThis.browser || globalThis.chrome;
const $ = id => document.getElementById(id);
const params = new URL(location.href).searchParams;
const requestId = params.get('passkey');
let state, currentId, currentTab, ticker, editingId, panel, busy = false;
const notice = (message = '', error = false) => {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').setAttribute('role', error ? 'alert' : 'status');
};
async function call(message) {
  const result = await api.runtime.sendMessage(message);
  if (!result?.ok) {
    const error = Error(result?.error || 'The extension restarted. Unlock your vault again.');
    error.locked = result?.locked ?? true;
    throw error;
  }
  return result.value;
}
function refreshButtons() {
  document.querySelectorAll('button').forEach(button => {
    button.disabled = busy || button.dataset.blocked === 'true';
  });
}
function blocked(id, value) { $(id).dataset.blocked = String(value); }
async function action(work, label) {
  if (busy) return;
  busy = true; notice(); refreshButtons();
  const submit = document.querySelector('form:not([hidden]) button[type="submit"]');
  const previous = submit?.textContent;
  if (submit && label) submit.textContent = label;
  document.querySelector('main').setAttribute('aria-busy','true');
  try { await work(); }
  catch (error) {
    if (state?.unlocked && (error.locked || Date.now() >= state.deadline)) {
      render({...state, unlocked:false, items:[], deadline:0});
    }
    notice(error.message, true);
    $('notice').focus();
  } finally {
    busy = false;
    if (submit && label) submit.textContent = previous;
    document.querySelector('main').setAttribute('aria-busy','false');
    refreshButtons();
  }
}
function reveal(inputId, buttonId, hidden = true) {
  $(inputId).type = hidden ? 'password' : 'text';
  $(buttonId).textContent = hidden ? 'Show' : 'Hide';
  $(buttonId).setAttribute('aria-pressed', String(!hidden));
  $(buttonId).setAttribute('aria-label', `${hidden ? 'Show' : 'Hide'} password`);
}
function show(name) {
  const changed = panel !== name;
  panel = name; clearInterval(ticker);
  for (const id of ['signin','vault','detail','editor','approval','trash-confirm']) $(id).hidden = id !== name;
  if (name !== 'approval') $('approval-password').value = '';
  if (name !== 'detail') {
    for (const id of ['detail-password','detail-username']) $(id).value = '';
    $('otp').textContent = ''; $('detail-notes').textContent = '';
  }
  if (name !== 'editor') { $('editor').reset(); editingId = null; reveal('password','editor-reveal'); }
  if (name !== 'signin') { $('master').value = ''; $('code').value = ''; reveal('master','master-reveal'); }
  if (name === 'signin') { currentId = null; $('items').replaceChildren(); }
  if (changed) {
    const focus = {signin:$('server').value && $('email').value ? 'master' : 'server', vault:'search', editor:'name', approval:'approval-password', 'trash-confirm':'trash-cancel', detail:'back'}[name];
    if (focus) $(focus).focus();
  }
}
function matchesPage(item) {
  if (!currentTab?.url?.startsWith('https:')) return false;
  const page = new URL(currentTab.url);
  return (item.uris || []).some(({uri, match}) => {
    try {
      const saved = new URL(uri);
      if (saved.protocol !== 'https:' || saved.origin !== page.origin || match === 5 || match === 4) return false;
      return match === 2 ? page.href.startsWith(saved.href) : match === 3 ? page.href === saved.href : true;
    } catch { return false; }
  });
}
function renderList() {
  $('items').replaceChildren();
  const query = $('search').value.trim().toLocaleLowerCase();
  const items = state.items.filter(item => [item.name,item.username,...(item.uris || []).map(u => u.uri)].join(' ').toLocaleLowerCase().includes(query))
    .sort((a,b) => Number(matchesPage(b)) - Number(matchesPage(a)) || a.name.localeCompare(b.name));
  $('item-count').textContent = state.items.length;
  for (const item of items) {
    const li = document.createElement('li'), button = document.createElement('button');
    const avatar = document.createElement('span'), text = document.createElement('span');
    avatar.className = 'item-avatar'; avatar.textContent = [...(item.name || '?')][0].toLocaleUpperCase(); avatar.setAttribute('aria-hidden','true');
    text.className = 'item-text';
    const name = document.createElement('strong'), username = document.createElement('small');
    name.textContent = item.name; username.textContent = item.username || (item.hasPasskey ? 'Passkey' : 'No username');
    text.append(name,username); button.append(avatar,text);
    if (matchesPage(item)) { const badge = document.createElement('span'); badge.className = 'item-badge'; badge.textContent = 'THIS SITE'; button.append(badge); }
    if (item.reprompt) { const badge = document.createElement('span'); badge.className = 'item-badge'; badge.textContent = 'PROTECTED'; button.append(badge); }
    const arrow = document.createElement('span'); arrow.className = 'item-chevron'; arrow.textContent = '›'; arrow.setAttribute('aria-hidden','true'); button.append(arrow);
    li.append(button); $('items').append(li);
    button.addEventListener('click', () => action(() => detail(item.id)));
  }
  $('empty').hidden = items.length > 0;
  $('empty-title').textContent = query ? 'No logins found' : 'Your vault starts here';
  $('empty-description').textContent = query ? 'Try another name, username or website.' : 'Add your first login. It will be encrypted before it reaches your server.';
  $('clear-search').hidden = !query; $('empty-add').hidden = !!query;
  $('page').textContent = currentTab?.url?.startsWith('https:') ? `Matching logins appear first · ${new URL(currentTab.url).hostname}` : 'Open Credlet from an HTTPS page to fill a login.';
}
function sessionLabel() {
  $('session-status').textContent = state?.unlocked ? `Locks in ${Math.max(0,Math.ceil((state.deadline-Date.now())/60000))} min · Encrypted on your server` : 'Encrypted on your device · Stored on your server';
}
function render(next) {
  state = next;
  $('server').value = state.server || $('server').value;
  $('email').value = state.email || $('email').value;
  $('lock').hidden = !state.unlocked;
  show(state.unlocked ? (requestId ? 'approval' : 'vault') : 'signin');
  sessionLabel();
  if (requestId) { loadApproval().catch(error => notice(error.message,true)); return; }
  renderList();
}
async function detail(id) {
  const item = await call({type:'details',id}); currentId = id;
  // A newly opened Chrome tab can still have an empty URL when the popup
  // starts. Resolve it again before deciding whether autofill is available.
  if (currentTab) currentTab = await api.tabs.get(currentTab.id).catch(() => null);
  show('detail'); $('detail-name').textContent = item.name;
  $('detail-username').value = item.login.username;
  $('detail-password').value = item.login.password; reveal('detail-password','reveal');
  $('detail-uri').textContent = item.login.uris.map(u => u.uri).filter(Boolean).join('\n');
  $('detail-notes').textContent = item.notes; $('detail-notes-panel').hidden = !item.notes;
  $('otp-panel').hidden = !item.login.totp;
  const match = matchesPage(state.items.find(i => i.id === id) || {});
  blocked('fill',!match); blocked('fill-code',!match);
  $('fill-help').textContent = match ? 'Review and submit the filled form yourself.' : 'Open the extension from a matching HTTPS website to fill this login.';
  blocked('copy-username',!item.login.username); blocked('copy-password',!item.login.password);
  const update = async () => {
    try {
      const {code,remaining,period} = await call({type:'totp',id});
      if (panel !== 'detail' || currentId !== id) return;
      $('otp').textContent = code; $('otp-time').textContent = `Refreshes in ${remaining}s`;
      $('otp-progress').max = period; $('otp-progress').value = remaining;
    } catch (error) {
      clearInterval(ticker); $('otp').textContent = '';
      if (error.locked) render({...state,unlocked:false,items:[],deadline:0});
      notice(error.message,true);
    }
  };
  if (item.login.totp) { await update(); if (panel === 'detail') ticker = setInterval(update,1000); }
  refreshButtons();
}
async function loadApproval() {
  const info = await call({type:'passkey-info',requestId});
  $('locked-request').hidden = state.unlocked;
  if (!state.unlocked) { notice('Unlock your vault to continue the passkey request from '+info.origin); return; }
  $('approval-title').textContent = info.kind === 'create' ? 'Create a passkey' : 'Sign in with a passkey';
  $('approval-origin').textContent = info.origin; $('approval-rp').textContent = info.rpId;
  $('approval-user').textContent = info.kind === 'create' ? `Account: ${info.displayName || info.userName} (${info.userName})` : '';
  $('approval-choice-label').hidden = info.kind === 'create'; $('approval-choice').hidden = info.kind === 'create';
  $('approval-choice').replaceChildren();
  for (const choice of info.choices) { const option = document.createElement('option'); option.value = choice.id; option.textContent = choice.userName || 'Passkey'; $('approval-choice').append(option); }
  const missing = info.kind === 'get' && !info.choices.length;
  if (missing) notice('No matching passkey in this vault. You can use your device instead.');
  blocked('approve',missing); refreshButtons();
}
async function closeApproval(type) {
  await call({type,requestId});
  const tab = await api.tabs.getCurrent(); if (tab) await api.tabs.remove(tab.id);
}
$('approval').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const password = $('approval-password').value; $('approval-password').value = '';
    await call({type:'passkey-approve',requestId,password,credentialId:$('approval-choice').value});
    const tab = await api.tabs.getCurrent(); if (tab) await api.tabs.remove(tab.id);
  },'Verifying…');
});
$('approval-cancel').addEventListener('click', () => action(() => closeApproval('passkey-cancel')));
$('approval-device').addEventListener('click', () => action(() => closeApproval('passkey-device')));
$('signin-cancel').addEventListener('click', () => action(() => closeApproval('passkey-cancel')));
$('signin-device').addEventListener('click', () => action(() => closeApproval('passkey-device')));
$('signin').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const password = $('master').value; $('master').value = '';
    const code = $('code').value; $('code').value = '';
    render(await call({type:'login',server:$('server').value.trim(),email:$('email').value.trim(),password,code}));
  },'Unlocking…');
});
$('lock').addEventListener('click', () => action(async () => { render(await call({type:'lock'})); notice('Vault locked.'); }));
$('sync').addEventListener('click', () => action(async () => { render(await call({type:'sync'})); notice('Vault is up to date.'); }));
$('search').addEventListener('input', renderList);
$('clear-search').addEventListener('click', () => { $('search').value = ''; renderList(); $('search').focus(); });
$('back').addEventListener('click', () => render(state));
$('cancel').addEventListener('click', () => render(state));
function addLogin() {
  show('editor'); editingId = null; $('editor-title').textContent = 'Save a login'; $('editor').reset();
  if (currentTab?.url?.startsWith('https:')) $('uri').value = new URL(currentTab.url).origin;
  $('name').focus();
}
$('add').addEventListener('click',addLogin); $('empty-add').addEventListener('click',addLogin);
$('edit').addEventListener('click', () => action(async () => {
  const item = await call({type:'details',id:currentId});
  show('editor'); editingId = item.id; $('editor-title').textContent = 'Edit login';
  for (const id of ['username','password','totp']) $(id).value = item.login[id] || '';
  $('name').value = item.name; $('notes').value = item.notes || '';
  $('uri').value = item.login.uris.find(u => u.uri?.startsWith('https://'))?.uri || '';
}));
$('delete').addEventListener('click', () => { $('trash-name').textContent = $('detail-name').textContent; show('trash-confirm'); });
$('trash-cancel').addEventListener('click', () => action(() => detail(currentId)));
$('trash-submit').addEventListener('click', () => action(async () => { render(await call({type:'delete',id:currentId})); notice('Login moved to trash. Restore it from your web vault if needed.'); }));
for (const [button,input] of [['reveal','detail-password'],['master-reveal','master'],['editor-reveal','password']]) {
  $(button).addEventListener('click', () => reveal(input,button,$(input).type !== 'password'));
}
for (const [button,field] of [['copy-username','username'],['copy-password','password'],['copy-code','code']]) {
  $(button).addEventListener('click', () => action(async () => {
    // Recheck the session before releasing a value already displayed in the UI.
    const value = field === 'code' ? (await call({type:'totp',id:currentId})).code : (await call({type:'details',id:currentId})).login[field];
    await navigator.clipboard.writeText(value); notice(`${field === 'code' ? 'Authenticator code' : field === 'password' ? 'Password' : 'Username'} copied.`);
  }));
}
for (const [button,type] of [['fill','fill'],['fill-code','fill-code']]) {
  $(button).addEventListener('click', () => action(async () => {
    if (!currentTab) throw Error('Open Credlet from the page you want to fill.');
    await call({type,id:currentId,tabId:currentTab.id}); notice(type === 'fill' ? 'Login filled. Review and submit it on the page.' : 'Authenticator code filled.');
  }));
}
$('generate').addEventListener('click', () => action(async () => {
  $('password').value = await call({type:'generate'}); $('generate-help').textContent = 'New 24-character password generated. Save this login to keep it.';
}));
$('editor').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const login = Object.fromEntries(['name','username','password','totp','notes'].map(id => [id,$(id).value]));
    login.uri = $('uri').value.trim();
    render(await call({type:'save',login,id:editingId})); notice('Login encrypted and saved.');
  },'Encrypting and saving…');
});
$('expand').hidden = !!requestId;
$('expand').addEventListener('click', () => action(async () => {
  const url = api.runtime.getURL('vault.html') + (currentTab ? '?target='+currentTab.id : '');
  await api.tabs.create({url});
}));
const target = Number(params.get('target'));
(target ? api.tabs.get(target).then(tab => [tab]) : api.tabs.query({active:true,currentWindow:true})).catch(() => []).then(tabs => {
  if (tabs[0] && !tabs[0].url?.startsWith(api.runtime.getURL(''))) currentTab = tabs[0];
}).then(() => action(async () => render(await call({type:'status'}))));
setInterval(() => {
  sessionLabel();
  if (state?.unlocked && Date.now() >= state.deadline) {
    // Clear visible secrets immediately, even while a network operation is pending.
    render({...state,unlocked:false,items:[],deadline:0}); notice('Vault locked after five minutes.');
    call({type:'lock'}).catch(() => {});
  }
},1000);
setInterval(async () => {
  if (!state?.unlocked || busy) return;
  try { const next = await call({type:'status'}); if (!next.unlocked) { render(next); notice('Vault locked.'); } }
  catch { render({...state,unlocked:false,items:[],deadline:0}); notice('The extension restarted. Unlock your vault again.'); }
},5000);
