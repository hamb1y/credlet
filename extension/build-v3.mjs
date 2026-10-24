import {build} from 'esbuild';
import {mkdir,cp,writeFile,readFile,rm} from 'node:fs/promises';
import path from 'node:path';
const pkg=JSON.parse(await readFile('package.json','utf8'));
const icons=Object.fromEntries([16,32,48,128].map(size=>[size,`icon-${size}.png`]));
for(const target of ['chrome','firefox']) {
  const out=path.resolve('extension/dist',target);
  await rm(out,{recursive:true,force:true});await mkdir(out,{recursive:true});
  await cp('client/dist',out,{recursive:true});
  await cp(path.join(out,'index.html'),path.join(out,'vault.html'));
  await build({entryPoints:['background-v3','content','passkey-page','passkey-bridge'].map(name=>'extension/src/'+name+'.js'),outdir:out,bundle:true,format:'iife',target:['chrome122','firefox142'],entryNames:'[name]',legalComments:'eof'});
  for(const size of [16,32,48,128]) await cp(`extension/assets/icon-${size}.png`,path.join(out,`icon-${size}.png`));
  const common={name:'Credlet',version:pkg.version,description:'Private credentials with a C server and application-encrypted HTTP sync.',icons,
    permissions:['storage','alarms','activeTab','tabs','clipboardWrite'],options_ui:{page:'vault.html',open_in_tab:true},
    content_scripts:[{matches:['https://*/*'],js:['passkey-bridge.js'],run_at:'document_start'},{matches:['https://*/*'],js:['passkey-page.js'],world:'MAIN',run_at:'document_start'}]};
  const csp="script-src 'self' 'wasm-unsafe-eval'; object-src 'none'; base-uri 'none'";
  const manifest=target==='chrome' ? {...common,manifest_version:3,minimum_chrome_version:'122',permissions:[...common.permissions,'scripting'],host_permissions:['http://*/*','https://*/*'],
    background:{service_worker:'background-v3.js'},action:{default_popup:'vault.html',default_title:'Credlet',default_icon:icons},content_security_policy:{extension_pages:csp}}
    : {...common,manifest_version:2,permissions:[...common.permissions,'http://*/*','https://*/*'],background:{scripts:['background-v3.js'],persistent:false},browser_action:{default_popup:'vault.html',default_title:'Credlet',default_icon:icons},
      browser_specific_settings:{gecko:{id:'lockbox@selfhost.local',strict_min_version:'142.0',data_collection_permissions:{required:['authenticationInfo','websiteContent'],optional:[]}},gecko_android:{strict_min_version:'142.0'}},content_security_policy:csp};
  await writeFile(path.join(out,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  await cp('LICENSE',path.join(out,'LICENSE'));
  console.log('Built unified Svelte '+target+' extension: '+out);
}
