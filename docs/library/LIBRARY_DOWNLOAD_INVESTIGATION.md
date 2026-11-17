# Clippy Library: Download and Desktop Integration Notes

**Integration target:** `main`  
**Base:** `78700201434df5f901c93bfc313c77a5ebab3e13`

## Download implementation

The current Tauri desktop app already has a native streaming writer for generated MP4 downloads. The Library extends that native pattern to accept project ZIP exports as well, rather than creating a second browser-Blob implementation for large media files.

The native writer sanitizes filenames, selects a collision-free name, supports only MP4/ZIP, and restricts writes to the Clippy Downloads directory. Every append/finalize/cancel operation revalidates the path. The Library reveal command canonicalizes its target and refuses paths outside the configured Library root.

## Persistent storage

The existing Tauri supervisor anchors application data at `%LOCALAPPDATA%/Clippy`. It provisions `data/library` and passes the resolved path as `CLIPPY_LIBRARY_DIR`. The permanent archive remains separate from temporary `data/output` and `data/uploads`.

## Frontend behavior

- Local desktop History shows the local Library and its archived project list.
- Cloud mode continues to use the existing cloud History component and API.
- Project cover and clip preview images use validated backend API routes, not paths from local disk.
- When the Tauri bridge is absent, browser mode retains the browser download fallback already present in the Library UI.

## Export contract

The ZIP contains generated clips, platform caption files, and a portable project manifest. It excludes source footage, workspace files, thumbnails, local/absolute paths, and internal storage fingerprints. Video streams are copied without recompression.

## Acceptance still required

Automated CI and source review are not substitutes for launching the packaged Windows application. Verify persistence across restart and job cleanup, retention snapshot semantics across multiple projects, thumbnail display and fallback, captions, rename/delete, native downloads, Explorer reveal, ZIP contents, and unchanged cloud History in an installed build.
