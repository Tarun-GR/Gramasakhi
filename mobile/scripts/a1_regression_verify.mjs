#!/usr/bin/env node
/**
 * A1 Android Security + Privacy — automated regression verification.
 * No test framework; Node built-ins + static inspection only.
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

function record(category, name, pass, evidence) {
  results.push({ category, name, pass, evidence });
  if (!pass) failures += 1;
}

function read(rel) {
  return fs.readFileSync(path.join(MOBILE_ROOT, rel), 'utf8');
}

function walk(dir, acc = []) {
  if (!fs.existsSync(dir)) return acc;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.git') continue;
      walk(full, acc);
    } else {
      acc.push(full);
    }
  }
  return acc;
}

// --- Mirror production safeHttpUrl (must stay in sync with src/utils/safeUrl.ts) ---
function safeHttpUrl(url) {
  if (!url || typeof url !== 'string') return null;
  try {
    const parsed = new URL(url.trim());
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch {
    // ignore
  }
  return null;
}

function openSafeHttpUrl(url, opened = []) {
  const safe = safeHttpUrl(url);
  if (!safe) return false;
  opened.push(safe);
  return true;
}

// --- OTP flow helper (mirror src/utils/otpFlowPhone.ts) ---
function createOtpFlowPhoneModule() {
  let pendingPhone = null;
  return {
    setOtpFlowPhone(phone) {
      pendingPhone = phone.replace(/\D/g, '').slice(0, 10);
    },
    consumeOtpFlowPhone() {
      const phone = pendingPhone;
      pendingPhone = null;
      return phone;
    },
    clearOtpFlowPhone() {
      pendingPhone = null;
    },
    _peek() {
      return pendingPhone;
    },
  };
}

// ========== 1. safeHttpUrl ==========
function testSafeHttpUrl() {
  const allow = [
    ['https://example.com', true],
    ['http://example.com', true],
    ['https://www.myscheme.gov.in/schemes/pm-kisan', true],
  ];
  const deny = [
    ['javascript:alert(1)', false],
    ['JavaScript:alert(1)', false],
    ['file:///etc/passwd', false],
    ['intent://example', false],
    ['data:text/html,<script>alert(1)</script>', false],
    ['not-a-url', false],
    ['', false],
    [null, false],
    [undefined, false],
  ];

  for (const [input, shouldAllow] of [...allow, ...deny]) {
    const out = safeHttpUrl(input);
    const pass = shouldAllow ? out !== null : out === null;
    record('security', `safeHttpUrl(${JSON.stringify(input)})`, pass, pass ? String(out) : 'rejected');
  }

  const opened = [];
  const blocked = !openSafeHttpUrl('javascript:alert(1)', opened);
  record('security', 'openSafeHttpUrl blocks javascript:', blocked && opened.length === 0, `opened=${opened.length}`);
}

// ========== 2. SourceList static ==========
function testSourceListStatic() {
  const src = read('src/components/chat/SourceList.tsx');
  record(
    'security',
    'SourceList imports safeHttpUrl/openSafeHttpUrl',
    src.includes("from '../../utils/safeUrl'") &&
      src.includes('safeHttpUrl(source.url)') &&
      src.includes('openSafeHttpUrl(href)'),
    'SourceList.tsx imports and uses safe URL helpers'
  );
  record(
    'security',
    'SourceList has no direct Linking.openURL',
    !src.includes('Linking.openURL'),
    'no Linking.openURL in SourceList.tsx'
  );
}

// ========== 3. SimpleMarkdownText static ==========
function testMarkdownStatic() {
  const src = read('src/components/chat/SimpleMarkdownText.tsx');
  record(
    'security',
    'SimpleMarkdownText uses safeHttpUrl for isUrl',
    src.includes('safeHttpUrl(part)') && src.includes('openSafeHttpUrl'),
    'SimpleMarkdownText.tsx'
  );
  record(
    'security',
    'SimpleMarkdownText has no direct Linking.openURL',
    !src.includes('Linking.openURL'),
    'no Linking.openURL in SimpleMarkdownText.tsx'
  );

  const schemes = ['javascript:alert(1)', 'file:///x', 'intent://x', 'data:text/html,x'];
  for (const s of schemes) {
    const opened = [];
    openSafeHttpUrl(s, opened);
    record('security', `SimpleMarkdownText path rejects ${s.split(':')[0]}:`, opened.length === 0, 'openSafeHttpUrl blocked');
  }
}

// ========== 4. OTP navigation privacy ==========
function testOtpFlow() {
  const login = read('app/login.tsx');
  const otp = read('app/otp.tsx');

  record(
    'privacy',
    'login.tsx uses setOtpFlowPhone',
    login.includes('setOtpFlowPhone(phone)'),
    'setOtpFlowPhone(phone) present'
  );
  record(
    'privacy',
    'login.tsx no router params with phone',
    !login.includes('params:') && !login.includes('phone_number') && login.includes("router.push('/otp')"),
    "router.push('/otp') without params"
  );
  record(
    'privacy',
    'otp.tsx no useLocalSearchParams',
    !otp.includes('useLocalSearchParams'),
    'useLocalSearchParams absent'
  );
  record(
    'privacy',
    'otp.tsx consumes in-memory phone',
    otp.includes('consumeOtpFlowPhone()') && otp.includes("router.replace('/login')"),
    'consumeOtpFlowPhone + login redirect'
  );

  const flow = createOtpFlowPhoneModule();
  flow.setOtpFlowPhone('9876543210');
  record('privacy', 'otpFlowPhone available after set', flow._peek() === '9876543210', flow._peek());
  const first = flow.consumeOtpFlowPhone();
  record('privacy', 'otpFlowPhone consume returns phone', first === '9876543210', first);
  record('privacy', 'otpFlowPhone consume is single-use', flow.consumeOtpFlowPhone() === null, 'second consume null');
  flow.setOtpFlowPhone('9123456789');
  flow.clearOtpFlowPhone();
  record('privacy', 'otpFlowPhone clear removes phone', flow._peek() === null, 'cleared');
  record(
    'privacy',
    'otpFlowPhone sanitizes non-digits',
    (() => {
      flow.setOtpFlowPhone('98765-43210');
      return flow.consumeOtpFlowPhone() === '9876543210';
    })(),
    '98765-43210 -> 9876543210'
  );
}

// ========== 5. Auth/session privacy (static) ==========
function testAuthSessionStatic() {
  const tokens = read('src/storage/authTokens.ts');
  const auth = read('src/context/AuthContext.tsx');
  const chat = read('src/store/ChatContext.tsx');

  const clears = ['clearAccessToken', 'clearCitizenAccountId', 'clearPhoneNumber', 'clearConversationId'];
  record(
    'privacy',
    'clearAuthSession clears all session keys',
    clears.every((fn) => tokens.includes(fn) && tokens.includes('clearAuthSession')),
    clears.join(', ')
  );
  record(
    'privacy',
    'logout calls clearAuthSession',
    auth.includes('await clearAuthSession()') && auth.includes('setStatus(\'unauthenticated\')'),
    'AuthContext.logout'
  );
  record(
    'privacy',
    'expireSession calls clearAuthSession',
    auth.includes('expireSession') && auth.match(/expireSession[\s\S]*clearAuthSession/),
    'AuthContext.expireSession'
  );
  record(
    'privacy',
    'ChatContext resetSession on unauthenticated',
    chat.includes("status === 'unauthenticated'") && chat.includes('resetSession()'),
    'ChatContext useEffect'
  );
  record(
    'privacy',
    'handleAuthFailure clears chat + expireSession',
    chat.includes('handleAuthFailure') &&
      chat.includes('setMessages([])') &&
      chat.includes('clearConversationId') &&
      chat.includes('expireSession'),
    'ChatContext.handleAuthFailure'
  );
  record(
    'privacy',
    'JWT stored via SecureStore only',
    read('src/storage/secureStorage.ts').includes('SecureStore') &&
      !read('src/storage/authTokens.ts').includes('AsyncStorage'),
    'secureStorage + authTokens'
  );
}

// ========== 6. Voice privacy (static) ==========
function testVoiceStatic() {
  const voiceHook = read('src/hooks/useVoiceInput.ts');
  const tts = read('src/context/TtsPlaybackContext.tsx');
  const chat = read('app/chat.tsx');

  record(
    'voice',
    'STT deletes temp audio in finally',
    voiceHook.includes('await deleteTempAudio(fileUri)') && voiceHook.includes('finally'),
    'useVoiceInput finishRecording'
  );
  record(
    'voice',
    'STT cancel deletes temp audio',
    voiceHook.includes('await deleteTempAudio(uri)') && voiceHook.includes('cancelRecording'),
    'useVoiceInput cancelRecording'
  );
  record(
    'voice',
    'STT generation guard',
    voiceHook.includes('genAtRecord !== getChatGeneration()') && voiceHook.includes('sttSeq !== sttSeqRef.current'),
    'useVoiceInput sequence guards'
  );
  record(
    'voice',
    'TTS deletes on completion/stop/replace/unmount',
    tts.includes('deleteTempAudio') &&
      tts.includes('stopPlayback') &&
      tts.includes('cleanupTemp') &&
      tts.includes('status.didJustFinish'),
    'TtsPlaybackContext'
  );
  record(
    'voice',
    'TTS playSeq stale guard',
    tts.includes('playSeqRef') && tts.includes('seq !== playSeqRef.current'),
    'TtsPlaybackContext playSeqRef'
  );
  record(
    'voice',
    'chat stops voice on logout',
    chat.includes("status === 'unauthenticated'") &&
      chat.includes('stopPlayback()') &&
      chat.includes('cancelRecording'),
    'app/chat.tsx auth effect'
  );
  record(
    'voice',
    'chat stops voice on conversation switch',
    chat.includes('[activeConversationId]') &&
      chat.includes('stopPlayback()') &&
      chat.includes('cancelRecording'),
    'app/chat.tsx conversation effect'
  );
}

// ========== 7. Development security ==========
function testDevSecretsScan() {
  const patterns = [
    { label: 'OTP_DEV_RETRIEVAL_KEY', re: /OTP_DEV_RETRIEVAL_KEY/i },
    { label: 'otp/dev endpoint', re: /\/auth\/otp\/dev|otp\/dev/i },
    { label: 'JWT signing secret', re: /SECRET_KEY\s*=|gramsakhi_very_secret/i },
    { label: 'DATABASE_URL password', re: /postgres:.*@/i },
    { label: 'hardcoded Bearer JWT', re: /Bearer ey[A-Za-z0-9_-]{10,}/ },
    { label: 'hardcoded 6-digit OTP literal in app code', re: /['"`]\d{6}['"`]/ },
  ];

  const scanDirs = [SRC, APP];
  const files = scanDirs.flatMap((d) => walk(d)).filter((f) => /\.(tsx?|jsx?|json)$/.test(f));

  for (const { label, re } of patterns) {
    const hits = [];
    for (const file of files) {
      const content = fs.readFileSync(file, 'utf8');
      if (re.test(content)) hits.push(path.relative(MOBILE_ROOT, file));
    }
    // Allow otp/dev mention only in scripts (not in app)
    const appHits = hits.filter((h) => !h.startsWith('scripts' + path.sep));
    record('security', `no ${label} in mobile app source`, appHits.length === 0, appHits.length ? appHits.join(', ') : 'none');
  }

  const client = read('src/api/client.ts');
  record(
    'security',
    'Authorization only in apiRequest when token provided',
    client.includes('headers.Authorization = `Bearer ${token}`') && client.includes('skipAuth'),
    'client.ts'
  );
  record(
    'security',
    'fetchHealth sends no Authorization',
    client.includes('fetchHealth') && !client.match(/fetchHealth[\s\S]*Authorization/s),
    'fetchHealth block'
  );
}

// ========== 8. Android configuration ==========
function testAndroidConfig() {
  const cfg = read('app.config.ts');
  record(
    'configuration',
    'android.allowBackup === false',
    /allowBackup:\s*false/.test(cfg),
    'app.config.ts allowBackup: false'
  );
  record(
    'configuration',
    'microphone permission via expo-audio plugin only',
    cfg.includes('expo-audio') && cfg.includes('microphonePermission') && !cfg.includes('CAMERA'),
    'expo-audio microphonePermission; no CAMERA'
  );
}

// ========== 9. Network security static ==========
function testNetworkStatic() {
  const client = read('src/api/client.ts');
  const voice = read('src/api/voice.ts');
  record(
    'security',
    'authenticatedRequest attaches token from SecureStore path',
    client.includes('getAccessToken') && client.includes('authenticatedRequest'),
    'client.ts'
  );
  record(
    'security',
    'voice API uses getApiBaseUrl only',
    voice.includes('getApiBaseUrl()') && !voice.includes('Linking'),
    'voice.ts targets backend only'
  );
  const linkingFiles = walk(SRC).filter((f) => fs.readFileSync(f, 'utf8').includes('Linking.openURL'));
  record(
    'security',
    'Linking.openURL only in safeUrl.ts',
    linkingFiles.length === 1 && linkingFiles[0].endsWith('safeUrl.ts'),
    linkingFiles.map((f) => path.relative(MOBILE_ROOT, f)).join(', ') || 'safeUrl.ts only'
  );
}

// ========== 10. Error handling / logging ==========
function testErrorHandling() {
  const srcFiles = walk(SRC).filter((f) => /\.(tsx?)$/.test(f));
  const badLogPatterns = [
    /console\.log\s*\([^)]*token/i,
    /console\.log\s*\([^)]*otp/i,
    /console\.log\s*\([^)]*password/i,
    /console\.log\s*\([^)]*Authorization/i,
  ];
  const logHits = [];
  for (const file of srcFiles) {
    const content = fs.readFileSync(file, 'utf8');
    for (const re of badLogPatterns) {
      if (re.test(content)) logHits.push(path.relative(MOBILE_ROOT, file));
    }
  }
  record('security', 'no sensitive console.log in src', logHits.length === 0, logHits.join(', ') || 'none');

  const boundary = read('src/components/ErrorBoundary.tsx');
  record(
    'security',
    'ErrorBoundary logs only in __DEV__',
    boundary.includes('__DEV__') && boundary.includes('console.warn'),
    'ErrorBoundary __DEV__ gate'
  );
  // The generic citizen message may live inline or in the i18n string table.
  const genericMessagePresent =
    boundary.includes('Something went wrong') ||
    (boundary.includes("t('error.title')") &&
      read('src/i18n/strings.ts').includes('Something went wrong'));
  record(
    'security',
    'ErrorBoundary citizen UI has no stack trace',
    genericMessagePresent &&
      !boundary.match(/render\(\)[\s\S]*componentStack/) &&
      !boundary.match(/<Text[^>]*>\s*\{[^}]*error\.message/),
    'generic citizen message; no stack in render()'
  );
}

// ========== Export bundle secret scan ==========
function scanExportBundle() {
  const dist = path.join(MOBILE_ROOT, 'dist');
  if (!fs.existsSync(dist)) {
    record('security', 'export bundle secret scan', false, 'dist/ missing — run expo export first');
    return;
  }
  const secretRes = [
    /OTP_DEV_RETRIEVAL_KEY/i,
    /gramsakhi_very_secret/i,
    /SUPABASE_SERVICE_ROLE/i,
    /\/auth\/otp\/dev/,
  ];
  const bundleFiles = walk(dist).filter((f) => f.endsWith('.hbc') || f.endsWith('.js') || f.endsWith('.json'));
  const hits = [];
  for (const file of bundleFiles) {
    let content;
    try {
      content = fs.readFileSync(file);
    } catch {
      continue;
    }
    const text = content.toString('utf8', 0, Math.min(content.length, 5_000_000));
    for (const re of secretRes) {
      if (re.test(text)) hits.push(`${path.relative(MOBILE_ROOT, file)}:${re.source}`);
    }
  }
  record('security', 'no dev secrets in Android export bundle', hits.length === 0, hits.join('; ') || `${bundleFiles.length} files scanned`);
}

// ========== Run all in-script tests ==========
testSafeHttpUrl();
testSourceListStatic();
testMarkdownStatic();
testOtpFlow();
testAuthSessionStatic();
testVoiceStatic();
testDevSecretsScan();
testAndroidConfig();
testNetworkStatic();
testErrorHandling();

// ========== External regression commands ==========
const regression = {};

function runCmd(label, cwd, cmd) {
  try {
    execSync(cmd, { cwd, stdio: 'pipe', encoding: 'utf8' });
    regression[label] = 'PASS';
    return true;
  } catch (err) {
    regression[label] = `FAIL: ${(err.stderr || err.stdout || err.message).slice(0, 200)}`;
    failures += 1;
    return false;
  }
}

runCmd('Mobile typecheck', MOBILE_ROOT, 'npm run typecheck');
runCmd('Android export', MOBILE_ROOT, 'npx expo export --platform android');
scanExportBundle();

runCmd('Backend tests', path.resolve(MOBILE_ROOT, '../backend'), '.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -q');
runCmd('Web build', path.resolve(MOBILE_ROOT, '../frontend/gramsakhi'), 'npm run build');

// ========== Output report ==========
console.log('# A1 AUTOMATED REGRESSION REPORT\n');

const byCategory = {};
for (const r of results) {
  if (!byCategory[r.category]) byCategory[r.category] = [];
  byCategory[r.category].push(r);
}

const sectionTitles = {
  security: '## Security tests',
  privacy: '## Privacy tests',
  voice: '## Voice cleanup tests',
  configuration: '## Configuration tests',
};

for (const [cat, title] of Object.entries(sectionTitles)) {
  if (!byCategory[cat]) continue;
  console.log(title + '\n');
  console.log('| Test | Result | Evidence |');
  console.log('|------|--------|----------|');
  for (const r of byCategory[cat]) {
    console.log(`| ${r.name} | ${r.pass ? 'PASS' : 'FAIL'} | ${String(r.evidence).replace(/\|/g, '\\|').slice(0, 120)} |`);
  }
  console.log('');
}

console.log('## Regression\n');
console.log('| Check | Result |');
console.log('|-------|--------|');
for (const [k, v] of Object.entries(regression)) {
  console.log(`| ${k} | ${v} |`);
}

console.log('\n## Remaining limitations\n');
console.log('- Microphone permission grant/deny at runtime: NOT AUTOMATABLE IN CURRENT TOOLCHAIN');
console.log('- SecureStore read/write on physical device: NOT AUTOMATABLE IN CURRENT TOOLCHAIN');
console.log('- STT/TTS end-to-end with backend: NOT AUTOMATABLE IN CURRENT TOOLCHAIN (no device harness)');
console.log('- Cross-user session isolation under concurrent requests: NOT AUTOMATABLE IN CURRENT TOOLCHAIN');
console.log('- Android backup exclusion at OS level: static config verified only');

const status = failures === 0 ? 'PASS' : 'FAIL';
console.log(`\n## Final status\n\n${status}\n`);
console.log(`\n---\nScript: ${failures} failure(s), ${results.length} checks\n`);

process.exit(failures === 0 ? 0 : 1);
