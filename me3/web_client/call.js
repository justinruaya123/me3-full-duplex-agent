// One browser microphone feeds rolling Whisper. Only a completed final reaches the controller.
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
  const mic = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, channelCount: 1}});
  let ctx, source, processor, clip, busy = false, closed = false, lead = [], discardQuiet = null;
  const controller = new AbortController();
  const session = {abort, group: null, last: null};
  async function post(path, headers, body) {
    return request(path, {method: 'POST', headers, body, signal: controller.signal});
  }
  async function abort() {
    if (closed) return;
    closed = true;
    const current = clip;
    controller.abort();
    if (processor) { processor.onaudioprocess = null; processor.disconnect(); }
    source?.disconnect();
    mic.getTracks().forEach(t => t.stop());
    halt();
    if (current && !current.released) {
      await fetch('/mic/release', {method: 'POST', headers: current.headers}).catch(() => {});
    }
    if (ctx) await ctx.close();
    callSession = null;
    $('mic').disabled = false;
    callButton.textContent = 'Start voice conversation';
    statusLine.textContent = 'Microphone off';
  }
  async function finish(c, tooLong) {
    busy = true;
    try {
      await c.open;
      await post('/mic/stop', c.headers);
      await c.partial;
      if (tooLong) {
        statusLine.textContent = 'Turn too long · pause and try a shorter request';
        discardQuiet = 0;
        return;
      }
      const reply = await post('/transcribe', {...c.headers, 'X-Final': '1', 'X-Live-Call': '1'}, new Blob(c.frames));
      c.released = true;
      const {text, complete} = await reply.json();
      if (closed) return;
      if (!complete || !text.trim()) {
        statusLine.textContent = 'Listening · please repeat the full thought';
        return;
      }
      callLine('user', text);
      session.group = c.id;
      statusLine.textContent = 'Waiting for ME3…';
      await post('/message', c.headers, text);
    } catch (e) {
      if (!closed) { error(e); statusLine.textContent = 'Turn failed · listening again'; }
    } finally {
      if (!closed && !c.released) await fetch('/mic/release', {method: 'POST', headers: c.headers}).catch(() => {});
      clip = null;
      busy = false;
      lead = [];
    }
  }
  function capture(event) {
    if (closed || busy) return;
    const f = event.inputBuffer.getChannelData(0);
    let power = 0;
    for (const sample of f) power += sample * sample;
    const voiced = power / f.length > 0.00012;
    if (discardQuiet !== null) {
      discardQuiet = voiced ? 0 : discardQuiet + f.length;
      if (discardQuiet >= 14400) { discardQuiet = null; statusLine.textContent = 'Listening'; }
      return;
    }
    const pcm = Int16Array.from(f, x => Math.round(Math.max(-1, Math.min(1, x)) * 32767));
    if (!clip) {
      if (!voiced) {
        lead.push(pcm);
        if (lead.length > 4) lead.shift();
        return;
      }
      const id = crypto.randomUUID();
      const headers = {'Content-Type': 'application/octet-stream', 'X-Turn': id, 'X-Client': key};
      clip = {id, headers, frames: lead, silence: 0, partial: null, lastPartial: 0, open: post('/mic/start', headers)};
      clip.open.catch(() => {});
      lead = [];
      statusLine.textContent = 'Hearing you…';
    }
    const c = clip;
    c.frames.push(pcm);
    c.silence = voiced ? 0 : c.silence + f.length;
    // One interim request in flight. Drop intermediate windows if Whisper is busy.
    if (c.frames.length >= 185 || c.silence >= 14400) {
      statusLine.textContent = 'Recognizing…';
      void finish(c, c.frames.length >= 185);
    } else if (voiced && !c.partial && c.frames.length - c.lastPartial >= 18) {
      c.lastPartial = c.frames.length;
      const body = new Blob(c.frames);
      c.partial = c.open.then(() => post('/transcribe', c.headers, body))
        .catch(e => { if (!closed) error(e); }).finally(() => { c.partial = null; });
    }
  }
  try {
    ctx = new AudioContext({sampleRate: 16000});
    source = ctx.createMediaStreamSource(mic);
    processor = ctx.createScriptProcessor(1024, 1, 1);
    processor.onaudioprocess = capture;
    await ctx.resume();
    source.connect(processor);
    processor.connect(ctx.destination);
  } catch (e) { await abort(); throw e; }
  callSession = session;
  $('dialogue').replaceChildren();
  $('error').textContent = '';
  $('filter').value = 'live';
  $('mic').disabled = true;
  callButton.textContent = 'End conversation';
  statusLine.textContent = 'Listening';
}

callButton.onclick = async () => {
  callButton.disabled = true;
  try {
    if (callSession) { await callSession.abort(); await send('stop talking', crypto.randomUUID()); }
    else await startCall();
  } catch (e) { error(e); }
  finally { callButton.disabled = false; }
};

events.addEventListener('message', m => {
  const s = callSession;
  if (!s) return;
  for (const e of JSON.parse(m.data)) {
    if (e.group !== s.group || e.source !== 'live') continue;
    if (e.name === 'tts.text') { s.last = callLine('assistant', e.text); statusLine.textContent = 'Preparing speech…'; }
    if (e.name === 'tts.first_pcm') statusLine.textContent = 'ME3 is speaking';
    if (e.name === 'playback.ended') {
      if (s.last) s.last.dataset.played = 'true';
      statusLine.textContent = 'Listening';
    }
    if (['tts.error', 'tts.unavailable', 'playback.interrupted'].includes(e.name)) statusLine.textContent = 'Playback interrupted · listening';
  }
});
window.addEventListener('me3-audio-disconnected', () => callSession?.abort());
window.addEventListener('pagehide', () => callSession?.abort());
