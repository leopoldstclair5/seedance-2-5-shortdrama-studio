import pathlib
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from drama.pipeline import DramaError, VideoClient, assemble, body_for_scene, build


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def close(self):
        pass


class Recorder:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(self.payloads.pop(0))


class PipelineTests(unittest.TestCase):
    def test_build_has_character_sheet_and_stable_scene_ids(self):
        plan = build(
            1,
            ["小雨捡起钥匙", "她走向影院"],
            title="旧钥匙",
            characters=[{"id": "xiaoyu", "description": "短发女孩", "wardrobe": "蓝色雨衣"}],
            reference_images=["https://cdn.test/xiaoyu.png"],
        )
        self.assertEqual([row["id"] for row in plan["scenes"]], ["scene-01", "scene-02"])
        self.assertEqual(plan["characters"][0]["wardrobe"], "蓝色雨衣")
        self.assertEqual(body_for_scene(plan, plan["scenes"][0])["model"], "seedance-2.5")
        self.assertEqual(body_for_scene(plan, plan["scenes"][0])["reference_images"][0]["url"], "https://cdn.test/xiaoyu.png")

    def test_build_rejects_local_reference_and_bad_ratio(self):
        with self.assertRaises(ValueError):
            build(1, ["x"], reference_images=["./face.png"])
        with self.assertRaises(ValueError):
            build(1, ["x"], aspect_ratio="adaptive")

    def test_client_sends_auth_and_user_agent(self):
        recorder = Recorder([b'{"request_id":"job-1"}'])
        client = VideoClient("secret", base_url="https://api.test/v1", opener=recorder)
        self.assertEqual(client.submit({"model": "seedance-2.5", "prompt": "x"}), "job-1")
        self.assertEqual(recorder.requests[0].get_header("Authorization"), "Bearer secret")
        self.assertEqual(recorder.requests[0].get_header("User-agent"), "seedance-2-5-shortdrama-studio/1.0")

    def test_assembly_builds_ffmpeg_command_and_does_not_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            a, b = root / "a.mp4", root / "b.mp4"
            a.write_bytes(b"a")
            b.write_bytes(b"b")
            with patch("drama.pipeline.subprocess.run") as run:
                assemble([a, b], root / "episode.mp4")
            self.assertEqual(run.call_args.args[0][0], "ffmpeg")
            (root / "episode.mp4").touch()
            with self.assertRaises(FileExistsError):
                assemble([a, b], root / "episode.mp4")

    def test_unknown_provider_state_is_not_treated_as_success(self):
        recorder = Recorder([b'{"status":"running"}'])
        client = VideoClient("secret", base_url="https://api.test/v1", opener=recorder)
        with self.assertRaises(DramaError):
            client.status("job-1")


if __name__ == "__main__":
    unittest.main()
