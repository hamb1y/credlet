// Bundle the private vault bridge; Python packaging supplies the platform-specific UI.
import {build} from 'esbuild';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const out=path.join(root,'build','runtime');
await mkdir(out,{recursive:true});
await build({entryPoints:[path.join(root,'bridge.mjs')],outfile:path.join(out,'bridge.mjs'),
  bundle:true,platform:'node',format:'esm',target:'node24',legalComments:'eof'});
await writeFile(path.join(out,'THIRD_PARTY_LICENSES.txt'),'hash-wasm\n\n'+await readFile(path.join(root,'../node_modules/hash-wasm/LICENSE'),'utf8'));
console.log('Bundled desktop vault bridge: '+out);
