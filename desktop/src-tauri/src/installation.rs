use std::{
    fs,
    path::{Path, PathBuf},
};

/// Mutex ownership is thread-affine on Windows. Keep the guard on the thread
/// that acquires it, including across payload activation and rollback.
pub struct InstallationLock {
    #[cfg(windows)]
    handle: *mut std::ffi::c_void,
    _thread_bound: std::marker::PhantomData<std::rc::Rc<()>>,
}

pub fn lock_name(root: &Path, purpose: &str) -> String {
    use sha2::{Digest, Sha256};
    let root = root
        .to_string_lossy()
        .trim_end_matches(['\\', '/'])
        .to_lowercase();
    format!(
        "Local\\Clippy.{purpose}.{:x}",
        Sha256::digest(root.as_bytes())
    )
}

impl InstallationLock {
    pub fn acquire(root: &Path, purpose: &str, wait_ms: u32) -> Result<Self, String> {
        #[cfg(windows)]
        {
            #[link(name = "kernel32")]
            extern "system" {
                fn CreateMutexW(
                    attributes: *const std::ffi::c_void,
                    owner: i32,
                    name: *const u16,
                ) -> *mut std::ffi::c_void;
                fn WaitForSingleObject(handle: *mut std::ffi::c_void, timeout: u32) -> u32;
                fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
            }
            let name: Vec<u16> = lock_name(root, purpose)
                .encode_utf16()
                .chain(Some(0))
                .collect();
            unsafe {
                let handle = CreateMutexW(std::ptr::null(), 0, name.as_ptr());
                if handle.is_null() {
                    return Err(format!(
                        "Cannot create installation lock: {}",
                        std::io::Error::last_os_error()
                    ));
                }
                match WaitForSingleObject(handle, wait_ms) {
                    0 | 0x80 => Ok(Self {
                        handle,
                        _thread_bound: std::marker::PhantomData,
                    }), // acquired or abandoned
                    result => {
                        let error = std::io::Error::last_os_error();
                        CloseHandle(handle);
                        if result == 0x102 {
                            Err("Clippy is already running or another installation is in progress. Close the other instance and try again.".into())
                        } else {
                            Err(format!("Cannot acquire installation lock: {error}"))
                        }
                    }
                }
            }
        }
        #[cfg(not(windows))]
        {
            let _ = (root, purpose, wait_ms);
            Ok(Self {
                _thread_bound: std::marker::PhantomData,
            })
        }
    }
}

impl Drop for InstallationLock {
    fn drop(&mut self) {
        #[cfg(windows)]
        unsafe {
            #[link(name = "kernel32")]
            extern "system" {
                fn ReleaseMutex(handle: *mut std::ffi::c_void) -> i32;
                fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
            }
            ReleaseMutex(self.handle);
            CloseHandle(self.handle);
        }
    }
}

fn is_link(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0 // includes junctions/reparse points
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

/// Copy before deleting any old payload. Retry is idempotent; a conflicting
/// file aborts the upgrade instead of silently overwriting someone's library.
fn preserve_tree(source: &Path, destination: &Path) -> Result<(), String> {
    if !source.exists() {
        return Ok(());
    }
    let metadata = fs::symlink_metadata(source).map_err(|e| e.to_string())?;
    if is_link(&metadata) {
        return Err(format!(
            "Cannot migrate a linked reference path: {}",
            source.display()
        ));
    }
    if destination.exists()
        && is_link(&fs::symlink_metadata(destination).map_err(|e| e.to_string())?)
    {
        return Err(format!(
            "Reference migration destination is linked: {}",
            destination.display()
        ));
    }
    if metadata.is_dir() {
        if destination.exists()
            && !fs::symlink_metadata(destination)
                .map_err(|e| e.to_string())?
                .is_dir()
        {
            return Err(format!(
                "Reference migration destination is not a directory: {}",
                destination.display()
            ));
        }
        fs::create_dir_all(destination).map_err(|e| e.to_string())?;
        for entry in fs::read_dir(source).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            preserve_tree(&entry.path(), &destination.join(entry.file_name()))?;
        }
    } else if metadata.is_file() {
        if destination.exists() {
            if fs::symlink_metadata(destination)
                .map_err(|e| e.to_string())?
                .file_type()
                .is_symlink()
                || file_digest(source)? != file_digest(destination)?
            {
                return Err(format!(
                    "Reference migration conflict at {}; the previous payload has been retained.",
                    destination.display()
                ));
            }
        } else {
            // An interrupted copy must never appear to be a completed reference.
            let partial = destination.with_extension("clippy-migrating");
            fs::copy(source, &partial).map_err(|e| e.to_string())?;
            fs::OpenOptions::new()
                .write(true)
                .open(&partial)
                .and_then(|f| f.sync_all())
                .map_err(|e| e.to_string())?;
            fs::rename(&partial, destination).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

fn file_digest(path: &Path) -> Result<Vec<u8>, String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut file = fs::File::open(path).map_err(|e| e.to_string())?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    Ok(hash.finalize().to_vec())
}

pub fn preserve_references(root: &Path) -> Result<(), String> {
    let destination = root.join("data").join("reference_templates");
    // current wins; any disagreement with an interrupted upgrade is surfaced,
    // never resolved by deleting or silently overwriting either copy.
    for payload in ["current", "current.previous"] {
        let source = root.join("app").join(payload).join("reference_templates");
        preserve_tree(&source, &destination)?;
        if source.exists() {
            fs::remove_dir_all(&source)
                .map_err(|e| format!("Cannot finish reference migration: {e}"))?;
        }
    }
    Ok(())
}

pub fn user_root() -> Result<PathBuf, String> {
    std::env::var_os("LOCALAPPDATA")
        .map(|p| PathBuf::from(p).join("Clippy"))
        .ok_or_else(|| "Windows LOCALAPPDATA directory is unavailable".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp_root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "clippy-migration-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }
    #[test]
    fn references_survive_upgrade_and_migration_retries() {
        let root = temp_root();
        let source = root.join("app/current/reference_templates/ref_example");
        fs::create_dir_all(&source).unwrap();
        fs::write(source.join("reference.mp4"), b"saved video").unwrap();
        preserve_references(&root).unwrap();
        preserve_references(&root).unwrap();
        let target = root.join("data/reference_templates/ref_example/reference.mp4");
        assert_eq!(fs::read(&target).unwrap(), b"saved video");
        assert!(!source.exists());
        fs::create_dir_all(&source).unwrap();
        fs::write(source.join("reference.mp4"), b"saved video").unwrap();
        fs::write(&target, b"different saved video").unwrap();
        assert!(preserve_references(&root).is_err());
        assert!(source.join("reference.mp4").is_file());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    #[cfg(windows)]
    fn installation_lock_excludes_other_threads_and_releases() {
        let root = temp_root();
        let lock = InstallationLock::acquire(&root, "Install", 0).unwrap();
        let other = root.clone();
        assert!(std::thread::spawn(
            move || InstallationLock::acquire(&other, "Install", 0).is_err()
        )
        .join()
        .unwrap());
        drop(lock);
        assert!(InstallationLock::acquire(&root, "Install", 0).is_ok());
    }
}
