# Clippy release process

Clippy uses semantic versioning. The canonical version is stored in the repository-root `VERSION` file.

## Version rules

- Patch (`0.2.1`): backwards-compatible fixes.
- Minor (`0.3.0`): backwards-compatible features and improvements.
- Major (`1.0.0`): intentional breaking changes or the first stable public contract.

Before preparing a release, update `VERSION` and keep these files synchronized:
- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml` and `desktop/src-tauri/Cargo.lock`
- `dashboard/package.json` and `dashboard/package-lock.json`

Run the consistency check:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\validate-version.ps1
```

The local installer build runs this check automatically.

## Release flow

1. Merge completed work into `windows-installer-release`.
2. Confirm CI and the Windows desktop validation workflow are green.
3. Confirm the installer has been exercised on a Windows machine.
4. Create and push a tag matching the canonical version, for example `v0.2.0`.
5. The `Clippy Windows Release` workflow builds the NSIS installer from that tag.
6. The workflow publishes the installer and a SHA-256 checksum as GitHub Release assets.
7. Users download the new installer from the GitHub Releases page and run it over their existing Clippy installation.

The release workflow rejects tags whose version does not match `VERSION`. It never silently builds an installer with mismatched application, dashboard, or Rust package versions.

## Update behavior

This is an installer-based update channel, not an in-app auto-updater. Users install each published release manually. User data and separately stored AI model weights must remain outside the versioned application payload.
