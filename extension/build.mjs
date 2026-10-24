import { build } from 'esbuild';
import { mkdir, cp, writeFile, rm, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(await readFile(path.join(root,'..','package.json'),'utf8'));
let licenses='Credlet\n\n'+await readFile(path.join(root,'..','LICENSE'),'utf8')+'\n\nThird-party libraries\n\n';
for (const dependency of ['hash-wasm','tldts','tldts-core']) licenses += dependency+'\n\n'+await readFile(path.join(root,'..','node_modules',dependency,'LICENSE'),'utf8')+'\n\n';
for (const target of ['firefox', 'chrome']) {
  const out = path.resolve(root, 'dist', target);
  await rm(out, {recursive:true, force:true}); await mkdir(out, {recursive:true});
  await build({entryPoints: ['background','content','ui','passkey-page','passkey-bridge'].map(x => path.join(root,'src',x+'.js')),
    outdir:out, bundle:true, format:'iife', target:['firefox142','chrome122'], legalComments:'eof'});
  for (const file of ['vault.html','vault.css']) await cp(path.join(root,'src',file), path.join(out,file));
  for (const file of ['icon.svg',...['16','32','48','128'].map(size=>`icon-${size}.png`)]) await cp(path.join(root,'assets',file),path.join(out,file));
  await writeFile(path.join(out,'THIRD_PARTY_LICENSES.txt'), licenses);
  const icons=Object.fromEntries([16,32,48,128].map(size=>[size,`icon-${size}.png`]));
  const common = {name:'Credlet', version:pkg.version, icons, description:'Your self-hosted password vault, with encrypted sync, TOTP and passkeys.',
    content_scripts:[{matches:['https://*/*'],js:['passkey-bridge.js'],run_at:'document_start'},
      {matches:['https://*/*'],js:['passkey-page.js'],world:'MAIN',run_at:'document_start'}],
    permissions:['storage','alarms','activeTab','tabs','clipboardWrite'], options_ui:{page:'vault.html',open_in_tab:true}};
  const manifest = target === 'firefox' ? {...common, manifest_version:2,
    permissions:[...common.permissions,'https://*/*'],
    background:{scripts:['background.js'],persistent:false}, browser_action:{default_popup:'vault.html',default_title:'Credlet',default_icon:icons},
    browser_specific_settings:{gecko:{id:'lockbox@selfhost.local',strict_min_version:'142.0',
      data_collection_permissions:{required:['authenticationInfo','websiteContent'],optional:[]}},gecko_android:{strict_min_version:'142.0'}},
    content_security_policy:"script-src 'self' 'wasm-unsafe-eval'; object-src 'none'"}
    : {...common,manifest_version:3,minimum_chrome_version:'122',permissions:[...common.permissions,'scripting'],host_permissions:['https://*/*'],
      background:{service_worker:'background.js'},action:{default_popup:'vault.html',default_title:'Credlet',default_icon:icons},
      content_security_policy:{extension_pages:"script-src 'self' 'wasm-unsafe-eval'; object-src 'none'"}};
  await writeFile(path.join(out,'manifest.json'), JSON.stringify(manifest,null,2)+'\n');
  console.log(`Built ${target}: ${out}`);
}
