const {test}=require('node:test');
const assert=require('node:assert/strict');
const {isPlaidCompletion,isHostedLink,registerPlaidLinkIPC}=require('../plaid-link.cjs');

test('only the fixed Plaid completion signal and exact Hosted Link host are accepted',()=>{
  assert.ok(isPlaidCompletion('pfos://plaid-complete'));
  for(const url of ['pfos://plaid-complete?public_token=forged','pfos://evil','pfos://plaid-complete/path','https://plaid-complete'])assert.equal(isPlaidCompletion(url),false);
  assert.ok(isHostedLink('https://secure.plaid.com/hl/synthetic'));
  for(const url of ['http://secure.plaid.com/hl/x','https://secure.plaid.com.evil.test/hl/x','https://evil@secure.plaid.com/hl/x','https://secure.plaid.com:444/hl/x','https://secure.plaid.com/other','file:///tmp/file'])assert.equal(isHostedLink(url),false);
});
test('browser opening requires a trusted frame and authenticated API-issued URL',async()=>{
  let handler,opened=[],requests=[];
  const mainFrame={url:'http://127.0.0.1:37841/connections'},webContents={mainFrame};
  const event={sender:webContents,senderFrame:mainFrame};
  const original=global.fetch;
  let response={status:'pending',session_id:'11111111-1111-4111-8111-111111111111',can_reopen:true,hosted_link_url:'https://secure.plaid.com/hl/synthetic'};
  let ok=true;
  global.fetch=async(url,options)=>{requests.push({url,options});return {ok,json:async()=>response}};
  try{
    registerPlaidLinkIPC({ipcMain:{handle:(_name,callback)=>handler=callback},getBackend:()=>({url:'http://127.0.0.1:12345',token:'private-capability'}),getWindow:()=>({isDestroyed:()=>false,webContents}),origin:'http://127.0.0.1:37841',openExternal:async url=>opened.push(url)});
    assert.equal((await handler({...event,senderFrame:{url:mainFrame.url}},{action:'open',token:'jwt'})).ok,false);
    assert.equal(requests.length,0);
    ok=false;response={detail:'Invalid or expired token'};
    assert.equal((await handler(event,{action:'open',token:'bad-jwt'})).ok,false);assert.equal(opened.length,0);
    ok=true;response={status:'pending',can_reopen:true,hosted_link_url:'https://evil.invalid/hl/x'};
    assert.equal((await handler(event,{action:'open',token:'jwt'})).ok,false);assert.equal(opened.length,0);
    response.hosted_link_url='https://secure.plaid.com/hl/synthetic';
    const result=await handler(event,{action:'open',token:'jwt',url:'https://evil.invalid'});
    assert.equal(result.ok,true);assert.equal(result.hosted_link_url,undefined);assert.deepEqual(opened,[response.hosted_link_url]);
    assert.equal(requests.at(-1).options.headers.Authorization,'Bearer jwt');
    assert.equal(requests.at(-1).options.headers['X-PFOS-Desktop-Token'],'private-capability');
    assert.equal((await handler(event,{action:'check',token:'jwt',sessionId:'../../auth/register'})).ok,false);
  }finally{global.fetch=original}
});
