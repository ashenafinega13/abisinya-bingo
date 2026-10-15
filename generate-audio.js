// generate-audio.js
// Run once: node generate-audio.js
// Creates 75 MP3 files in ./public/audio/

const fs = require('fs');
const path = require('path');
const https = require('https');

const OUT_DIR = path.join(__dirname, 'public', 'audio');
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

function letterOf(n) {
  if (n <= 15) return 'B';
  if (n <= 30) return 'I';
  if (n <= 45) return 'N';
  if (n <= 60) return 'G';
  return 'O';
}

function numberToWords(n) {
  const ones = ['zero','one','two','three','four','five','six','seven','eight','nine',
                'ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen',
                'seventeen','eighteen','nineteen'];
  const tens = ['','','twenty','thirty','forty','fifty','sixty','seventy'];
  if (n < 20) return ones[n];
  const t = Math.floor(n / 10);
  const o = n % 10;
  return o === 0 ? tens[t] : tens[t] + '-' + ones[o];
}

// Google Translate TTS endpoint (free, no API key, male voice via tl param)
function googleTTS(text, lang = 'en') {
  return new Promise((resolve, reject) => {
    const url = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(text)}&tl=${lang}&client=tw-ob&ttsspeed=0.9`;
    const options = {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      }
    };
    https.get(url, options, res => {
      if (res.statusCode !== 200) return reject(new Error('HTTP ' + res.statusCode));
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    }).on('error', reject);
  });
}

(async () => {
  console.log('🎙️  Generating 75 MP3 announcements…\n');
  for (let n = 1; n <= 75; n++) {
    const letter = letterOf(n);
    const text = `${letter}, ${numberToWords(n)}`;
    const file = path.join(OUT_DIR, `call_${n}.mp3`);
    try {
      const buf = await googleTTS(text, 'en');
      fs.writeFileSync(file, buf);
      console.log(`✅ ${n}  →  "${text}"  (${(buf.length/1024).toFixed(1)} KB)`);
    } catch (e) {
      console.error(`❌ ${n}  →  ${e.message}`);
    }
    // be polite — 200ms between requests
    await new Promise(r => setTimeout(r, 200));
  }
  console.log('\n🎉 Done! Check ./public/audio/');
})();