# 天天足球

每天自动生成一集足球新闻音频播客：

- 抓取当天足球新闻
- 选出 10 条热门新闻
- 生成中文播报稿
- 使用微软云扬声音合成 MP3
- 更新 RSS，方便播客客户端订阅

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/daily_football_podcast.py
```

生成内容会放在：

- `docs/audio/`
- `docs/cover.jpg`
- `docs/rss.xml`
- `data/episodes.json`

## 自动每天运行

项目已经包含 GitHub Actions 配置：`.github/workflows/daily-football-podcast.yml`。

默认按巴黎时间凌晨 1 点运行。GitHub Actions 使用 UTC，所以当前配置是：

```yaml
cron: "0 23 * * *"
```

如果你想改成北京时间凌晨 1 点，请改为：

```yaml
cron: "0 17 * * *"
```

如果你想改成美国东部时间凌晨 1 点，请根据夏令时改为 `05:00 UTC` 或 `06:00 UTC`。

## GitHub Pages

把仓库 Pages 发布目录设为 `docs/` 后，RSS 地址通常是：

```text
https://你的用户名.github.io/仓库名/rss.xml
```

## 可配置项

在 GitHub Actions 或本地环境变量里可设置：

- `PODCAST_TITLE`：播客标题，默认 `天天足球`
- `PODCAST_AUTHOR`：作者，默认 `天天足球`
- `SITE_BASE_URL`：发布后的站点根地址，例如 `https://user.github.io/repo`
- `TTS_VOICE`：默认 `zh-CN-YunyangNeural`
- `TTS_API_URL`：默认 `https://tts.wangwangit.com/v1/audio/speech`
- `TTS_STYLE`：默认 `newscast`
- `TZ_NAME`：默认 `Europe/Paris`

## 手动触发

在 GitHub Actions 页面选择 `Daily Football Podcast`，点击 `Run workflow`。
