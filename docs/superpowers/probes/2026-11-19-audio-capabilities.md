# Audio capability probe on 2026-11-19 CET

[#26](https://github.com/plagor44-ux/liam-e/issues/26) ran against the model configuration for
main at 3388f19. The installed SDK was mistralai 3.7.0. The probe used HTTPX 0.28.1 and the app's
local workspace credential resolver. Each call sent a single short German synthetic sample to
the official provider API. The isolated process kept the credential in memory. Samples and
temporary output stayed in local scratch space except for the direct inference requests.

| Capability and method | UTC time on 18 Nov | Result |
| --- | --- | --- |
| STT, multipart PCM WAV, `POST /v1/audio/transcriptions` with `voxtral-mini-transcribe-3` and `language=de` | 23:08:41 | HTTP 200 in 454 ms. 88,812 B, 2.013 s. Response named `voxtral-mini-transcribe-3` and the normalized transcript matched. |
| STT, Chromium WebM/Opus, same endpoint and model | 23:11:41 | HTTP 200 in 456 ms. 36,038 B, 2.220 s of decoded audio. Same returned model and transcript match. |
| STT, locally encoded fragmented MP4/AAC, same endpoint and model | 23:12:03 | HTTP 200 in 342 ms. 18,464 B, 2.090 s of decoded audio. Same returned model and transcript match. |
| TTS, JSON `POST /v1/audio/speech` with `voxtral-mini-tts-3-0`, German preset `voice_481` and `response_format=mp3` | 23:08:08 | HTTP 200 in 607 ms. The decoded response had 18,576 B of MP3, mono at 22,050 Hz. The response did not identify the resolved model revision. |

The STT response reported the requested model identifier without a separate version suffix.
The SDK has methods for both calls. This run verifies the documented HTTP contracts with the
workspace credential. The measured TTS sample rate was 22,050 Hz, while the general provider
format docs describe 24 kHz.
[File transcription](https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-files),
[speech generation](https://docs.mistral.ai/studio/audio/text-to-speech/generate-speech),
[preset voices](https://docs.mistral.ai/studio/audio/text-to-speech/voices),
[audio formats](https://docs.mistral.ai/studio/audio/specs-and-limits/audio-formats).

## Browser and container evidence

| Check | Evidence |
| --- | --- |
| Chromium 157.0.8103.38 on Linux, Playwright 1.62.0 | Real browser muxer fed by the eSpeak WAV through a fake microphone. One 48 kHz mono track used a programmatic permission grant. Both a default recorder and an explicit `audio/webm;codecs=opus` recorder wrote actual WebM/Opus. This Chromium build rejected the explicit AAC MIME declaration. Closing the probe stopped the fake track. |
| Local Chromium permission and embedding | Loopback was a secure context. The top-level page reported `prompt`, the cross-origin frame without microphone delegation reported `denied`, and the delegated frame reported `prompt`. Real prompts, devices and Studio framing remain open. |
| Chromium MP3 playback | An actual button click with active user activation played the provider MP3 to the `ended` event in headless Chromium with volume set to zero. FFprobe measured a 2.480 s format duration, while the browser exposed 2.691 s. |
| iOS Safari | **BLOCKED** without an iOS device. WebKit documents MP4/AAC in the original recorder implementation and WebM/Opus from Safari 18.4. Verify actual recorder bytes, permissions and playback inside the intended Studio frame on the supported iOS versions. The local MP4 fixture is codec evidence only. |

Microphone access requires a secure context and user permission. A cross-origin frame also
depends on both the embedding policy and document policy.
[Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/),
[WebKit MediaRecorder](https://webkit.org/blog/11353/),
[WebKit Safari 18.4](https://webkit.org/blog/16574/webkit-features-in-safari-18-4/).

### Candidate duration check

FFmpeg/FFprobe 9.0.2 ran only as offline command-line tools on synthetic local fixtures. The
probe checked the file byte count before invoking a demuxer, checked the WebM EBML DocType or
MP4 `ftyp` header, required exactly one audio stream with the declared container's codec,
and compared decoded sample count with container duration when present. For the decoded count
it resampled to 48 kHz mono signed 16-bit PCM, regenerated timestamps from sample counts and
stopped at 121 seconds. Each tool ran with a three-second subprocess timeout, one decode thread,
64 MiB per-allocation limit and only the local file protocol. PCM and parser stderr stayed local.

- Actual Chromium WebM/Opus and synthetic fragmented MP4/AAC passed. Cross-declared WebM as
  MP4, a 12-byte truncated header and a 10,485,761-byte file failed.
- Both 121-second fixtures failed. Both 119.5-second fixtures passed. The exact 120-second
  WebM fixture was rejected conservatively when its metadata reported 120.008 seconds although
  the decoded sample count measured 120.000 seconds.
- Before offering either container, #27 still needs a bounded production validator with tests for
  the actual browser files, malformed structures, timestamp gaps, codec padding and timeout.
  The current deployment image has no audio validator.

## Release decision

| Capability | State and remaining evidence |
| --- | --- |
| STT | **Keep disabled.** Provider access and the Chromium muxer passed. **BLOCKED** on real iOS Safari and Chromium microphone evidence, bounded production validation, verified owner identity, approved workspace data handling, and the Studio gateway size and upload path. The production upload acceptance belongs to #27. |
| TTS | **Keep disabled.** The German preset generated playable MP3 in Chromium. **BLOCKED** on real Safari playback, approved workspace data handling, owner verification, and demonstrated production request and response limits. The secure message lookup and playback lifecycle belong to #28. |

The existing workspace key passed the public inference endpoints. There was no authorized
multipart receiver in the deployed app to show what body the Studio gateway would forward or
how it would enforce size. The runtime caller token and worker credential were outside this
probe. The local limits of 10 MiB, 120 seconds, and one active STT request are app limits.
The [previous gateway probe](2026-11-18-gateway-zugang.md) concerns authenticated GET access.

**Workspace retention is unverified.** Mistral documents support for organization-level zero
data retention on both stateless audio endpoints, depending on plan and activation, separately
from training opt-out. The workspace credential and the successful inference responses provide
no evidence about the active organization settings. Verify the effective policy with the
organization administrator before using personal or mail-derived content.
[Mistral zero data retention](https://docs.mistral.ai/admin/monitor-comply/zero-data-retention).

## Runtime contract

`GET /api/v1/audio/capabilities` is browser-only and `Cache-Control: no-store`. It reads release
attestations locally and makes no provider requests. Production owner verification remains
unconfigured. The audio subtree returns 401 until a trusted server adapter installs
`get_audio_owner_verifier`. The Studio SDK's caller-token binding alone does not establish
that the caller is the app owner. Verified test callers receive independent `stt` and `tts`
objects. Both are `unknown` until their own current model and evidence match.

`AUDIO_STT_MODEL` and `AUDIO_TTS_MODEL` default to the candidates above. The corresponding
`AUDIO_STT_VERIFICATION` and `AUDIO_TTS_VERIFICATION` are optional JSON objects with a matching
`model`, timezone-aware `checked_at`, `outcome` and optional `resolved_model`. A `failed` outcome
reports `unavailable`. A `verified` outcome is an owner-reviewed release attestation and requires
one or more checked formats. TTS also requires `app_limits` with positive
`max_input_characters`, `max_response_bytes` and `timeout_seconds`. Missing, invalid or
mismatched evidence stays unknown. No attestation is configured from this probe. When a
deployment, credential, model, format or data-handling term changes, clear the affected
attestation until its release checks have run again.

## Reproduce with synthetic data

Create a private temporary directory and use eSpeak NG 1.52.0 to generate the German fixture.
Run the provider probe from the checkout with existing authorized app configuration. Set
`probe_script` to its absolute path if that checkout is separate. Enable `--live` only for this
synthetic data. Every inference call uses the same German utterance.

```bash
scratch=$(mktemp -d)
probe_script=tools/audio_provider_probe.py
espeak-ng -v de -w "$scratch/synthetic.wav" 'Eine gelbe Ente schwimmt im Teich.'
bash tools/uv.sh run --no-sync python "$probe_script" tts "$scratch" --live
bash tools/uv.sh run --no-sync python "$probe_script" wav "$scratch" --live

ffmpeg -v error -i "$scratch/synthetic.wav" -map 0:a:0 -c:a aac \
  -movflags frag_keyframe+empty_moov+default_base_moof "$scratch/recorded.mp4"
bash tools/uv.sh run --no-sync python "$probe_script" mp4 "$scratch" --live
```

The probe script is [audio_provider_probe.py](../../../tools/audio_provider_probe.py). For the
browser pass, launch an isolated Playwright Chromium with `--use-fake-device-for-media-stream`
and `--use-file-for-fake-audio-capture=<scratch>/synthetic.wav`. Serve an empty test page on
loopback, grant its microphone permission in the browser context and call
`getUserMedia({audio:true})`. Record for 2,270 ms, wait for the final data and stop events, then
write the resulting blob as `recorded.webm`. Repeat with explicit WebM/Opus, MP4/AAC and the
default recorder option. Check the top frame and cross-origin test frames with and without
`allow="microphone"` using `isSecureContext`, the document feature policy and the permission
query. Serve the returned `output.mp3` from that origin, play it from a button handler, and
observe the `ended` event. Stop all tracks and close the browser and local servers.

```bash
bash tools/uv.sh run --no-sync python "$probe_script" webm "$scratch" --live
ffprobe -v error -show_entries \
  format=format_name,duration,size:stream=codec_name,sample_rate,channels \
  -of json "$scratch/recorded.webm"
ffprobe -v error -show_entries \
  format=format_name,duration,size:stream=codec_name,sample_rate,channels \
  -of json "$scratch/output.mp3"
```

For the local duration check, prepare silence fixtures using
`ffmpeg -f lavfi -i anullsrc=r=48000:cl=mono -t <seconds>` with `-c:a libopus -b:a 24k` for
WebM, or `-c:a aac -b:a 24k -movflags frag_keyframe+empty_moov+default_base_moof` for MP4.
Inspect container and stream with
`ffprobe -show_entries format=format_name,duration:stream=codec_name,codec_type`. With the
matching demuxer allowlist, run
`ffmpeg -xerror -threads 1 -i <fixture> -map 0:a:0 -af asetpts=N/SR/TB -t 121 -ac 1 -ar 48000 -f s16le pipe:1`
under the stated timeout and allocation bounds, then divide the PCM byte count by 96,000.
Use `truncate -s 10485761` and `head -c 12` for the rejection fixtures. Close the local
processes and delete the scratch directory after inspecting the redacted results.

## Repository checks

- `bash tools/uv.sh run --no-sync pytest -q apps/api/tests tests` passed 1,172 tests, including the owner boundary, separate capability states, and publication hygiene.
- `bun run check` passed build, type checks, and generated-client drift checks. `bun run test -- --output-style=static` passed the three project test targets. The database target skipped 205 PostgreSQL cases.
- The API suite emitted a pre-existing `Connection._cancel` coroutine warning, which also appeared on the unchanged baseline.
