use std::{fs, path::Path};

fn path_exists(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok()
}

fn reject_link(path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(format!("Refusing to modify a linked application payload path: {}", path.display()));
        }
    }
    #[cfg(not(windows))]
    if metadata.file_type().is_symlink() {
        return Err(format!("Refusing to modify a linked application payload path: {}", path.display()));
    }
    Ok(())
}

fn remove_payload(path: &Path) -> Result<(), String> {
    if !path_exists(path) {
        return Ok(());
    }
    reject_link(path)?;
    let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if metadata.is_dir() {
        fs::remove_dir_all(path).map_err(|error| format!("Cannot remove {}: {error}", path.display()))
    } else {
        fs::remove_file(path).map_err(|error| format!("Cannot remove {}: {error}", path.display()))
    }
}

/// Activate a fully extracted and verified payload without discarding the
/// previous known-good payload. The caller commits only after service health.
pub fn activate(app_root: &Path, staging: &Path) -> Result<(), String> {
    let current = app_root.join("current");
    let previous = app_root.join("current.previous");
    let failed = app_root.join("current.failed");

    if path_exists(&previous) {
        return Err("A previous application payload transaction is still pending.".into());
    }
    if !path_exists(staging) {
        return Err(format!("Staged application payload is missing: {}", staging.display()));
    }
    reject_link(staging)?;
    if path_exists(&current) {
        reject_link(&current)?;
    }
    remove_payload(&failed)?;

    let had_current = path_exists(&current);
    if had_current {
        fs::rename(&current, &previous)
            .map_err(|error| format!("Cannot preserve current application before update: {error}"))?;
    }
    if let Err(error) = fs::rename(staging, &current) {
        if had_current {
            fs::rename(&previous, &current).map_err(|restore_error| {
                format!("Cannot activate application payload: {error}. Restoring the previous payload also failed: {restore_error}")
            })?;
        }
        return Err(format!("Cannot activate application payload: {error}"));
    }
    Ok(())
}

/// Commit only after the new application runtime and managed services are
/// healthy. Cleanup is idempotent and safe to retry on the next launch.
pub fn commit(app_root: &Path) -> Result<(), String> {
    remove_payload(&app_root.join("current.previous"))?;
    remove_payload(&app_root.join("current.failed"))?;
    Ok(())
}

/// Restore the previous payload after a failed startup. The failed payload is
/// retained separately until the restored application passes health checks.
pub fn rollback(app_root: &Path) -> Result<bool, String> {
    let current = app_root.join("current");
    let previous = app_root.join("current.previous");
    let failed = app_root.join("current.failed");

    if !path_exists(&previous) {
        return Ok(false);
    }
    reject_link(&previous)?;
    if path_exists(&current) {
        reject_link(&current)?;
    }
    remove_payload(&failed)?;

    let had_current = path_exists(&current);
    if had_current {
        fs::rename(&current, &failed)
            .map_err(|error| format!("Cannot preserve failed application payload: {error}"))?;
    }
    if let Err(error) = fs::rename(&previous, &current) {
        if had_current {
            fs::rename(&failed, &current).map_err(|restore_error| {
                format!("Cannot restore previous application payload: {error}. Restoring the failed payload also failed: {restore_error}")
            })?;
        }
        return Err(format!("Cannot restore previous application payload: {error}"));
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "clippy-payload-transaction-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    fn write_payload(path: &Path, marker: &str) {
        fs::create_dir_all(path).unwrap();
        fs::write(path.join("payload.txt"), marker).unwrap();
    }

    #[test]
    fn activation_keeps_previous_payload_until_commit() {
        let root = temp_root();
        let current = root.join("current");
        let staging = root.join("current.installing");
        write_payload(&current, "old");
        write_payload(&staging, "new");

        activate(&root, &staging).unwrap();

        assert_eq!(fs::read_to_string(root.join("current/payload.txt")).unwrap(), "new");
        assert_eq!(fs::read_to_string(root.join("current.previous/payload.txt")).unwrap(), "old");
        assert!(commit(&root).is_ok());
        assert!(!root.join("current.previous").exists());
        assert_eq!(fs::read_to_string(root.join("current/payload.txt")).unwrap(), "new");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rollback_restores_previous_and_keeps_failed_payload_until_commit() {
        let root = temp_root();
        let current = root.join("current");
        let staging = root.join("current.installing");
        write_payload(&current, "old");
        write_payload(&staging, "new");

        activate(&root, &staging).unwrap();
        assert!(rollback(&root).unwrap());

        assert_eq!(fs::read_to_string(root.join("current/payload.txt")).unwrap(), "old");
        assert_eq!(fs::read_to_string(root.join("current.failed/payload.txt")).unwrap(), "new");
        assert!(commit(&root).is_ok());
        assert!(!root.join("current.failed").exists());
        assert_eq!(fs::read_to_string(root.join("current/payload.txt")).unwrap(), "old");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rollback_without_previous_payload_is_a_noop() {
        let root = temp_root();
        fs::create_dir_all(&root).unwrap();
        assert!(!rollback(&root).unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn failed_activation_restores_the_previous_payload() {
        let root = temp_root();
        write_payload(&root.join("current"), "old");
        let missing_stage = root.join("missing.installing");

        assert!(activate(&root, &missing_stage).is_err());
        assert_eq!(fs::read_to_string(root.join("current/payload.txt")).unwrap(), "old");
        assert!(!root.join("current.previous").exists());
        fs::remove_dir_all(root).unwrap();
    }
}
