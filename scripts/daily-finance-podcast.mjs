import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { basename } from 'node:path';

const SITE = 'https://lida2008-create.github.io/tiantian-ai-news';
const ROOT = new URL('../', import.meta.url);
const RSS_PATH = new URL('finance-rss.xml', ROOT);
const AUDIO_DIR = new URL('audio/', ROOT);
const EPISODE_DIR = new URL('episodes/', ROOT);

const TTS_ENDPOINT = 'https://tts.wangwangit.com/v1/audio/speech';
const TTS_VOICE = 'zh-CN-YunyangNeural';
const TTS_STYLE = 'newscast';

const NEWS_QUERIES = [
  'Reuters global markets oil stocks bonds economy finance when:1d',
  'Reuters business finance economy central bank markets when:1d',
  'CNBC markets economy finance stocks oil bonds when:1d',
  'Bloomberg markets economy finance stocks rates oil when:1d',
  '财经 市场 经济 股市 债券 原油 汇率 今日 when:1d'
];

const CN_NUMBERS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];

function decodeEntities(text = '') {
  return text
    .replace(/<!\[CDATA\[(.*?)\]\]>/gs, '$1')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)));
}

function stripHtml(text = '') {
  return decodeEntities(text)
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function escapeXml(text = '') {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function parisParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Paris',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).formatToParts(date);
  return Object.fromEntries(parts.map((p) => [p.type, p.value]));
}

function episodeDate() {
  const p = parisParts();
  return `${p.year}-${p.month}-${p.day}`;
}

function zhDate(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return `${year}年${month}月${day}日`;
}

function isParisTargetHour() {
  const hour = parisParts().hour;
  return hour === '01' || hour === '02';
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: {
      'User-Agent': 'TiantianFinancePodcastBot/1.0'
    }
  });
  if (!response.ok) {
    throw new Error(`Fetch failed ${response.status}: ${url}`);
  }
  return response.text();
}

function parseGoogleNewsRss(xml) {
  const items = [...xml.matchAll(/<item>(.*?)<\/item>/gs)].map((match) => {
    const item = match[1];
    const field = (name) => {
      const m = item.match(new RegExp(`<${name}[^>]*>(.*?)<\\/${name}>`, 's'));
      return m ? decodeEntities(m[1]).trim() : '';
    };
    const title = stripHtml(field('title')).replace(/\s+-\s+[^-]+$/, '').trim();
    return {
      title,
      link: stripHtml(field('link')),
      source: stripHtml(field('source')),
      pubDate: stripHtml(field('pubDate')),
      snippet: stripHtml(field('description'))
    };
  });
  return items.filter((item) => item.title && item.link);
}

async function collectNews() {
  const all = [];
  for (const query of NEWS_QUERIES) {
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=zh-CN&gl=US&ceid=US:zh-Hans`;
    try {
      all.push(...parseGoogleNewsRss(await fetchText(url)));
    } catch (error) {
      console.warn(`Skipping source query: ${query}: ${error.message}`);
    }
  }

  const seen = new Set();
  const unique = [];
  for (const item of all) {
    const key = item.title.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').slice(0, 90);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    unique.push(item);
  }
  return unique.slice(0, 18);
}

function fallbackScript(date, news) {
  const topTen = news.slice(0, 10);
  const intro = `这里是天天财经，今天是${zhDate(date)}，主播天天带你快速听懂今天最重要的十条财经新闻。今天我们关注全球市场、央行利率、能源价格、科技股、汇率和资本流动。`;
  const body = topTen.map((item, index) => {
    const snippet = item.snippet || item.title;
    return `第${CN_NUMBERS[index]}条，${item.title}。${snippet}。这条新闻值得关注，是因为它可能影响投资者风险偏好、企业成本、利率预期，或者全球资金流向。`;
  }).join('\n\n');
  const outro = `总结一下，今天财经市场的主线，是资金在增长预期、通胀压力和政策不确定性之间重新定价。这里是天天财经，我是天天，我们明天继续用十条新闻，抓住全球市场的重点。`;
  return `${intro}\n\n${body}\n\n${outro}`;
}

async function openAiScript(date, news) {
  if (!process.env.OPENAI_API_KEY) {
    return fallbackScript(date, news);
  }

  const response = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || 'gpt-4.1-mini',
      input: [
        {
          role: 'system',
          content: '你是中文财经播客主编。写作必须准确、克制、口语化，不提供投资建议，不编造事实。'
        },
        {
          role: 'user',
          content: [
            `日期：${zhDate(date)}。主播名：天天。`,
            '请从候选新闻中选出十条最重要的财经新闻，写成约1800到2200个中文字符的单人播客口播稿。',
            '结构：开场一句；第一条到第十条；最后总结。风格参考“天天财经”：清楚、紧凑、解释为什么重要。',
            '不要添加背景音乐说明，不要使用 Markdown，不要输出来源列表。',
            '候选新闻：',
            JSON.stringify(news, null, 2)
          ].join('\n')
        }
      ]
    })
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI failed ${response.status}: ${error.slice(0, 500)}`);
  }
  const json = await response.json();
  const output = json.output_text || json.output?.flatMap((o) => o.content || []).map((c) => c.text || '').join('\n');
  if (!output || output.length < 600) {
    throw new Error('OpenAI returned an unexpectedly short script.');
  }
  return output.trim();
}

async function generateSpeech(script) {
  const response = await fetch(TTS_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Origin: 'https://tts.wangwangit.com',
      Referer: 'https://tts.wangwangit.com/'
    },
    body: JSON.stringify({
      input: script,
      voice: TTS_VOICE,
      speed: 1,
      pitch: '0',
      style: TTS_STYLE
    })
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`TTS failed ${response.status}: ${error.slice(0, 500)}`);
  }
  return Buffer.from(await response.arrayBuffer());
}

function durationFromBytesEstimate(bytes) {
  const seconds = Math.round((bytes * 8) / 48000);
  const minutes = Math.floor(seconds / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return `00:${String(minutes).padStart(2, '0')}:${rest}`;
}

function htmlFor(date, script, audioFileName) {
  const paragraphs = script.split(/\n{2,}/).map((p) => `<p>${escapeXml(p.trim())}</p>`).join('\n  ');
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>天天财经｜${date} 十条财经新闻</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.75; max-width: 820px; margin: 40px auto; padding: 0 20px; color: #1f2933; }
    h1 { line-height: 1.25; }
    audio { width: 100%; margin: 20px 0; }
    .meta { color: #607080; }
  </style>
</head>
<body>
  <h1>天天财经｜${date} 十条财经新闻</h1>
  <p class="meta">主播：天天｜音色：云扬 Yunyang 男声新闻播报｜版本：无背景音乐</p>
  <audio controls src="../audio/${escapeXml(audioFileName)}"></audio>
  ${paragraphs}
</body>
</html>
`;
}

function rssItem({ date, script, audioFileName, audioBytes, duration }) {
  const description = script.replace(/\s+/g, ' ').slice(0, 280);
  const pageName = `tiantian-finance-${date}.html`;
  const audioUrl = `${SITE}/audio/${audioFileName}`;
  return `    <item>
      <title>天天财经｜${date} 十条财经新闻</title>
      <description>${escapeXml(description)}</description>
      <link>${SITE}/episodes/${pageName}</link>
      <guid isPermaLink="false">${audioUrl}</guid>
      <pubDate>${new Date().toUTCString()}</pubDate>
      <enclosure url="${audioUrl}" length="${audioBytes}" type="audio/mpeg"/>
      <itunes:duration>${duration}</itunes:duration>
      <itunes:episodeType>full</itunes:episodeType>
    </item>`;
}

async function updateRss(itemXml, date) {
  let rss = await readFile(RSS_PATH, 'utf8');
  if (rss.includes(`天天财经｜${date} 十条财经新闻`) || rss.includes(`tiantian-finance-${date}`)) {
    console.log(`RSS already contains finance episode for ${date}; skipping RSS update.`);
    return false;
  }
  rss = rss.replace(/<lastBuildDate>.*?<\/lastBuildDate>/s, `<lastBuildDate>${new Date().toUTCString()}</lastBuildDate>`);
  rss = rss.replace(/\s*<\/channel>\s*<\/rss>\s*$/s, `\n${itemXml}\n  </channel>\n</rss>\n`);
  await writeFile(RSS_PATH, rss);
  return true;
}

async function main() {
  const scheduled = process.argv.includes('--scheduled');
  if (scheduled && !isParisTargetHour()) {
    console.log('Not 01:00 hour in Europe/Paris; skipping scheduled duplicate.');
    return;
  }

  const date = episodeDate();
  const existingRss = await readFile(RSS_PATH, 'utf8');
  if (existingRss.includes(`tiantian-finance-${date}`)) {
    console.log(`Episode already exists for ${date}; exiting.`);
    return;
  }

  await mkdir(AUDIO_DIR, { recursive: true });
  await mkdir(EPISODE_DIR, { recursive: true });

  const news = await collectNews();
  if (news.length < 10) {
    throw new Error(`Only found ${news.length} candidate news items.`);
  }

  let script;
  try {
    script = await openAiScript(date, news);
  } catch (error) {
    console.warn(`Falling back to templated script: ${error.message}`);
    script = fallbackScript(date, news);
  }

  const audio = await generateSpeech(script);
  const audioFileName = `tiantian-finance-${date}-wangwangit-yunyang-newscast.mp3`;
  const pageFileName = `tiantian-finance-${date}.html`;
  const contentHash = createHash('sha256').update(audio).digest('hex').slice(0, 12);
  console.log(`Generated ${basename(audioFileName)} (${audio.length} bytes, sha256 ${contentHash})`);

  await writeFile(new URL(audioFileName, AUDIO_DIR), audio);
  await writeFile(new URL(pageFileName, EPISODE_DIR), htmlFor(date, script, audioFileName));

  const item = rssItem({
    date,
    script,
    audioFileName,
    audioBytes: audio.length,
    duration: durationFromBytesEstimate(audio.length)
  });
  await updateRss(item, date);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
