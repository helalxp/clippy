# Arabic Subtitle and Rendering Audit

**Date:** 2026-11-28  
**Status:** Investigation documented; first rendering fix implemented on the Arabic-rendering PR branch. No changes to `main`.

## Scope and evidence

This audit covers the generated video and job log supplied for job
`1c3f0297-ee07-41fc-8470-4fec9d954d7a`.

- Selected clip: clip 6, source range `910.39s–959.98s`.
- Delivered file: `subtitled_1795808790_hooked_1795808790_..._clip_6.mp4`.
- Output: 1080×1920, 24 fps.
- Relevant code: `subtitles.py`, `transcribe_backends.py`, and
  `main.py`.

The video was reviewed through a contact sheet and selected frames. The log was
reviewed around transcription, FFmpeg subtitle rendering, renderer failures,
and the final clip lifecycle. Findings below distinguish observed defects from
items that still need a controlled test.

## Findings

### 1. Arabic karaoke word order was reversed by ASS inline styling

**Status: Root cause reproduced; targeted fix implemented; Windows validation pending.**

In the delivered video, the first words of Arabic phrases appeared on the
left-hand side rather than the right-hand side. Examples:

- Around clip time 13.5s, the displayed order of `انا بآمنب` is reversed.
  The matching transcript segment is at source time 923.19s.
- Around clip time 42.4s, the displayed order of `فيها دفنس` is reversed.
  The matching transcript segment is at source time 951.42s.

The original code builds ASS dialogue text by concatenating words in transcript
order, but puts inline style overrides around the currently highlighted word
(for example colour, scale, transform, and reset tags). A small FFmpeg/libass
reproduction using the same pattern reproduced the defect: a plain Arabic
line rendered in the correct RTL order, while putting an ASS colour override
before the first Arabic word caused libass to place that word on the wrong side.

Prepending U+200F RIGHT-TO-LEFT MARK to the dialogue text, before any ASS
override tags, restored the correct order in the reproduction. The mixed-script
test also retained the English word as an LTR run within the RTL line.

**Code change:** `generate_ass()` now prefixes dialogue events containing RTL
text with U+200F. The marker precedes per-scene alignment overrides and
per-word styling tags. English-only events are unchanged.

**Validation boundary:** The reproduction was run with the local FFmpeg 7.1.5
/libass build. The affected Windows logs report libass 0.17.5, FriBidi 1.0.16,
and HarfBuzz 14.4.0. The packaged Windows validation and a real Windows
generation are still required before calling this fixed in production.

### 2. Arabic transcription contains substantial recognition errors

**Status: Confirmed output-quality issue; cause not yet attributed.**

The transcript includes Arabic phrases that look substantially misrecognized,
as well as some output containing unrelated scripts. Examples from the
selected region include:

- `917.33s`: `اوه انا اشعب فيلك بوتكاس`
- `920.77s`: `لماذا своей؟ لっぱع شوفت أنني`
- `941.46s`: `صراحة ما عنديش اهigenي يقوم بحاجة ا Schn manner`
- `948.84s`: `لا بس Langley`

The overall detected language is `ar`, but the supplied log does not identify
the actual ASR backend, selected model, device, or compute type. It also prints
segment text rather than the word-level timestamp array used by karaoke
captions. The repository defaults to Whisper unless
`TRANSCRIBE_BACKEND=parakeet` is configured; the job log does not establish
which path this run used.

This must be treated separately from rendering. A renderer cannot repair
incorrect words.

**Next investigation:**

1. Record the effective ASR backend, model, device, and compute type for a job.
2. Compare the transcript against the audio in the same source-time ranges.
3. Test an Arabic/dialect sample with the current backend and at least one
   controlled alternative before changing model defaults.
4. Keep any transcript correction grounded in the audio; do not silently
   rewrite the user's spoken words.

### 3. ASS reports a missing PlayResX value

**Status: Warning confirmed; visual impact not demonstrated; deferred.**

The generated ASS header sets `PlayResY: 288` but omits `PlayResX`.
FFmpeg repeatedly logs:

```text
PlayResX undefined, setting to 384
```

This is a real configuration warning. However, a minimal local render test of
the affected short caption produced no visible difference between the implicit
default width and an explicit portrait-ratio width. It is therefore not
currently established as the cause of the observed order or layout defects.

**Next investigation:** Revisit only if line wrapping, caption width, or
placement remains incorrect after the RTL base-direction fix. Compare real
portrait clips and the actual caption presets before changing the coordinate
system or font sizes.

### 4. GPU and encoder memory pressure causes render fallbacks and missing captions

**Status: Confirmed failures; resource-pressure cause is strongly indicated.**

The job log contains GPU frame-sampling failures with
`Cannot allocate memory`, followed by CPU decode fallback. It also contains
multiple libx264 allocation failures during parallel output encoding.

Some auto-caption attempts then fail at FFmpeg encoding. The code deliberately
treats caption failure as non-fatal and delivers the underlying clip without
captions. That protects the clip, but it means a memory-related render failure
can silently result in an uncaptioned deliverable.

The log records 95 GPU decode operations and 21 fallbacks. The current
`main.py` clip-render pool defaults to six concurrent workers.

**Next investigation:**

1. Repeat the same source with `CLIP_WORKERS=2`, then `CLIP_WORKERS=1`,
   comparing GPU fallbacks, encoder failures, completion time, and caption
   success.
2. Do not globally lower concurrency until the result is measured.
3. If lower concurrency materially improves reliability, choose a simple
   hardware-aware limit or a documented safe default for low-VRAM machines.

### 5. Successful clips can be reported as failed during temporary-file cleanup

**Status: Failure sequence confirmed; lock owner unknown.**

For clip 6, the log reports successful reframe, hook rendering, combined
hook-plus-caption rendering, and `Clip 6 ready`. The worker then raises
`PermissionError: [WinError 32]` while deleting its temporary input MP4 in
the `finally` block. The retry encounters the same condition.

In `main.py`, cleanup is performed with an unguarded `os.remove()` in
`finally`. An exception from cleanup can therefore override a successful
render return and cause the worker to be classified as failed even though the
deliverable already exists.

The log does not identify which process or handle still owns the temporary
file. Do not assume the owner without a targeted reproduction.

**Next investigation/fix:**

1. Make cleanup failure non-fatal to an already successful clip, while
   logging the leftover path.
2. Inspect why the file handle remains open and whether the file can be
   removed after a short delay or by the job cleanup task.
3. Ensure a leftover temporary file cannot trigger an expensive full clip
   rerender when the final deliverable is valid.

### 6. YouTube JavaScript challenge failure falls back successfully

**Status: Non-blocking in this run.**

The Node challenge solver failed with
`TypeError: a.addOnDisposeCallback is not a function`. Some YouTube formats
were skipped, but yt-dlp's fallback download succeeded. The source was
downloaded and processed, so this did not cause the subtitle defects.

Investigate only if this recurs as a download failure or materially affects
format quality. The log also notes that `YOUTUBE_COOKIES` was not configured;
there is no evidence in this run that adding cookies would have fixed this
specific JavaScript error.

### 7. Font-directory warnings are non-fatal

**Status: Observed; low priority.**

libass attempts to load `Montserrat-OFL.txt` and
`openshorts-fontmap.conf` from the fonts directory as font files and reports
that it cannot open them. It subsequently selects Segoe UI Bold successfully,
and Arabic text is visibly shaped.

This is noisy directory enumeration, not the cause of the RTL reversal. Keep it
as a cleanup item, not a blocker.

### 8. Other observations

- A Windows asyncio `ConnectionResetError: [WinError 10054]` appears during
  startup. The supplied evidence does not connect it to this generation's
  rendering.
- Total job time was approximately 4,184 seconds; transcription progress
  reached approximately 2,930 seconds. The log does not identify enough ASR
  configuration to attribute that duration to a specific model or device.

### 9. yt-dlp TLS certificate verification is disabled

**Status: Confirmed security configuration issue; separate fix required.**

The verbose yt-dlp log records `nocheckcertificate: True`. The same option is
set unconditionally in `main.py` inside `download_youtube_video()`'s
`_base_opts()`. yt-dlp documents this option as disabling SSL certificate
verification. This makes the downloader accept a connection without proving
that the remote endpoint is the intended YouTube host.

The supplied run reports that `YOUTUBE_COOKIES` was not configured, so this
particular run did not use that cookie source. The code does support a
`cookiefile` when `cookies_path` is present, however. Leaving certificate
verification disabled becomes especially risky when logged-in cookies or
other credentials are supplied: an intercepting network can impersonate the
remote host and capture or alter that traffic.

This did not cause the subtitle issue, and the download fallback succeeded.
It is nevertheless a security defect independent of the rendering work.

**Next investigation/fix:**

1. Remove the unconditional insecure override and restore normal certificate
   verification by default.
2. Test the packaged Windows downloader against YouTube with and without the
   configured cookie file.
3. If a real certificate-trust failure appears, fix the trust store or CA
   configuration rather than disabling verification globally.
4. Keep any exceptional insecure mode explicit, opt-in, and clearly warned;
   do not silently enable it for every download.

References:
- [yt-dlp option definition](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py)
- [yt-dlp maintainer warning about cookies and MITM risk](https://github.com/yt-dlp/yt-dlp/issues/16372#issuecomment-)

## Prioritized implementation plan

| Priority | Work item | Acceptance criteria |
|---|---|---|
| P0 | RTL base-direction marker in ASS events | Arabic words display right-to-left with the active highlight on the correct word; English-only rendering is unchanged |
| P1 | Restore yt-dlp TLS verification by default | Certificate verification is enabled; normal and cookie-backed Windows downloads pass |
| P2 | Windows validation and real-video check | Packaged Windows smoke passes; generated Arabic, mixed Arabic/English, punctuation, numbers, pop/highlight, and split-scene captions are visually checked |
| P3 | Arabic ASR accuracy investigation | Effective backend/model/device recorded; selected audio ranges compared against transcript; model changes justified by a controlled test |
| P4 | Low-VRAM render stability | Worker-count comparison documents fallback counts, encoder failures, caption success, and total time |
| P5 | Temporary-file cleanup lifecycle | Cleanup errors cannot mark an already-delivered clip as failed; leftovers are logged and cleaned safely |
| P6 | ASS PlayResX investigation | Real portrait line wrapping/placement is measured before changing resolution settings |
| P7 | Non-blocking cleanup | Font-folder enumeration noise and recurring downloader/startup warnings are addressed only if they remain reproducible |

## Current execution status

- [x] Reproduce the Arabic order reversal with a minimal ASS/libass test.
- [x] Verify that a leading U+200F restores RTL order in the reproduction.
- [x] Implement the marker in the existing Arabic-rendering PR branch.
- [x] Add focused regression tests for RTL events, split-scene alignment tags,
      and unchanged English-only events.
- [ ] Run focused Python tests in the repository environment.
- [ ] Pass packaged Windows validation and perform a real generated-video check.
- [ ] Investigate the remaining P2–P5 items one at a time.

No changes were made directly to `main`.
