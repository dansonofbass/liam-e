// Record synthetic microphone input with Chromium and check the resulting containers locally.
const { spawnSync } = require("node:child_process");
const { mkdtemp, rm, writeFile } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const origin = "http://localhost";
const recorderTypes = [null, "audio/webm;codecs=opus", "audio/mp4;codecs=mp4a.40.2"];
const containers = new Map([["audio/webm", "webm"], ["audio/mp4", "mp4"]]);

async function record(page, requestedMime) {
  return page.evaluate(async (mimeType) => {
    if (mimeType && !MediaRecorder.isTypeSupported(mimeType)) {
      return { status: "unsupported" };
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const tracks = stream.getTracks();
    const chunks = [];
    let stopTimer;
    let deadline;
    try {
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      await new Promise((resolve, reject) => {
        recorder.addEventListener("dataavailable", ({ data }) => chunks.push(data));
        recorder.addEventListener("stop", resolve, { once: true });
        recorder.addEventListener("error", reject, { once: true });
        recorder.start();
        stopTimer = setTimeout(() => recorder.stop(), 1500);
        deadline = setTimeout(() => reject(new Error("Recording timed out")), 5000);
      });
    } finally {
      clearTimeout(stopTimer);
      clearTimeout(deadline);
      tracks.forEach((track) => track.stop());
    }

    const actualMime = chunks.find((chunk) => chunk.size)?.type ?? "";
    const blob = new Blob(chunks);
    if (!blob.size || blob.size > 256 * 1024) {
      return { status: "unexpected_recording_size", actualMime, bytes: blob.size };
    }
    return {
      status: "recorded",
      actualMime,
      tracksStopped: tracks.length === 1 && tracks.every((track) => track.readyState === "ended"),
      audio: Array.from(new Uint8Array(await blob.arrayBuffer())),
    };
  }, requestedMime);
}

async function validate(scratch, mime, audio) {
  const kind = containers.get(mime.split(";")[0]);
  if (!kind) return { status: "unexpected_container" };

  await writeFile(join(scratch, `recorded.${kind}`), Buffer.from(audio), { mode: 0o600 });
  const result = spawnSync(
    "python3",
    [join(__dirname, "audio_provider_probe.py"), kind, scratch, "--validate-container"],
    { encoding: "utf8", timeout: 10_000, maxBuffer: 16_384 },
  );
  if (result.status !== 0 && result.status !== 1) return { status: "validator_failed" };
  return JSON.parse(result.stdout);
}

async function main(executablePath) {
  const { chromium } = require("playwright");
  const playwrightVersion = require("playwright/package.json").version;
  const scratch = await mkdtemp(join(tmpdir(), "liam-e-audio-"));
  let browser;
  try {
    browser = await chromium.launch({
      executablePath,
      args: ["--use-fake-device-for-media-stream"],
    });
    const context = await browser.newContext({ serviceWorkers: "block" });
    await context.route("**/*", (route) => {
      if (route.request().url() === origin + "/") {
        return route.fulfill({ contentType: "text/html", body: "<title>Audio probe</title>" });
      }
      return route.abort();
    });
    await context.grantPermissions(["microphone"], { origin });
    const page = await context.newPage();
    await page.goto(origin, { timeout: 5000 });
    const secureContext = await page.evaluate(() => window.isSecureContext);

    for (const requestedMime of recorderTypes) {
      const { audio, ...recording } = await record(page, requestedMime);
      const validation = audio ? await validate(scratch, recording.actualMime, audio) : null;
      console.log(JSON.stringify({
        browser: browser.version(),
        playwright: playwrightVersion,
        secureContext,
        requestedMime,
        ...recording,
        validation,
      }));
      if (!secureContext || (recording.status !== "unsupported" &&
        (!recording.tracksStopped || validation?.status !== "accepted"))) {
        process.exitCode = 1;
      }
    }
  } finally {
    try {
      await browser?.close();
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
}

if (process.argv.length > 3) {
  console.error("Usage: node tools/audio_browser_probe.cjs [chromium-executable]");
  process.exitCode = 2;
} else {
  main(process.argv[2]).catch(() => {
    console.error("The local browser probe failed. Check Chromium, Playwright, Python and FFmpeg.");
    process.exitCode = 1;
  });
}
