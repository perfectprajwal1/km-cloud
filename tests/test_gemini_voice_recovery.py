"""Offline regression tests for verified Gemini no-audio recovery.

All key files and HTTP responses in this suite are synthetic. urllib is
replaced before every call; no Google endpoint is contacted.
"""
import base64
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import types
import urllib.error
import unittest
import wave
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import gemini_voice as voice


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def wav_base64():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x10\x00" * 16000)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def no_audio_answer():
    return {
        "candidates": [{"finishReason": "OTHER", "content": {"parts": []}}],
        "usageMetadata": {"promptTokenCount": 162, "totalTokenCount": 162},
        "modelVersion": "mock-model",
    }


def audio_answer():
    return {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{
                "inlineData": {"mimeType": "audio/wav", "data": wav_base64()}
            }]},
        }],
        "usageMetadata": {"promptTokenCount": 162, "totalTokenCount": 162},
        "modelVersion": "mock-model",
    }


class VoiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="km-voice-recovery-", dir=ROOT.parent)
        self.root = pathlib.Path(self.temp.name)
        self.work = self.root / "one_call_voice" / "fingerprint" / "half1" / "missing_cards" / "c04"
        self.work.mkdir(parents=True)
        self.master = self.work / "master.wav"
        self.key1 = self.root / "gemini_key.txt"
        self.key2 = self.root / "gemini_key2.txt"
        self.key1.write_text("synthetic-key-slot-1", encoding="utf-8")
        self.key2.write_text("synthetic-key-slot-2", encoding="utf-8")
        self.story = {"id": "RV_TEST", "cards": [{"vo": "नमुना वाक्य।", "voice_tone": "neutral"}]}
        self.texts = ["नमुना वाक्य।"]

    def tearDown(self):
        self.temp.cleanup()

    def module_stub(self):
        return types.SimpleNamespace(
            spoken_form=lambda text: (text, []),
            AlignmentStop=type("AlignmentStop", (Exception,), {}),
        )

    def run_mocked(self, answers, **kwargs):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append((request, timeout))
            if not answers:
                raise AssertionError("unexpected extra HTTP call")
            return FakeResponse(answers.pop(0))

        with mock.patch.dict(sys.modules, {"km_ctc": self.module_stub()}):
            with mock.patch.object(voice.urllib.request, "urlopen", side_effect=fake_urlopen):
                voice.generate(self.story, self.texts, self.master, self.work, self.key1, self.key2, **kwargs)
        return calls

    def test_new_no_audio_response_is_durable_then_manual_recovery_succeeds(self):
        with self.assertRaisesRegex(voice.Stop, "Gemini returned no audio"):
            self.run_mocked([no_audio_answer()])

        marker_path = self.work / "request_attempt.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        metadata = json.loads((self.work / "response_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "response_received_no_audio")
        self.assertEqual(marker["attempts"][-1]["status"], "response_received_no_audio")
        self.assertEqual(metadata["audio_part_count"], 0)
        self.assertFalse(metadata["audio_payload_received"])
        self.assertFalse(self.master.exists())
        self.assertFalse((self.work / "response_audio.bin").exists())

        before_blocked_retry = marker_path.read_bytes()
        blocked_calls = []
        with mock.patch.dict(sys.modules, {"km_ctc": self.module_stub()}):
            with mock.patch.object(voice.urllib.request, "urlopen", side_effect=lambda *a, **k: blocked_calls.append(a)):
                with self.assertRaisesRegex(voice.Stop, "Run py resume_failed.py"):
                    voice.generate(self.story, self.texts, self.master, self.work, self.key1, self.key2)
        self.assertEqual(blocked_calls, [])
        self.assertEqual(marker_path.read_bytes(), before_blocked_retry)

        calls = self.run_mocked([audio_answer()], retry_verified_no_audio=True)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.master.is_file())
        self.assertTrue((self.work / "response_audio.bin").is_file())
        final_marker = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(final_marker["manual_no_audio_retries"], 1)
        self.assertEqual(len(final_marker["attempts"]), 1)
        self.assertEqual(final_marker["status"], "audio_saved")
        history = list((self.work / "no_audio_attempt_history").glob("*/response_metadata.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0].read_text(encoding="utf-8"))["audio_part_count"], 0)
        archived_marker = json.loads(history[0].with_name("request_attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(archived_marker["attempts"][-1]["status"], "response_received_no_audio")
        self.assertNotIn("synthetic-key-slot", marker_path.read_text(encoding="utf-8"))
        print("CHECK PASS: explicit retry recovered a no-audio response without losing the prior attempt")

    def test_legacy_other_marker_from_current_release_is_recoverable(self):
        (self.work / "request_attempt.json").write_text(json.dumps({
            "model": voice.MODEL, "voice": voice.VOICE,
            "status": "attempted_once",
            "automatic_retry": False,
            "attempts": [{"key_slot": 1, "key_file": "gemini_key.txt", "status": "response_received"}],
        }), encoding="utf-8")
        (self.work / "response_metadata.json").write_text(json.dumps({
            "finish_reasons": ["OTHER"],
            "usage": {"promptTokenCount": 162, "totalTokenCount": 162},
            "response_model": "mock-model",
        }), encoding="utf-8")

        calls = self.run_mocked([audio_answer()], retry_verified_no_audio=True)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.master.is_file())
        marker = json.loads((self.work / "request_attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["manual_no_audio_retries"], 1)
        print("CHECK PASS: legacy OTHER/response_received marker is recoverable only through explicit resume")

    def test_unknown_outcome_is_not_retryable_even_with_manual_flag(self):
        (self.work / "request_attempt.json").write_text(json.dumps({
            "status": "attempted_once",
            "automatic_retry": False,
            "attempts": [{"key_slot": 1, "key_file": "gemini_key.txt", "status": "unknown_outcome"}],
        }), encoding="utf-8")
        marker_before = (self.work / "request_attempt.json").read_bytes()
        calls = []
        with mock.patch.dict(sys.modules, {"km_ctc": self.module_stub()}):
            with mock.patch.object(voice.urllib.request, "urlopen", side_effect=lambda *a, **k: calls.append(a)):
                with self.assertRaisesRegex(voice.Stop, "not a verified no-audio response"):
                    voice.generate(self.story, self.texts, self.master, self.work, self.key1, self.key2,
                                   retry_verified_no_audio=True)
        self.assertEqual(calls, [])
        self.assertEqual((self.work / "request_attempt.json").read_bytes(), marker_before)
        print("CHECK PASS: unknown outcome stays blocked and unchanged")

    def test_audio_payload_metadata_without_saved_bytes_is_not_retryable(self):
        (self.work / "request_attempt.json").write_text(json.dumps({
            "status": "attempted_once",
            "automatic_retry": False,
            "attempts": [{"key_slot": 1, "key_file": "gemini_key.txt", "status": "response_received"}],
        }), encoding="utf-8")
        (self.work / "response_metadata.json").write_text(json.dumps({
            "finish_reasons": ["OTHER"], "audio_part_count": 1, "audio_payload_received": True,
        }), encoding="utf-8")
        calls = []
        with mock.patch.dict(sys.modules, {"km_ctc": self.module_stub()}):
            with mock.patch.object(voice.urllib.request, "urlopen", side_effect=lambda *a, **k: calls.append(a)):
                with self.assertRaisesRegex(voice.Stop, "not a verified no-audio response"):
                    voice.generate(self.story, self.texts, self.master, self.work, self.key1, self.key2,
                                   retry_verified_no_audio=True)
        self.assertEqual(calls, [])
        print("CHECK PASS: a response known to contain audio is not retried")

    def test_missing_key_does_not_consume_or_mutate_verified_marker(self):
        marker_path = self.work / "request_attempt.json"
        marker_path.write_text(json.dumps({
            "model": voice.MODEL, "voice": voice.VOICE,
            "status": "response_received_no_audio", "automatic_retry": False,
            "attempts": [{"key_slot": 1, "key_file": "gemini_key.txt", "status": "response_received_no_audio"}],
        }), encoding="utf-8")
        (self.work / "response_metadata.json").write_text(json.dumps({
            "finish_reasons": ["OTHER"], "audio_part_count": 0, "audio_payload_received": False,
        }), encoding="utf-8")
        before_marker = marker_path.read_bytes()
        before_metadata = (self.work / "response_metadata.json").read_bytes()
        self.key1.unlink()
        calls = []
        with mock.patch.dict(sys.modules, {"km_ctc": self.module_stub()}):
            with mock.patch.object(voice.urllib.request, "urlopen", side_effect=lambda *a, **k: calls.append(a)):
                with self.assertRaisesRegex(voice.Stop, "Key file 1 missing"):
                    voice.generate(self.story, self.texts, self.master, self.work, self.key1, self.key2,
                                   retry_verified_no_audio=True)
        self.assertEqual(calls, [])
        self.assertEqual(marker_path.read_bytes(), before_marker)
        self.assertEqual((self.work / "response_metadata.json").read_bytes(), before_metadata)
        print("CHECK PASS: missing key leaves the verified marker and metadata intact")

    def test_definite_dual_429_rejections_still_archive_for_later_resume(self):
        with self.assertRaisesRegex(voice.Stop, "Gemini returned no audio"):
            self.run_mocked([no_audio_answer()])
        calls = []

        def rejected(request, timeout=None):
            calls.append(request)
            raise urllib.error.HTTPError(
                request.full_url, 429, "quota", {}, io.BytesIO(b'{"error":{}}')
            )

        with mock.patch.dict(sys.modules, {"km_ctc": self.module_stub()}):
            with mock.patch.object(voice.urllib.request, "urlopen", side_effect=rejected):
                with self.assertRaisesRegex(voice.Stop, "All attempts definitely rejected"):
                    voice.generate(self.story, self.texts, self.master, self.work, self.key1, self.key2,
                                   retry_verified_no_audio=True)
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.work / "request_attempt.json").exists())
        rejected_archives = list((self.work / "rejected_attempt_backups").glob("*/request_attempt.json"))
        no_audio_history = list((self.work / "no_audio_attempt_history").glob("*/request_attempt.json"))
        self.assertEqual(len(rejected_archives), 1)
        self.assertEqual(len(no_audio_history), 1)
        print("CHECK PASS: dual definite 429s remain archived and keep the no-audio history")


class ResumeLauncherTests(unittest.TestCase):
    def test_resume_command_requests_only_the_explicit_verified_no_audio_mode(self):
        spec = importlib.util.spec_from_file_location("km_resume_launcher_test", ROOT / "resume_failed.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(prefix="km-resume-launcher-", dir=ROOT.parent) as temp:
            module.ROOT = pathlib.Path(temp)
            (module.ROOT / "stories").mkdir()
            (module.ROOT / "stories" / "RV_TEST.json").write_text(json.dumps(self_story()), encoding="utf-8")
            commands = []

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            def fake_run(command):
                commands.append(command)
                if command[0] == module.NPM:
                    out = module.ROOT / "out" / "RV_TEST.mp4"
                    out.parent.mkdir(exist_ok=True)
                    out.write_bytes(b"synthetic mp4")
                return Result()

            module.run = fake_run
            module.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="CHECK PASS: mocked optional history", stderr="")
            self.assertEqual(module.voice_and_render("RV_TEST", recover=True), 0)
            self.assertIn("--retry-verified-no-audio", commands[0])
            self.assertNotIn("--retry-verified-no-audio", commands[1])
            print("CHECK PASS: resume_failed grants the narrow retry flag; reviewed install does not")


def self_story():
    return {"id": "RV_TEST", "cards": [{"vo": "नमुना वाक्य।", "voice_tone": "neutral"}]}


if __name__ == "__main__":
    unittest.main(verbosity=2)
