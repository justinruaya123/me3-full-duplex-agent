// The input context stays live while the independent speaker context is suspended.
let callSession = null;
const callButton = $('call'), statusLine = $('callStatus');

function callLine(role, text) {
  const row = node('p', role, '');
  row.append(node('strong', '', role === 'assistant' ? 'ME3  ' : 'You  '), document.createTextNode(text));
  const box = $('dialogue');
  box.append(row);
  while (box.children.length > 12) box.firstChild.remove();
  return row;
}

async function startCall() {
  await unlock();
  const mic = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}});
  let ctx, source, processor, timer;
  const session = {ready: false, group: null, last: null, close, control};
  callSession = session;
  function close(reason) {
    if (callSession !== session) return;
    clearTimeout(timer);
    callSession = null;
    if (processor) { processor.onaudioprocess = null; processor.disconnect(); }
    source?.disconnect();
    mic.getTracks().forEach(track => track.stop());
    if (ctx) void ctx.close();
    halt();
    if (output?.state === 'suspended') void output.resume();
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'call.end'}));
    $('mic').disabled = false;
    callButton.textContent = 'Start voice conversation';
    statusLine.textContent = reason || 'Microphone off';
  }
  function control(p) {
    if (p.type === 'call.error') { close(p.text); return; }
    if (p.type === 'call.ready') {
      clearTimeout(timer); session.ready = true; statusLine.textContent = 'Listening'; return;
    }
    if (p.type !== 'floor') return;
    if (p.state === 'start') {
      if (output) void output.suspend();
      statusLine.textContent = 'Hearing you…';
    } else if (p.state === 'stop') {
      statusLine.textContent = 'Recognizing…';
    } else {
      if (output) void output.resume();
      statusLine.textContent = p.state === 'expired' ? 'Listening · unfinished turn expired' : 'Listening';
    }
  }
  try {
    ctx = new AudioContext({sampleRate: 16000});
    source = ctx.createMediaStreamSource(mic);
    processor = ctx.createScriptProcessor(512, 1, 1);
    processor.onaudioprocess = e => {
      if (!session.ready) return;
      if (ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 16000) {
        close('Audio connection fell behind · restart conversation'); return;
      }
      ws.send(Int16Array.from(e.inputBuffer.getChannelData(0), x => Math.round(Math.max(-1, Math.min(1, x))*32767)));
    };
    await ctx.resume();
    if (callSession !== session) return;
    source.connect(processor); processor.connect(ctx.destination);
    $('dialogue').replaceChildren(); $('error').textContent = ''; $('filter').value = 'live';
    $('mic').disabled = true; callButton.textContent = 'End conversation';
    statusLine.textContent = 'Starting speech detection…';
    ws.send(JSON.stringify({type:'call.start'}));
    timer = setTimeout(() => close('Speech detection startup timed out'), 30000);
  } catch (e) { close(); throw e; }
}

callButton.onclick = async () => {
  callButton.disabled = true;
  try { if (callSession) callSession.close(); else await startCall(); }
  catch (e) { error(e); }
  finally { callButton.disabled = false; }
};
events.addEventListener('message', m => {
  const s = callSession;
  if (!s || !s.ready) return;
  for (const e of JSON.parse(m.data)) {
    if (e.source !== 'live') continue;
    if (e.name === 'user.sent') { s.group = e.group; callLine('user', e.text); }
    if (e.group !== s.group) continue;
    if (e.name === 'tts.text') { s.last = callLine('assistant', e.text); statusLine.textContent = 'Preparing speech…'; }
    if (e.name === 'tts.first_pcm') statusLine.textContent = 'ME3 is speaking';
    if (e.name === 'playback.ended') {
      if (s.last) s.last.dataset.played = 'true';
      statusLine.textContent = 'Listening';
    }
    if (['tts.error','tts.unavailable','playback.interrupted'].includes(e.name)) statusLine.textContent = 'Playback interrupted · listening';
  }
});
window.addEventListener('me3-audio-disconnected', () => callSession?.close());
window.addEventListener('pagehide', () => callSession?.close());
