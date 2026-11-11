import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Cpu, Download, FolderOpen, HardDrive, RefreshCw, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { apiJson } from '../lib/api';

const MODEL_SIZES = ['tiny', 'base', 'small', 'medium', 'large-v3', 'large-v3-turbo'];

export default function LocalModelSettings() {
  const [data, setData] = useState(null);
  const [verification, setVerification] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const hasLoaded = useRef(false);
  const [modelSize, setModelSize] = useState('small');
  const [modelPath, setModelPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    const result = await apiJson('/api/local-models/whisper');
    setData(result);
    if (!hasLoaded.current) {
      setModelSize(result.selection?.model_size || 'small');
      setModelPath(result.selection?.source === 'local' ? result.selection.model_path || '' : '');
      hasLoaded.current = true;
    }
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.detail || err.message || 'Could not load local model settings.'));
  }, [refresh]);

  const downloadTasks = Object.values(data?.downloads || {});
  const activeDownload = downloadTasks.find((task) => ['queued', 'downloading'].includes(task.status));
  const completedDownload = downloadTasks.find((task) => task.status === 'complete');
  const failedDownload = downloadTasks.find((task) => task.status === 'failed');

  useEffect(() => {
    if (!activeDownload) return undefined;
    const timer = window.setInterval(() => {
      refresh().catch(() => {});
    }, 1800);
    return () => window.clearInterval(timer);
  }, [activeDownload, refresh]);

  const saveCatalogModel = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      await apiJson('/api/local-models/whisper/select', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_size: modelSize }),
      });
      setMessage(`Whisper ${modelSize} selected. It will be used for the next transcription.`);
      await refresh();
    } catch (err) {
      setError(err.detail || err.message || 'Could not save the model selection.');
    } finally { setBusy(false); }
  };

  const downloadModel = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      await apiJson('/api/local-models/whisper/download', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_size: modelSize }),
      });
      setMessage(`Downloading Whisper ${modelSize}. You can leave this page open while it finishes.`);
      await refresh();
    } catch (err) {
      setError(err.detail || err.message || 'Could not start the model download.');
    } finally { setBusy(false); }
  };

  const verifyModel = async () => {
    setVerifying(true); setError(''); setMessage(''); setVerification(null);
    try {
      const result = await apiJson('/api/local-models/whisper/verify', { method: 'POST' });
      setVerification(result);
    } catch (err) {
      setError(err.detail || err.message || 'Whisper model verification failed.');
    } finally { setVerifying(false); }
  };

  const useLocalFolder = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      await apiJson('/api/local-models/whisper/select', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_path: modelPath }),
      });
      setMessage('Existing Whisper model validated and selected.');
      await refresh();
    } catch (err) {
      setError(err.detail || err.message || 'That folder is not a supported faster-whisper model.');
    } finally { setBusy(false); }
  };

  return (
    <section className="card p-4 sm:p-6 mt-8">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
          <Cpu size={17} className="text-brass" />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-medium text-ink lowercase">Local runtime &amp; AI models</h2>
          <p className="text-xs text-muted">Application dependencies and model weights are managed separately.</p>
        </div>
      </div>

      <div className="rounded-input border border-rule bg-paper2 p-3 mb-5">
        <div className="flex items-center gap-2 text-sm text-ink">
          <CheckCircle2 size={15} className="text-ok shrink-0" />
          <strong>Core application dependencies</strong>
          <span className="badge-ok ml-auto">One-time setup</span>
        </div>
        <p className="text-xs text-muted leading-relaxed mt-2">
          On the first launch, Clippy's setup will install its required runtimes and libraries.
          It will show you what is being installed and the progress. These components stay
          installed for future launches and are not downloaded again unless an update or repair
          requires it. You do not need to manage Python, Node.js, FFmpeg, or GPU libraries yourself.
        </p>
      </div>

      <div className="flex items-start gap-2 mb-4">
        <HardDrive size={15} className="text-brass mt-0.5 shrink-0" />
        <div>
          <h3 className="text-sm font-medium text-ink">Whisper speech recognition model</h3>
          <p className="text-xs text-muted leading-relaxed mt-1">
            Whisper weights are separate from the core app. Choose a model to download, or use
            a compatible faster-whisper model already on your computer. Your choice is remembered.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <label className="block text-xs text-muted" htmlFor="clippy-whisper-size">Model size</label>
        <select id="clippy-whisper-size" value={modelSize} onChange={(e) => setModelSize(e.target.value)} className="input-field w-full">
          {(data?.models || MODEL_SIZES.map((id) => ({ id, label: id }))).map((model) => (
            <option key={model.id} value={model.id}>
              {model.label}{model.selected ? ' · selected' : ''}{model.downloaded ? ' · downloaded' : ' · not downloaded'}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted">
          {data?.models?.find((model) => model.id === modelSize)?.description || 'Choose the balance of speed, accuracy and memory use.'}
        </p>
        <div className="rounded-input border border-rule bg-paper2 p-3 space-y-1">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted">Saved model selection</span>
            <strong className="text-xs text-ink">
              {data?.selection?.source === 'local'
                ? 'Custom local model'
                : (data?.selection?.model_size || 'small').toUpperCase()}
            </strong>
          </div>
          <div className="text-xs">
            {data?.selection?.installed
              ? <span className="text-ok">Model files found and structurally valid</span>
              : <span className="text-warn">Selected, but model weights are not installed yet</span>}
          </div>
          {data?.selection?.source === 'local' && (
            <p className="break-all text-[11px] text-muted">{data.selection.model_path}</p>
          )}
        </div>
        <p className="text-xs text-muted">
          Saving a size records your choice. It does not claim the model is installed. Download it here,
          or allow faster-whisper to fetch it the first time transcription runs.
        </p>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={downloadModel} disabled={busy || Boolean(activeDownload)} className="btn-primary px-4 py-2 text-xs">
            {activeDownload ? <><Loader2 size={14} className="animate-spin" /> Downloading…</> : <><Download size={14} /> Download &amp; use model</>}
          </button>
          <button type="button" onClick={saveCatalogModel} disabled={busy} className="btn-quiet px-4 py-2 text-xs">
            Save selection
          </button>
          <button type="button" onClick={verifyModel} disabled={verifying || !data?.selection?.installed} className="btn-quiet px-4 py-2 text-xs">
            {verifying ? <><Loader2 size={14} className="animate-spin" /> Testing model…</> : <><CheckCircle2 size={14} /> Test model load</>}
          </button>
        </div>
      </div>

      <div className="border-t border-rule my-5" />
      <div className="flex items-center gap-2 mb-2">
        <FolderOpen size={15} className="text-brass" />
        <h3 className="text-sm font-medium text-ink">Use an existing model</h3>
      </div>
      <p className="text-xs text-muted mb-3">
        Enter the full path to a faster-whisper model folder, or directly to its model.bin file.
        The folder must contain model.bin, config.json, tokenizer.json and vocabulary.json.
      </p>
      <input
        type="text" value={modelPath} onChange={(e) => setModelPath(e.target.value)}
        className="input-field w-full" placeholder="D:\AI\Models\faster-whisper-small"
        aria-label="Existing Whisper model path"
      />
      <button type="button" onClick={useLocalFolder} disabled={busy || !modelPath.trim()} className="btn-quiet px-4 py-2 text-xs mt-2">
        <CheckCircle2 size={14} /> Validate &amp; use existing model
      </button>

      {activeDownload && (
        <div className="mt-4 rounded-input border border-rule bg-paper2 p-3 text-xs text-ink2 flex items-center gap-2">
          <Loader2 size={14} className="animate-spin text-brass" />
          {activeDownload.message || 'Downloading model files…'} This is a one-time model download.
        </div>
      )}
      {data?.selection?.available === false && (
        <div className="mt-4 text-xs text-warn">The previously selected model folder is unavailable. Select another model or update its path.</div>
      )}
      {completedDownload && (
        <div className="mt-4 text-xs text-ok flex items-center gap-2">
          <CheckCircle2 size={14} /> Whisper {completedDownload.model_size} is downloaded, saved as the active selection, and ready for verification.
        </div>
      )}
      {verification?.ok && (
        <div className="mt-4 rounded-input border border-ok/30 bg-paper2 p-3 text-xs text-ok space-y-1">
          <div className="flex items-center gap-2 font-medium"><CheckCircle2 size={14} /> Model loaded successfully</div>
          <p>{verification.message}</p>
          <p className="break-all text-muted">{verification.model_path}</p>
        </div>
      )}
      {failedDownload && (
        <div className="mt-4 text-xs text-warn flex items-center gap-2">
          <AlertCircle size={14} /> Model download failed: {failedDownload.message}
        </div>
      )}
      {message && <div className="mt-4 text-xs text-ok flex items-center gap-2"><CheckCircle2 size={14} />{message}</div>}
      {error && <div className="mt-4 text-xs text-warn flex items-center gap-2"><AlertCircle size={14} />{error}</div>}
      <div className="mt-4 text-xs text-muted flex items-start gap-2">
        <RefreshCw size={13} className="mt-0.5 shrink-0" />
        Models are stored separately from Clippy's installation, so application updates do not remove them.
      </div>
    </section>
  );
}
