"""Local stdio host for the ME3 Pi extension. Only stdout carries protocol frames."""

import asyncio
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from me3.foreground import configured_foreground
from me3.harnesses import configured_backend
from me3.memory import worker_clarification
from me3.runtime import AgentRuntime, start_local_voice
from me3.session_folder import SessionFolder


async def serve(output):
    def emit(event_type, **fields):
        print(json.dumps({"type": event_type, **fields}), file=output, flush=True)

    root = Path(os.getenv("ME3_PI_STATE") or os.getenv("ME3_STATE_DIR", ".local/runtime"))
    worker = configured_backend()
    runtime = AgentRuntime(root, worker, configured_foreground())
    owner = os.getenv("ME3_PI_OWNER", "local-operator")
    voice_task = control = None
    chat = None

    voice_request = None
    lookups = set()

    def forward_tool(kind, text, epoch):
        nonlocal voice_request
        ident = uuid4().hex
        voice_request = (ident, epoch, kind)
        emit("terminal_request", id=ident, kind=kind, text=text, chat=chat)

    def current_voice(ident):
        return bool(voice_request and voice_request[0] == ident and voice_task
                    and not voice_task.done() and control.controller.terminal_current(voice_request[1]))

    async def search(ident, intent, bound_chat):
        from me3.lookup import BraveLookup, lookup_token
        token = lookup_token(intent[1], os.environ)
        try:
            async with asyncio.timeout(25):
                provider = BraveLookup(token)
                result = await provider.web_lookup(*intent)
            if chat == bound_chat:
                emit("response", id=ident, text=result.terminal_text(intent[1]))
            else:
                emit("response", id=ident, error="Pi chat changed.")
        except asyncio.CancelledError:
            emit("response", id=ident, error="Search cancelled.")
            raise
        except Exception as exc:
            error = ("Set BRAVE_SEARCH_API_KEY to enable Brave search."
                     if not token
                     else f"Brave search unavailable ({type(exc).__name__}).")
            emit("response", id=ident, error=error)

    async def context_question(ident, question, bound_chat):
        from me3.file_collection import open_collection
        from me3.files import answer as answer_files

        try:
            with open_collection(Path("context"), Path(".local/file-index")) as collection:
                result = await answer_files(collection, question)
            if chat != bound_chat:
                emit("response", id=ident, error="Pi chat changed.")
                return
            lines = []
            for claim in result["claims"]:
                location = (f"page {claim['page']} · box {claim['bbox']}" if "page" in claim
                            else f"lines {claim['line_start']}–{claim['line_end']}")
                lines.append(f"{claim['text']}\n{claim['path']} · {location} · {claim['id']}")
            emit("response", id=ident, text="\n\n".join(lines) or "Insufficient evidence in the project context.")
        except asyncio.CancelledError:
            emit("response", id=ident, error="Context request cancelled.")
            raise
        except Exception as exc:
            emit("response", id=ident, error=str(exc) or type(exc).__name__)

    async def display(text):
        emit("message", text=text)
        return True

    async def stop():
        pass

    session = runtime.open_session(display, stop, owner=owner)
    session.companion = lambda text: emit("message", text=text)
    jobs = session.jobs
    watched = None
    if hasattr(worker, "on_text_delta"):
        def delta(workspace, text):
            nonlocal watched
            key = (workspace.parent.name, workspace.name)
            if watched is None or key != watched[0]:
                try:
                    row = jobs.get(key[0])
                    visible = workspace.name == f"revision-{row['revision']}"
                except KeyError:
                    visible = False
                watched = key, visible
            if watched[1]:
                emit("delta", job=key[0], revision=key[1], text=text)
        worker.on_text_delta = delta

    original_trace = runtime.supervisor.trace
    def trace(event, **fields):
        original_trace(event, **fields)
        if event in {"job_started", "job_completed", "job_failed", "job_cancelled"}:
            try:
                row = jobs.get(fields["job_id"])
            except KeyError:
                return
            emit("job", job=row["id"], revision=row["revision"], status=row["status"],
                 title=row["prompt"].splitlines()[0][:80])
    runtime.supervisor.trace = trace

    def voice_done(task):
        if not task.cancelled():
            exc = task.exception()
            emit("message", text=f"Voice stopped: {exc}" if exc else "Voice stopped.")

    reader = asyncio.StreamReader(limit=100000)
    pipe, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    try:
        while line := await reader.readline():
            ident = None
            try:
                request = json.loads(line)
                ident = request["id"]
                op, text = request["op"], request.get("text", "").strip()
                if op == "shutdown":
                    break
                if op == "bind":
                    if chat is not None and text != chat:
                        raise ValueError("Detach the previous Pi chat before switching folders")
                    session.work_folder = SessionFolder(root, owner, text)
                    chat = text
                    answer = str(session.work_folder.path)
                elif request.get("chat") != chat:
                    raise ValueError("Pi chat changed. Retry in the current chat.")
                elif op in {"folder", "files", "read", "save", "create"}:
                    folder = session.work_folder
                    if folder is None:
                        raise ValueError("The Pi chat has no attached work folder")
                    if op == "save" and request.get("request_id", "").startswith("voice-"):
                        if not current_voice(request["request_id"][6:]) or voice_request[2] != "prototype":
                            raise ValueError("Voice prototype request expired")
                    if op == "folder":
                        answer = str(folder.path)
                    elif op == "files":
                        answer = folder.command("/files")
                    elif op == "read":
                        answer = folder.read(text)
                    elif op == "create":
                        draft = json.loads(text)
                        folder.create_requested(draft["name"], draft["content"], draft["request"])
                        answer = "Saved " + draft["name"] + " in this chat's work folder."
                    else:
                        answer = folder.command("/save " + text)
                        if answer is None:
                            raise ValueError("Use /me3 save FILENAME = TEXT")
                elif op == "delegate":
                    question = worker_clarification(session.memory, text)
                    if question:
                        answer = question
                    else:
                        job = jobs.submit(text, request_id=request.get("request_id") or ident)
                        answer = f"Queued job {job['id']} · revision {job['revision']}"
                elif op == "context":
                    if not chat or not text or len(text.encode()) > 1024:
                        raise ValueError("Use /me3 context QUESTION in an attached local chat")
                    if len(lookups) >= 2:
                        raise ValueError("Search is busy. Try again shortly.")
                    task = asyncio.create_task(context_question(ident, text, chat))
                    lookups.add(task)
                    task.add_done_callback(lookups.discard)
                    continue
                elif op in {"lookup", "auto_lookup"}:
                    from me3.lookup import lookup_intent

                    intent = lookup_intent(text, model_selected=op == "lookup")
                    if intent:
                        if len(lookups) >= 2:
                            raise ValueError("Brave search is busy. Try again shortly.")
                        task = asyncio.create_task(search(ident, intent, chat))
                        lookups.add(task)
                        task.add_done_callback(lookups.discard)
                        continue
                    answer = "" if op == "auto_lookup" else "Ask for a standalone public search query."
                elif op == "voice_current":
                    answer = "current" if current_voice(text) else "expired"
                elif op == "voice_report":
                    ident_voice = request.get("request_id")
                    if current_voice(ident_voice):
                        controller = control.controller
                        reports = {"done": "Your requested tool finished. The result is in Pi.",
                                   "failed": "The tool did not complete. The details are in Pi.",
                                   "busy": "Pi is busy. Ask again when this terminal turn finishes."}
                        controller._spawn(controller._deliver(reports[text], voice_request[1], record=False))
                        voice_request = None
                    answer = ""
                elif op == "jobs":
                    answer = "\n".join(f"{j['id']}  r{j['revision']}  {j['status']}  {j['prompt'][:120]}"
                                       for j in jobs.list(limit=20)) or "No jobs for this owner."
                elif op == "result":
                    answer = jobs.result(text)
                elif op == "voice":
                    if text not in {"", "demo"}:
                        raise ValueError("Use /me3 voice or /me3 voice demo")
                    if voice_task is not None and not voice_task.done():
                        raise ValueError("Voice is already attached. Use /me3 end to change modes.")
                    voice_task, control = await start_local_voice(
                        runtime, local_mcp=True, terminal_demo_owner=owner if text == "demo" else None,
                        on_voice=lambda kind, **fields: emit("voice", kind=kind, **fields))
                    control.controller.work_folder = session.work_folder
                    control.controller.terminal_request = forward_tool
                    voice_task.add_done_callback(voice_done)
                    answer = ("Starting trusted local microphone demo (owner verification bypassed)."
                              if text else "Starting owner-verified local voice.")
                elif op in {"end", "detach", "mute"}:
                    voice_request = None
                    if op == "detach":
                        for task in tuple(lookups):
                            task.cancel()
                    if voice_task and not voice_task.done():
                        if op == "mute":
                            await control.mute()
                        await control()
                        await voice_task
                    if op == "detach":
                        await runtime.end_session(session)
                        session = runtime.open_session(display, stop, owner=owner)
                        session.companion = lambda value: emit("message", text=value)
                        jobs = session.jobs
                        chat = None
                    answer = "Voice muted." if op == "mute" else "Microphone detached."
                elif op == "enroll":
                    if not voice_task or voice_task.done():
                        raise ValueError("Start /me3 voice first")
                    control.enroll(text)
                    answer = "Enrollment armed."
                elif op == "turn":
                    answer = await session.accept(text, addressed=True)
                else:
                    raise ValueError("Unknown ME3 operation")
                emit("response", id=ident, text=answer)
            except (ValueError, TypeError, KeyError, RuntimeError, PermissionError, OSError, ImportError) as exc:
                emit("response", id=ident, error=str(exc) or type(exc).__name__)
    finally:
        pipe.close()
        for task in tuple(lookups):
            task.cancel()
        await asyncio.gather(*lookups, return_exceptions=True)
        try:
            if voice_task and not voice_task.done():
                await control()
                await asyncio.gather(voice_task, return_exceptions=True)
        finally:
            await runtime.close()


if __name__ == "__main__":
    wire = sys.stdout
    with redirect_stdout(sys.stderr):
        asyncio.run(serve(wire))
