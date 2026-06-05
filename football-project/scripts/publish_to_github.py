#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_URL = os.getenv("PUBLISH_REPO_URL", "https://github.com/lida2008-create/tiantian-ai-news.git")
PAGES_BASE_URL = os.getenv("SITE_BASE_URL", "https://lida2008-create.github.io/tiantian-ai-news/football")
WORKDIR = Path(os.getenv("PUBLISH_WORKDIR", "/private/tmp/tiantian-ai-news-football-publish"))
PUBLISH_BRANCH = os.getenv("PUBLISH_BRANCH", "main")
PUBLISH_SITE_DIR = os.getenv("PUBLISH_SITE_DIR", "football").strip("/")
PUBLISH_PROJECT_DIR = os.getenv("PUBLISH_PROJECT_DIR", "football-project").strip("/")
PROJECT_FILES = ["scripts", "data", "requirements.txt", "README.md", ".gitignore"]


def load_local_env():
    env_file = ROOT / ".env.local"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def run(args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def sync_path(src: Path, dst: Path):
    if src.is_dir():
        copy_tree(src, dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def sync_directory_contents(src_dir: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for child in src_dir.iterdir():
        sync_path(child, dst_dir / child.name)


def repo_target(base: Path, relative_dir: str) -> Path:
    if not relative_dir:
        return base
    return base / relative_dir


def main():
    load_local_env()
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    clone_url = REPO_URL
    push_url = REPO_URL
    if token and REPO_URL.startswith("https://github.com/"):
        path = REPO_URL.removeprefix("https://github.com/")
        push_url = f"https://x-access-token:{token}@github.com/{path}"

    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    run(["git", "clone", clone_url, str(WORKDIR)])

    site_dir = repo_target(WORKDIR, PUBLISH_SITE_DIR)
    project_dir = repo_target(WORKDIR, PUBLISH_PROJECT_DIR)

    if PUBLISH_SITE_DIR:
        copy_tree(ROOT / "docs", site_dir)
    else:
        sync_directory_contents(ROOT / "docs", site_dir)

    if PUBLISH_PROJECT_DIR:
        project_dir.mkdir(parents=True, exist_ok=True)
        for name in PROJECT_FILES:
            src = ROOT / name
            dst = project_dir / name
            sync_path(src, dst)
    else:
        for name in PROJECT_FILES:
            src = ROOT / name
            dst = WORKDIR / name
            sync_path(src, dst)

    for path in WORKDIR.rglob(".DS_Store"):
        path.unlink()

    add_targets = []
    if PUBLISH_SITE_DIR:
        add_targets.append(PUBLISH_SITE_DIR)
    else:
        add_targets.append("docs")
    if PUBLISH_PROJECT_DIR:
        add_targets.append(PUBLISH_PROJECT_DIR)
    else:
        add_targets.extend(PROJECT_FILES)

    run(["git", "add", *add_targets], cwd=WORKDIR)
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=WORKDIR,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not status:
        print("No publish changes.")
        return

    run(["git", "commit", "-m", "Update daily football podcast"], cwd=WORKDIR)
    run(["git", "-c", "credential.helper=", "push", push_url, PUBLISH_BRANCH], cwd=WORKDIR)
    print(f"Published RSS: {PAGES_BASE_URL}/rss.xml")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
