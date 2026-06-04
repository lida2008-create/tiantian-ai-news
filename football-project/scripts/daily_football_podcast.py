#!/usr/bin/env python3
import asyncio
import html
import json
import os
import re
import subprocess
import textwrap
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from dateutil import parser as date_parser


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
AUDIO_DIR = DOCS_DIR / "audio"
DATA_DIR = ROOT / "data"
SCRIPT_DIR = DATA_DIR / "scripts"
EPISODES_FILE = DATA_DIR / "episodes.json"
RSS_FILE = DOCS_DIR / "rss.xml"
COVER_FILE = DOCS_DIR / "cover.jpg"

PODCAST_TITLE = os.getenv("PODCAST_TITLE", "天天足球")
PODCAST_AUTHOR = os.getenv("PODCAST_AUTHOR", "天天足球")
PODCAST_DESCRIPTION = os.getenv(
    "PODCAST_DESCRIPTION",
    "每天凌晨更新的足球新闻音频播报，精选当天 10 条热门足球新闻。",
)
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "").rstrip("/")
TZ_NAME = os.getenv("TZ_NAME", "Europe/Paris")
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-YunyangNeural")
TTS_API_URL = os.getenv("TTS_API_URL", "https://tts.wangwangit.com/v1/audio/speech")
TTS_STYLE = os.getenv("TTS_STYLE", "newscast")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
TTS_PITCH = os.getenv("TTS_PITCH", "0")
TTS_VOLUME = os.getenv("TTS_VOLUME", "0")

if not SITE_BASE_URL and os.getenv("GITHUB_REPOSITORY"):
    owner, repo = os.getenv("GITHUB_REPOSITORY").split("/", 1)
    SITE_BASE_URL = f"https://{owner.lower()}.github.io/{repo}"


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime
    summary: str
    score: float


def today_local() -> datetime:
    return datetime.now(ZoneInfo(TZ_NAME))


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_for_speech(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"\s+-\s+[^。！？.!?]{1,40}$", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -，,。")


def parse_date(entry) -> datetime:
    for key in ("published", "updated", "created"):
        if entry.get(key):
            try:
                dt = date_parser.parse(entry[key])
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(timezone.utc)


def news_feeds():
    query = urllib.parse.quote("足球 OR 英超 OR 西甲 OR 欧冠 OR 中超")
    return [
        ("Google News 足球", f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", 100),
        ("Google News 世界足球", "https://news.google.com/rss/search?q=football%20soccer%20when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", 85),
        ("BBC Football", "https://feeds.bbci.co.uk/sport/football/rss.xml", 70),
        ("ESPN Soccer", "https://www.espn.com/espn/rss/soccer/news", 65),
    ]


def fetch_feed(url: str):
    headers = {"User-Agent": "DailyFootballPodcast/1.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return feedparser.parse(response.content)


def score_item(entry, feed_name: str, base_score: float, now: datetime) -> NewsItem:
    published = parse_date(entry)
    age_hours = max((now.astimezone(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600, 0)
    recency_score = max(0, 24 - age_hours) * 3
    title = clean_text(entry.get("title", ""))
    summary = clean_text(entry.get("summary", ""))
    hot_words = ["官宣", "转会", "冠军", "决赛", "欧冠", "世界杯", "梅西", "C罗", "皇马", "巴萨", "曼联", "利物浦", "阿森纳", "切尔西", "曼城", "国足", "中超"]
    hot_score = sum(8 for word in hot_words if word.lower() in title.lower())
    score = base_score + recency_score + hot_score
    return NewsItem(
        title=title,
        link=entry.get("link", ""),
        source=entry.get("source", {}).get("title") or feed_name,
        published=published,
        summary=summary,
        score=score,
    )


def collect_top_news(limit: int = 10) -> list[NewsItem]:
    now = datetime.now(timezone.utc)
    items: list[NewsItem] = []
    for feed_name, url, base_score in news_feeds():
        try:
            parsed = fetch_feed(url)
        except Exception as exc:
            print(f"Skip feed {feed_name}: {exc}")
            continue
        for entry in parsed.entries[:40]:
            item = score_item(entry, feed_name, base_score, now)
            if item.title and item.link:
                items.append(item)

    seen = set()
    deduped = []
    for item in sorted(items, key=lambda x: x.score, reverse=True):
        key = re.sub(r"[^\w\u4e00-\u9fff]", "", item.title.lower())[:32]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) == limit:
            break
    return deduped


def build_script(items: list[NewsItem], date_text: str) -> str:
    lines = [f"{date_text}，天天足球。"]
    for index, item in enumerate(items, start=1):
        title = normalize_for_speech(item.title)
        summary = normalize_for_speech(item.summary)
        details = []
        if title:
            details.append(title)
        if summary and summary not in title:
            details.append(summary)
        text = "。".join(details).strip("。")
        lines.append(f"第{index}条，{text}。")
    script = "\n".join(lines)
    return trim_script(script, target_chars=2000)


def trim_script(script: str, target_chars: int) -> str:
    if len(script) <= target_chars:
        return script
    lines = script.splitlines()
    result = []
    remaining = target_chars
    for line in lines:
        if remaining <= 0:
            break
        if len(line) <= remaining:
            result.append(line)
            remaining -= len(line)
            continue
        clipped = line[:remaining].rsplit("。", 1)[0]
        if clipped:
            result.append(f"{clipped}。")
        break
    return "\n".join(result)
    return "\n".join(lines)


async def synthesize_audio(script: str, output_file: Path):
    payload = {
        "input": script,
        "voice": TTS_VOICE,
        "speed": TTS_SPEED,
        "pitch": TTS_PITCH,
        "style": TTS_STYLE,
        "volume": TTS_VOLUME,
    }
    try:
        response = requests.post(
            TTS_API_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        output_file.write_bytes(response.content)
    except requests.RequestException:
        result = subprocess.run(
            [
                "curl",
                "-L",
                "-sS",
                "-X",
                "POST",
                TTS_API_URL,
                "-H",
                "Content-Type: application/json",
                "--data-binary",
                "@-",
                "-o",
                str(output_file),
            ],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "TTS request failed")


def load_episodes() -> list[dict]:
    if not EPISODES_FILE.exists():
        return []
    return json.loads(EPISODES_FILE.read_text(encoding="utf-8"))


def save_episodes(episodes: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EPISODES_FILE.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")


def save_script(date_key: str, script: str):
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    (SCRIPT_DIR / f"{date_key}.txt").write_text(script, encoding="utf-8")


def public_url(path: Path) -> str:
    rel = path.relative_to(DOCS_DIR).as_posix()
    if SITE_BASE_URL:
        return f"{SITE_BASE_URL}/{rel}"
    return rel


def write_rss(episodes: list[dict]):
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "link").text = SITE_BASE_URL or "."
    ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "language").text = "zh-cn"
    ET.SubElement(channel, "itunes:author").text = PODCAST_AUTHOR
    ET.SubElement(channel, "itunes:summary").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "itunes:explicit").text = "false"
    if COVER_FILE.exists():
        cover_url = public_url(COVER_FILE)
        image = ET.SubElement(channel, "image")
        ET.SubElement(image, "url").text = cover_url
        ET.SubElement(image, "title").text = PODCAST_TITLE
        ET.SubElement(image, "link").text = SITE_BASE_URL or "."
        ET.SubElement(channel, "itunes:image", {"href": cover_url})
    if SITE_BASE_URL:
        ET.SubElement(channel, "atom:link", {
            "href": f"{SITE_BASE_URL}/rss.xml",
            "rel": "self",
            "type": "application/rss+xml",
        })

    for episode in episodes[:60]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = episode["title"]
        ET.SubElement(item, "description").text = episode["description"]
        ET.SubElement(item, "pubDate").text = episode["pub_date"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = episode["guid"]
        ET.SubElement(item, "enclosure", {
            "url": episode["audio_url"],
            "length": str(episode["audio_bytes"]),
            "type": "audio/mpeg",
        })

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(RSS_FILE, encoding="utf-8", xml_declaration=True)


def episode_exists(episodes: list[dict], guid: str) -> bool:
    return any(item.get("guid") == guid for item in episodes)


def main():
    local_now = today_local()
    date_key = local_now.strftime("%Y-%m-%d")
    date_text = local_now.strftime("%Y年%m月%d日")
    guid = f"daily-football-{date_key}"

    episodes = load_episodes()
    if episode_exists(episodes, guid) and os.getenv("FORCE_REGENERATE") != "1":
        print(f"Episode already exists: {guid}")
        write_rss(episodes)
        return

    script_file = os.getenv("SCRIPT_FILE")
    items = []
    if script_file:
        script = Path(script_file).read_text(encoding="utf-8")
    else:
        items = collect_top_news(limit=10)
        if not items:
            raise RuntimeError("No football news found today.")
        script = build_script(items, date_text)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    save_script(date_key, script)
    audio_file = AUDIO_DIR / f"{date_key}.mp3"
    asyncio.run(synthesize_audio(script, audio_file))

    if items:
        description = "\n".join(
            [f"{idx}. {normalize_for_speech(item.title)}" for idx, item in enumerate(items, start=1)]
        )
    else:
        description = textwrap.shorten(script, width=3900, placeholder="...")
    episode = {
        "guid": guid,
        "title": f"{date_text} 足球新闻早报",
        "description": textwrap.shorten(description, width=3900, placeholder="..."),
        "pub_date": format_datetime(local_now, usegmt=False),
        "audio_url": public_url(audio_file),
        "audio_bytes": audio_file.stat().st_size,
        "items": [item.__dict__ | {"published": item.published.isoformat()} for item in items],
    }
    episodes = [episode] + [item for item in episodes if item.get("guid") != guid]
    save_episodes(episodes)
    write_rss(episodes)
    print(f"Created episode: {episode['title']}")
    print(f"RSS: {RSS_FILE}")


if __name__ == "__main__":
    main()
