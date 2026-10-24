import nacl from 'tweetnacl';
import {b64, unb64, utf8, text, random} from './crypto.js';

export function serverOrigin(value) {
  let url;
  try { url = new URL(value); } catch { throw Error('Enter the HTTP address of your Credlet server.'); }
  if (url.protocol !== 'http:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw Error('Use an HTTP server address without a path, credentials or query.');
  return url.origin;
}

export async function httpExchange(origin, envelope) {
  let response;
  try {
    response = await fetch(origin+'/v1/exchange',{method:'POST',body:JSON.stringify(envelope),headers:{'Content-Type':'application/json'},credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(30000)});
  } catch { throw Error('Could not reach your Credlet server. Check its HTTP address and your connection.'); }
  if (!response.ok) throw Error('The server rejected the encrypted connection. Check its address and pinned key.');
  const body = await response.text();
  if (body.length>16*1024*1024) throw Error('The server response is too large.');
  return JSON.parse(body);
}

export class Transport {
  constructor({server, serverKey, exchange=httpExchange, now=Date.now}) {
    this.origin=serverOrigin(server); this.key=unb64(serverKey,32); this.exchange=exchange; this.now=now;
    if (this.key.every(n=>n===0)) throw Error('Invalid pinned server key.');
  }
  async request(action,data={},token=null) {
    const pair=nacl.box.keyPair(), nonce=random(24), id=crypto.randomUUID(); let plain, decoded;
    try {
      plain=utf8(JSON.stringify({v:1,id,direction:'request',issuedAt:Math.floor(this.now()/1000),action,data,token}));
      const envelope={v:1,key:b64(pair.publicKey),nonce:b64(nonce),box:b64(nacl.box(plain,nonce,this.key,pair.secretKey))};
      const reply=await this.exchange(this.origin,envelope);
      if (reply.v!==1) throw Error('Unsupported encrypted server response.');
      decoded=nacl.box.open(unb64(reply.box),unb64(reply.nonce,24),this.key,pair.secretKey);
      if (!decoded) throw Error('Server authentication failed. Check the pinned server key.');
      const result=JSON.parse(text(decoded));
      if (result.id!==id || result.v!==1 || result.direction!=='response' || !Number.isInteger(result.status)) throw Error('Invalid or replayed server response.');
      if (result.status!==200) { const error=Error(typeof result.error==='string' ? result.error.slice(0,240) : 'Vault request rejected.'); error.status=result.status; throw error; }
      return result.data;
    } finally { pair.secretKey.fill(0); plain?.fill(0); decoded?.fill(0); }
  }
}
