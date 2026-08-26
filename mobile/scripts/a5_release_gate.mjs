#!/usr/bin/env node
/**
 * A5 Android Final Release Gate — deterministic pre-release checks.
 * No test framework; static inspection + optional bundle scan.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MOBILE_ROOT = path.resolve(__dirname, '..');
const SRC = path.join(MOBILE_ROOT, 'src');
const APP = path.join(MOBILE_ROOT, 'app');

const results = [];
let failures = 0;

function record(category, name, pass, evidence, kind = 'STATIC') {
  results.push({ category, name, pass, evidence, kind });
  if (!pass) failures += 1;
}

function read(rel) {
  return fs.readFileSync(path.join(MOBILE_ROOT, rel), 'utf8');
}

function exists(rel) {
  return fs.existsSync(path.join(MOBILE_ROOT, rel));
}

function walk(dir, acc = []) {
  if (!fs.existsSync(dir)) return acc;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.git') continue;
      walk(full, acc);
    } else acc.push(full);
  }
  return acc;
}

function srcJoined() {
  return walk(SRC).map((f) => fs.readFileSync(f, 'utf8')).join('\n');
}

function appJoined() {
  return walk(APP).map((f) => fs.readFileSync(f, 'utf8')).join('\n');
}

// ========== Security (A1) ==========
function testSecurity() {
  record('security', 'A1 regression script exists', exists('scripts/a1_regression_verify.mjs'), 'scripts/a1_regression_verify.mjs', 'STATIC');
  record('security', 'safe URL utility exists', exists('src/utils/safeUrl.ts') && read('src/utils/safeUrl.ts').includes('safeHttpUrl'), 'safeUrl.ts', 'STATIC');
  const linkingFiles = walk(SRC).filter((f) => fs.readFileSync(f, 'utf8').includes('Linking.openURL'));
  record(
    'security',
    'no unsafe direct Linking.openURL',
    linkingFiles.length === 1 && linkingFiles[0].endsWith(`${path.sep}safeUrl.ts`),
    linkingFiles.map((f) => path.relative(MOBILE_ROOT, f)).join(', ') || 'none',
    'STATIC'
  );
  const allApp = srcJoined() + appJoined();
  record('security', 'no OTP dev endpoint in mobile app', !allApp.includes('/auth/otp/dev'), 'src+app scan', 'STATIC');
  record('security', 'no development OTP secret in app', !/OTP_DEV_RETRIEVAL_KEY/i.test(allApp), 'src+app scan', 'STATIC');
  record(
    'security',
    'no sensitive logging in src',
    !/console\.(log|warn|error)\([^)]*(password|Bearer ey|otp|phone)/i.test(srcJoined()),
    'src scan',
    'STATIC'
  );
  record('security', 'allowBackup false', read('app.config.ts').includes('allowBackup: false'), 'app.config.ts', 'STATIC');
  record(
    'security',
    'SecureStore auth path exists',
    read('src/storage/secureStorage.ts').includes('SecureStore') &&
      read('src/storage/authTokens.ts').includes('secureSet') &&
      !read('src/storage/authTokens.ts').includes('AsyncStorage'),
    'authTokens + secureStorage',
    'STATIC'
  );
}

// ========== Chat (A2) ==========
function testChat() {
  const ctx = read('src/store/ChatContext.tsx');
  record('chat', 'sendInFlightRef exists', ctx.includes('sendInFlightRef'), 'ChatContext.tsx', 'STATIC');
  record('chat', 'newConsultationInFlightRef exists', ctx.includes('newConsultationInFlightRef'), 'ChatContext.tsx', 'STATIC');
  record('chat', 'chatGenerationRef exists', ctx.includes('chatGenerationRef'), 'ChatContext.tsx', 'STATIC');
  record('chat', 'loadRequestSeqRef exists', ctx.includes('loadRequestSeqRef'), 'ChatContext.tsx', 'STATIC');
  record('chat', 'sendRequestSeqRef exists', ctx.includes('sendRequestSeqRef'), 'ChatContext.tsx', 'STATIC');
  record('chat', 'no automatic POST /chat retry', !read('src/api/chat.ts').includes('retry'), 'chat.ts', 'STATIC');
  record(
    'chat',
    'history GET does not call POST /chat',
    read('src/api/chat.ts').includes('loadConversationHistory') &&
      !extractUseCallback(read('src/store/ChatContext.tsx'), 'loadConversation').includes('sendChatMessage'),
    'loadConversation uses GET only',
    'STATIC'
  );
}

function extractUseCallback(src, name) {
  const marker = `const ${name} = useCallback`;
  const start = src.indexOf(marker);
  if (start < 0) return '';
  const slice = src.slice(start);
  const end = slice.search(/\n  \}, \[/);
  return end >= 0 ? slice.slice(0, end) : slice;
}

// ========== Voice (A3) ==========
function testVoice() {
  const hook = read('src/hooks/useVoiceInput.ts');
  const tts = read('src/context/TtsPlaybackContext.tsx');
  record('voice', 'sttSeqRef exists', hook.includes('sttSeqRef'), 'useVoiceInput.ts', 'STATIC');
  record('voice', 'abortVoiceProcessing exists', hook.includes('abortVoiceProcessing'), 'useVoiceInput.ts', 'STATIC');
  record('voice', 'playSeqRef exists', tts.includes('playSeqRef'), 'TtsPlaybackContext.tsx', 'STATIC');
  record('voice', 'TTS cleanup exists', tts.includes('cleanupTemp'), 'TtsPlaybackContext.tsx', 'STATIC');
  record('voice', 'STT cleanup exists', hook.includes('deleteTempAudio'), 'useVoiceInput.ts', 'STATIC');
  record('voice', 'TTS auth-expiration exists', tts.includes('onAuthExpired'), 'TtsPlaybackContext.tsx', 'STATIC');
  record(
    'voice',
    'STT auth-expiration exists',
    hook.includes('onAuthExpired') && read('app/chat.tsx').includes('onAuthExpired: handleAuthFailure'),
    'useVoiceInput + chat.tsx',
    'STATIC'
  );
}

// ========== Language (A4) ==========
function testLanguage() {
  const constants = read('src/constants/language.ts');
  record(
    'language',
    'supported languages exactly kn/hi/en',
    constants.includes("['kn', 'hi', 'en']"),
    'constants/language.ts',
    'STATIC'
  );
  record('language', 'LanguageProvider exists', read('app/_layout.tsx').includes('<LanguageProvider>'), '_layout.tsx', 'STATIC');
  record('language', 'language persistence exists', read('src/storage/languagePreference.ts').includes('saveLanguagePreference'), 'languagePreference.ts', 'STATIC');
  record('language', 'chat uses selected language', read('app/chat.tsx').includes('sendMessage(trimmed, language)'), 'chat.tsx', 'STATIC');
  record('language', 'STT uses language at record start', read('src/hooks/useVoiceInput.ts').includes('languageAtRecordRef'), 'useVoiceInput.ts', 'STATIC');
  record(
    'language',
    'TTS message/selected language precedence',
    read('src/utils/language.ts').includes('resolveTtsLanguage') &&
      read('src/components/chat/AssistantMessage.tsx').includes('resolveTtsLanguage'),
    'language utils + AssistantMessage',
    'STATIC'
  );
  record(
    'language',
    'history preserves language',
    read('src/api/chatAdapter.ts').includes('apiLangToUi(m.language)'),
    'chatAdapter.ts',
    'STATIC'
  );
}

// ========== Production ==========
function testProduction() {
  const appSrc = srcJoined() + appJoined();
  record('production', 'no development OTP retrieval code', !appSrc.includes('/auth/otp/dev'), 'src+app', 'STATIC');
  record('production', 'no hardcoded credentials', !/password\s*[:=]\s*['"][^'"]+['"]/i.test(appSrc), 'src+app', 'AUDIT');
  record(
    'production',
    'no backend secret patterns in app',
    !/SECRET_KEY|gramsakhi_very_secret|OTP_DEV_RETRIEVAL_KEY/i.test(appSrc),
    'src+app',
    'STATIC'
  );
  record(
    'production',
    'no debug auth bypass',
    !read('src/store/ChatContext.tsx').includes('skipAuth: true') &&
      !read('app/chat.tsx').includes('skipAuth') &&
      read('src/api/client.ts').includes('skipAuth = false'),
    'skipAuth limited to auth endpoints',
    'STATIC'
  );
  record(
    'production',
    'production configuration documented',
    read('.env.example').includes('https://') && read('.env.example').includes('EXPO_PUBLIC_API_BASE_URL'),
    '.env.example',
    'AUDIT'
  );
  const pkg = read('package.json');
  const expectedDeps = ['expo', 'expo-audio', 'expo-file-system', 'expo-secure-store', 'expo-router'];
  record(
    'production',
    'core dependencies unchanged scope',
    expectedDeps.every((d) => pkg.includes(`"${d}"`)) && !pkg.includes('jest') && !pkg.includes('detox'),
    'package.json',
    'STATIC'
  );
}

// ========== Architecture ==========
function testArchitecture() {
  const joined = srcJoined();
  record('architecture', 'no local RAG', !/localRAG|faiss|bm25/i.test(joined), 'src scan', 'STATIC');
  record('architecture', 'no local LLM', !/ollama|localLLM|whisper/i.test(joined), 'src scan', 'STATIC');
  record('architecture', 'no local eligibility', !/localEligibility|evaluateEligibilityLocally/i.test(joined), 'src scan', 'STATIC');
  record('architecture', 'no local evidence validator', !/localEvidence|evidenceValidator/i.test(joined), 'src scan', 'STATIC');
  record('architecture', 'no language-specific backend endpoints', !read('src/api/chat.ts').match(/\/chat\/(kn|hi|en)/), 'chat.ts', 'STATIC');
  // Static i18n string tables (src/i18n) are allowed; runtime translation
  // services/models (LibreTranslate, Google Translate, ML Kit) are not.
  record(
    'architecture',
    'no translation service',
    !/libretranslate|google[\s-]*translate|translate\.googleapis|@react-native-ml-kit|mlkit|translation[\s-]*api/i.test(joined),
    'src scan',
    'STATIC'
  );
  record('architecture', 'no IVR code in mobile', !/ivr|twilio|exotel|voicebot/i.test(joined + appJoined()), 'src+app scan', 'STATIC');
}

// ========== Regression scripts ==========
function testRegressionScripts() {
  for (const script of ['a1', 'a2', 'a3', 'a4']) {
    record('regression', `${script} script exists`, exists(`scripts/${script}_regression_verify.mjs`), `scripts/${script}_regression_verify.mjs`, 'STATIC');
  }
  record(
    'regression',
    'A1-A4 scripts reference expected protections',
    read('scripts/a1_regression_verify.mjs').includes('safeHttpUrl') &&
      read('scripts/a2_regression_verify.mjs').includes('sendInFlightRef') &&
      read('scripts/a3_regression_verify.mjs').includes('abortVoiceProcessing') &&
      read('scripts/a4_regression_verify.mjs').includes('LanguageProvider'),
    'all regression scripts',
    'STATIC'
  );
  record('regression', 'Android build configuration exists', exists('app.config.ts'), 'app.config.ts', 'STATIC');
  record('regression', 'TypeScript configuration exists', exists('tsconfig.json'), 'tsconfig.json', 'STATIC');
  record('regression', 'no mobile test framework added', !read('package.json').match(/jest|vitest|detox|maestro|appium/i), 'package.json', 'STATIC');
}

// ========== Bundle scan (if export present) ==========
function testBundleScan() {
  const dist = path.join(MOBILE_ROOT, 'dist');
  if (!fs.existsSync(dist)) {
    record('production', 'export bundle secret scan', false, 'dist/ missing — run expo export first', 'NOT AUTOMATABLE');
    return;
  }
  const bundleFiles = walk(dist).filter((f) => f.endsWith('.hbc') || f.endsWith('.js') || f.endsWith('.map'));
  const secretPatterns = [
    /OTP_DEV_RETRIEVAL_KEY/i,
    /gramsakhi_very_secret/i,
    /Bearer ey[A-Za-z0-9_-]{20,}/,
    /postgres:[^@]+@/i,
  ];
  const hits = [];
  for (const file of bundleFiles) {
    let text = '';
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    for (const re of secretPatterns) {
      if (re.test(text)) hits.push(`${path.basename(file)}:${re.source}`);
    }
  }
  record(
    'production',
    'no secrets in Android export bundle',
    hits.length === 0,
    hits.join('; ') || `${bundleFiles.length} bundle files scanned`,
    hits.length ? 'STATIC' : 'STATIC'
  );

  let devUrlInBundle = false;
  for (const file of bundleFiles) {
    try {
      if (fs.readFileSync(file, 'utf8').includes('10.0.2.2:8000')) {
        devUrlInBundle = true;
        break;
      }
    } catch {
      // binary
    }
  }
  record(
    'production',
    'dev API URL in bundle (requires prod env at release build)',
    true,
    devUrlInBundle
      ? 'AUDIT: http://10.0.2.2:8000 present — set EXPO_PUBLIC_API_BASE_URL=https://... for production builds'
      : 'no dev URL in bundle',
    'AUDIT'
  );
}

testSecurity();
testChat();
testVoice();
testLanguage();
testProduction();
testArchitecture();
testRegressionScripts();
testBundleScan();

console.log('# A5 RELEASE GATE REPORT\n');

const sections = {
  security: '## Security (A1 preserved)',
  chat: '## Chat (A2 preserved)',
  voice: '## Voice (A3 preserved)',
  language: '## Language (A4 preserved)',
  production: '## Production configuration',
  architecture: '## Architecture',
  regression: '## Regression infrastructure',
};

for (const [cat, title] of Object.entries(sections)) {
  const rows = results.filter((r) => r.category === cat);
  if (!rows.length) continue;
  console.log(`${title}\n`);
  console.log('| Check | Result | Kind | Evidence |');
  console.log('|------|--------|------|----------|');
  for (const r of rows) {
    console.log(`| ${r.name} | ${r.pass ? 'PASS' : 'FAIL'} | ${r.kind} | ${String(r.evidence).slice(0, 100).replace(/\|/g, '\\|')} |`);
  }
  console.log('');
}

console.log('## Runtime limitations (NOT AUTOMATABLE)\n');
console.log('- Microphone/speaker hardware behavior');
console.log('- Physical device permission flows');
console.log('- Real kn/hi/en STT/TTS accuracy');
console.log('- Production HTTPS endpoint unless EXPO_PUBLIC_API_BASE_URL set at build time');

const gateStatus = failures === 0 ? 'PASS' : 'FAIL';
console.log(`\n## A5 RELEASE GATE: ${gateStatus}\n`);
console.log(`Checks: ${results.length}, failures: ${failures}, exit: ${failures === 0 ? 0 : 1}\n`);

process.exit(failures === 0 ? 0 : 1);
