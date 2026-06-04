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


def run(args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main():
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    clone_url = REPO_URL
    push_url = REPO_URL
    if token and REPO_URL.startswith("https://github.com/"):
        path = REPO_URL.removeprefix("https://github.com/")
        push_url = f"https://x-access-token:{token}@github.com/{path}"

    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    run(["git", "clone", clone_url, str(WORKDIR)])

    copy_tree(ROOT / "docs", WORKDIR / "football")
    project_dir = WORKDIR / "football-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    for name in ["scripts", "data", "requirements.txt", "README.md", ".gitignore"]:
        src = ROOT / name
        dst = project_dir / name
        if src.is_dir():
            copy_tree(src, dst)
        else:
            shutil.copy2(src, dst)

    for path in WORKDIR.rglob(".DS_Store"):
        path.unlink()

    run(["git", "add", "football", "football-project"], cwd=WORKDIR)
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
    run(["git", "-c", "credential.helper=", "push", push_url, "main"], cwd=WORKDIR)
    print(f"Published RSS: {PAGES_BASE_URL}/rss.xml")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
