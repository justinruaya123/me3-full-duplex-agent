"""Bounded real-provider text/job smoke; no physical audio or browser claim."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit
import uuid

from me3.configuration import ForegroundConfig
from me3.foreground import ForegroundBackend
from me3.harnesses import configured_backend
from me3.runtime import AgentRuntime

os.umask(0o077)
project = Path(__file__).resolve().parents[3]
root = project / '.local/verification/conversation-return' / ('provider-smoke-' + time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
root.mkdir(mode=0o700)
start = time.monotonic()
receipt = {
    'kind': 'actual configured Pi worker and Qwen foreground, trusted local text control, static host build and loopback HTTP preview',
    'scope': 'no microphone, audio, acoustic, browser, responsive visual, physical ownership or Raspberry Pi qualification',
    'agent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip(),
    'runtime_source_sha256': {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (project / 'me3').glob('*.py')},
    'worker_provider': os.environ.get('ME3_WORKER_PROVIDER'),
    'worker_model': os.environ.get('ME3_WORKER_MODEL'),
    'foreground_model': os.environ.get('ME3_FOREGROUND_MODEL'),
    'deadline_seconds': 180,
    'checks': {}, 'events': [], 'passed': False,
}


def event(name, **fields):
    receipt['events'].append({'event': name, 'seconds': time.monotonic() - start, **fields})


def check(name, value):
    receipt['checks'][name] = bool(value)
    if not value:
        raise AssertionError(name)


async def settle(session):
    while session.busy:
        await asyncio.sleep(0.01)


async def main():
    worker = configured_backend()
    check('actual_pi_backend', type(worker).__name__ == 'PersistentPiBackend')
    runtime = AgentRuntime(root / 'runtime', worker, ForegroundBackend(ForegroundConfig.from_env(os.environ)))
    texts = []
    other_texts = []

    async def speak(text):
        texts.append(text)
        event('trusted_text_delivery', text=text)
        return True

    async def other_speak(text):
        other_texts.append(text)
        return True

    async def stop():
        event('text_output_cancelled')

    try:
        async with asyncio.timeout(180):
            owner = 'private-smoke-owner'
            session = runtime.open_session(speak, stop, owner=owner, quiet_seconds=0)
            request = ('Create a website for a cafe named Cedar Cafe. Build one compact welcoming page with a menu of coffee, tea and pastries, opening hours, a responsive layout, and a small JavaScript button that reveals a friendly greeting. Use no external resources and keep the total bundle under 5000 characters; only tell me when I ask.')
            result = await session.accept(request)
            check('website_delegated', result == 'delegated')
            await settle(session)
            jobs = session.jobs.list()
            check('one_website_job', len(jobs) == 1 and jobs[0]['kind'] == 'website')
            job = jobs[0]
            jid = job['id']
            receipt.update(job_id=jid, revision=job['revision'])
            check('ask_first_policy', job['return_policy'] == 'ask_first')
            check('policy_suffix_not_worker_prompt', 'only tell me when i ask' not in job['prompt'].casefold())
            while runtime.supervisor.get(jid)['status'] == 'queued':
                await asyncio.sleep(0.01)
            check('job_running_before_conversation', runtime.supervisor.get(jid)['status'] == 'running')
            event('job_running')
            before = len(texts)
            arithmetic_start = time.monotonic()
            check('foreground_turn_accepted', await session.accept('What is 19 plus 23? Answer with just the number.') == 'turn')
            await settle(session)
            arithmetic = ' '.join(texts[before:])
            receipt['foreground_seconds'] = time.monotonic() - arithmetic_start
            receipt['foreground_answer'] = arithmetic
            check('foreground_real_answer_42', bool(re.search(r'\b42\b', arithmetic)))
            event('foreground_returned_while_job_status', status=runtime.supervisor.get(jid)['status'])
            check('job_still_running_before_session_end', runtime.supervisor.get(jid)['status'] == 'running')
            await runtime.end_session(session)
            event('session_ended_while_job_running', status=runtime.supervisor.get(jid)['status'])
            check('ending_session_preserved_running_job', runtime.supervisor.get(jid)['status'] == 'running')
            await runtime.supervisor.wait(jid)
            final = runtime.supervisor.get(jid)
            receipt['job_final_status'] = final['status']
            receipt['job_error_type'] = (final.get('error') or '').split(':', 1)[0] or None
            event('job_settled', status=final['status'], revision=final['revision'])
            check('real_job_completed', final['status'] == 'completed')
            check('revision_current', final['revision'] == job['revision'])
            reconnect = runtime.open_session(speak, stop, owner=owner, quiet_seconds=0)
            text_count = len(texts)
            check('same_owner_reconnect_no_unsolicited_poll', reconnect.poll() is False)
            await settle(reconnect)
            check('reconnect_no_unsolicited_output', len(texts) == text_count)
            check('reconnect_no_focus_switch', reconnect.focus is None)
            check('unretrieved_result_not_acknowledged', not reconnect.jobs.get(jid)['notified'])
            check('natural_result_request', await reconnect.accept('Show me the website.') == 'result')
            await settle(reconnect)
            result_text = reconnect.jobs.result(jid, expected_revision=job['revision'])
            check('real_verified_result_retrieved', 'Verified static website' in result_text and result_text in texts)
            check('explicit_result_acknowledged', bool(reconnect.jobs.get(jid)['notified']))
            check('retrieval_preserved_focus', reconnect.focus is None)
            workspace = (runtime.supervisor.root / final['artifact']).parent
            verification = json.loads((workspace / 'verification.json').read_text())
            receipt['build_verification'] = verification
            check('trusted_build_passed', verification['passed'] and 'node --check' in verification['checks'])
            check('saved_files_match_build_receipt', all(hashlib.sha256((workspace / 'site' / name).read_bytes()).hexdigest() == h for name, h in verification['sha256'].items()))
            check('website_contains_requested_cafe', 'cedar' in (workspace / 'site/index.html').read_text().casefold())
            other = runtime.open_session(other_speak, stop, owner='different-private-smoke-owner', quiet_seconds=0)
            check('other_owner_list_empty', not other.jobs.list())
            denied = False
            try:
                other.jobs.result(jid, expected_revision=job['revision'])
            except KeyError:
                denied = True
            check('other_owner_cannot_retrieve_result', denied)
            check('other_owner_command_denied', await other.accept('/result ' + jid) == 'unavailable')
            await settle(other)
            check('other_owner_output_has_no_result', result_text not in other_texts)
            preview_denied = False
            try:
                await other.jobs.preview(jid, expected_revision=job['revision'])
            except KeyError:
                preview_denied = True
            check('other_owner_cannot_preview', preview_denied)
            check('preview_only_after_request', not runtime.previews.servers)
            check('explicit_preview_request', await reconnect.accept('Open the website.') == 'preview')
            await settle(reconnect)
            url = runtime.previews.servers[jid][2]
            receipt['preview_url'] = url
            parts = urlsplit(url)
            reader, writer = await asyncio.open_connection(parts.hostname, parts.port)
            try:
                writer.write(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 5)
            finally:
                writer.close()
                await writer.wait_closed()
            headers, body = response.split(b'\r\n\r\n', 1)
            receipt['preview_http_status'] = headers.split(b'\r\n')[0].decode('ascii')
            receipt['preview_body_sha256'] = hashlib.sha256(body).hexdigest()
            check('preview_http_200', response.startswith(b'HTTP/1.1 200 OK'))
            check('preview_body_matches_verified_index', receipt['preview_body_sha256'] == verification['sha256']['index.html'])
            await runtime.end_session(reconnect)
            check('preview_closed_on_session_end', not runtime.previews.servers)
            event('smoke_completed')
            receipt['passed'] = all(receipt['checks'].values())
    except BaseException as exc:
        receipt['error_type'] = type(exc).__name__
        if isinstance(exc, AssertionError):
            receipt['failed_assertion'] = str(exc)
        raise
    finally:
        process = worker.process
        receipt['worker_pid_before_cleanup'] = process.pid if process else None
        await runtime.close()
        receipt['cleanup'] = {'runtime_closed': runtime.closed, 'worker_process_cleared': worker.process is None, 'worker_returncode': process.returncode if process else None, 'previews_empty': not runtime.previews.servers}
        receipt['elapsed_seconds'] = time.monotonic() - start
        (root / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'receipt': str(root / 'receipt.json'), 'passed': receipt['passed'], 'elapsed_seconds': receipt['elapsed_seconds'], 'error_type': receipt.get('error_type'), 'checks': receipt['checks'], 'cleanup': receipt['cleanup']}, indent=2), flush=True)


asyncio.run(main())
