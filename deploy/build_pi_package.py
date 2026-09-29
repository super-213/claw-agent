#!/usr/bin/env python3
"""Build the frontend and package only the files needed on a Raspberry Pi."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "release" / "claw-agent-pi.tar.gz"
SOURCE_DIRS = ("agent_runtime", "config", "core", "services", "skills", "utils")
SOURCE_SUFFIXES = {".py", ".md", ".skill", ".json"}
SINGLE_FILES = (
    "Agent.md",
    "main.py",
    "web_app.py",
    "requirements.txt",
    "deploy/pi-start.sh",
    "deploy/pi-status.sh",
    "deploy/pi-stop.sh",
    "deploy/pi-update.sh",
    "deploy/pi-nginx.sh",
    "deploy/claw-agent.conf",
    "deploy/README.md",
)


def is_payload(path: Path) -> bool:
    return not any(
        part.startswith("._") or part in {"__pycache__", ".DS_Store"}
        for part in path.relative_to(ROOT).parts
    )


def package_files() -> list[Path]:
    files = [ROOT / name for name in SINGLE_FILES]
    files.append(ROOT / "config" / ".env.example")
    for dirname in SOURCE_DIRS:
        for path in (ROOT / dirname).rglob("*"):
            if path.is_file() and path.suffix in SOURCE_SUFFIXES and is_payload(path):
                files.append(path)
    dist = ROOT / "web-react" / "dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("前端构建缺少 web-react/dist/index.html")
    files.extend(path for path in dist.rglob("*") if path.is_file() and is_payload(path))
    result = sorted(set(files))
    for path in result:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"无效的打包文件：{path}")
    return result


def main() -> None:
    frontend_bin = ROOT / "web-react" / "node_modules" / ".bin"
    if not (frontend_bin / "vite").exists() or not (frontend_bin / "tsc").exists():
        print("安装前端依赖…", flush=True)
        subprocess.run(["npm", "--prefix", "web-react", "ci"], cwd=ROOT, check=True)
    print("构建 React 前端…", flush=True)
    subprocess.run(["npm", "--prefix", "web-react", "run", "build"], cwd=ROOT, check=True)
    files = package_files()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUTPUT, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path in files:
            relative = path.relative_to(ROOT)
            info = archive.gettarinfo(str(path), arcname=str(Path("claw-agent") / relative))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if relative.parent == Path("deploy") and relative.suffix == ".sh" else 0o644
            with path.open("rb") as source:
                archive.addfile(info, source)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    print(f"压缩包：{OUTPUT}")
    print(f"文件数：{len(files)}，大小：{OUTPUT.stat().st_size:,} 字节")
    print(f"SHA-256：{digest}")


if __name__ == "__main__":
    main()
