# Clippy Library v1: Product Specification

**Status:** Agreed product direction; implementation details subject to repository inspection  
**Branch:** `feature/library-history`  
**Base:** `windows-installer-release`

## 1. Purpose

The Library is Clippy's persistent home for completed and in-progress content projects. Users must be able to generate clips across multiple projects, leave a project, start another, and later return to previously generated videos and their associated captions.

The Library is a durable archive, not merely a view over temporary generation jobs.

## 2. Core product principles

1. A **Project** is a permanent user-facing content collection.
2. A **Generation Run** is one execution of the generation pipeline inside a project.
3. A **Clip** is an individual generated video and its associated editable metadata.
4. Temporary job cleanup must never delete archived project content.
5. Project and clip identifiers remain stable when titles are renamed.
6. The first release must not claim to support full video reconstruction unless all required source media and edit inputs are actually present.

## 3. Project creation and naming

- Create or reserve a project when a generation workflow begins, not only after all clips finish.
- Automatically name the project from the original YouTube video's title when available.
- Provide a user-initiated rename action.
- Keep a stable UUID independent of the title.
- Preserve source title and source URL/identifier as metadata when available.
- Represent incomplete, failed, interrupted, and completed projects honestly.

## 4. Project and clip organization

The Library landing view is project-first, not a flat list of every clip.

Each project card should expose:
- Project title
- Representative thumbnail
- Creation/last-updated date
- Number of clips
- Project processing/completion state
- Rename, open, export (if implemented), and delete actions

Inside a project, show its clips with:
- Video preview/thumbnail
- Clip name or index
- Original source start/end timestamps
- Render status
- Preview and download actions
- Caption editing/copy actions
- Individual deletion

A project may contain multiple generation runs and multiple clips from each run.

## 5. Automatic archival

- Archive each successfully rendered clip automatically.
- Persist the final video, thumbnail, caption/transcript data, platform-specific caption variants, and available editing/render metadata.
- Do not require the user to click Save after generation.
- Publish a clip as completed in the Library only after its video file has been validated and its metadata has been written successfully.
- Use a temporary staging location and an atomic finalization/move where supported.
- A failed archive operation must be visible and recoverable; do not silently report success.

## 6. Optional original-source retention

Original footage retention is **optional and OFF by default**.

When enabled:
- Copy the source into the permanent project source directory.
- Never move or delete the user's original input file.
- Verify the copied file before marking it retained.
- Preserve source metadata and relative path references.
- Report copy failures, including insufficient disk space.

When disabled:
- Keep final rendered clips and all associated captions/metadata.
- Do not retain the original footage in permanent Library storage.
- Clean up only Clippy-owned temporary copies after they are no longer needed.
- Preserve source timestamps and editing settings where possible.
- Explain that video re-rendering/regeneration requires the original source.

The setting should be available at project creation and, if feasible, editable later with clear consequences. The default remains OFF to protect disk space.

## 7. Editing promise in v1

Supported in v1:
- Preview and download archived videos.
- Edit and save caption/transcript text where current data supports it.
- Edit/copy platform-specific caption variants independently.
- View source timestamps and saved render/edit metadata.

Not promised in v1:
- Reconstructing the complete prior editing session.
- Re-rendering historical videos after changing visual settings.
- Regenerating clips when original footage was not retained.
- Full project version history.

When source footage is retained, the data model should preserve enough information to make future re-editing feasible, but the UI must not advertise a capability until implemented and tested.

## 8. Platform-specific captions

A clip may have distinct publishing text for:
- YouTube Shorts
- Instagram Reels
- TikTok

Store each platform variant independently, including the fields currently supported by the product (for example title, description/caption, and hashtags). Editing one platform's copy must not overwrite another's.

## 9. Storage and portability

- Keep permanent Library storage separate from temporary generation workspaces.
- Prefer stable project/clip UUIDs and paths relative to each project root.
- Include schema versions in persisted project metadata.
- Keep the Library root configurable in a future iteration; choose a suitable Windows user-data/video location for the initial implementation after inspecting the current desktop app's storage conventions.
- Support safe project deletion and clear storage accounting where practical.
- Do not hardcode assumptions about the current working directory.

Illustrative layout (not yet the final path decision):

```text
Clippy/
  Library/
    project_<UUID>/
      project.json
      thumbnail.jpg
      source/                 # only when retention is enabled
      runs/
        run_<UUID>/
      clips/
        clip_<UUID>/
          video.mp4
          thumbnail.jpg
          captions.json
          captions.srt
          platforms.json
          edit_settings.json
  Temp/
    active_jobs/
    intermediate_renders/
    temporary_uploads/
```

The final directory root and exact file layout must follow the existing Windows installer/runtime architecture discovered during implementation.

## 10. Reliability and safety requirements

- Temporary cleanup must be scoped to known temporary roots and must never traverse into permanent Library storage.
- Use atomic writes for JSON metadata where practical.
- Validate file existence, size, and media readability before marking a clip archived.
- Handle interrupted generation and interrupted archival.
- Prevent path traversal and ensure all project paths resolve beneath the configured Library root.
- Avoid deleting external user files when a project is deleted.
- Preserve project data across application restarts and upgrades.
- Provide clear status when source footage is missing or was not retained.

## 11. Acceptance criteria

- Generate multiple clips from one source and see them under one project.
- Start another project without losing the previous project.
- Restart Clippy and see all saved projects and clips.
- Rename a project and retain all clip associations.
- Preview and download archived clips.
- Edit and persist caption text.
- Keep platform caption variants independent.
- Delete a clip without deleting its project.
- Delete one project without affecting another.
- Verify source retention ON copies and validates source footage.
- Verify source retention OFF leaves no permanent source copy.
- Verify original user input is never moved/deleted.
- Interrupt generation and verify project state remains honest and recoverable.
- Verify temporary cleanup cannot delete Library content.

## 12. Scope boundaries

The first release prioritizes dependable local persistence and retrieval. Cloud sync, team sharing, campaign management, nested folders, full historical re-rendering, and advanced project versioning are deferred.


## 13. Local Windows desktop requirement

The Library v1 target includes the self-hosted/local Windows desktop application. It must work without `BILLING_ENABLED`, cloud authentication, Cloudflare R2, or signed cloud URLs.

Repository inspection found that the existing HistoryTab is backed by cloud-only `/api/history` and `/api/projects` routes. Those routes are mounted only when billing mode is enabled. They are not the persistence foundation for the local desktop Library.

The local desktop runtime currently uses:
- Managed root: `%LOCALAPPDATA%\\Clippy` (or `%CLIPPY_HOME%`)
- Temporary generated jobs: `<root>\\data\\output\\<job_uuid>`
- Temporary uploaded sources: `<root>\\data\\uploads`
- User-exported single clips: `%USERPROFILE%\\Downloads\\Clippy`

The permanent Library must have its own root, separate from both temporary job output and the user's export/download folder. The final permanent root is a product decision to confirm before implementation; a dedicated directory under the managed Clippy data root is the most compatible with the existing desktop runtime, while a user-visible Videos location would require a clear migration/configuration strategy.

## 14. Existing cloud behavior is not the local v1 contract

The cloud Library already archives clip files and metadata to R2 and can restore clip-level project state. It does not retain the original source video, and its current project title is derived from the first generated clip title. Local Library v1 must implement the agreed source-title naming and optional original-source retention independently of those cloud assumptions.


## 15. Confirmed v1 UI actions

- Project-level **Show in Folder** opens the permanent project directory in Windows File Explorer.
- Clip-level **Show in Folder** selects the archived video file in Explorer.
- Project-level **Download Project** exports a ZIP containing archived clip videos, each clip's platform caption JSON, and project metadata.
- Individual clips can be downloaded independently.
- Individual clips and whole projects can be deleted with confirmation.
- The original-source retention preference is a Library setting, OFF by default, and applies to new archives. When enabled, Clippy copies the source into the project. It never moves or deletes the original input.
- **Move To** (relocating the Library or a project to another drive/folder) is explicitly deferred beyond v1. Do not add a partial move implementation.

## 16. Implemented local storage layout

The current implementation uses this Windows root:

```text
%LOCALAPPDATA%\\Clippy\\data\\library\\
  library_settings.json
  projects/
    <project-uuid>/
      project.json
      clips/
        <project-uuid>-001/
          video.mp4
          captions.json
        <project-uuid>-002/
          video.mp4
          captions.json
      workspace/
        <source-title>_metadata.json
        other non-video project metadata/assets
      source/                 # only when source retention is enabled
        <original-source>
  exports/                    # temporary ZIPs, removed after response
```

Temporary generation output remains under `%LOCALAPPDATA%\\Clippy\\data\\output\\<job-uuid>`; it is not the permanent Library. Rendered videos are copied once into the clip archive rather than duplicated into the metadata workspace.

## 17. Synchronization behavior

- A completed job is archived immediately after successful generation.
- When the user navigates from the active project workspace to Library, the app asks the backend to synchronize the latest rendered clip versions.
- Synchronization preserves the stable project ID, user-renamed project title, original creation timestamp, and user-edited platform captions.
- The first Library listing also imports completed jobs that are still present inside the current output retention window.
- If the temporary job directory has already expired, the Library's permanent copies remain available for preview, caption editing, download, and deletion. Full source-based re-rendering remains unsupported unless source retention was enabled and the relevant editor workflow is implemented.



## 18. In-progress project visibility

- Reserve a project record when a local generation job is successfully queued.
- Show queued, processing, completed, failed, interrupted, and archive-failed states in Library.
- If the app restarts and a job cannot be resumed, retain an interrupted project record rather than silently losing the project.
- When a completed job is recovered from temporary output, retry archiving any existing queued/interrupted/archive-failed project.
- Automatic source-title resolution replaces the temporary title when metadata becomes available. A user rename always wins and survives subsequent synchronization.
- Project and clip deletion tombstones prevent automatic job recovery or synchronization from resurrecting deleted items.


## 19. Synchronization and deletion guarantees

- The archive records a render fingerprint for each active clip (original clip index, filename, size, and modification timestamp) and a separate digest for generated publishing-caption fields.
- Entering Library or resetting the active project does not recopy unchanged video files. Only changed renders, changed generated caption fields, missing archives, or newly enabled source retention trigger synchronization.
- User-edited Library captions take precedence over later generated caption changes. A saved user-edit flag is stored per clip.
- Individual clip deletion is committed to project metadata before physical cleanup. Startup cleanup removes orphan clip folders left by an interrupted deletion.
- Project deletion is recorded in a persistent tombstone before storage removal, preventing the temporary job importer from resurrecting it.
- Interrupted ZIP exports are cleaned on application startup.
