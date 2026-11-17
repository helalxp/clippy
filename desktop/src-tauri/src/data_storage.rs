use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

const STORAGE_CONFIG_SCHEMA: u32 = 1;
const COPY_BUFFER_SIZE: usize = 256 * 1024;

#[derive(Debug, Serialize, Deserialize)]
struct StorageLocationConfig {
    schema_version: u32,
    data_directory: String,
}

pub fn config_path(install_root: &Path) -> PathBuf {
    install_root.join("storage-location.json")
}

pub fn configured_data_directory(install_root: &Path) -> Result<PathBuf, String> {
    let config = config_path(install_root);
    if !config.is_file() {
        let default = install_root.join("data");
        if default.exists() {
            reject_link(&default)?;
            return default
                .canonicalize()
                .map_err(|error| format!("Cannot resolve Clippy data directory: {error}"));
        }
        return Ok(default);
    }

    let raw = fs::read_to_string(&config)
        .map_err(|error| format!("Cannot read Clippy storage location {}: {error}", config.display()))?;
    let saved: StorageLocationConfig = serde_json::from_str(&raw)
        .map_err(|error| format!("Clippy storage location is invalid: {error}"))?;
    if saved.schema_version != STORAGE_CONFIG_SCHEMA || saved.data_directory.trim().is_empty() {
        return Err("Clippy storage location uses an unsupported or incomplete configuration.".into());
    }
    let path = PathBuf::from(saved.data_directory);
    if !path.is_absolute() {
        return Err("Clippy data directory must be an absolute path.".into());
    }
    reject_link(&path)?;
    if !path.is_dir() {
        return Err(format!(
            "The configured Clippy data directory is unavailable: {}",
            path.display()
        ));
    }
    path.canonicalize()
        .map_err(|error| format!("Cannot resolve configured Clippy data directory: {error}"))
}

pub fn write_config(install_root: &Path, data_directory: &Path) -> Result<(), String> {
    if !data_directory.is_absolute() || !data_directory.is_dir() {
        return Err("The new Clippy data directory must be an existing absolute folder.".into());
    }
    reject_link(data_directory)?;
    let canonical = data_directory
        .canonicalize()
        .map_err(|error| format!("Cannot resolve the new Clippy data directory: {error}"))?;
    fs::create_dir_all(install_root)
        .map_err(|error| format!("Cannot create Clippy installation directory: {error}"))?;

    let config = config_path(install_root);
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    let temporary = install_root.join(format!(".storage-location-{nonce}.tmp"));
    let payload = serde_json::to_vec_pretty(&StorageLocationConfig {
        schema_version: STORAGE_CONFIG_SCHEMA,
        data_directory: canonical.to_string_lossy().into_owned(),
    })
    .map_err(|error| format!("Cannot serialize storage location: {error}"))?;

    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|error| format!("Cannot create storage configuration: {error}"))?;
    if let Err(error) = file.write_all(&payload).and_then(|_| file.sync_all()) {
        let _ = fs::remove_file(&temporary);
        return Err(format!("Cannot write storage configuration: {error}"));
    }
    drop(file);
    if let Err(error) = replace_file(&temporary, &config) {
        let _ = fs::remove_file(&temporary);
        return Err(format!("Cannot activate storage configuration: {error}"));
    }
    Ok(())
}

pub fn validate_destination(source: &Path, destination: &Path) -> Result<(PathBuf, PathBuf), String> {
    reject_link(source)?;
    reject_link(destination)?;
    let source = source
        .canonicalize()
        .map_err(|error| format!("Cannot resolve the current Clippy data directory: {error}"))?;
    let destination = destination
        .canonicalize()
        .map_err(|error| format!("Choose an existing destination folder: {error}"))?;
    if !destination.is_dir() {
        return Err("The selected destination is not a folder.".into());
    }
    if destination.file_name().is_none() {
        return Err("Choose a folder, not a drive root.".into());
    }

    let source_key = normalized_path(&source);
    let destination_key = normalized_path(&destination);
    let overlaps = source_key == destination_key
        || destination_key.starts_with(&(source_key.clone() + "\\"))
        || source_key.starts_with(&(destination_key.clone() + "\\"));
    if overlaps {
        return Err("The new location must be separate from the current Clippy data folder.".into());
    }

    let mut entries = fs::read_dir(&destination)
        .map_err(|error| format!("Cannot inspect the destination folder: {error}"))?;
    if entries.next().is_some() {
        return Err("Choose an empty folder. Clippy will place its complete data folder there.".into());
    }
    Ok((source, destination))
}

pub fn staging_path(destination: &Path) -> Result<PathBuf, String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "The selected destination has no parent folder.".to_string())?;
    let name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "The selected destination folder name is invalid.".to_string())?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    Ok(parent.join(format!(".{name}.clippy-moving-{}-{nonce}", std::process::id())))
}

pub fn copy_tree_verified(
    source: &Path,
    destination: &Path,
    mut report_progress: impl FnMut(u64, u64),
) -> Result<u64, String> {
    if destination.exists() {
        return Err(format!("Temporary move folder already exists: {}", destination.display()));
    }
    reject_link(source)?;
    let total_bytes = measure_tree(source)?;
    let source_root = source.canonicalize().map_err(|error| error.to_string())?;
    let reserve_bytes = (total_bytes / 20).max(64 * 1024 * 1024);
    let required_bytes = total_bytes.saturating_add(reserve_bytes);
    let capacity_path = destination
        .parent()
        .ok_or_else(|| "The selected destination has no parent folder.".to_string())?;
    let available_bytes = available_space(capacity_path)?;
    if available_bytes < required_bytes {
        return Err(format!(
            "The selected drive does not have enough free space. Clippy needs about {:.2} GiB including a safety margin, but only {:.2} GiB is available.",
            required_bytes as f64 / 1024f64.powi(3),
            available_bytes as f64 / 1024f64.powi(3),
        ));
    }
    fs::create_dir(destination)
        .map_err(|error| format!("Cannot create temporary data folder: {error}"))?;
    let mut copied_bytes = 0u64;
    if let Err(error) = copy_directory(source, destination, &source_root, &mut copied_bytes, total_bytes, &mut report_progress) {
        let _ = fs::remove_dir_all(destination);
        return Err(error);
    }
    report_progress(copied_bytes, total_bytes);
    Ok(copied_bytes)
}

pub fn activate_staged_directory(staging: &Path, destination: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(destination)
        .map_err(|error| format!("Cannot inspect the destination folder: {error}"))?;
    if !metadata.is_dir() || is_link_metadata(&metadata) {
        return Err("The destination changed while Clippy was preparing the move.".into());
    }
    let mut entries = fs::read_dir(destination)
        .map_err(|error| format!("Cannot inspect the destination folder: {error}"))?;
    if entries.next().is_some() {
        return Err("The destination folder is no longer empty. No files were overwritten.".into());
    }
    fs::remove_dir(destination)
        .map_err(|error| format!("Cannot prepare the destination folder: {error}"))?;
    if let Err(error) = fs::rename(staging, destination) {
        let _ = fs::create_dir(destination);
        return Err(format!("Cannot activate the moved Clippy data folder: {error}"));
    }
    Ok(())
}

pub fn remove_tree(path: &Path) -> Result<(), String> {
    if !path.exists() {
        return Ok(());
    }
    reject_link(path)?;
    fs::remove_dir_all(path).map_err(|error| format!("Cannot remove old Clippy data folder: {error}"))
}

#[cfg(windows)]
fn available_space(path: &Path) -> Result<u64, String> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetDiskFreeSpaceExW(
            directory: *const u16,
            free_bytes_available: *mut u64,
            total_bytes: *mut u64,
            total_free_bytes: *mut u64,
        ) -> i32;
    }
    let directory: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let mut available = 0u64;
    let result = unsafe {
        GetDiskFreeSpaceExW(
            directory.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if result == 0 {
        return Err(format!(
            "Cannot check available space on the selected drive: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(available)
}

#[cfg(not(windows))]
fn available_space(_path: &Path) -> Result<u64, String> {
    // The relocation UI is Windows-only. Keep the filesystem copy unit tests
    // portable without introducing a platform-specific statvfs dependency.
    Ok(u64::MAX)
}

fn measure_tree(path: &Path) -> Result<u64, String> {
    reject_link(path)?;
    let root = path
        .canonicalize()
        .map_err(|error| format!("Cannot resolve Clippy data root: {error}"))?;
    measure_tree_inner(path, &root)
}

fn measure_tree_inner(path: &Path, root: &Path) -> Result<u64, String> {
    let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if !metadata.is_dir() {
        return Err(format!("Clippy data path is not a folder: {}", path.display()));
    }
    let mut total = 0u64;
    for entry in fs::read_dir(path).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let item = entry.path();
        let metadata = fs::symlink_metadata(&item).map_err(|error| error.to_string())?;
        if is_link_metadata(&metadata) {
            let target = item.canonicalize().map_err(|error| {
                format!("Cannot resolve data-file link {}: {error}", item.display())
            })?;
            if !is_within_root(&target, root) {
                return Err(format!(
                    "Cannot move a data-file link that points outside Clippy's data directory: {}",
                    item.display()
                ));
            }
            let target_metadata = fs::metadata(&target).map_err(|error| error.to_string())?;
            if !target_metadata.is_file() {
                return Err(format!(
                    "Directory links and junctions are not supported inside Clippy data: {}",
                    item.display()
                ));
            }
            total = total.saturating_add(target_metadata.len());
        } else if metadata.is_dir() {
            total = total.saturating_add(measure_tree_inner(&item, root)?);
        } else if metadata.is_file() {
            total = total.saturating_add(metadata.len());
        } else {
            return Err(format!("Unsupported item in Clippy data folder: {}", item.display()));
        }
    }
    Ok(total)
}

fn copy_directory(
    source: &Path,
    destination: &Path,
    source_root: &Path,
    copied_bytes: &mut u64,
    total_bytes: u64,
    report_progress: &mut impl FnMut(u64, u64),
) -> Result<(), String> {
    for entry in fs::read_dir(source).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let source_item = entry.path();
        let destination_item = destination.join(entry.file_name());
        let metadata = fs::symlink_metadata(&source_item).map_err(|error| error.to_string())?;
        if is_link_metadata(&metadata) {
            let target = source_item.canonicalize().map_err(|error| {
                format!("Cannot resolve data-file link {}: {error}", source_item.display())
            })?;
            if !is_within_root(&target, source_root) {
                return Err(format!(
                    "Cannot move a data-file link that points outside Clippy's data directory: {}",
                    source_item.display()
                ));
            }
            let target_metadata = fs::metadata(&target).map_err(|error| error.to_string())?;
            if !target_metadata.is_file() {
                return Err(format!(
                    "Directory links and junctions are not supported inside Clippy data: {}",
                    source_item.display()
                ));
            }
            copy_file_verified(&target, &destination_item, copied_bytes, total_bytes, report_progress)?;
        } else if metadata.is_dir() {
            fs::create_dir(&destination_item)
                .map_err(|error| format!("Cannot create {}: {error}", destination_item.display()))?;
            copy_directory(&source_item, &destination_item, source_root, copied_bytes, total_bytes, report_progress)?;
        } else if metadata.is_file() {
            copy_file_verified(&source_item, &destination_item, copied_bytes, total_bytes, report_progress)?;
        } else {
            return Err(format!("Unsupported item in Clippy data folder: {}", source_item.display()));
        }
    }
    Ok(())
}

fn copy_file_verified(
    source: &Path,
    destination: &Path,
    copied_bytes: &mut u64,
    total_bytes: u64,
    report_progress: &mut impl FnMut(u64, u64),
) -> Result<(), String> {
    let mut input = File::open(source)
        .map_err(|error| format!("Cannot read {}: {error}", source.display()))?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|error| format!("Cannot create {}: {error}", destination.display()))?;
    let mut source_hash = Sha256::new();
    let mut buffer = vec![0u8; COPY_BUFFER_SIZE];
    loop {
        let count = input.read(&mut buffer)
            .map_err(|error| format!("Cannot read {}: {error}", source.display()))?;
        if count == 0 {
            break;
        }
        output.write_all(&buffer[..count])
            .map_err(|error| format!("Cannot write {}: {error}", destination.display()))?;
        source_hash.update(&buffer[..count]);
        *copied_bytes = copied_bytes.saturating_add(count as u64);
        report_progress(*copied_bytes, total_bytes);
    }
    output.sync_all()
        .map_err(|error| format!("Cannot flush {}: {error}", destination.display()))?;
    drop(output);

    let expected = source_hash.finalize();
    let actual = hash_file(destination)?;
    if expected.as_slice() != actual.as_slice() {
        return Err(format!("Data verification failed after copying {}.", source.display()));
    }
    Ok(())
}

fn hash_file(path: &Path) -> Result<Vec<u8>, String> {
    let mut file = File::open(path).map_err(|error| error.to_string())?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0u8; COPY_BUFFER_SIZE];
    loop {
        let count = file.read(&mut buffer).map_err(|error| error.to_string())?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    Ok(hash.finalize().to_vec())
}

fn is_within_root(path: &Path, root: &Path) -> bool {
    #[cfg(windows)]
    {
        let path = normalized_path(path);
        let root = normalized_path(root);
        path == root || path.starts_with(&(root + "\\"))
    }
    #[cfg(not(windows))]
    {
        path.starts_with(root)
    }
}

fn normalized_path(path: &Path) -> String {
    path.to_string_lossy()
        .replace('/', "\\")
        .trim_end_matches('\\')
        .to_ascii_lowercase()
}

fn reject_link(path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if is_link_metadata(&metadata) {
        return Err(format!("Clippy data paths cannot be symbolic links or junctions: {}", path.display()));
    }
    Ok(())
}

#[cfg(windows)]
fn is_link_metadata(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    metadata.file_attributes() & 0x400 != 0
}

#[cfg(not(windows))]
fn is_link_metadata(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> Result<(), std::io::Error> {
    use std::os::windows::ffi::OsStrExt;

    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(existing: *const u16, new: *const u16, flags: u32) -> i32;
    }
    const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x8;
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination.as_os_str().encode_wide().chain(Some(0)).collect();
    let result = unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn replace_file(source: &Path, destination: &Path) -> Result<(), std::io::Error> {
    if destination.exists() {
        fs::remove_file(destination)?;
    }
    fs::rename(source, destination)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "clippy-data-move-test-{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
        ))
    }

    #[test]
    fn copies_and_verifies_nested_data_without_touching_source() {
        let root = temp_root();
        let source = root.join("data");
        let destination = root.join("new-data");
        let staging = root.join(".new-data-staging");
        fs::create_dir_all(&source).unwrap();
        fs::create_dir(&destination).unwrap();
        fs::create_dir_all(source.join("library/projects/project-a/clips")).unwrap();
        fs::write(source.join("library/projects/project-a/project.json"), b"{\"title\":\"demo\"}").unwrap();
        fs::write(source.join("library/projects/project-a/clips/clip.mp4"), b"video bytes").unwrap();
        fs::write(source.join("models/whisper/model.bin"), b"model bytes").unwrap();

        let mut last = 0;
        let total = copy_tree_verified(&source, &staging, |copied, _| last = copied).unwrap();
        assert_eq!(total, last);
        activate_staged_directory(&staging, &destination).unwrap();
        assert_eq!(
            fs::read(destination.join("library/projects/project-a/clips/clip.mp4")).unwrap(),
            b"video bytes"
        );
        assert_eq!(fs::read(destination.join("models/whisper/model.bin")).unwrap(), b"model bytes");
        assert!(source.join("library/projects/project-a/project.json").is_file());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn refuses_non_empty_destination_and_overlapping_paths() {
        let root = temp_root();
        let source = root.join("data");
        let destination = root.join("destination");
        fs::create_dir_all(&source).unwrap();
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("keep.txt"), b"do not overwrite").unwrap();
        assert!(validate_destination(&source, &destination).is_err());
        fs::remove_file(destination.join("keep.txt")).unwrap();
        fs::create_dir_all(source.join("nested")).unwrap();
        assert!(validate_destination(&source, &source.join("nested")).is_err());
        assert!(validate_destination(&source, &root).is_err());
        assert!(validate_destination(&source, &destination).is_ok());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn writes_and_reads_a_portable_absolute_location() {
        let root = temp_root();
        let destination = root.join("external-data");
        fs::create_dir_all(&destination).unwrap();
        write_config(&root, &destination).unwrap();
        assert_eq!(
            configured_data_directory(&root).unwrap(),
            destination.canonicalize().unwrap()
        );
        fs::remove_dir_all(root).unwrap();
    }
}
