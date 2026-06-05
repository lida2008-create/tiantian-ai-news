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

当前发布地址：

```text
https://lida2008-create.github.io/tiantian-ai-news/football/rss.xml
```

本地或自动任务每天运行：

```bash
SITE_BASE_URL=https://lida2008-create.github.io/tiantian-ai-news/football \
python scripts/daily_football_podcast.py
python scripts/publish_to_github.py
```

如果你想把足球播客和别的栏目彻底拆开，可以给发布脚本单独指定目标仓库、分支和目录：

```bash
PUBLISH_REPO_URL=https://github.com/yourname/football-podcast.git \
PUBLISH_BRANCH=main \
PUBLISH_SITE_DIR='' \
PUBLISH_PROJECT_DIR='project' \
python scripts/publish_to_github.py
```

说明：

- `PUBLISH_REPO_URL`：目标仓库
- `PUBLISH_BRANCH`：推送分支，默认 `main`
- `PUBLISH_SITE_DIR`：站点内容目录，默认 `football`
- `PUBLISH_PROJECT_DIR`：项目数据目录，默认 `football-project`

如果 `PUBLISH_SITE_DIR=''`，会把 `docs/` 内容直接发布到仓库根目录，适合独立仓库单独做 Pages。

默认按巴黎时间凌晨 1 点运行。

如果使用 GitHub Actions，巴黎时间凌晨 1 点对应：

```yaml
cron: "0 23 * * *"
```

如果你想改成北京时间凌晨 1 点，请改为：

```yaml
cron: "0 17 * * *"
```

如果你想改成美国东部时间凌晨 1 点，请根据夏令时改为 `05:00 UTC` 或 `06:00 UTC`。

## 外网抓取失败时怎么改

如果运行环境偶发无法解析 `news.google.com`、`feeds.bbci.co.uk`、`github.com` 这类域名，原来的流程会直接失败。现在脚本支持手工新闻回退，不需要手写整篇 2000 字播报稿。

1. 在 `data/manual_news/` 下创建当天文件，例如 `data/manual_news/2026-06-05.json`
2. 写入至少 10 条新闻，每条包含 `title` 和 `summary`
3. 重新运行 `python scripts/daily_football_podcast.py`

示例：

```json
[
  {
    "title": "皇马推进夏窗关键引援",
    "summary": "俱乐部与球员团队的谈判进入新阶段，转会费和合同年限仍在拉锯。",
    "link": "https://example.com/news-1",
    "published": "2026-06-05T00:30:00+02:00"
  }
]
```

也可以不用默认路径，直接指定：

```bash
NEWS_JSON_FILE=/absolute/path/to/news.json python scripts/daily_football_podcast.py
```

如果你已经手写好了完整播报稿，仍然可以继续使用原来的：

```bash
SCRIPT_FILE=/absolute/path/to/script.txt python scripts/daily_football_podcast.py
```

如果你已经在浏览器里手动生成好了 MP3，也可以跳过 TTS，只做数据更新：

```bash
USE_EXISTING_AUDIO=1 \
SITE_BASE_URL=https://lida2008-create.github.io/tiantian-ai-news/football \
python scripts/daily_football_podcast.py
```

默认会读取 `docs/audio/YYYY-MM-DD.mp3`。如果音频在别的位置，可以显式指定：

```bash
AUDIO_FILE=/absolute/path/to/2026-06-05.mp3 \
SITE_BASE_URL=https://lida2008-create.github.io/tiantian-ai-news/football \
python scripts/daily_football_podcast.py
```

## Azure Speech 直连

如果 `tts.wangwangit.com` 不稳定，可以直接改走 Azure Speech。脚本会在检测到 `SPEECH_KEY` 和 `SPEECH_REGION` 后自动优先使用 Azure REST。

```bash
export SPEECH_KEY='your-azure-speech-key'
export SPEECH_REGION='eastasia'
SITE_BASE_URL=https://lida2008-create.github.io/tiantian-ai-news/football \
PYTHONPYCACHEPREFIX=/private/tmp/tiantian_pycache \
.venv/bin/python scripts/daily_football_podcast.py
```

默认仍使用 `zh-CN-YunyangNeural`。如果风格设为 `newscast`，脚本会自动映射成 Azure 官方更接近的 `newscast-casual`。

如果你需要以后每天自动运行，推荐直接使用 GitHub Actions + Azure Speech，不要依赖本机网络环境。

需要在 GitHub 仓库里配置两个 Secrets：

- `SPEECH_KEY`
- `SPEECH_REGION`

配置好后，仓库里的 [`/.github/workflows/daily-football-podcast.yml`](/Users/daniel/Documents/天天足球/.github/workflows/daily-football-podcast.yml) 会按计划自动执行，直接在 GitHub 服务器上生成音频、更新 RSS 和提交结果。

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
