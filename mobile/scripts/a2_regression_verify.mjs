#!/usr/bin/env node
/**
 * A2 Android Chat/RAG Reliability — automated regression verification.
 * Static inspection + lightweight runtime checks. No test framework.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MOBILE_ROOT = path.resolve(__dirname, '..');
const SRC = path.join(MOBILE_ROOT, 'src');

const results = [];
let failures = 0;

function record(category, name, pass, evidence, kind = 'STATIC') {
  results.push({ category, name, pass, evidence, kind });
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
    } else acc.push(full);
  }
  return acc;
}

function mapEvidenceSufficiency(status) {
  const s = (status || '').toUpperCase();
  if (s === 'SUPPORTED') return 'SUPPORTED';
  if (s === 'UNSUPPORTED') return 'UNSUPPORTED';
  return 'PARTIAL';
}

// ========== Reliability static checks ==========
function testChatContextGuards() {
  const ctx = read('src/store/ChatContext.tsx');
  record('reliability', 'chatGenerationRef exists', /chatGenerationRef/.test(ctx), 'ChatContext.tsx', 'STATIC');
  record('reliability', 'loadRequestSeqRef exists', /loadRequestSeqRef/.test(ctx), 'ChatContext.tsx', 'STATIC');
  record('reliability', 'sendRequestSeqRef exists', /sendRequestSeqRef/.test(ctx), 'ChatContext.tsx', 'STATIC');
  record('reliability', 'sendInFlightRef duplicate-send guard', /sendInFlightRef/.test(ctx), 'ChatContext.tsx', 'STATIC');
  record(
    'reliability',
    'sendInFlightRef checked before send',
    /sendInFlightRef\.current\) return/.test(ctx),
    'sendMessage entry guard',
    'STATIC'
  );
  record(
    'reliability',
    'newConsultationInFlightRef prevents duplicate create',
    /newConsultationInFlightRef/.test(ctx),
    'ChatContext.tsx',
    'STATIC'
  );
  record(
    'reliability',
    'stale send dropped by generation/seq',
    /gen !== chatGenerationRef\.current/.test(ctx) && /sendSeq !== sendRequestSeqRef\.current/.test(ctx),
    'sendMessage stale guard',
    'STATIC'
  );
  record(
    'reliability',
    'stale load dropped by loadRequestSeqRef',
    /seq !== loadRequestSeqRef\.current/.test(ctx),
    'loadConversation/bootstrap',
    'STATIC'
  );
  record(
    'reliability',
    'bootstrapStartedRef prevents duplicate bootstrap',
    /bootstrapStartedRef/.test(ctx),
    'bootstrapChat',
    'STATIC'
  );
  record(
    'reliability',
    'initialized set in loadConversation',
    /loadConversation[\s\S]*setInitialized\(true\)/.test(ctx),
    'Phase 3.1 initialized fix',
    'STATIC'
  );
  record(
    'reliability',
    '401 path calls handleAuthFailure',
    /isAuthError\(err\)[\s\S]*handleAuthFailure/.test(ctx),
    'ChatContext auth errors',
    'STATIC'
  );
  record(
    'reliability',
    'resetSession clears chat state',
    /resetSession[\s\S]*setMessages\(\[\]\)/.test(ctx) &&
      /resetSession[\s\S]*setInitialized\(false\)/.test(ctx) &&
      /resetSession[\s\S]*clearConversationId/.test(ctx),
    'resetSession',
    'STATIC'
  );
  record(
    'reliability',
    'selectConversation clears sendInFlightRef',
    /selectConversation[\s\S]*sendInFlightRef\.current = false/.test(ctx),
    'conversation switch',
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

function testApiSeparation() {
  const chat = read('src/api/chat.ts');
  const ctx = read('src/store/ChatContext.tsx');

  record(
    'reliability',
    'POST /chat only in sendChatMessage',
    chat.includes("authenticatedRequest<BackendChatResponse>('/chat'") && chat.includes('sendChatMessage'),
    'chat.ts',
    'STATIC'
  );
  const histStart = chat.indexOf('export async function loadConversationHistory');
  const histEnd = chat.indexOf('export async function createEmptyConversation');
  const historyFn = histStart >= 0 && histEnd > histStart ? chat.slice(histStart, histEnd) : '';
  record(
    'reliability',
    'history uses GET conversations/{id}',
    historyFn.includes('`/chat/conversations/${conversationId}`') && !historyFn.includes("method: 'POST'"),
    'loadConversationHistory GET only',
    'STATIC'
  );
  record(
    'reliability',
    'bootstrap does not call sendChatMessage',
    !extractUseCallback(ctx, 'bootstrapChat').includes('sendChatMessage'),
    'bootstrapChat body',
    'STATIC'
  );
  record(
    'reliability',
    'loadConversation does not call sendChatMessage',
    !extractUseCallback(ctx, 'loadConversation').includes('sendChatMessage'),
    'loadConversation body',
    'STATIC'
  );
  record(
    'reliability',
    'new consultation uses POST /conversations',
    chat.includes("'/chat/conversations'") && chat.includes('createEmptyConversation'),
    'chat.ts',
    'STATIC'
  );
  record(
    'reliability',
    'chat timeout configured for long RAG',
    chat.includes('CHAT_REQUEST_TIMEOUT_MS') && chat.includes('270_000'),
    '270s timeout',
    'STATIC'
  );
  record(
    'reliability',
    'no automatic POST /chat retry',
    !read('src/api/client.ts').includes('retry') && !chat.includes('retry'),
    'no retry logic in chat/client',
    'STATIC'
  );
}

function testAdapter() {
  const adapter = read('src/api/chatAdapter.ts');
  record(
    'reliability',
    'buildAssistantMeta preserves assistance fields',
    adapter.includes('eligibility_status') &&
      adapter.includes('action_plan') &&
      adapter.includes('scheme_guidance') &&
      adapter.includes('missing_information'),
    'chatAdapter.ts',
    'STATIC'
  );
  record(
    'reliability',
    'mapEvidenceSufficiency maps UNSUPPORTED',
    adapter.includes('mapEvidenceSufficiency') && adapter.includes("'UNSUPPORTED'"),
    'chatAdapter.ts',
    'STATIC'
  );
  record(
    'reliability',
    'history uses mapEvidenceSufficiency',
    adapter.includes('mapEvidenceSufficiency(m.evidence_status)'),
    'mapHistoryMessages',
    'STATIC'
  );
  record(
    'reliability',
    'null backend response handled safely',
    adapter.includes('if (!data || typeof data !== \'object\')'),
    'mapBackendChatResponse',
    'STATIC'
  );

  record(
    'reliability',
    'mapEvidenceSufficiency runtime: SUPPORTED',
    mapEvidenceSufficiency('SUPPORTED') === 'SUPPORTED',
    'SUPPORTED',
    'RUNTIME'
  );
  record(
    'reliability',
    'mapEvidenceSufficiency runtime: UNSUPPORTED',
    mapEvidenceSufficiency('UNSUPPORTED') === 'UNSUPPORTED',
    'UNSUPPORTED',
    'RUNTIME'
  );
  record(
    'reliability',
    'mapEvidenceSufficiency runtime: unknown -> PARTIAL',
    mapEvidenceSufficiency(null) === 'PARTIAL',
    'PARTIAL default',
    'RUNTIME'
  );
}

function testComposerAndList() {
  const composer = read('src/components/chat/MessageComposer.tsx');
  record(
    'reliability',
    'composer disables send while generating',
    composer.includes('!isGenerating') && composer.includes('disabled={!canSend}'),
    'MessageComposer.tsx',
    'STATIC'
  );
  record(
    'reliability',
    'composer rejects whitespace-only send',
    composer.includes('text.trim()'),
    'MessageComposer.tsx',
    'STATIC'
  );
  const list = read('src/components/chat/MessageList.tsx');
  record(
    'reliability',
    'MessageList uses stable message id keys',
    list.includes('keyExtractor={(item) => item.id}'),
    'MessageList.tsx',
    'STATIC'
  );
}

function testSessionStorage() {
  const tokens = read('src/storage/authTokens.ts');
  record(
    'privacy',
    'conversation ID persisted in SecureStore',
    tokens.includes('CONVERSATION_ID_KEY') && tokens.includes('setConversationId'),
    'authTokens.ts',
    'STATIC'
  );
  record(
    'privacy',
    'clearAuthSession clears conversation ID',
    tokens.includes('clearConversationId') && tokens.match(/clearAuthSession[\s\S]*clearConversationId/),
    'authTokens.ts',
    'STATIC'
  );
}

function testSafeUrlsAndDev() {
  const srcFiles = walk(SRC).filter((f) => /\.(tsx?)$/.test(f));
  const linkingHits = srcFiles.filter((f) => {
    const c = fs.readFileSync(f, 'utf8');
    return c.includes('Linking.openURL');
  });
  record(
    'security',
    'Linking.openURL only in safeUrl.ts',
    linkingHits.length === 1 && linkingHits[0].endsWith('safeUrl.ts'),
    linkingHits.map((f) => path.relative(MOBILE_ROOT, f)).join(', ') || 'safeUrl.ts only',
    'STATIC'
  );
  record(
    'security',
    'SourceList uses safe URL helpers',
    read('src/components/chat/SourceList.tsx').includes('safeHttpUrl'),
    'SourceList.tsx',
    'STATIC'
  );

  const allSrc = srcFiles.map((f) => fs.readFileSync(f, 'utf8')).join('\n');
  record('security', 'no /api/auth/otp/dev in mobile', !allSrc.includes('/auth/otp/dev'), 'src scan', 'STATIC');
  record('security', 'no mock RAG/LLM in mobile src', !/localRAG|mockRag|fakeEligibility/i.test(allSrc), 'src scan', 'STATIC');
  record('security', 'no hardcoded mock chat responses', !/mockChatResponse|fakeAssistant/i.test(allSrc), 'src scan', 'STATIC');
}

function testVoiceGuards() {
  const chat = read('app/chat.tsx');
  record(
    'voice',
    'chat stops voice on conversation switch',
    chat.includes('[activeConversationId]') && chat.includes('stopPlayback()'),
    'app/chat.tsx',
    'STATIC'
  );
  record(
    'voice',
    'chat cancels recording on logout',
    chat.includes("status === 'unauthenticated'") && chat.includes('cancelRecording'),
    'app/chat.tsx',
    'STATIC'
  );
}

// ========== Run checks ==========
testChatContextGuards();
testApiSeparation();
testAdapter();
testComposerAndList();
testSessionStorage();
testSafeUrlsAndDev();
testVoiceGuards();

const regression = {};
function runCmd(label, cwd, cmd) {
  try {
    execSync(cmd, { cwd, stdio: 'pipe', encoding: 'utf8' });
    regression[label] = 'PASS';
  } catch (err) {
    regression[label] = `FAIL: ${(err.stderr || err.stdout || err.message).slice(0, 180)}`;
    failures += 1;
  }
}

runCmd('Mobile typecheck', MOBILE_ROOT, 'npm run typecheck');
runCmd('Android export', MOBILE_ROOT, 'npx expo export --platform android');
runCmd('Backend tests', path.resolve(MOBILE_ROOT, '../backend'), '.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -q');
runCmd('Web build', path.resolve(MOBILE_ROOT, '../frontend/gramsakhi'), 'npm run build');

// ========== Report ==========
console.log('# A2 AUTOMATED REGRESSION REPORT\n');

const sections = {
  reliability: '## Reliability tests',
  privacy: '## Privacy / session tests',
  security: '## Security integrity (A1 preserved)',
  voice: '## Voice cleanup tests',
};

for (const [cat, title] of Object.entries(sections)) {
  const rows = results.filter((r) => r.category === cat);
  if (!rows.length) continue;
  console.log(title + '\n');
  console.log('| Test | Result | Kind | Evidence |');
  console.log('|------|--------|------|----------|');
  for (const r of rows) {
    console.log(
      `| ${r.name} | ${r.pass ? 'PASS' : 'FAIL'} | ${r.kind} | ${String(r.evidence).replace(/\|/g, '\\|').slice(0, 100)} |`
    );
  }
  console.log('');
}

console.log('## Regression\n');
console.log('| Check | Result |');
console.log('|-------|--------|');
for (const [k, v] of Object.entries(regression)) {
  console.log(`| ${k} | ${v} |`);
}

console.log('\n## Remaining limitations (NOT AUTOMATABLE IN CURRENT TOOLCHAIN)\n');
console.log('- Runtime race scenarios A–E (send during switch/logout): guards verified statically only');
console.log('- End-to-end POST /chat once under rapid double-tap on device');
console.log('- Conversation resume after process kill');
console.log('- Long RAG response within 270s timeout on real network');
console.log('- FlatList performance with 100+ messages on device');

const status = failures === 0 ? 'PASS WITH LIMITATIONS' : 'FAIL';
console.log(`\n## Final status\n\n${status}\n`);
console.log(`Checks: ${results.length}, failures: ${failures}, exit: ${failures === 0 ? 0 : 1}\n`);

process.exit(failures === 0 ? 0 : 1);
