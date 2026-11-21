const el = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
let pinned = params.get('job');
let pinnedRevision = Number(params.get('revision')) || null;
let selected = '', feed, jobs = [], streamAvailable = false, railKey = '';
let cursor = 0, stick = true;
const output = el('output');

function scrollLatest() {
  stick = true;
  output.scrollTop = output.scrollHeight;
  el('latest').hidden = true;
}
output.addEventListener('scroll', () => {
  stick = output.scrollHeight - output.scrollTop - output.clientHeight < 20;
  el('latest').hidden = stick;
});
el('latest').onclick = scrollLatest;

function pick(job, revision) {
  const key = job.id + '/' + revision;
  if (selected === key) return;
  feed?.close();
  selected = key;
  cursor = 0;
  output.textContent = '';
  scrollLatest();
  el('brief').textContent = job.revision === revision ? job.prompt : 'Earlier job revision';
  el('revision').textContent = 'Revision ' + revision;
  el('identity').textContent = job.id.slice(0, 8);
  el('identity').title = job.id;
  el('status').textContent = job.status;
  el('source').textContent = 'Worker output';
  el('notice').textContent = 'Loading output…';
  let firstPacket = true;
  const source = new EventSource('/jobs/' + job.id + '/output?revision=' + revision);
  feed = source;
  source.onmessage = event => {
    if (source !== feed) return;
    const data = JSON.parse(event.data);
    el('status').textContent = data.status;
    el('source').textContent = data.source;
    if (typeof data.start === 'number') {
      if (cursor !== data.start) output.textContent = data.start ? '…\n' : '';
      output.append(document.createTextNode(data.text));
      cursor = data.end;
      if (output.textContent.length > 131072) {
        output.textContent = '…\n' + output.textContent.slice(-65536);
      }
      if (stick && !(firstPacket && data.done)) scrollLatest();
    }
    let note = '';
    if (data.error) note = data.error;
    else if (data.status === 'superseded') note = 'This revision was superseded. Select the job to view its current revision.';
    else if (!output.textContent) note = data.done ? 'No output retained for this revision.' :
      data.status === 'queued' ? 'Queued for the worker.' :
      streamAvailable ? 'Waiting for the first output from the worker…' : 'The result will appear when the job finishes.';
    el('notice').textContent = note;
    firstPacket = false;
    if (data.done) source.close();
  };
  source.onerror = () => {
    if (source === feed) el('notice').textContent = 'Connection interrupted. Reconnecting…';
  };
}

function select(job) {
  pinned = job?.id || null;
  pinnedRevision = job?.revision || null;
  history.replaceState(null, '', pinned ? '/workers?job=' + pinned + '&revision=' + pinnedRevision : '/workers');
  render();
}

function render() {
  el('auto').setAttribute('aria-pressed', String(!pinned));
  const job = pinned ? jobs.find(j => j.id === pinned) :
    jobs.find(j => j.status === 'running') || jobs[0];
  if (job) pick(job, pinnedRevision || job.revision);
  else {
    feed?.close();
    feed = null;
    selected = '';
    output.textContent = '';
    el('brief').textContent = pinned ? 'Job unavailable' : 'Waiting for a delegated job';
    for (const name of ['revision', 'identity', 'status', 'notice']) el(name).textContent = '';
  }
  const key = JSON.stringify([selected, jobs]);
  if (key === railKey) return;
  railKey = key;
  el('jobs').replaceChildren(...jobs.map(j => {
    const button = document.createElement('button');
    button.className = 'job';
    button.setAttribute('aria-current', String(selected === j.id + '/' + j.revision));
    const brief = document.createElement('span');
    brief.textContent = j.prompt;
    const label = document.createElement('small');
    label.textContent = j.status + ' · r' + j.revision + ' · ' + j.id.slice(0, 8);
    button.append(brief, label);
    button.onclick = () => select(j);
    return button;
  }));
}

el('auto').onclick = () => select(null);
async function refresh() {
  try {
    const response = await fetch('/workers/jobs' + (pinned ? '?job=' + encodeURIComponent(pinned) : ''), {cache:'no-store'});
    if (!response.ok) throw Error();
    const state = await response.json();
    jobs = state.jobs.slice().reverse();
    streamAvailable = state.streaming;
    el('engine').textContent = 'Configured worker · ' + (state.harness === 'pi' ? 'Pi.dev' : state.harness) + ' · ' + (state.model || 'Model unspecified');
    el('connection').textContent = 'Connected';
    render();
  } catch {
    el('connection').textContent = 'Reconnecting…';
  }
  setTimeout(refresh, 1000);
}
refresh();
