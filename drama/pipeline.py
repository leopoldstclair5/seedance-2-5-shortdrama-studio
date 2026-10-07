"""A reviewable Chinese short-drama planner and resumable Seedance runner."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

BASE_URL = "https://argolink.io/v1"
MODEL = "seedance-2.5"
USER_AGENT = "seedance-2-5-shortdrama-studio/1.0"
RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
RESOLUTIONS = {"480p", "720p", "1080p"}
STATUSES = {"pending", "done", "failed", "expired"}


class DramaError(RuntimeError):
    pass


def _https(value: str, field: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field} 必须是完整的 HTTPS 媒体 URL")
    return value


def build(
    episode: int,
    scenes: List[str],
    *,
    title: str = "",
    characters: Optional[List[Dict[str, Any]]] = None,
    reference_images: Optional[List[str]] = None,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
) -> Dict[str, Any]:
    """Create a validated, reviewable episode plan; this function never calls the API."""
    if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
        raise ValueError("episode must be a positive integer")
    if not scenes:
        raise ValueError("at least one scene is required")
    if resolution not in RESOLUTIONS:
        raise ValueError("resolution must be 480p, 720p, or 1080p")
    if aspect_ratio not in RATIOS:
        raise ValueError("short-drama text/reference shots need a fixed aspect ratio")
    refs = reference_images or []
    if len(refs) > 30:
        raise ValueError("Seedance 2.5 accepts at most 30 reference images")
    for index, value in enumerate(refs):
        _https(value, f"reference_images[{index}]")
    character_rows = []
    for character in characters or []:
        if not isinstance(character, dict) or not character.get("id") or not character.get("description"):
            raise ValueError("each character needs id and description")
        character_rows.append({
            "id": str(character["id"]),
            "description": str(character["description"]),
            "wardrobe": str(character.get("wardrobe", "")),
            "continuity_rules": list(character.get("continuity_rules", [])),
        })
    rows = []
    for index, text in enumerate(scenes, 1):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"scene {index} needs a non-empty description")
        rows.append({
            "id": f"scene-{index:02d}",
            "duration": 5,
            "prompt": text.strip(),
            "continuity": "Keep the established character appearance, wardrobe, time of day, and screen direction.",
            "status": "draft",
        })
    return {
        "schema_version": 1,
        "episode": episode,
        "title": title,
        "model": MODEL,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "reference_images": refs,
        "characters": character_rows,
        "scenes": rows,
    }


def body_for_scene(plan: Dict[str, Any], scene: Dict[str, Any]) -> Dict[str, Any]:
    prompt = scene["prompt"] + "\n\nContinuity: " + scene["continuity"]
    body: Dict[str, Any] = {
        "model": MODEL,
        "prompt": prompt,
        "duration": scene["duration"],
        "resolution": plan["resolution"],
        "aspect_ratio": plan["aspect_ratio"],
        "generate_audio": True,
    }
    if plan.get("reference_images"):
        body["reference_images"] = [{"url": value} for value in plan["reference_images"]]
    return body


class VideoClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        opener: Optional[Callable[..., Any]] = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 90.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("VIDEO_API_KEY")
        self.base_url = (base_url or os.environ.get("VIDEO_API_BASE_URL") or BASE_URL).rstrip("/")
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self.timeout = timeout

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        if not self.api_key:
            raise DramaError("VIDEO_API_KEY 未设置")
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            response = self._open(request, timeout=self.timeout)
            raw = response.read()
            response.close()
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode("utf-8", errors="replace")
            raise DramaError(f"{method} {path} HTTP {error.code}: {detail[:300]}") from None
        if path.endswith("/content"):
            return raw
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DramaError(f"{method} {path} 返回的不是 JSON") from error
        if not isinstance(result, dict):
            raise DramaError(f"{method} {path} 返回的不是对象")
        return result

    def submit(self, body: Dict[str, Any]) -> str:
        result = self.call("POST", "/videos/generations", body)
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise DramaError("提交响应没有 request_id")
        return request_id

    def status(self, request_id: str) -> Dict[str, Any]:
        result = self.call("GET", f"/videos/{request_id}")
        if result.get("status") not in STATUSES:
            raise DramaError(f"未知任务状态: {result.get('status')!r}")
        return result

    def download(self, request_id: str, target: Path) -> None:
        if target.exists():
            return
        raw = self.call("GET", f"/videos/{request_id}/content")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".partial-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        finally:
            temporary.unlink(missing_ok=True)


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".plan-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run(
    plan: Dict[str, Any],
    output_dir: Path,
    client: VideoClient,
    *,
    poll_interval: float = 10.0,
    timeout: float = 1800.0,
) -> Dict[str, Any]:
    if poll_interval <= 0 or timeout <= 0:
        raise ValueError("poll_interval and timeout must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"episode": plan["episode"], "scenes": {}}
    for scene in plan["scenes"]:
        record = manifest["scenes"].setdefault(scene["id"], {"body": body_for_scene(plan, scene)})
        record["body"] = body_for_scene(plan, scene)
        if record.get("status") == "done" and record.get("clip"):
            continue
        if not record.get("request_id"):
            record["request_id"] = client.submit(record["body"])
            record["status"] = "pending"
            _save(manifest_path, manifest)
        started = time.monotonic()
        while True:
            state = client.status(record["request_id"])
            record["status"] = state["status"]
            record["provider"] = state
            _save(manifest_path, manifest)
            if state["status"] == "done":
                break
            if state["status"] in {"failed", "expired"}:
                raise DramaError(f"{scene['id']} {state['status']}: {state.get('error', '')}")
            if time.monotonic() + poll_interval > started + timeout:
                raise TimeoutError(f"{scene['id']} 仍在 pending；保留 request_id 后稍后继续")
            client._sleep(poll_interval)
        target = output_dir / "clips" / f"{scene['id']}.mp4"
        client.download(record["request_id"], target)
        record["clip"] = str(target)
        _save(manifest_path, manifest)
    return manifest


def assemble(clip_paths: Iterable[Path], output: Path) -> None:
    paths = [Path(p) for p in clip_paths]
    if not paths or any(not p.is_file() for p in paths):
        raise DramaError("合成前必须准备好每个场景的 MP4")
    if output.exists():
        raise FileExistsError(str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".ffconcat", encoding="utf-8", delete=False) as handle:
        manifest = Path(handle.name)
        handle.write("ffconcat version 1.0\n")
        for path in paths:
            escaped = str(path.resolve()).replace("'", "'\\\\''")
            handle.write(f"file '{escaped}'\n")
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output)],
            check=True,
        )
    finally:
        manifest.unlink(missing_ok=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="中文短剧分镜与 Seedance 2.5 runner")
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--characters", type=Path, help="JSON character sheet")
    parser.add_argument("--references", nargs="*", default=[])
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--out", type=Path, default=Path("episode-plan.json"))
    parser.add_argument("--run", action="store_true", help="提交并下载视频；默认只写计划")
    parser.add_argument("--output-dir", type=Path, default=Path(".drama"))
    parser.add_argument("--output", type=Path, default=Path("episode.mp4"))
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("scenes", nargs="+")
    args = parser.parse_args(argv)
    characters = json.loads(args.characters.read_text(encoding="utf-8")) if args.characters else []
    plan = build(
        args.episode, args.scenes, title=args.title, characters=characters,
        reference_images=args.references, resolution=args.resolution, aspect_ratio=args.aspect_ratio,
    )
    _save(args.out, plan)
    if not args.run:
        print(f"已写入分镜计划: {args.out}")
        return 0
    manifest = run(plan, args.output_dir, VideoClient(), poll_interval=args.poll_interval, timeout=args.timeout)
    assemble([Path(manifest["scenes"][scene["id"]]["clip"]) for scene in plan["scenes"]], args.output)
    print(f"已写入成片: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
