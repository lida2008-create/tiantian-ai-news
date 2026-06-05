#!/usr/bin/env python3
import asyncio
import html
import html as html_lib
import json
import os
import re
import subprocess
import tempfile
import textwrap
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import feedparser
import requests
from dateutil import parser as date_parser


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
AUDIO_DIR = DOCS_DIR / "audio"
DATA_DIR = ROOT / "data"
SCRIPT_DIR = DATA_DIR / "scripts"
MANUAL_NEWS_DIR = DATA_DIR / "manual_news"
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
MACOS_TTS_VOICE = os.getenv("MACOS_TTS_VOICE", "Tingting")
MACOS_TTS_RATE = os.getenv("MACOS_TTS_RATE", "185")
AUDIO_MIN_BYTES = int(os.getenv("AUDIO_MIN_BYTES", "50000"))
AUDIO_MIN_DURATION = float(os.getenv("AUDIO_MIN_DURATION", "30"))
ENABLE_LOCAL_TTS_FALLBACK = os.getenv("ENABLE_LOCAL_TTS_FALLBACK", "0") == "1"
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") or os.getenv("SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION") or os.getenv("SPEECH_REGION")
AZURE_TTS_OUTPUT_FORMAT = os.getenv("AZURE_TTS_OUTPUT_FORMAT", "audio-48khz-192kbitrate-mono-mp3")

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


@dataclass
class FeedFailure:
    feed_name: str
    url: str
    error: str


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


def effective_tts_style(voice: str, style: str) -> str:
    if voice == "zh-CN-YunyangNeural" and style == "newscast":
        return "newscast-casual"
    return style


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


def collect_top_news(limit: int = 10) -> tuple[list[NewsItem], list[FeedFailure]]:
    now = datetime.now(timezone.utc)
    items: list[NewsItem] = []
    failures: list[FeedFailure] = []
    for feed_name, url, base_score in news_feeds():
        try:
            parsed = fetch_feed(url)
        except Exception as exc:
            print(f"Skip feed {feed_name}: {exc}")
            failures.append(FeedFailure(feed_name=feed_name, url=url, error=str(exc)))
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
    return deduped, failures


def parse_manual_news_item(raw: dict, index: int) -> NewsItem:
    if not isinstance(raw, dict):
        raise ValueError(f"Manual news item #{index} is not an object.")
    title = normalize_for_speech(str(raw.get("title", "")).strip())
    summary = normalize_for_speech(str(raw.get("summary", "")).strip())
    if not title:
        raise ValueError(f"Manual news item #{index} is missing title.")
    published_raw = str(raw.get("published", "")).strip()
    if published_raw:
        try:
            published = date_parser.parse(published_raw)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise ValueError(f"Manual news item #{index} has invalid published value: {exc}") from exc
    else:
        published = datetime.now(timezone.utc)
    return NewsItem(
        title=title,
        link=str(raw.get("link", "")).strip() or f"manual://item-{index}",
        source=str(raw.get("source", "")).strip() or "manual",
        published=published,
        summary=summary,
        score=float(raw.get("score", max(0, 100 - index))),
    )


def manual_news_file_for_date(date_key: str) -> Path:
    return MANUAL_NEWS_DIR / f"{date_key}.json"


def load_manual_news(path: Path, limit: int = 10) -> list[NewsItem]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Manual news file must be a JSON array.")
    items = [parse_manual_news_item(item, index) for index, item in enumerate(raw, start=1)]
    if len(items) < limit:
        raise ValueError(f"Manual news file only contains {len(items)} items; at least {limit} are required.")
    return items[:limit]


def build_no_news_error(date_key: str, failures: list[FeedFailure]) -> str:
    lines = [f"No football news found for {date_key}."]
    if failures:
        lines.append("Feed fetch failures:")
        for failure in failures:
            lines.append(f"- {failure.feed_name}: {failure.error}")
    manual_path = manual_news_file_for_date(date_key)
    lines.append(
        "Create a manual fallback file with 10 items and rerun:"
    )
    lines.append(
        f"- {manual_path} or set NEWS_JSON_FILE to another JSON file path."
    )
    lines.append(
        'Each item should look like: {"title": "...", "summary": "...", "link": "https://...", "published": "2026-06-05T00:00:00+02:00"}'
    )
    return "\n".join(lines)


def item_context(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}"
    contexts = []
    if any(word in text for word in ["转会", "标价", "皇马", "阿森纳", "曼联", "曼城", "巴萨", "切尔西", "利物浦"]):
        contexts.append("这类消息的重点不只是球员本人，还包括报价节奏、合同年限、薪资空间和俱乐部夏窗优先级。")
        contexts.append("如果谈判继续推进，相关球队的阵容结构和后续引援预算都会受到影响。")
    if any(word in text for word in ["世界杯", "亚洲杯", "国家队", "国足", "签证"]):
        contexts.append("国家队层面的新闻更看重备战连续性，赛程、旅行、训练安排和球员状态都会影响比赛内容。")
        contexts.append("越接近正式比赛，任何非竞技因素都会被放大，教练组需要尽快把注意力拉回阵容和战术。")
    if any(word in text for word in ["青训", "少年", "U12", "小将", "校园足球", "巴塞罗那"]):
        contexts.append("青训新闻的价值在于长期跟踪，签约和夺冠只是起点，真正关键的是后续训练质量和比赛环境。")
        contexts.append("年轻球员能否稳定成长，取决于技术培养、身体发育、心理适应和高水平比赛机会。")
    if any(word in text for word in ["中超", "申花", "国安", "泰山", "海港"]):
        contexts.append("中超球队的补强通常更强调即战力，本土球员位置适配和更衣室稳定性同样重要。")
        contexts.append("相关传闻最终还要看俱乐部计划、球员意愿和注册窗口安排。")
    if any(word in text for word in ["欧冠", "冠军", "C罗", "梅西", "球王"]):
        contexts.append("这类话题往往会回到荣誉、数据、关键比赛表现和时代影响力的比较。")
        contexts.append("不同标准会得出不同结论，所以争议本身也反映了球迷对足球价值的不同排序。")
    if not contexts:
        contexts.append("这条新闻后续要重点看事件是否进入正式流程，以及相关球队和球员有没有进一步动作。")
        contexts.append("如果细节继续增加，它可能会影响接下来一天的赛程讨论、转会判断或球队备战节奏。")
    return contexts


def expand_item_for_speech(item: NewsItem, index: int, target_chars: int) -> str:
    title = normalize_for_speech(item.title)
    summary = normalize_for_speech(item.summary)
    parts = [f"第{index}条，{title}。"]
    if summary and summary not in title:
        parts.append(f"{summary}。")
    for context in item_context(title, summary):
        if sum(len(part) for part in parts) >= target_chars:
            break
        parts.append(context)
    return "".join(parts)


def build_script(items: list[NewsItem], date_text: str) -> str:
    lines = [f"{date_text}，天天足球。"]
    item_target = max(150, (2000 - len(lines[0])) // max(len(items), 1))
    for index, item in enumerate(items, start=1):
        lines.append(expand_item_for_speech(item, index, item_target))
    script = "\n".join(lines)
    return fit_script(script, target_chars=2000)


def fit_script(script: str, target_chars: int) -> str:
    if len(script) <= target_chars + 120:
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


async def synthesize_audio(script: str, output_file: Path):
    if AZURE_SPEECH_KEY and AZURE_SPEECH_REGION:
        synthesize_audio_azure(script, output_file)
        return

    style = effective_tts_style(TTS_VOICE, TTS_STYLE)
    payload = {
        "input": script,
        "voice": TTS_VOICE,
        "speed": TTS_SPEED,
        "pitch": TTS_PITCH,
        "style": style,
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
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "audio" not in content_type and "mpeg" not in content_type and "octet-stream" not in content_type:
            raise RuntimeError(
                f"Remote TTS returned non-audio content-type: {content_type or 'unknown'}; "
                f"body={response.text[:200]!r}"
            )
        output_file.write_bytes(response.content)
    except Exception as first_error:
        with tempfile.TemporaryDirectory(prefix="daily-football-curl-") as tmpdir:
            headers_file = Path(tmpdir) / "headers.txt"
            body_file = Path(tmpdir) / "body.bin"
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
                    "-D",
                    str(headers_file),
                    "--data-binary",
                    "@-",
                    "-o",
                    str(body_file),
                ],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                header_text = headers_file.read_text(encoding="utf-8", errors="ignore")
                content_type_match = re.search(r"^content-type:\s*(.+)$", header_text, flags=re.IGNORECASE | re.MULTILINE)
                content_type = (content_type_match.group(1).strip().lower() if content_type_match else "")
                if "audio" in content_type or "mpeg" in content_type or "octet-stream" in content_type:
                    output_file.write_bytes(body_file.read_bytes())
                    return

                body_preview = body_file.read_text(encoding="utf-8", errors="ignore")[:200]
                raise RuntimeError(
                    f"Remote TTS returned non-audio content-type via curl: {content_type or 'unknown'}; "
                    f"body={body_preview!r}"
                ) from first_error

            if ENABLE_LOCAL_TTS_FALLBACK:
                synthesize_audio_macos(script, output_file)
                return

            raise RuntimeError(
                result.stderr.strip() or f"Remote TTS request failed: {first_error}"
            ) from first_error


def build_azure_ssml(script: str) -> str:
    escaped_script = html_lib.escape(script)
    style = effective_tts_style(TTS_VOICE, TTS_STYLE)
    return (
        "<speak version='1.0' xml:lang='zh-CN' "
        "xmlns='http://www.w3.org/2001/10/synthesis' "
        "xmlns:mstts='https://www.w3.org/2001/mstts'>"
        f"<voice name='{TTS_VOICE}'>"
        f"<mstts:express-as style='{style}'>{escaped_script}</mstts:express-as>"
        "</voice>"
        "</speak>"
    )


def synthesize_audio_azure(script: str, output_file: Path):
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        raise RuntimeError("Azure Speech credentials are missing.")

    endpoint = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    ssml = build_azure_ssml(script)
    response = requests.post(
        endpoint,
        headers={
            "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": AZURE_TTS_OUTPUT_FORMAT,
            "User-Agent": "DailyFootballPodcast/1.0",
        },
        data=ssml.encode("utf-8"),
        timeout=120,
    )
    response.raise_for_status()
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "audio" not in content_type and "mpeg" not in content_type and "octet-stream" not in content_type:
        raise RuntimeError(
            f"Azure TTS returned non-audio content-type: {content_type or 'unknown'}; "
            f"body={response.text[:200]!r}"
        )
    output_file.write_bytes(response.content)


def synthesize_audio_macos(script: str, output_file: Path):
    with tempfile.TemporaryDirectory(prefix="daily-football-tts-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        script_file = tmpdir_path / "script.txt"
        aiff_file = tmpdir_path / "speech.aiff"
        script_file.write_text(script, encoding="utf-8")

        say_result = subprocess.run(
            [
                "say",
                "-v",
                MACOS_TTS_VOICE,
                "-r",
                MACOS_TTS_RATE,
                "-f",
                str(script_file),
                "-o",
                str(aiff_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if say_result.returncode != 0:
            raise RuntimeError(say_result.stderr.strip() or "macOS say synthesis failed")

        ffmpeg_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(aiff_file),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(output_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if ffmpeg_result.returncode != 0:
            raise RuntimeError(ffmpeg_result.stderr.strip() or "ffmpeg mp3 conversion failed")


def validate_audio_file(path: Path):
    if not path.exists():
        raise RuntimeError(f"Audio file was not created: {path}")
    if path.stat().st_size < AUDIO_MIN_BYTES:
        raise RuntimeError(f"Audio file is too small to be valid: {path.stat().st_size} bytes")

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or "ffprobe validation failed")

    try:
        payload = json.loads(probe.stdout)
        duration = float(payload["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Failed to parse audio metadata: {exc}") from exc

    if duration < AUDIO_MIN_DURATION:
        raise RuntimeError(f"Audio duration is too short to be valid: {duration:.2f}s")


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


def resolve_existing_audio_file(date_key: str) -> Optional[Path]:
    audio_file_env = os.getenv("AUDIO_FILE")
    if audio_file_env:
        return Path(audio_file_env)
    if os.getenv("USE_EXISTING_AUDIO") == "1":
        return AUDIO_DIR / f"{date_key}.mp3"
    return None


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
    episode_date = os.getenv("EPISODE_DATE")
    if episode_date:
        local_now = datetime.strptime(episode_date, "%Y-%m-%d").replace(tzinfo=ZoneInfo(TZ_NAME))
    else:
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
    manual_news_env = os.getenv("NEWS_JSON_FILE")
    manual_news_path = Path(manual_news_env) if manual_news_env else manual_news_file_for_date(date_key)
    items = []
    if script_file:
        script = Path(script_file).read_text(encoding="utf-8")
    elif manual_news_path.exists():
        items = load_manual_news(manual_news_path, limit=10)
        script = build_script(items, date_text)
    else:
        items, failures = collect_top_news(limit=10)
        if not items:
            raise RuntimeError(build_no_news_error(date_key, failures))
        script = build_script(items, date_text)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    save_script(date_key, script)
    audio_file = AUDIO_DIR / f"{date_key}.mp3"
    existing_audio_file = resolve_existing_audio_file(date_key)
    if existing_audio_file:
        existing_audio_file = existing_audio_file.resolve()
        if not existing_audio_file.exists():
            raise RuntimeError(f"Existing audio file not found: {existing_audio_file}")
        if existing_audio_file != audio_file.resolve():
            audio_file.write_bytes(existing_audio_file.read_bytes())
    else:
        asyncio.run(synthesize_audio(script, audio_file))
    validate_audio_file(audio_file)

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
