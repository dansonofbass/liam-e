// Run the browser against the real web app and API with disposable local fixtures.
const assert = require("node:assert/strict");
const { execFileSync, spawn, spawnSync } = require("node:child_process");
const { randomUUID } = require("node:crypto");
const net = require("node:net");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const image = "pgvector/pgvector:0.8.0-pg16";
const engine = ["docker", "podman"].find(candidate =>
  spawnSync(candidate, ["image", "inspect", image], { stdio: "ignore" }).status === 0
);
const timeout = 15_000;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function run(command, args, options = {}) {
  return execFileSync(command, args, { cwd: root, encoding: "utf8", timeout: 60_000, ...options });
}

function localPort() {
  return new Promise((resolve, reject) => {
    const listener = net.createServer();
    listener.on("error", reject);
    listener.listen(0, "127.0.0.1", () => {
      const { port } = listener.address();
      listener.close(() => resolve(port));
    });
  });
}

async function waitFor(check, label, process) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline && (!process || process.exitCode === null)) {
    try { if (await check()) return; } catch { /* The local service is still starting. */ }
    await sleep(100);
  }
  throw new Error(label + " did not become ready");
}

function start(command, args, options) {
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  let logs = "";
  for (const stream of [child.stdout, child.stderr]) {
    stream.setEncoding("utf8");
    stream.on("data", chunk => { logs = (logs + chunk).slice(-6000); });
  }
  return { child, logs: () => logs };
}

async function stop(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise(resolve => {
    const timer = setTimeout(() => child.kill("SIGKILL"), 3000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
    child.kill("SIGTERM");
  });
}

async function testSpeechInput(page, webOrigin, conversation) {
  const calls = { upload: 0, chat: [], speech: [] };
  page.on("request", request => {
    const url = new URL(request.url());
    if (request.method() !== "POST") return;
    if (url.pathname === "/api/v1/audio/transcriptions") calls.upload++;
    if (url.pathname === "/api/v1/chat/stream") calls.chat.push(request.postDataJSON());
    if (url.pathname === "/api/v1/audio/speech") calls.speech.push(request.postDataJSON());
  });
  await page.addInitScript(() => {
    window.audioFixture = { tracks: [], recordings: [], playback: [], revoked: [], deferPermission: false };
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async options => {
      const stream = await getUserMedia(options);
      window.audioFixture.tracks.push(...stream.getTracks());
      if (window.audioFixture.deferPermission) {
        await new Promise(resolve => { window.audioFixture.allowPermission = resolve; });
      }
      return stream;
    };
    const start = MediaRecorder.prototype.start;
    MediaRecorder.prototype.start = function (...args) {
      const current = { packets: 0 };
      window.audioFixture.recordings.push(current);
      this.addEventListener("dataavailable", event => {
        if (event.data.size) current.packets++;
      });
      return start.apply(this, args);
    };
    const nativeRevoke = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = url => {
      window.audioFixture.revoked.push(url);
      nativeRevoke(url);
    };
    window.Audio = new Proxy(window.Audio, {
      construct(target, args) {
        const media = Reflect.construct(target, args);
        const playback = { media, url: args[0], played: false, ended: false };
        window.audioFixture.playback.push(playback);
        media.addEventListener("playing", () => { playback.played = true; });
        media.addEventListener("ended", () => { playback.ended = true; });
        return media;
      },
    });
  });

  await page.goto(webOrigin + "/chat/" + conversation);
  const draft = page.locator(".le-composer textarea");
  const button = name => page.getByRole("button", { name, exact: true });
  const record = button("Sprache aufnehmen");
  await record.waitFor();
  await draft.fill("Vorhandener Entwurf.");

  // Abandon a permission prompt before the browser supplies its stream.
  await page.evaluate(() => { window.audioFixture.deferPermission = true; });
  await record.click();
  await page.waitForFunction(() => Boolean(window.audioFixture.allowPermission));
  await button("Aufnahme abbrechen").click();
  await page.evaluate(() => {
    window.audioFixture.deferPermission = false;
    window.audioFixture.allowPermission();
  });
  await page.waitForFunction(() => window.audioFixture.tracks.length === 1 &&
    window.audioFixture.tracks.every(track => track.readyState === "ended"));

  await record.click();
  await button("Aufnahme verwerfen").click();
  await page.waitForFunction(() => window.audioFixture.tracks.length === 2 &&
    window.audioFixture.tracks.every(track => track.readyState === "ended"));
  assert.equal(calls.upload, 0);
  assert.equal(await draft.inputValue(), "Vorhandener Entwurf.");

  // Simulate the browser visibility notification while using a real recorder and stream.
  const beforeHidden = await page.evaluate(() => window.audioFixture.recordings.length);
  await record.click();
  await button("Beenden und übertragen").waitFor();
  await page.waitForFunction(previous => window.audioFixture.recordings.length > previous &&
    window.audioFixture.recordings.at(-1).packets > 0, beforeHidden);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await button("Aufnahme übertragen").waitFor();
  assert.equal(calls.upload, 0);
  assert(await page.evaluate(() => window.audioFixture.tracks.every(track => track.readyState === "ended")));
  await page.evaluate(() => {
    delete document.hidden;
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await button("Aufnahme verwerfen").click();

  const before = await page.evaluate(() => window.audioFixture.recordings.length);
  await record.click();
  const upload = button("Beenden und übertragen");
  await upload.waitFor();
  await page.waitForFunction(previous => window.audioFixture.recordings.length > previous &&
    window.audioFixture.recordings.at(-1).packets > 0, before);
  assert.equal(await button("Senden").isDisabled(), true);
  assert.equal(await button("Mistral Medium").isDisabled(), true);
  assert.equal(calls.upload, 0);
  assert.equal(calls.chat.length, 0);

  await draft.fill("Vorhandener Entwurf mit Ergänzung.");
  await upload.click();
  await page.waitForFunction(() => document.querySelector(".le-composer textarea").value ===
    "Vorhandener Entwurf mit Ergänzung.\n\nEin synthetischer Satz.");
  assert.equal(calls.upload, 1);
  assert.equal(calls.chat.length, 0);
  assert.equal(await page.evaluate(() => window.audioFixture.tracks.every(track =>
    track.readyState === "ended")), true);

  await draft.fill("Bearbeiteter Testentwurf.");
  await button("Senden").click();
  await page.getByText("Hier ist die", { exact: false }).last().waitFor();
  assert.equal(calls.chat.length, 1);
  assert.equal(calls.chat[0].text, "Bearbeiteter Testentwurf.");
  assert.equal(calls.chat[0].conversation_id, conversation);
  console.log("STT e2e passed: Chromium recording, permission cancellation, discard, background track cleanup, explicit upload, draft editing and manual send.");
  return calls;
}

async function testSpeechOutput(page, calls, conversation) {
  const reply = page.locator(".le-chat-entry").filter({ hasText: "Hier ist die synthetische Antwort." });
  const read = reply.getByRole("button", { name: "Antwort vorlesen", exact: true });
  await read.waitFor();
  assert.equal(calls.speech.length, 0);
  const response = page.waitForResponse(item => new URL(item.url()).pathname === "/api/v1/audio/speech");
  await read.click();
  const audio = await response;
  assert.equal(audio.status(), 200);
  assert.equal(audio.headers()["content-type"], "audio/mpeg");
  assert.equal(audio.headers()["cache-control"], "no-store");
  await page.waitForFunction(() => window.audioFixture.playback[0]?.played);
  await reply.getByText("Vorlesen beendet.", { exact: true }).waitFor();
  assert(await page.evaluate(() => {
    const playback = window.audioFixture.playback[0];
    return playback.ended && window.audioFixture.revoked.includes(playback.url);
  }));
  assert.equal(calls.speech.length, 1);
  assert.equal(calls.speech[0].conversation_id, conversation);
  assert.equal(calls.speech[0].message_id, (await reply.getAttribute("id")).replace(/^message-/, ""));
  assert.deepEqual(Object.keys(calls.speech[0]).sort(), ["conversation_id", "message_id"]);

  await read.click();
  await page.waitForFunction(() => window.audioFixture.playback[1]?.played);
  await page.getByRole("button", { name: "Sprache aufnehmen", exact: true }).click();
  await page.waitForFunction(() => {
    const playback = window.audioFixture.playback[1];
    return playback.media.paused && window.audioFixture.revoked.includes(playback.url);
  });
  await page.getByRole("button", { name: "Aufnahme verwerfen", exact: true }).click();
  assert.equal(calls.speech.length, 2);

  await read.click();
  await page.waitForFunction(() => window.audioFixture.playback[2]?.played);
  await reply.getByRole("button", { name: "Vorlesen beenden", exact: true }).click();
  await page.waitForFunction(() => {
    const playback = window.audioFixture.playback[2];
    return playback.media.paused && window.audioFixture.revoked.includes(playback.url);
  });
  assert.equal(calls.speech.length, 3);

  // Hold a successful server response until the user cancels the download.
  let intercepted;
  const routePattern = "**/api/v1/audio/speech";
  const hold = route => {
    if (route.request().method() !== "POST") return route.fallback();
    intercepted = route;
  };
  await page.route(routePattern, hold);
  await read.click();
  await waitFor(() => intercepted, "Intercepted speech request");
  const late = await intercepted.fetch({ timeout });
  assert.equal(late.status(), 200);
  await reply.getByRole("button", { name: "Vorlesen beenden", exact: true }).click();
  // Chromium may already have cancelled this request when the fixture tries to deliver it.
  await intercepted.fulfill({ response: late }).catch(() => undefined);
  await page.unroute(routePattern, hold);
  await read.waitFor();
  assert.equal(await page.evaluate(() => window.audioFixture.playback.length), 3);

  await read.click();
  await page.waitForFunction(() => window.audioFixture.playback[3]?.played);
  await page.locator(".le-side .le-conv").filter({ hasText: "Newsletter aufräumen" }).click();
  await page.waitForFunction(id => !location.pathname.endsWith("/" + id), conversation);
  await page.waitForFunction(() => {
    const playback = window.audioFixture.playback[3];
    return playback.media.paused && window.audioFixture.revoked.includes(playback.url);
  });
  assert.equal(calls.speech.length, 5);
  assert.equal(calls.chat.length, 1);
  console.log("TTS e2e passed: saved assistant reply, MP3 playback, stop, late-response cancellation, microphone interruption and conversation change.");
}

async function testOwnerDeviceCheck(page, webOrigin, calls) {
  const before = { upload: calls.upload, chat: calls.chat.length, speech: calls.speech.length };
  let probeUploads = 0;
  const countProbeUpload = request => {
    if (new URL(request.url()).pathname === "/api/v1/audio/device-test/recording") probeUploads++;
  };
  page.on("request", countProbeUpload);
  try {
    await page.goto(webOrigin + "/audio-device-test");
    const button = name => page.getByRole("button", { name, exact: true });
    const draft = page.getByRole("textbox", { name: "Editierbarer Beispielentwurf" });
    await page.getByRole("heading", { name: "Audio-Geräteprobe" }).waitFor();
    await draft.fill("Mein vorheriger Testtext.");

    await button("Sprache aufnehmen").click();
    await page.waitForFunction(() => window.audioFixture.recordings[0]?.packets > 0);
    assert.equal(probeUploads, 0);
    await button("Beenden und übertragen").click();
    await page.getByText("Aufnahme geprüft. Du kannst den Beispielentwurf bearbeiten.").waitFor();
    assert.equal(await draft.inputValue(), "Mein vorheriger Testtext.\n\nEine gelbe Ente schwimmt im Teich.");
    await draft.fill("Editiert nach der Geräteprobe.");
    assert.equal(await draft.inputValue(), "Editiert nach der Geräteprobe.");
    await page.waitForFunction(() => window.audioFixture.tracks.every(track => track.readyState === "ended"));

    await button("Beispielsatz vorlesen").click();
    await page.waitForFunction(() => window.audioFixture.playback[0]?.played && window.audioFixture.playback[0]?.ended);
    assert.equal(probeUploads, 1);
    assert.deepEqual({ upload: calls.upload, chat: calls.chat.length, speech: calls.speech.length }, before);
    console.log("Device check e2e passed: real WebM upload, editable test draft, real bundled speech playback and no chat or inference request.");
  } finally {
    page.off("request", countProbeUpload);
  }
}

async function main() {
  if (!engine) throw new Error("Install the local pgvector image before running this test");
  let db;
  let api;
  let web;
  let browser;
  try {
    db = run(engine, ["run", "--pull=never", "--rm", "-d", "--name", "liam-e-audio-" + randomUUID().slice(0, 8),
      "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=test-only", "-e", "POSTGRES_DB=liam_e_audio_e2e", image]).trim();
    const port = run(engine, ["port", db, "5432/tcp"]).trim().match(/^127\.0\.0\.1:(\d+)$/)?.[1];
    if (!port) throw new Error("Expected an isolated loopback database");
    await waitFor(() => spawnSync(engine, ["exec", db, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "liam_e_audio_e2e"],
      { stdio: "ignore" }).status === 0, "Database");
    const [apiPort, webPort] = await Promise.all([localPort(), localPort()]);
    const apiOrigin = "http://127.0.0.1:" + apiPort;
    const webOrigin = "http://127.0.0.1:" + webPort;
    const env = {
      ...process.env,
      DATABASE_URL: "postgresql+asyncpg://postgres:test-only@127.0.0.1:" + port + "/liam_e_audio_e2e",
      CORS_ORIGIN: webOrigin,
      MISTRAL_API_KEY: "",
      TELEMETRY_ENABLED: "false",
      MISTRAL_SECRETS_ENABLED: "false",
      MAIL_WORKER_ENABLED: "false",
      VITE_API_URL: apiOrigin,
    };
    run("bash", ["tools/db.sh", "migrate"], { env });
    api = start(path.join(root, ".venv/bin/python"), ["tests/audio_e2e_server.py", String(apiPort)], { cwd: root, env });
    web = start(path.join(root, "node_modules/.bin/vite"), ["--host", "127.0.0.1", "--port", String(webPort), "--strictPort"],
      { cwd: path.join(root, "apps/web"), env });
    let conversation;
    await waitFor(async () => {
      const response = await fetch(apiOrigin + "/api/v1/chat/conversations");
      if (!response.ok) return false;
      const messages = await response.json();
      conversation = messages.find(item => item.title === "Was ist heute wichtig?")?.id;
      return Boolean(conversation);
    }, "Seeded API", api.child);
    await waitFor(async () => (await fetch(webOrigin)).ok, "Web app", web.child);

    browser = await chromium.launch({
      executablePath: process.env.AUDIO_E2E_CHROMIUM,
      args: ["--use-fake-device-for-media-stream"],
    });
    const context = await browser.newContext({ locale: "de-DE", serviceWorkers: "block" });
    await context.grantPermissions(["microphone"], { origin: webOrigin });
    await context.route("**/*", route => [webOrigin, apiOrigin].includes(new URL(route.request().url()).origin)
      ? route.continue() : route.abort());
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const calls = await testSpeechInput(page, webOrigin, conversation);
    await testSpeechOutput(page, calls, conversation);
    await testOwnerDeviceCheck(page, webOrigin, calls);
  } catch (error) {
    if (api) console.error(api.logs());
    if (web) console.error(web.logs());
    throw error;
  } finally {
    await browser?.close();
    await Promise.all([stop(api?.child), stop(web?.child)]);
    if (db) run(engine, ["stop", "-t", "2", db], { stdio: "ignore" });
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
