import unittest

from me3.voicechat_trial import VoiceEvents


class VoiceChatTrialTests(unittest.TestCase):
    def test_final_is_dispatched_once_across_delta_replay(self):
        stream = VoiceEvents()
        final = {"type": "conversation.item.input_audio_transcription.completed",
                 "item_id": "mic-1", "transcript": "What did I say earlier?"}
        self.assertIsNone(stream.accept(final | {"type": "conversation.item.input_audio_transcription.delta"}))
        self.assertEqual(stream.accept(final)["text"], final["transcript"])
        self.assertIsNone(stream.accept(final))

    def test_remote_speech_and_tools_have_no_execution_authority(self):
        stream = VoiceEvents()
        for name in ["response.output_audio.delta", "response.output_audio_transcript.done",
                     "response.function_call_arguments.done"]:
            self.assertIsNone(stream.accept(dict(type=name, delta="123")))
        call = dict(type="app.tool_call", name="delegate_task", ok=True, call_id="c", prompt="use Pi")
        self.assertIsNone(stream.accept(call | {"ok": 1}))
        self.assertEqual(stream.accept(call)["kind"], "proposal")
        self.assertIsNone(stream.accept(call))


class NativePlaybackTests(unittest.TestCase):
    def test_remote_audio_is_playable_interruptible_and_bounded(self):
        import base64
        import threading
        from me3.voicechat_trial import Devices

        device = object.__new__(Devices)
        device.lock = threading.Lock()
        device.playing = bytearray()
        pcm = b"\x01\x08" * 1920
        packet = base64.b64encode(pcm).decode()
        device.native_audio(packet)
        self.assertEqual(device.playing, pcm)
        device.clear()
        device.native_audio(packet)
        self.assertEqual(device.playing, pcm)
        with self.assertRaises(ValueError):
            device.native_audio("eA==")
        device.playing.extend(bytes(24000 * 2 * 4))
        with self.assertRaises(BufferError):
            device.native_audio(packet)


class RelayResultsTests(unittest.TestCase):
    def test_only_live_bound_calls_can_return_one_outcome(self):
        from me3.voicechat_trial import RelayResults
        results = RelayResults("s", 512)
        call = dict(session_id="s", call_id="c", input_item_id="i",
                    result_timeout_ms=7000)
        self.assertFalse(results.open(call | {"session_id": "other"}, now=1))
        self.assertTrue(results.open(call, now=1))
        result = dict(id="c", item="i", status="success", summary="Verified.")
        self.assertIsNone(results.take(result | {"item": "other"}, now=2))
        payload = results.take(result, now=2)
        self.assertEqual(payload, {"type": "app.tool_result", "session_id": "s",
                                   "input_item_id": "i", "call_id": "c",
                                   "status": "success", "summary": "Verified."})
        self.assertIsNone(results.take(result, now=3))
        self.assertTrue(results.open(call | {"call_id": "later"}, now=4))
        self.assertIsNone(results.take(result | {"id": "later"}, now=12))

    def test_unbound_tool_loop_stops_native_output_until_next_mic_onset(self):
        from me3.voicechat_trial import NativeReplyGate
        gate = NativeReplyGate()
        self.assertTrue(gate.observe("app.error", "tool_input_unresolved"))
        self.assertFalse(gate.observe("app.error", "tool_input_unresolved"))
        self.assertFalse(gate.observe("response.output_audio.delta"))
        self.assertFalse(gate.observe("response.output_audio_transcript.delta"))
        self.assertTrue(gate.observe("app.tool_result.accepted"))
        self.assertTrue(gate.observe("input_audio_buffer.speech_started"))
        self.assertTrue(gate.observe("response.output_audio.delta"))

    def test_rollover_precedes_the_advertised_audio_ceiling(self):
        from me3.voicechat_trial import voice_chunk_limit
        self.assertEqual(voice_chunk_limit(180), 2249)
        self.assertIsNone(voice_chunk_limit(None))
        self.assertIsNone(voice_chunk_limit(-1))
