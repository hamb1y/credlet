// Prove an authenticated vault notification crosses real TLS/WebSocket reverse proxying.
import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';
import {Vault} from '../extension/src/vault.js';
const sender=new Vault(),receiver=new Vault();let ws,created;
try {
  const login={server:process.env.TEST_SERVER,email:process.env.TEST_EMAIL,password:process.env.TEST_PASSWORD};
  await sender.login(login);await receiver.login(login);
  const address=new URL('/notifications/hub',receiver.server);address.protocol='wss:';address.searchParams.set('access_token',receiver.token);
  ws=new WebSocket(address);ws.binaryType='arraybuffer';
  const frames=[];let ready=false;
  ws.addEventListener('message',event=>{
    const data=typeof event.data==='string'?Buffer.from(event.data):Buffer.from(event.data);
    if(data.equals(Buffer.from('{}\x1e')))ready=true;else frames.push(data);
  });
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('WebSocket handshake timed out.')),15000);
    ws.addEventListener('open',()=>{clearTimeout(timer);ws.send('{"protocol":"messagepack","version":1}\x1e');resolve();},{once:true});
    ws.addEventListener('error',()=>{clearTimeout(timer);reject(Error('WebSocket connection failed.'));},{once:true});
  });
  for(let i=0;i<150 && !ready;i++)await delay(100);
  assert(ready,'Vault notification protocol handshake did not complete');
  await sender.saveLogin({name:'WebSocket notification fixture',username:'disposable',password:process.env.TEST_ITEM_PASSWORD,uri:'https://example.com'});
  created=sender.items.find(i=>i.name==='WebSocket notification fixture').id;
  let notified=false;
  for(let i=0;i<150;i++) {
    // SignalR MessagePack strings include the method name and exact new cipher UUID.
    if(frames.some(b=>b.includes(Buffer.from('ReceiveMessage')) && b.includes(Buffer.from(created)))) {notified=true;break;}
    await delay(100);
  }
  assert(notified,'A second client did not receive the new cipher notification through WSS');
  await receiver.sync();assert.equal(receiver.items.find(i=>i.id===created).login.password,process.env.TEST_ITEM_PASSWORD);
  process.stdout.write('PASS authenticated WSS handshake, cipher-change delivery and second-client sync\n');
} finally {
  ws?.close();
  if(created)await sender.request('/api/ciphers/'+created,{method:'DELETE',authenticated:true});
  sender.lock();receiver.lock();
}
