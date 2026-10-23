---
name: get-started
description: Use OpenShorts to turn a long video (YouTube link or video file) into vertical 9:16 clips with captions and titles, restyle or re-cut those clips, and publish them to TikTok, Instagram Reels and YouTube Shorts. Use when the user wants shorts, reels or clips from a video, the best moments of a podcast or interview, or to post a clip.
---

# OpenShorts: long video to vertical clips

OpenShorts downloads, transcribes and analyses the video on its own servers,
picks the strongest moments and renders 15-60 s vertical clips with
word-by-word captions and an AI-written title. A job takes minutes.

## The flow

1. **Rights first.** The user must own the video or hold the rights. Ask once,
   then pass `confirm_rights=true` to `process_video`.
2. **Submit.** Give `process_video` the link exactly as the user wrote it. Do
   not open, search, summarise or transcribe the URL yourself: you cannot reach
   the video and it is not needed. For a file the user shares, call
   `create_upload` and follow its instructions, then pass `upload_id`.
3. **Wait.** Poll `get_job_status` every 30-60 s until `completed` or `failed`.
   Tell the user it takes a few minutes; do not invent progress.
4. **Show.** Call `list_clips` and present each clip with its title.

## Options worth setting only when asked

- `target_clips` (1-15): a target, not a guarantee. Leave it unset by default.
- `clip_min_seconds` / `clip_max_seconds`: default 15 and 60; the max must be at
  least 5 s above the min.
- `auto_hook=false` removes the title burned over the first seconds.
- `captions=false` when the source already has burned-in subtitles.

## After the clips exist

- **Captions:** `add_subtitles` with a preset or a style (`karaoke`, one word
  at a time, highlight colour, font, size).
- **Re-cut:** `recut_clip` with segments in seconds of the ORIGINAL video. It
  replaces the clip's current render, so confirm with the user first.
- **Publish:** `publish_clip` only when the user explicitly asks, to the
  platforms they name. TikTok lands as a draft in the TikTok app; Instagram and
  YouTube publish directly. Use `scheduled_date` (ISO-8601) to schedule.

## Minutes and limits

Processing uses minutes from the user's OpenShorts account. Call `get_quota`
before long videos. If a tool returns `quota_exceeded` or `no_plan`, tell the
user and give them the `upgrade_url` it returns; never retry in a loop.

## What OpenShorts does not do

It does not edit projects in desktop editors, does not download videos for
reuse outside OpenShorts, and does not post anything the user did not ask for.
