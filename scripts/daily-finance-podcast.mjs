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
  '今日 财经 市场 经济 股市 债券 原油 汇率 央行 when:1d',
  '中国 财经 新闻 股市 人民币 资本市场 证券时报 财联社 when:1d',
  '全球 财经 新闻 美股 欧股 日股 原油 黄金 汇率 when:1d',
  '央行 利率 通胀 就业 数据 债券 市场 财经 when:1d',
  '科技股 银行 能源 房地产 消费 财报 财经 when:1d'
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
  return unique.filter((item) => hasChinese(item.title) || hasChinese(item.snippet)).slice(0, 18);
}

function hasChinese(text = '') {
  return /[\u4e00-\u9fff]/.test(text);
}

function removeEnglish(text = '') {
  return stripHtml(text)
    .replace(/[A-Za-z][A-Za-z0-9&;:'’.\/\-]*/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*[-|—_]\s*/g, '，')
    .replace(/，{2,}/g, '，')
    .replace(/^[，。\s]+|[，。\s]+$/g, '')
    .trim();
}

function fallbackScript(date, news) {
  const topTen = news
    .map((item) => ({
      ...item,
      title: removeEnglish(item.title),
      snippet: removeEnglish(item.snippet || item.title)
    }))
    .filter((item) => hasChinese(item.title))
    .slice(0, 10);

  const openers = [
    '先看市场情绪',
    '第二个焦点转向政策面',
    '接下来是大宗商品',
    '第四条看汇率和资金流向',
    '第五条关注科技和成长板块',
    '第六条来自债券市场',
    '第七条说到银行和金融机构',
    '第八条看消费与企业经营',
    '第九条关注海外市场',
    '最后一条看资本市场动态'
  ];

  const intro = `这里是天天财经，今天是${zhDate(date)}，主播天天带你快速听懂今天最重要的十条财经新闻。`;
  const body = topTen.map((item, index) => {
    const detail = item.snippet && item.snippet !== item.title ? `。${item.snippet}` : '';
    return `第${CN_NUMBERS[index]}条，${openers[index]}，${item.title}${detail}。`;
  }).join('\n\n');
  const outro = `今天的财经主线先到这里。这里是天天财经，我是天天，我们明天继续用十条新闻，抓住全球市场的重点。`;
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
            '必须全部使用中文口语表达。不要出现英文标题、英文机构名、英文单词；遇到英文内容要翻译或改写成中文。',
            '结构：开场一句；第一条到第十条；最后总结。每条写法要有变化，不要套同一句模板。',
            '不要解释“为什么重要”，不要说“这条新闻值得关注”，不要给投资建议。',
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
