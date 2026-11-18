import { useEffect, useRef, useState } from 'react';
import { check } from '@tauri-apps/plugin-updater';
import { AlertTriangle, CheckCircle2, Download, RefreshCw } from 'lucide-react';

export default function DesktopUpdaterCard() {
  const isDesktop = typeof window !== 'undefined'
    && typeof window.__TAURI__?.core?.invoke === 'function';
  const invoke = isDesktop ? window.__TAURI__.core.invoke : null;
  const updateRef = useRef(null);
  const [version, setVersion] = useState('');
  const [update, setUpdate] = useState(null);
  const [phase, setPhase] = useState('idle');
  const [progress, setProgress] = useState({ downloaded: 0, total: 0 });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!isDesktop) return undefined;
    let active = true;
    const versionPromise = window.__TAURI__?.app?.getVersion?.();
    if (versionPromise?.then) {
      versionPromise.then((value) => { if (active) setVersion(value); }).catch(() => {});
    }
    return () => {
      active = false;
      const pending = updateRef.current;
      updateRef.current = null;
      if (pending) pending.close().catch(() => {});
    };
  }, [isDesktop]);

  const closeUpdate = async () => {
    const pending = updateRef.current;
    updateRef.current = null;
    if (pending) {
      try { await pending.close(); } catch (_) { /* resource already released */ }
    }
    setUpdate(null);
    setPhase('idle');
    setProgress({ downloaded: 0, total: 0 });
  };

  const checkForUpdates = async () => {
    setError('');
    setNotice('');
    setPhase('checking');
    try {
      await closeUpdate();
      const candidate = await check();
      if (!candidate) {
        setPhase('current');
        setNotice('You are running the latest available version.');
        return;
      }
      updateRef.current = candidate;
      setUpdate({
        version: candidate.version,
        date: candidate.date || '',
        notes: candidate.body || 'No release notes were provided.',
      });
      setPhase('available');
    } catch (cause) {
      setPhase('idle');
      setError(cause?.message || String(cause));
    }
  };

  const downloadUpdate = async () => {
    const candidate = updateRef.current;
    if (!candidate) return;
    setError('');
    setNotice('');
    setProgress({ downloaded: 0, total: 0 });
    setPhase('downloading');
    try {
      await candidate.download((event) => {
        if (event.event === 'Started') {
          setProgress({ downloaded: 0, total: event.data.contentLength || 0 });
        } else if (event.event === 'Progress') {
          setProgress((current) => ({
            ...current,
            downloaded: current.downloaded + event.data.chunkLength,
          }));
        } else if (event.event === 'Finished') {
          setNotice('Update package downloaded and signature-verified.');
        }
      });
      setPhase('downloaded');
    } catch (cause) {
      setPhase('available');
      setError(cause?.message || String(cause));
    }
  };

  const installUpdate = async () => {
    const candidate = updateRef.current;
    if (!candidate || phase !== 'downloaded') return;

    const activeWork = Array.isArray(window.__CLIPPY_ACTIVE_WORK__)
      ? window.__CLIPPY_ACTIVE_WORK__
      : [];
    if (activeWork.length > 0) {
      setError('Finish or close the active work first: ' + activeWork.join(', ') + '.');
      return;
    }

    setError('');
    setNotice('');
    let servicesStopped = false;
    setPhase('preparing');
    try {
      await invoke('prepare_update_install');
      servicesStopped = true;
      setPhase('installing');
      await candidate.install();
      // On Windows, Tauri exits the app after it successfully launches the installer.
    } catch (cause) {
      let message = cause?.message || String(cause);
      if (servicesStopped) {
        try {
          if (typeof window.__CLIPPY_RESTORE_SERVICES__ !== 'function') {
            throw new Error('The service recovery handler is unavailable.');
          }
          await window.__CLIPPY_RESTORE_SERVICES__();
          message += ' Clippy services were restarted.';
        } catch (recoveryError) {
          message += ' Service recovery failed: ' + (recoveryError?.message || String(recoveryError));
        }
      }
      setPhase('downloaded');
      setError(message);
    }
  };

  if (!isDesktop) return null;

  const downloadPercent = progress.total > 0
    ? Math.min(100, Math.round(progress.downloaded / progress.total * 100))
    : 0;

  return (
    <section className="card p-4 sm:p-6 mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
            <RefreshCw size={16} className="text-brass" />
          </div>
          <div>
            <h2 className="text-base font-medium text-ink">Clippy updates</h2>
            <p className="text-xs text-muted">Installed version: {version || 'Checking…'}</p>
          </div>
        </div>
        {phase === 'current' && <span className="badge-ok">Up to date</span>}
        {phase === 'available' && <span className="badge-warn">Update available</span>}
      </div>

      {update && (
        <div className="rounded-input border border-rule bg-paper2 p-3 mb-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-ink">Version {update.version}</p>
            {update.date && <p className="text-xs text-muted">{update.date}</p>}
          </div>
          <p className="text-xs text-muted leading-relaxed whitespace-pre-wrap mt-2">{update.notes}</p>
        </div>
      )}

      {phase === 'downloading' && (
        <div className="mb-4">
          <div className="flex justify-between text-xs text-muted mb-2">
            <span>Downloading and verifying update</span>
            <span>{progress.total > 0 ? downloadPercent + '%' : 'Downloading…'}</span>
          </div>
          <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
            <div className="h-full bg-brass transition-all" style={{ width: downloadPercent + '%' }} />
          </div>
        </div>
      )}

      {notice && <p className="text-xs text-ok mb-3">{notice}</p>}
      {error && (
        <div className="flex items-start gap-2 rounded-input border border-warn/30 bg-paper2 p-3 mb-4">
          <AlertTriangle size={15} className="text-warn shrink-0 mt-0.5" />
          <p className="text-xs text-muted whitespace-pre-wrap">{error}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {phase === 'available' && (
          <button onClick={downloadUpdate} className="btn-primary py-2 px-4 text-sm">
            <Download size={15} /> Download update
          </button>
        )}
        {phase === 'downloaded' && (
          <button onClick={installUpdate} className="btn-primary py-2 px-4 text-sm">
            <CheckCircle2 size={15} /> Install and restart
          </button>
        )}
        {phase === 'available' || phase === 'downloaded' ? (
          <button onClick={closeUpdate} className="btn-quiet py-2 px-4 text-sm">Cancel</button>
        ) : null}
        {phase === 'idle' || phase === 'current' ? (
          <button onClick={checkForUpdates} className="btn-quiet py-2 px-4 text-sm">
            <RefreshCw size={15} /> Check for updates
          </button>
        ) : null}
        {phase === 'checking' && <span className="text-xs text-muted py-2">Checking for updates…</span>}
        {phase === 'preparing' && <span className="text-xs text-muted py-2">Checking that Clippy is idle…</span>}
        {phase === 'installing' && <span className="text-xs text-muted py-2">Launching the Windows installer…</span>}
      </div>
    </section>
  );
}
