# Clippy Local Library v1

**Status:** Agreed v1 scope  
**Integration branch:** `feature/library-v1-integration`  
**Base:** `78700201434df5f901c93bfc313c77a5ebab3e13`

## Purpose

The Library is Clippy's durable, on-device home for generated projects. It is separate from temporary generation output so archived clips survive job cleanup, app restarts, and future installs.

## Product model

- One source video creates one project.
- The project contains the generated clips and platform captions for that source.
- A stable UUID is assigned when generation is queued. The project title can be changed without changing its identity.
- Project lifecycle states distinguish queued, processing, interrupted, failed, archive-failed, and completed work.
- A project is complete only when its media and metadata are durably published to the Library.

## Storage layout

```text
%LOCALAPPDATA%/Clippy/data/library/
  projects/<project UUID>/
    project.json
    thumbnail.jpg
    clips/<clip UUID>/
      video.mp4
      thumbnail.jpg
      captions.json
  exports/
  library_settings.json
  deleted_projects.json
```

The Library is separate from temporary `data/output` and `data/uploads`. Original footage is copied, never moved. Source retention is off by default.

## Managed data location

The desktop can relocate the complete Clippy data directory to an existing empty folder on another local or removable drive. The move includes temporary generation output, uploads, the permanent Library, cached models, and reference templates. The installed application, managed Python/Node/FFmpeg runtimes, Remotion browser, settings, and logs remain in the per-user installation root.

The selected destination must be separate from and outside the current data folder, and must have enough free space for the copied data plus a safety margin. Clippy refuses the move while generation jobs or incomplete uploads are active, blocks new API work and drains active responses (including downloads) during the handover, copies into a staging directory, verifies every copied file with SHA-256, activates the new location, and restarts both local services against it. Internal file symlinks are copied as ordinary files; directory junctions and links that point outside the data root are rejected. The old folder is removed only after the new services report healthy. A failed copy or startup retains the original data and attempts to restart from it. The selected drive or location must remain connected whenever Clippy is used.

The active data path is persisted separately in `%LOCALAPPDATA%/Clippy/storage-location.json`, so updating the application payload or repairing managed runtimes does not silently move data back to the default location. If a configured data directory is missing or invalid, startup reports the problem instead of silently creating an empty Library elsewhere.

## Source retention semantics

The setting applies to **new projects only**. The setting is sampled atomically when a new project is reserved. Changing the default never changes the retention decision for an existing project. Legacy projects without an explicit snapshot default to their existing retained state, or false when no source was previously retained.

## Thumbnails

A JPEG thumbnail is generated for every archived clip using the FFmpeg already managed by Clippy. The first successful clip thumbnail becomes the project cover. Extraction failure is non-fatal: successful clips still archive and the UI uses its placeholder. Thumbnails are served through validated project/clip API endpoints; the frontend never treats local filesystem paths as image URLs.

When an older project has a missing thumbnail, Library reads backfill the missing clip preview and project cover from the archived MP4. This repairs projects created before thumbnail generation or media authentication was corrected. Thumbnail generation remains derived data and does not change a project's user-visible update timestamp.

The desktop shell cannot attach the local API session header to native `img` and `video` requests. It therefore appends the current session token only to the exact read-only Library thumbnail and clip-video routes. Other API routes continue to require the normal authenticated header.

## Archive lifecycle and concurrency

The service stages media in a temporary directory and atomically publishes the completed project. Project rename, caption edits, clip deletion, and retention-setting changes are serialized with metadata operations. Long file copies stay outside the lock. Immediately before publish, the archive reconciles the newest project title, user-edited captions, deleted-clip tombstones, and source-retention metadata. A delete or edit made while a copy is running is therefore not overwritten by that copy.

Project deletion writes a tombstone before removing the project directory. Interrupted stage/backup swaps are recovered when the service starts.

## Project ZIP export

The portable ZIP contains generated MP4 clips, per-clip YouTube/Instagram/TikTok caption data, and an export-specific `project.json` manifest with stable IDs, timing, titles, and essential portable project metadata. It excludes original footage, workspace files, thumbnails, absolute paths, local storage metadata, and fingerprints. MP4 files are stored without recompression.

## v1 user capabilities

Browse projects with cover thumbnails; preview archived clips; edit platform captions; rename a project; download an individual clip or lightweight project ZIP; reveal a project in File Explorer; delete an individual clip or project; and configure source retention for future projects.

## Non-goals

Cloud synchronization, collaboration, nested folders, reconstruction of a full editable timeline, and a separate generation-run entity are outside v1.
