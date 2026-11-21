// Real local web/API/Postgres entry points; audio and model providers are synthetic stubs.
const assert = require('node:assert/strict')
const { execFileSync, spawn, spawnSync } = require('node:child_process')
const { randomUUID } = require('node:crypto')
const net = require('node:net')
const path = require('node:path')
const { chromium } = require('playwright')
const root = path.resolve(__dirname, '..'), image = 'pgvector/pgvector:0.8.0-pg16'
const run = (command, args, options = {}) => execFileSync(command, args, { cwd: root, encoding: 'utf8', timeout: 60000, ...options })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const port = () => new Promise(resolve => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)) }) })
const start = (cmd, args, options) => { const child = spawn(cmd, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] }); let log = ''; for (const s of [child.stdout, child.stderr]) s.on('data', chunk => { log = (log + chunk).slice(-5000) }); return { child, log: () => log } }
async function wait(check, label) { const end = Date.now() + 30000; while (Date.now() < end) { try { const result = await check(); if (result) return result } catch {} await sleep(100) } throw new Error(`${label} timed out`) }
async function stop(child) { if (!child || child.exitCode !== null) return; child.kill('SIGTERM'); await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(3000)]); if (child.exitCode === null) child.kill('SIGKILL') }

async function main() {
  const session = process.env.AO_SESSION_ID
  if (!session) throw new Error('AO_SESSION_ID required for the disposable database label')
  let db, api, web, browser
  try {
    db = run('docker', ['run', '--pull=never', '--rm', '-d', '--label', `ao.session=${session}`, '--name', `liam-e-voice-${randomUUID().slice(0, 8)}`, '-p', '127.0.0.1::5432', '-e', 'POSTGRES_PASSWORD=test-only', '-e', 'POSTGRES_DB=liam_e_voice_e2e', image]).trim()
    const dbPort = run('docker', ['port', db, '5432/tcp']).trim().match(/^127\.0\.0\.1:(\d+)$/)?.[1]
    if (!dbPort) throw new Error('Database is not confined to loopback')
    await wait(() => spawnSync('docker', ['exec', db, 'pg_isready', '-U', 'postgres', '-d', 'liam_e_voice_e2e'], { stdio: 'ignore' }).status === 0, 'Postgres')
    const [apiPort, webPort] = await Promise.all([port(), port()]), apiOrigin = `http://127.0.0.1:${apiPort}`, webOrigin = `http://127.0.0.1:${webPort}`
    const env = { ...process.env, DATABASE_URL: `postgresql+asyncpg://postgres:test-only@127.0.0.1:${dbPort}/liam_e_voice_e2e`, CORS_ORIGIN: webOrigin, MISTRAL_API_KEY: '', TELEMETRY_ENABLED: 'false', MISTRAL_SECRETS_ENABLED: 'false', MAIL_WORKER_ENABLED: 'false', VITE_API_URL: apiOrigin }
    run('bash', ['tools/db.sh', 'migrate'], { env })
    api = start(path.join(root, '.venv/bin/python'), ['tests/live_voice_e2e_server.py', String(apiPort)], { cwd: root, env })
    web = start(path.join(root, 'node_modules/.bin/vite'), ['--host', '127.0.0.1', '--port', String(webPort), '--strictPort'], { cwd: path.join(root, 'apps/web'), env })
    const conversation = await wait(async () => { const r = await fetch(`${apiOrigin}/api/v1/chat/conversations`); if (!r.ok) return; return (await r.json()).find(item => item.title === 'Synthetic voice test')?.id }, 'API')
    await wait(async () => (await fetch(webOrigin)).ok, 'Web')
    browser = await chromium.launch({ executablePath: process.env.AUDIO_E2E_CHROMIUM || '/usr/bin/chromium', args: ['--use-fake-device-for-media-stream'] })
    const context = await browser.newContext({ locale: 'de-DE', serviceWorkers: 'block' })
    await context.grantPermissions(['microphone'], { origin: webOrigin })
    await context.route('**/*', route => [webOrigin, apiOrigin].includes(new URL(route.request().url()).origin) ? route.continue() : route.abort())
    const page = await context.newPage(), calls = { chat: [], confirms: 0, speech: 0 }
    page.on('response', async response => { const p = new URL(response.url()).pathname; if (p === '/api/v1/audio/live/status') console.log('Live status', response.status(), await response.text().catch(() => 'unreadable')) })
    page.on('request', request => { const p = new URL(request.url()).pathname; if (p === '/api/v1/chat/stream') calls.chat.push(request.postDataJSON()); if (p.endsWith('/confirm')) calls.confirms++; if (p === '/api/v1/audio/live/speech') calls.speech++ })
    await page.addInitScript(() => {
      window.voiceEvidence = { tracks: [], played: 0, interrupted: 0 }
      const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
      navigator.mediaDevices.getUserMedia = async constraints => { const media = await getUserMedia(constraints); window.voiceEvidence.tracks.push(...media.getTracks()); return media }
      const start = AudioBufferSourceNode.prototype.start
      AudioBufferSourceNode.prototype.start = function (...args) { window.voiceEvidence.played++; return start.apply(this, args) }
      const stop = AudioBufferSourceNode.prototype.stop
      AudioBufferSourceNode.prototype.stop = function (...args) { window.voiceEvidence.interrupted++; return stop.apply(this, args) }
    })
    await page.goto(`${webOrigin}/chat/${conversation}`)
    const voice = page.getByRole('button', { name: /Sprachmodus starten|Start voice mode/ });
    try { await voice.waitFor({ timeout: 10000 }) } catch (error) { console.log('Buttons:', await page.locator('button').evaluateAll(nodes => nodes.map(node => node.getAttribute('aria-label') || node.textContent?.trim()).filter(Boolean))); throw error }
    await voice.click()
    await wait(() => calls.chat.length >= 3 && calls.speech >= 3, 'Three voice turns')
    assert.deepEqual(calls.chat.slice(0, 3).map(x => x.text), ['Merk dir: Die Testente ist gelb.', 'Welche Farbe hat die Testente?', 'Ja, mach das'])
    assert.ok(calls.chat.slice(0, 3).every(x => x.conversation_id === conversation))
    assert.equal(calls.confirms, 0)
    assert.equal(await page.getByText('Synthetischer Vorschlag').count(), 1)
    assert.ok(await page.getByRole('button', { name: /als gelesen markieren|mark.*read/i }).count())
    const history = await (await fetch(`${apiOrigin}/api/v1/chat/history?conversation_id=${encodeURIComponent(conversation)}`)).json()
    assert.equal(history.find(message => message.role === 'proposal')?.proposal_status, 'pending')
    assert.ok(await page.evaluate(() => window.voiceEvidence.played >= 3))
    assert.ok(await page.evaluate(() => window.voiceEvidence.interrupted >= 1))
    await page.getByRole('button', { name: /Sprachmodus beenden|End voice mode/ }).click()
    assert.ok(await page.evaluate(() => window.voiceEvidence.tracks.every(track => track.readyState === 'ended')))
    const turns = calls.chat.length; await sleep(1000); assert.equal(calls.chat.length, turns)
    console.log('Local synthetic integration passed: three text-event stubs, PCM tone playback, same conversation, no confirmation, stopped tracks.')
  } catch (error) { if (api) console.error(api.log()); if (web) console.error(web.log()); throw error }
  finally { await browser?.close(); await Promise.all([stop(api?.child), stop(web?.child)]); if (db) run('docker', ['stop', '-t', '2', db], { stdio: 'ignore' }) }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
