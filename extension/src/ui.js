const api = globalThis.browser || globalThis.chrome;
const $ = id => document.getElementById(id);
const requestId=new URL(location.href).searchParams.get('passkey');
let state, currentId, currentTab, ticker, editingId;
const notice = (message = '', error = false) => { $('notice').textContent = message; $('notice').classList.toggle('error', error); };
async function call(message) {
  const result = await api.runtime.sendMessage(message);
  if (!result?.ok) throw Error(result?.error || 'The extension restarted. Unlock your vault again.');
  return result.value;
}
async function action(work) {
  notice();
  const buttons = [...document.querySelectorAll('button')].filter(b => !b.disabled);
  buttons.forEach(b => b.disabled = true);
  try { await work(); } catch (error) { notice(error.message, true); }
  finally { buttons.forEach(b => b.disabled = b.id === 'approve' && b.dataset.blocked === 'true'); }
}
function show(name) {
  clearInterval(ticker);
  for (const panel of ['signin','vault','detail','editor','approval','trash-confirm']) $(panel).hidden = panel !== name;
  if (name !== 'approval') $('approval-password').value='';
  if (name !== 'detail') { $('detail-password').value = ''; $('detail-username').value = ''; $('otp').textContent = ''; }
  if (name !== 'editor') { $('editor').reset();editingId=null; }
  if (name === 'signin') currentId = null;
}
function render(next) {
  state = next;
  $('server').value = state.server || $('server').value;
  $('email').value = state.email || $('email').value;
  $('lock').hidden = !state.unlocked;
  show(state.unlocked ? (requestId ? 'approval' : 'vault') : 'signin');
  if (requestId) { loadApproval().catch(error=>notice(error.message,true)); return; }
  $('items').replaceChildren();
  const query = $('search').value.toLowerCase();
  for (const item of state.items.filter(i => (i.name + ' ' + i.username).toLowerCase().includes(query))) {
    const li = document.createElement('li'), button = document.createElement('button');
    const name = document.createElement('strong'), username = document.createElement('small');
    name.textContent = item.name; username.textContent = item.username;
    button.append(name, username); li.append(button); $('items').append(li);
    button.addEventListener('click', () => action(() => detail(item.id)));
  }
  if (!$('items').children.length) { const li = document.createElement('li'); li.textContent = 'No matching logins.'; $('items').append(li); }
  $('page').textContent = currentTab?.url?.startsWith('https:') ? `Current page: ${new URL(currentTab.url).hostname}` : 'Open this extension on an HTTPS page to fill a login.';
}
async function detail(id) {
  const item = await call({type:'details', id}); currentId = id;
  show('detail'); $('detail-name').textContent = item.name;
  $('detail-username').value = item.login.username;
  $('detail-password').type = 'password'; $('detail-password').value = item.login.password;
  $('reveal').textContent = 'Show';
  $('detail-uri').textContent = item.login.uris.map(u => u.uri).join(', ');
  $('otp-panel').hidden = !item.login.totp;
  const update = async () => {
    try {
      const {code, remaining} = await call({type:'totp', id});
      $('otp').textContent = code; $('otp-time').textContent = `${remaining} seconds remaining`;
    } catch (error) { clearInterval(ticker); $('otp').textContent = ''; notice(error.message, true); }
  };
  if (item.login.totp) { await update(); ticker = setInterval(update, 1000); }
}
async function loadApproval() {
  const info=await call({type:'passkey-info',requestId});
  if (!state.unlocked) { notice('Unlock your vault to continue the passkey request from '+info.origin); return; }
  $('approval-title').textContent=info.kind === 'create' ? 'Create a passkey' : 'Sign in with a passkey';
  $('approval-origin').textContent=info.origin; $('approval-rp').textContent=info.rpId;
  $('approval-user').textContent=info.kind === 'create' ? `Account: ${info.displayName || info.userName} (${info.userName})` : '';
  $('approval-choice-label').hidden=info.kind === 'create';
  $('approval-choice').replaceChildren();
  for (const choice of info.choices) {
    const option=document.createElement('option');option.value=choice.id;option.textContent=choice.userName || 'Passkey';$('approval-choice').append(option);
  }
  if (info.kind === 'get' && !info.choices.length) notice('No matching passkey in this vault. You can use your device instead.');
  $('approve').disabled=info.kind === 'get' && !info.choices.length;
  $('approve').dataset.blocked=String($('approve').disabled);
}
async function closeApproval(type) {
  await call({type,requestId});
  const tab=await api.tabs.getCurrent(); if (tab) await api.tabs.remove(tab.id);
}
$('approval').addEventListener('submit',event=>{
  event.preventDefault();action(async()=>{
    const password=$('approval-password').value;$('approval-password').value='';
    await call({type:'passkey-approve',requestId,password,credentialId:$('approval-choice').value});
    const tab=await api.tabs.getCurrent();if (tab) await api.tabs.remove(tab.id);
  });
});
$('approval-cancel').addEventListener('click',()=>action(()=>closeApproval('passkey-cancel')));
$('approval-device').addEventListener('click',()=>action(()=>closeApproval('passkey-device')));
$('signin').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const password = $('master').value; $('master').value = '';
    render(await call({type:'login', server:$('server').value, email:$('email').value, password, code:$('code').value}));
    $('code').value = '';
  });
});
$('lock').addEventListener('click', () => action(async () => render(await call({type:'lock'}))));
$('sync').addEventListener('click', () => action(async () => render(await call({type:'sync'}))));
$('search').addEventListener('input', () => render(state));
$('back').addEventListener('click', () => render(state));
$('cancel').addEventListener('click', () => { $('editor').reset(); render(state); });
$('add').addEventListener('click', () => { show('editor'); editingId=null;$('editor-title').textContent='Save a login';$('editor').reset(); if (currentTab?.url?.startsWith('https:')) $('uri').value = new URL(currentTab.url).origin; });
$('edit').addEventListener('click',()=>action(async()=>{
  const item=await call({type:'details',id:currentId});
  show('editor');editingId=item.id;$('editor-title').textContent='Edit login';
  for(const id of ['username','password','totp']) $(id).value=item.login[id] || '';
  $('name').value=item.name;$('uri').value=item.login.uris[0]?.uri || '';
}));
$('delete').addEventListener('click',()=>{
  $('trash-name').textContent=$('detail-name').textContent;show('trash-confirm');
});
$('trash-cancel').addEventListener('click',()=>action(()=>detail(currentId)));
$('trash-submit').addEventListener('click',()=>action(async()=>{
  render(await call({type:'delete',id:currentId}));notice('Login moved to trash.');
}));
$('fill-code').addEventListener('click',()=>action(async()=>{
  if (!currentTab) throw Error('Open the extension from the page you want to fill.');
  await call({type:'fill-code',id:currentId,tabId:currentTab.id});notice('Authenticator code filled.');
}));
$('reveal').addEventListener('click', () => {
  const hidden = $('detail-password').type === 'password';
  $('detail-password').type = hidden ? 'text' : 'password'; $('reveal').textContent = hidden ? 'Hide' : 'Show';
});
$('fill').addEventListener('click', () => action(async () => {
  if (!currentTab) throw Error('Open the extension from the page you want to fill.');
  await call({type:'fill', id:currentId, tabId:currentTab.id}); notice('Login filled. Review and submit it on the page.');
}));
$('generate').addEventListener('click', () => action(async () => { $('password').value = await call({type:'generate'}); }));
$('editor').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const uri = new URL($('uri').value);
    if (uri.protocol !== 'https:' || uri.username || uri.password) throw Error('Use an HTTPS website address.');
    const login = Object.fromEntries(['name','username','password','totp'].map(id => [id,$(id).value]));
    login.uri = uri.origin;
    render(await call({type:'save', login,id:editingId})); $('editor').reset(); notice('Login encrypted and saved.');
  });
});
const target = Number(new URL(location.href).searchParams.get('target'));
(target ? api.tabs.get(target).then(tab => [tab]) : api.tabs.query({active:true, currentWindow:true})).then(tabs => {
  if (tabs[0] && !tabs[0].url?.startsWith(api.runtime.getURL(''))) currentTab = tabs[0];
}).then(() => action(async () => render(await call({type:'status'}))));
setInterval(async () => {
  if (state?.unlocked && Date.now() >= state.deadline) {
    try { render(await call({type:'lock'})); notice('Vault locked.'); } catch { show('signin'); }
  }
}, 1000);
