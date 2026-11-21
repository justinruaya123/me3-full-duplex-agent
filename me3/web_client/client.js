const $=id=>document.getElementById(id);
const lanes=['user','asr','foreground','worker','tts','control'];
const rows=[];
let key='', ws, output, active=null, draftTurn='', raf=0, selected='', lastMemory='';
function node(tag,cls,text){const n=document.createElement(tag);n.className=cls;n.textContent=text;return n}
function error(e){$('error').textContent=e.message||String(e)}
async function request(path,options){const r=await fetch(path,options);if(!r.ok)throw Error((await r.text()).slice(0,160)||String(r.status));return r}
function paint(){if(!raf)raf=requestAnimationFrame(()=>{raf=0;draw()})}
const sec=t=>(t/1000).toFixed(2)+' s';
function draw(){
 const source=$('filter').value, all=rows.filter(r=>r.source===source);
 const run=all.at(-1)?.group;
 const data=source==='scenario'?all.filter(e=>e.group===run):all;
 const last=data.at(-1)?.t||0;
 const anchor=source==='scenario' ? data.findLast(e=>e.name==='scenario.start') : data.find(e=>e.name!=='inspector.ready');
 const start=Math.max(0,(anchor?.t||0)-180,last-45000);
 const end=Math.max(start+6000,(data.at(-1)?.t||0)+500);
 const chart=$('chart'), frag=document.createDocumentFragment();
 const axis=node('div','axis','');for(let i=0;i<=4;i++)axis.append(node('span','',sec(start+(end-start)*i/4)));frag.append(axis);
 for(const lane of lanes){
  const row=node('div','row '+lane,'');let seen={};
  for(const e of data.filter(r=>r.lane===lane)){
   let left=e.t;
   const join={'asr.partial':'asr.request','asr.final':'asr.request','mic.stop':'mic.start',
       'job_completed':'job_started','job_failed':'job_started','input_end':'input_start','tts.first_pcm':'tts.text',
       'tts.pcm':'tts.pcm','pcm':'pcm','tts.synthesized':'tts.first_pcm','playback.ended':'tts.synthesized'};
   const spanGroup=e.group+':'+(e.details.context||e.details.job_id||'');
   const anchor=seen[spanGroup+':'+join[e.name]];
   if(anchor!==undefined&&(e.name!=='pcm'||e.t-anchor<350))left=Math.max(anchor,start);
   seen[spanGroup+':'+e.name]=e.t;
   if(e.t<start)continue;
   const b=node('button','tick','');b.style.left=((left-start)/(end-start)*100)+'%';
   b.style.width=Math.max(.28,(e.t-left)/(end-start)*100)+'%';
   if((e.t-left)/(end-start)>.08)b.textContent=({'mic.stop':'Microphone','input_end':'Input','asr.partial':'Revision','asr.final':'Final','tts.first_pcm':'Synthesize','playback.ended':'Playback','job_completed':'Worker'})[e.name]||'';
   b.title=sec(e.t)+' · '+e.name+' '+e.text;b.setAttribute('aria-label',b.title);
   b.onclick=()=>{selected=String(e.id);$('follow').hidden=false;$('debug').textContent=logLine(e);$('debug').focus()};
   row.append(b);
   if(e.name==='floor_decision'&&e.details.decision){
    const caption=node('span','decision',e.details.decision);caption.style.left=b.style.left;row.append(caption);
   }
  }frag.append(row);
  if(lane==='asr'){
   const revisions=data.filter(e=>e.lane==='asr'&&['asr.partial','asr.final','asr_partial','asr_final'].includes(e.name)&&e.t>=start);
   const track=node('div','row wordtrack','');
   let previous=[],priorGroup='';
   revisions.forEach((e,i)=>{
    const words=e.text.split(/\s+/).filter(Boolean);
    let stable=0;
    if(priorGroup===e.group)while(stable<words.length&&stable<previous.length&&words[stable]===previous[stable])stable++;
    const marker=node('button','wordmark'+(e.name.includes('final')?' settled':''),'');
    marker.style.left=(100*(e.t-start)/(end-start))+'%';
    marker.style.maxWidth=(100*((revisions[i+1]?.t??end)-e.t)/(end-start))+'%';
    marker.title=sec(e.t)+' · '+e.name+' · '+e.text;marker.setAttribute('aria-label',marker.title);
    for(const word of words.slice(stable))marker.append(node('span','',word));
    if(!marker.childElementCount)marker.textContent=e.name.includes('final')?'✓':'·';
    marker.onclick=()=>{selected=String(e.id);$('follow').hidden=false;$('debug').textContent=logLine(e);$('debug').focus()};
    track.append(marker);previous=words;priorGroup=e.group;
   });
   frag.append(track);
  }
 }chart.replaceChildren(frag);
 const revisions=data.filter(e=>['asr.partial','asr.final','asr_partial','asr_final','user.sent'].includes(e.name)).slice(-16);
 const rev=$('revisions'), atBottom=rev.scrollHeight-rev.scrollTop-rev.clientHeight<12;
 rev.replaceChildren(...revisions.map(e=>{
  const partial=e.name.includes('partial'), typed=e.name==='user.sent';
  const block=node('div','rev '+(partial?'partial':typed?'sent':'final'),'');
  block.append(node('div','meta',sec(e.t)+'  ·  '+(typed?'Sent':partial?'Whisper revision':'Whisper final')));
  const words=node('div','tokens','');for(const word of e.text.split(/\s+/).filter(Boolean))words.append(node('span','token',word));
  block.append(words);return block;
 }));
 if(atBottom)rev.scrollTop=rev.scrollHeight;
 const recent=data.filter(e=>['asr.partial','asr.final','asr_partial','asr_final'].includes(e.name));
 const current=recent.at(-1), rolling=$('rolling');
 if(current){
  const samples=recent.filter(e=>e.group===current.group);
  let previous=[], wordRuns=[], revNo=0;
  for(const e of samples){
   const words=e.text.trim().split(/\s+/).filter(Boolean);
   let same=0;
   while(same<words.length&&same<previous.length&&words[same]===previous[same])same++;
   revNo++;wordRuns=wordRuns.slice(0,same).concat(words.slice(same).map(()=>revNo));previous=words;
  }
  const chips=node('div','tokens','');
  previous.forEach((word,i)=>{const run=wordRuns[i],token=node('span','word'+(i===0||run!==wordRuns[i-1]?' boundary':''),word);token.style.setProperty('--shade',String(run%3));token.title='First seen in revision '+run;chips.append(token)});
  rolling.replaceChildren(node('span','meta',(current.name.includes('final')?'Whisper final':'Whisper live')+' · '+sec(current.t)),chips);
 }else rolling.replaceChildren(node('span','meta','Whisper · awaiting speech'));
 const latest=data.at(-1), gaps=[];let group=latest?.group;
 if(source==='live')group=data.findLast(e=>['mic.start','user.sent'].includes(e.name))?.group;
 const g=data.filter(r=>r.group===group);
 for(const [a,b,label] of [['mic.stop','asr.final','Stop → final'],['user.sent','tts.first_pcm','Send → first PCM'],['tts.text','tts.first_pcm','Synthesis → PCM'],['input_end','asr_final','Input end → final']]){
  const finish=g.findLast(r=>r.name===b);
  const begin=finish&&g.findLast(r=>r.name===a&&r.t<=finish.t);
  if(begin&&!(a==='input_end'&&g.some(e=>e.name==='input_start'&&e.t>begin.t&&e.t<finish.t))){
   const duration=Math.round(finish.t-begin.t);
   gaps.push(label+' '+duration+' ms');
   if(begin.t>=start&&finish.t<=end&&a!=='user.sent'){
    const mark=node('div','gapmark','');mark.title=label+' · '+duration+' ms';
    mark.style.left=(100*(begin.t-start)/(end-start))+'%';
    mark.style.width=(100*duration/(end-start))+'%';
    if(duration/(end-start)>.08)mark.textContent=duration+' ms';
    chart.querySelector(a==='tts.text'?'.tts':'.asr').append(mark);
   }
  }
 }
 $('gaps').textContent=gaps.join('   ·   ')||'Gaps appear as stages finish';
 const replies=data.filter(e=>['tts.text','console.note'].includes(e.name)).slice(-6);
 $('reply').textContent=replies.map(e=>e.text).join('\n')||'Waiting for a reply';
 $('jobs').hidden=source==='scenario';
 $('artifact').hidden=source==='scenario'||!$('artifact').textContent;
 const speech=data.findLast(e=>e.lane==='tts');
 $('speechState').textContent=speech?sec(speech.t)+' · '+speech.name+' '+(speech.details.ms===undefined?'':speech.details.ms+' ms PCM'):'';
 if(!selected){const log=$('debug'),follow=log.scrollHeight-log.scrollTop-log.clientHeight<20;log.textContent=data.slice(-120).map(logLine).join('\n');if(follow)log.scrollTop=log.scrollHeight}
 const score=data.findLast(e=>e.name==='scenario.result');
 if(source==='scenario')$('checks').textContent=score?Object.entries(score.details.checks).map(([k,v])=>(v.passed?'✓ ':'✗ ')+k.replaceAll('_',' ')).join('   ·   '):data.at(-1)?.name||'';
}
function logLine(e){return sec(e.t)+'  '+e.lane+'  '+e.name+'  '+e.text+' '+(Object.keys(e.details).length?JSON.stringify(e.details):'')}
$('labels').append(node('div','axis','Elapsed'),...['Input','Whisper','Words','Foreground','Worker','Speech','Control'].map(n=>node('div','label',n)));
$('follow').onclick=()=>{selected='';$('follow').hidden=true;paint()};
$('filter').onchange=()=>{selected='';$('follow').hidden=true;paint()};
const events=new EventSource('/events');
events.onmessage=m=>{for(const e of JSON.parse(m.data))if(e.name!=='worker.delta')rows.push(e);if(rows.length>600)rows.splice(0,rows.length-600);paint()};
events.onerror=()=>$('link').textContent='Reconnecting…';
function halt(){
 if(!active)return;
 for(const s of active.nodes){s.onended=null;try{s.stop()}catch{}}
 if(ws.readyState===1)ws.send(JSON.stringify({type:'played',id:active.id,ok:false}));active=null;
}
$('mute').onclick=()=>{halt();send('stop talking',crypto.randomUUID()).catch(error)};
function connect(){
 ws=new WebSocket('ws://'+location.host+'/voice');ws.binaryType='arraybuffer';
 ws.onmessage=m=>{
  if(typeof m.data==='string'){
   const p=JSON.parse(m.data);
   if(p.type==='connected'){key=p.key;$('link').textContent='● Connected';return}
   if(p.type==='floor'||p.type.startsWith('call.')){callSession?.control(p);return}
   if(p.type==='stop'){halt();return}
   if(p.type==='start'){halt();active={id:p.id,nodes:new Set(),until:0,done:false};return}
   if(p.type==='end'&&active?.id===p.id){active.done=true;played();return}
  }else if(active&&output&&output.state!=='closed'){
   const samples=new Int16Array(m.data), buffer=output.createBuffer(1,samples.length,24000);
   const dst=buffer.getChannelData(0);for(let i=0;i<samples.length;i++)dst[i]=samples[i]/32768;
   const src=output.createBufferSource();src.buffer=buffer;src.connect(output.destination);
   const a=active;a.nodes.add(src);if(!a.started)ws.send(JSON.stringify({type:'playing',id:a.id}));a.started=true;
   const when=Math.max(output.currentTime+.014,a.until);src.start(when);a.until=when+buffer.duration;
   src.onended=()=>{a.nodes.delete(src);if(active===a)played()};
  }
 };
 ws.onclose=()=>{halt();key='';window.dispatchEvent(new Event('me3-audio-disconnected'));$('link').textContent='Reconnecting…';setTimeout(connect,1000)};
}
function played(){if(active?.done&&!active.nodes.size){ws.send(JSON.stringify({type:'played',id:active.id,ok:!!active.started}));active=null}}
async function unlock(){output??=new AudioContext();await output.resume();if(!key)throw Error('Audio channel reconnecting')}
function sendInput(text,gid,intent=$('intent').value){return send(intent==='task'?'/task '+text:text,gid)}
async function send(text,gid,headers={}){
 await unlock();$('filter').value='live';selected='';$('error').textContent='';
 await request('/message',{method:'POST',headers:{...headers,'X-Turn':gid,'X-Client':key},body:text});
 await state();
}
$('form').onsubmit=async e=>{e.preventDefault();try{await sendInput($('msg').value,draftTurn||crypto.randomUUID());$('msg').value='';draftTurn=''}catch(e){error(e)}};
document.querySelectorAll('[data-fill]').forEach(b=>b.onclick=()=>{$('intent').value='ask';$('msg').value=b.dataset.fill;$('msg').focus();draftTurn=''});
let finish=null;
$('mic').onclick=async()=>{
 if(finish){await finish();return}
 const b=$('mic');b.disabled=true;let stream,ctx,timer;
 try{
  await unlock();
  const automatic=$('autoSend').checked,intent=$('intent').value;
  stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true}});
  ctx=new AudioContext({sampleRate:16000});await ctx.resume();
  const id=crypto.randomUUID(),headers={'Content-Type':'application/octet-stream','X-Turn':id,'X-Client':key};
  await request('/mic/start',{method:'POST',headers});$('filter').value='live';$('error').textContent='';
  let pending=null,count=0,last=0,stopping=false;const chunks=[];
  const input=ctx.createMediaStreamSource(stream),processor=ctx.createScriptProcessor(1024,1,1);
  async function hypothesis(final){
   const audio=new Blob(chunks);
   const r=await request('/transcribe',{method:'POST',headers:{...headers,'X-Final':final?'1':'0'},body:audio});
   const {text}=await r.json();if(final){$('msg').value=text;draftTurn=id}
  }
  processor.onaudioprocess=e=>{
   const f=e.inputBuffer.getChannelData(0),n=Math.min(f.length,192000-count);
   if(stopping||n<=0)return;
   const pcm=new Int16Array(n);for(let i=0;i<n;i++)pcm[i]=Math.round(Math.max(-1,Math.min(1,f[i]))*32767);
   chunks.push(pcm);count+=n;
   if(!pending&&count-last>=12800){last=count;pending=hypothesis(false).catch(error).finally(()=>{pending=null})}
  };
  input.connect(processor);processor.connect(ctx.destination);
  finish=async()=>{finish=null;stopping=true;clearTimeout(timer);b.disabled=true;processor.disconnect();input.disconnect();
   stream.getTracks().forEach(t=>t.stop());await ctx.close();$('micStatus').textContent='Finalizing…';
   try{await request('/mic/stop',{method:'POST',headers});await pending;await hypothesis(true);
    if(automatic&&$('msg').value.trim()){await sendInput($('msg').value,id,intent);$('msg').value='';draftTurn='';$('micStatus').textContent='Final transcript sent.'}
    else $('micStatus').textContent='Review the final transcript, then send.'}
   catch(e){error(e);$('micStatus').textContent='Turn failed';await fetch('/mic/release',{method:'POST',headers}).catch(()=>{})}
   finally{b.textContent='Start microphone';b.disabled=false}
  };
  b.textContent='Stop and finalize';b.disabled=false;$('micStatus').textContent='Listening · 12 s maximum';timer=setTimeout(()=>finish?.(),12000);
 }catch(e){stream?.getTracks().forEach(t=>t.stop());if(ctx)await ctx.close();b.disabled=false;error(e)}
};
let enabled=false;
async function state(){
 const s=await(await request('/state')).json();enabled=s.enabled;
 $('model').replaceChildren(...[['Conversation',s.model],['Worker',s.worker_model],['ASR',s.course_mcp?'MCP · Whisper':'Whisper'],['TTS',(s.course_mcp?'MCP · ':'')+'Kokoro · '+s.tts],...(s.course_mcp?[['Task tools','MCP · local']]:[])].map(([label,value])=>{const item=node('span','role','');item.append(node('b','',label),document.createTextNode(value||'Unconfigured'));return item}));
 $('memory').textContent=enabled?'Pause memory':'Enable memory';
 const mem=JSON.stringify([enabled,s.notes,s.messages]);
 if(mem!==lastMemory){lastMemory=mem;
 $('notes').replaceChildren(...(enabled?[...s.notes.map(n=>n.key+' · '+n.content),...s.messages.slice(0,6).map(m=>m.role+' · '+m.content)]:[]).map(t=>node('div','item',t)));
 if(!$('notes').children.length)$('notes').textContent=enabled?'No saved entries yet.':'Persistence is paused.';
 }
 $('jobs').replaceChildren(...s.jobs.slice().reverse().map(j=>{const box=node('div','item','');box.append(node('strong','',j.status+' · r'+j.revision),node('span','',j.prompt));
 const watch=node('a','worker-link','Watch output ↗');
 watch.href='/workers?job='+encodeURIComponent(j.id)+'&revision='+j.revision;
 watch.target='_blank';watch.rel='noopener';box.append(watch);
 const inspect=node('button','minor','Inspect events');
 inspect.onclick=()=>{const records=rows.filter(e=>e.source==='live'&&e.lane==='worker'&&e.group===j.id);
 selected='job';$('follow').hidden=false;$('debug').textContent=records.length?records.map(logLine).join('\n'):'No retained events for this job.';$('debug').focus()};
 box.append(inspect);if(j.error)box.append(node('div','',String(j.error)));if(j.status==='completed'){const b=node('button','minor','Read result');b.onclick=async()=>{try{$('artifact').hidden=false;$('artifact').textContent=(await(await request('/jobs/'+j.id)).json()).text}catch(e){error(e)}};const speak=node('button','speak','Speak result');
 speak.onclick=()=>send('/result '+j.id,crypto.randomUUID(),{'X-Job-Revision':String(j.revision)}).catch(error);
 box.append(b,speak);if(j.report_state!=='pending')box.append(node('div','meta','Spoken report · '+j.report_state))}return box}));
 if(!s.jobs.length)$('jobs').textContent='No jobs for this owner.';
 document.querySelectorAll('[data-run]').forEach(b=>b.disabled=s.scenario);
}
$('memory').onclick=()=>send(enabled?'/memory off':'/memory on',crypto.randomUUID()).catch(error);
document.querySelectorAll('[data-run]').forEach(b=>b.onclick=async()=>{try{await request('/run/'+b.dataset.run,{method:'POST'});$('filter').value='scenario';$('checks').textContent='Starting…';selected='';paint();await state()}catch(e){error(e)}});
if(new URLSearchParams(location.search).get('view')==='scenario')$('filter').value='scenario';
async function pollState(){
 try{await state()}catch(e){error(e)}
 setTimeout(pollState,1800);
}
connect();paint();void pollState();
