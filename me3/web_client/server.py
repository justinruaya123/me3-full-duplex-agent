"""Loopback ME3 UAT console. All UI timestamps use the host monotonic clock."""

import asyncio
from collections import deque
from contextlib import aclosing
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid

from aiohttp import web, WSMsgType
from me3.audio_pipeline import ConfiguredSpeech
from me3.capture import wav16
from me3.duplex_voice import settings
from me3.foreground import configured_foreground
from me3.harnesses import configured_backend
from me3.runtime import AgentRuntime
from me3.incremental import TranscriptRevision
from me3.web_client.worker_console import WorkerDrafts, stream_output

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("ME3_UAT_PORT", "8766"))
HOST = f"127.0.0.1:{PORT}"
OWNER = "local-web-demo"


@web.middleware
async def local_only(request, handler):
    if request.host != HOST or (
        (request.method == "POST" or request.path == "/voice")
        and request.headers.get("Origin") != "http://" + HOST
    ):
        raise web.HTTPForbidden()
    return await handler(request)


async def app(*, course=False):
    origin = time.monotonic_ns()
    rows = deque(maxlen=600)
    serial = 0
    changed = asyncio.Event()
    closing = False

    def emit(lane, name, text="", group="", source="live", stamp=None, **details):
        nonlocal serial
        serial += 1
        rows.append(
            dict(
                id=serial,
                t=round(((stamp or time.monotonic_ns()) - origin) / 1e6),
                lane=lane,
                name=name,
                text=str(text)[:4000],
                group=group,
                source=source,
                details=details,
            )
        )
        changed.set()

    result = web.Application(middlewares=[local_only], client_max_size=384000)
    speech_config = settings()
    if course and speech_config["tts_backend"] != "local":
        raise ValueError("The course launcher requires local Kokoro")
    native_speech = ConfiguredSpeech(speech_config)
    speech = native_speech
    turn = ""
    listeners = {}
    speaker = None
    receipt = None
    utterance = ""
    scenario_task = None
    asr_lock = asyncio.Lock()
    capture = None
    capture_timeout = None
    turn_analyzer = None
    playing_id = None

    def stage(name, **fields):
        emit("foreground", name, group=turn, **fields)

    backend = configured_foreground(on_stage=stage)
    if hasattr(backend, "stream"):
        original_stream = backend.stream

        async def stream(prompt):
            group = turn
            try:
                async with aclosing(original_stream(prompt)) as upstream:
                    async for token in upstream:
                        emit("foreground", "foreground.delta", token, group)
                        yield token
            finally:
                emit("foreground", "foreground.stream_closed", group=group)

        backend.stream = stream
    worker = configured_backend()
    drafts = WorkerDrafts()
    if hasattr(worker, "on_text_delta"):

        def worker_delta(workspace, text):
            revision = int(workspace.name.removeprefix("revision-"))
            drafts.append(workspace.parent.name, revision, text)
            emit(
                "worker",
                "worker.delta",
                text,
                workspace.parent.name,
                revision=workspace.name,
            )

        worker.on_text_delta = worker_delta
    runtime = AgentRuntime(
        Path(os.getenv("ME3_UAT_STATE", ".local/course" if course else ".local/temporary-web/state")),
        worker,
        backend,
        memory_enabled=True,
    )
    store = runtime.memory
    if (
        store.db.execute(
            "SELECT 1 FROM memory_owners WHERE owner=?", (OWNER,)
        ).fetchone()
        is None
    ):
        store.set_enabled(OWNER, os.getenv("ME3_MEMORY_ENABLED") == "1")
    original_trace = runtime.supervisor.trace

    def trace(name, **fields):
        original_trace(name, **fields)
        job = fields.get("job_id")
        emit("worker" if job else "control", name, group=job or turn, **fields)

    runtime.supervisor.trace = trace

    async def speak(text):
        nonlocal receipt, utterance
        who = speaker
        group = turn
        emit("tts", "tts.text", text, group)
        if who is None or who.closed:
            emit("tts", "tts.unavailable", "Browser audio disconnected", group)
            return False
        uid = uuid.uuid4().hex[:12]
        utterance = uid
        receipt = asyncio.get_running_loop().create_future()
        try:
            await who.send_json(dict(type="start", id=uid))
            total = 0
            next_mark = 0
            async with aclosing(speech.synthesize(text)) as synthesis:
                async for chunk in synthesis:
                    if utterance != uid or who.closed:
                        return False
                    if not total:
                        emit("tts", "tts.first_pcm", group=group)
                    await who.send_bytes(chunk)
                    total += len(chunk)
                    if total >= next_mark:
                        emit("tts", "tts.pcm", group=group, ms=round(total / 48))
                        next_mark = total + 12000
            await who.send_json(dict(type="end", id=uid))
            emit("tts", "tts.synthesized", group=group, ms=round(total / 48))
            ok = await asyncio.wait_for(receipt, total / 48000 + 12)
            emit("tts", "playback.ended" if ok else "playback.interrupted", group=group)
            return ok
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            emit("tts", "tts.error", type(exc).__name__, group)
            return False
        finally:
            if uid == utterance:
                utterance = ""
                receipt = None

    async def stop():
        nonlocal utterance
        utterance = ""
        if receipt and not receipt.done():
            receipt.set_result(False)
        if speaker is not None and not speaker.closed:
            await speaker.send_json({"type": "stop"})

    session = runtime.open_session(speak, stop, owner=OWNER,
                                   is_playing=lambda: bool(utterance and playing_id == utterance))
    if course:
        from me3.course_mcp import CourseMCP

        def mcp_trace(tool, **fields):
            trace("mcp_tool", tool=tool, **fields)

        speech = CourseMCP(native_speech, session, mcp_trace)
        session.task_tools = speech.task

        async def services(application):
            async with speech.connect():
                yield

        result.cleanup_ctx.append(services)
    session.companion = lambda text: emit("control", "console.note", text, turn)

    def release_capture():
        nonlocal capture, capture_timeout
        if capture_timeout:
            capture_timeout.cancel()
            capture_timeout = None
        if capture is not None:
            capture = None
            session.dismiss_capture()

    async def poll_jobs():
        while True:
            if speaker is not None and not speaker.closed:
                session.poll()
            await asyncio.sleep(0.2)

    poller = asyncio.create_task(poll_jobs())

    async def events(request):
        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"}
        )
        await response.prepare(request)
        try:
            cursor = int(request.headers.get("Last-Event-ID", "0"))
        except ValueError:
            cursor = 0
        try:
            while not closing:
                changed.clear()
                batch = [r for r in rows if r["id"] > cursor]
                if batch:
                    cursor = batch[-1]["id"]
                    await asyncio.wait_for(
                        response.write(
                            f"id: {cursor}\ndata: {json.dumps(batch)}\n\n".encode()
                        ),
                        5,
                    )
                try:
                    await asyncio.wait_for(changed.wait(), 10)
                except asyncio.TimeoutError:
                    await response.write(b": heartbeat\n\n")
        except (ConnectionError, asyncio.TimeoutError):
            pass
        return response

    async def socket(request):
        nonlocal speaker, playing_id, turn, capture, turn_analyzer
        from me3.web_client.live import BrowserCapture, make_vad

        ws = web.WebSocketResponse(max_msg_size=2000, heartbeat=20)
        await ws.prepare(request)
        key = uuid.uuid4().hex
        listeners[key] = ws
        live = None
        await ws.send_json(dict(type="connected", key=key))

        async def mark(name, gid):
            if name == "start":
                if course:
                    await session.course_barge_in()
                else:
                    session.user_started()
            elif name == "stop":
                session.user_stopped()
            emit("user", "mic." + name, group=gid)
            await ws.send_json(dict(type="floor", state=name, group=gid))

        async def revision(event):
            nonlocal turn
            gid = event.turn_id
            emit("asr", "asr.final" if event.committed else "asr.partial",
                 event.text, gid, ms=round((event.end-event.start)*1000))
            if event.committed:
                turn = gid
                emit("user", "user.sent", event.text, gid)
            return await session.transcript(event, addressed=True)

        async def recognize(pcm):
            async with asr_lock:
                emit("asr", "asr.request", group=live.group, ms=len(pcm)//32)
                return await speech.transcribe(wav16(pcm))

        async def end_call():
            nonlocal live
            if live is not None:
                await live.close()
                live = None
                release_capture()
                await session.accept("stop talking", addressed=True)

        failed = asyncio.Event()
        def stream_error(exc):
            emit("control", "call.error", type(exc).__name__, turn)
            failed.set()

        try:
            async for msg in ws:
                if failed.is_set():
                    await ws.send_json(dict(type="call.error", text="Capture failed. Start a new conversation."))
                    await end_call()
                    failed.clear()
                if msg.type == WSMsgType.BINARY:
                    if live is not None:
                        try:
                            await live.feed(msg.data)
                        except (ValueError, BufferError, RuntimeError) as exc:
                            stream_error(exc)
                    continue
                if msg.type != WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                kind = data.get("type")
                if kind == "call.start":
                    if capture is not None or (speaker is not None and speaker is not ws and utterance):
                        await ws.send_json(dict(type="call.error", text="Another microphone or speaker is active."))
                        continue
                    capture = (key, "continuous")
                    try:
                        from me3.capture import SmartTurn
                        if turn_analyzer is None:
                            turn_analyzer = await asyncio.to_thread(SmartTurn)
                        vad = await asyncio.to_thread(make_vad)
                        live = BrowserCapture(session.jobs.session_id, vad, recognize, turn_analyzer,
                                              revision, mark, session.dismiss_capture, stream_error)
                    except Exception as exc:
                        release_capture()
                        emit("control", "call.error", type(exc).__name__)
                        await ws.send_json(dict(type="call.error", text="Unable to initialize speech detection."))
                        continue
                    speaker = ws
                    await ws.send_json(dict(type="call.ready"))
                elif kind == "call.end":
                    await end_call()
                elif speaker is ws and data.get("id") == utterance:
                    if kind == "playing":
                        playing_id = utterance
                    elif kind == "played" and receipt and not receipt.done():
                        playing_id = None
                        receipt.set_result(data.get("ok") is True)
        finally:
            await end_call()
            listeners.pop(key, None)
            if capture is not None and capture[0] == key:
                release_capture()
            if speaker is ws:
                speaker = None
                if receipt and not receipt.done():
                    receipt.set_result(False)
        return ws

    def group(request):
        value = request.headers.get("X-Turn", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", value):
            raise web.HTTPBadRequest()
        return value

    async def transcribe(request):
        gid = group(request)
        if capture != (request.headers.get("X-Client"), gid):
            raise web.HTTPConflict(text="Microphone session expired")
        if request.content_type != "application/octet-stream":
            raise web.HTTPUnsupportedMediaType()
        pcm = await request.read()
        if not 3200 <= len(pcm) <= 384000 or len(pcm) % 2:
            raise web.HTTPBadRequest()
        final = request.headers.get("X-Final") == "1"
        if asr_lock.locked():
            raise web.HTTPConflict(text="Whisper is busy")
        async with asr_lock:
            emit("asr", "asr.request", group=gid, ms=len(pcm) // 32, final=final)
            try:
                text = (await speech.transcribe(wav16(pcm))).strip()
            except Exception as exc:
                emit("asr", "asr.error", type(exc).__name__, gid)
                raise web.HTTPBadGateway(text="Whisper request failed") from None
            complete = True
            emit(
                "asr",
                "asr.incomplete" if not complete else "asr.final" if final else "asr.partial",
                text,
                gid,
                ms=len(pcm) // 32,
            )
        if capture != (request.headers.get("X-Client"), gid):
            raise web.HTTPConflict(text="Microphone session expired")
        if final:
            release_capture()
        return web.json_response(dict(text=text, complete=complete))

    async def mic_mark(request):
        nonlocal capture, capture_timeout
        name = request.match_info["name"]
        peer = request.headers.get("X-Client")
        if peer not in listeners:
            raise web.HTTPConflict(text="Reconnect the audio channel")
        identity = peer, group(request)
        if name == "start" and capture is None:
            capture = identity
            capture_timeout = asyncio.get_running_loop().call_later(45, release_capture)
            session.user_started()
        elif capture != identity:
            raise web.HTTPConflict(text="Another microphone turn is active")
        elif name == "stop":
            session.user_stopped()
        elif name == "release":
            release_capture()
        else:
            raise web.HTTPBadRequest()
        emit("user", "mic." + name, group=group(request))
        return web.Response(status=204)

    async def message(request):
        nonlocal turn, speaker
        text = (await request.text()).strip()
        if not 0 < len(text) <= 2000:
            raise web.HTTPBadRequest()
        who = listeners.get(request.headers.get("X-Client"))
        if who is None:
            raise web.HTTPConflict(text="Reconnect the audio channel")
        if capture is not None and capture[1] == "continuous" and capture[0] != request.headers.get("X-Client"):
            raise web.HTTPConflict(text="Another browser owns the live conversation")
        if speaker is not None and speaker is not who:
            await stop()
        speaker = who
        turn = group(request)
        emit("user", "user.sent", text, turn)
        expected = request.headers.get("X-Job-Revision")
        if expected is not None:
            match = re.fullmatch(r"/result ([a-f0-9]{32})", text)
            if not match or not expected.isdigit() or len(expected) > 9:
                raise web.HTTPBadRequest(text="Invalid result revision")
            try:
                job = session.jobs.get(match[1])
            except KeyError:
                raise web.HTTPNotFound(text="Unknown job") from None
            if job["revision"] != int(expected):
                raise web.HTTPConflict(
                    text="The job was revised. Select its current result."
                )
        event = TranscriptRevision(session.jobs.session_id, turn, 1, text, 0, 0, True)
        await session.transcript(
            event,
            addressed=True,
            expected_job_revision=int(expected) if expected else None,
        )
        return web.Response(status=204)

    def recent_jobs(pinned=None):
        jobs = session.jobs.list(limit=20)
        if pinned and all(j["id"] != pinned for j in jobs):
            try:
                jobs.insert(0, session.jobs.get(pinned))
            except KeyError:
                pass
        return [
            {
                k: j.get(k)
                for k in ("id", "revision", "status", "prompt", "error", "report_state")
            }
            for j in jobs
        ]

    async def worker_jobs(request):
        return web.json_response(dict(
            jobs=recent_jobs(request.query.get("job")), model=getattr(worker, "model", None),
            harness=os.getenv("ME3_HARNESS", "pi"),
            streaming=hasattr(worker, "on_text_delta"),
        ), headers={"Cache-Control": "no-store"})

    async def worker_output(request):
        return await stream_output(request, session.jobs, drafts, lambda: closing)

    async def state(request):
        enabled = store.enabled(OWNER)
        memory = store.recall(OWNER, "") if enabled else {}
        return web.json_response(
            dict(
                jobs=recent_jobs(),
                course_mcp=course,
                enabled=enabled,
                notes=memory.get("notes", [])[:30],
                messages=memory.get("messages", [])[:24],
                model=os.getenv("ME3_FOREGROUND_MODEL"),
                tts=speech_config["tts_backend"],
                tts_model=speech_config["tts_model"],
                worker_model=os.getenv("ME3_WORKER_MODEL"),
                scenario=bool(scenario_task and not scenario_task.done()),
            )
        )

    async def job_result(request):
        try:
            job_id = request.match_info["id"]
            if course:
                job = await speech.task("get_job", job_id=job_id)
                saved = await speech.task("get_result", job_id=job_id, revision=job["revision"])
                text = saved["text"]
            else:
                text = session.jobs.result(job_id)
        except (KeyError, ValueError, RuntimeError, FileNotFoundError):
            raise web.HTTPNotFound()
        return web.json_response({"text": text[:8000]})

    async def scenario(kind):
        gid = uuid.uuid4().hex[:8]

        def send(lane, name, text="", **d):
            emit(lane, name, text, gid, source="scenario", **d)

        send("control", "scenario.start", kind)
        proc = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "me3.web_client.scenario",
                    folder,
                    kind,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                async with asyncio.timeout(400):
                    async for line in proc.stdout:
                        try:
                            r = json.loads(line)
                        except ValueError:
                            continue
                        name = r.pop("event")
                        stamp = r.pop("mono_ns", None)
                        text = r.pop("text", "")
                        lane = (
                            "asr"
                            if name.startswith("asr_")
                            else "worker"
                            if "worker" in name or "job" in name
                            else "tts"
                            if name.startswith("tts.")
                            or name == "pcm"
                            or "speech" in name
                            or "playback" in name
                            or "utterance" in name
                            else "user"
                            if name.startswith("input")
                            else "foreground"
                            if "foreground" in name
                            else "control"
                        )
                        send(lane, name, text or r.pop("label", ""), stamp=stamp, **r)
                    if await proc.wait():
                        raise RuntimeError("Evaluator exited before completion")
        except Exception as exc:
            send("control", "scenario.error", str(exc))
        finally:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            send("control", "scenario.end")

    async def run(request):
        nonlocal scenario_task
        kind = request.match_info["kind"]
        if kind not in {"duplex", "checkpoint"}:
            raise web.HTTPNotFound()
        if scenario_task and not scenario_task.done():
            raise web.HTTPConflict()
        scenario_task = asyncio.create_task(scenario(kind))
        return web.Response(status=202)

    async def asset(request):
        name = request.match_info.get("asset", "index.html")
        if request.path == "/workers":
            name = "workers.html"
        if name not in {"index.html", "client.js", "client.css", "call.js",
                         "workers.html", "workers.js", "workers.css"}:
            raise web.HTTPNotFound()
        return web.FileResponse(HERE / name, headers={"Cache-Control": "no-store"})

    async def close(a):
        poller.cancel()
        if scenario_task:
            scenario_task.cancel()
        await asyncio.gather(
            poller, *([scenario_task] if scenario_task else []), return_exceptions=True
        )
        if turn_analyzer is not None:
            await turn_analyzer.close()
        await runtime.close()
        await native_speech.close()

    result.add_routes(
        [
            web.get("/", asset),
            web.get("/events", events),
            web.get("/voice", socket),
            web.get("/state", state),
            web.post("/transcribe", transcribe),
            web.post("/mic/{name}", mic_mark),
            web.post("/message", message),
            web.post("/run/{kind}", run),
            web.get("/workers", asset),
            web.get("/workers/jobs", worker_jobs),
            web.get("/jobs/{id}/output", worker_output),
            web.get("/jobs/{id}", job_result),
            web.get("/{asset}", asset),
        ]
    )

    async def disconnect(a):
        nonlocal closing
        closing = True
        changed.set()
        await asyncio.gather(*(ws.close() for ws in list(listeners.values())))

    result.on_shutdown.append(disconnect)
    async def lifetime(application):
        yield
        await close(application)

    result.cleanup_ctx.append(lifetime)
    emit("control", "inspector.ready", "Local browser session")
    return result


if __name__ == "__main__":
    raise SystemExit("The ME3 browser inspector is retired. Run ./scripts/me3.sh agent.")
