import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Cpu, Download, FolderOpen, HardDrive, RefreshCw,
  CheckCircle2, AlertCircle, Loader2, CloudDownload,
} from 'lucide-react';
import { apiJson } from '../lib/api';

const MODEL_SIZES = ['tiny', 'base', 'small', 'medium', 'large-v3', 'large-v3-turbo'];

function modelLabel(models, size) {
  return models?.find((model) => model.id === size)?.label || size || 'Small';
}

function taskTimestamp(task) {
  return Number(task?.updated_at || task?.created_at || 0);
}

export default function LocalModelSettings() {
  const [data, setData] = useState(null);
  const [verification, setVerification] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const hasLoaded = useRef(false);
  const selectionDirtyRef = useRef(false);
  const [selectionDirty, setSelectionDirty] = useState(false);
  const [modelSize, setModelSize] = useState('small');
  const [modelPath, setModelPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    const result = await apiJson('/api/local-models/whisper');
    setData(result);
    // Polling must not overwrite a draft choice the user has not saved yet.
    if (!hasLoaded.current || !selectionDirtyRef.current) {
      setModelSize(result.selection?.model_size || 'small');
      setModelPath(result.selection?.source === 'local' ? result.selection.model_path || '' : '');
      selectionDirtyRef.current = false;
      setSelectionDirty(false);
    }
    hasLoaded.current = true;
    return result;
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.detail || err.message || 'Could not load local model settings.'));
  }, [refresh]);

  const downloadTasks = Object.values(data?.downloads || {}).sort(
    (a, b) => taskTimestamp(b) - taskTimestamp(a),
  );
  const activeDownload = downloadTasks.find(
    (task) => ['queued', 'downloading', 'verifying'].includes(task.status),
  );
  const latestFinishedDownload = downloadTasks.find(
    (task) => ['complete', 'failed'].includes(task.status),
  );
  const selectedModel = data?.selection;
  const selectedCatalogModel = data?.models?.find((model) => model.id === modelSize);
  const selectedAlreadyDownloaded = Boolean(selectedCatalogModel?.downloaded);
  const activeModelLabel = selectedModel?.source === 'local'
    ? 'Custom local model'
    : `Whisper ${modelLabel(data?.models, selectedModel?.model_size || 'small')}`;

  useEffect(() => {
    if (!activeDownload) return undefined;
    const timer = window.setInterval(() => {
      refresh().catch(() => {});
    }, 1800);
    return () => window.clearInterval(timer);
  }, [activeDownload?.status, activeDownload?.created_at, refresh]);

  const handleModelSizeChange = (value) => {
    setModelSize(value);
    const changed = selectedModel?.source === 'local'
      || value !== (selectedModel?.model_size || 'small');
    selectionDirtyRef.current = changed;
    setSelectionDirty(changed);
    setMessage('');
    setVerification(null);
  };

  const saveCatalogModel = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    setVerification(null);
    try {
      await apiJson('/api/local-models/whisper/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_size: modelSize }),
      });
      selectionDirtyRef.current = false;
      setSelectionDirty(false);
      setMessage(`Whisper ${modelSize} is now your saved model. It will be used for the next transcription.`);
      try {
        await refresh();
      } catch (_) {
        setError('Your selection was saved, but the status display could not refresh. Reopen Settings to confirm it.');
      }
    } catch (err) {
      setError(err.detail || err.message || 'Could not save the model selection.');
    } finally {
      setBusy(false);
    }
  };

  const downloadModel = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    setVerification(null);
    try {
      if (selectedAlreadyDownloaded) {
        await apiJson('/api/local-models/whisper/select', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_size: modelSize }),
        });
        selectionDirtyRef.current = false;
        setSelectionDirty(false);
        setMessage(`Whisper ${modelSize} was already downloaded and is now selected.`);
      } else {
        const result = await apiJson('/api/local-models/whisper/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_size: modelSize }),
        });
        selectionDirtyRef.current = false;
        setSelectionDirty(false);
        setMessage(`Whisper ${modelSize} download started. Your current model remains active until the download is verified.`);
      }
      try {
        await refresh();
      } catch (_) {
        setError('The request was accepted, but the model status could not refresh. Reopen Settings to check progress.');
      }
    } catch (err) {
      setError(err.detail || err.message || 'Could not start or select the Whisper model.');
    } finally {
      setBusy(false);
    }
  };

  const verifyModel = async () => {
    setVerifying(true);
    setError('');
    setMessage('');
    setVerification(null);
    try {
      const result = await apiJson('/api/local-models/whisper/verify', { method: 'POST' });
      setVerification(result);
    } catch (err) {
      setError(err.detail || err.message || 'Whisper model verification failed.');
    } finally {
      setVerifying(false);
    }
  };

  const useLocalFolder = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    setVerification(null);
    try {
      const result = await apiJson('/api/local-models/whisper/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_path: modelPath }),
      });
      selectionDirtyRef.current = false;
      setSelectionDirty(false);
      setModelPath(result.selection?.model_path || modelPath);
      setMessage('Existing Whisper model validated and selected.');
      try {
        await refresh();
      } catch (_) {
        setError('The model was selected, but the status display could not refresh. Reopen Settings to confirm it.');
      }
    } catch (err) {
      setError(err.detail || err.message || 'That folder is not a supported faster-whisper model.');
    } finally {
      setBusy(false);
    }
  };

  const selectionStatus = !selectedModel?.selected
    ? 'Default · Small'
    : selectedModel.installed
      ? 'Ready on this device'
      : 'Selected · download needed';

  return (
    <section className="card p-4 sm:p-6 mt-8 space-y-5">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
          <Cpu size={17} className="text-brass" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-medium text-ink lowercase">Local runtime &amp; AI models</h2>
          <p className="text-xs text-muted mt-1">Application dependencies and AI model weights are managed separately.</p>
        </div>
      </div>

      <div className="rounded-input border border-rule bg-paper2 p-3">
        <div className="flex items-center gap-2 text-sm text-ink">
          <CheckCircle2 size={15} className="text-ok shrink-0" />
          <strong>Core application dependencies</strong>
          <span className="badge-ok ml-auto">One-time setup</span>
        </div>
        <p className="text-xs text-muted leading-relaxed mt-2">
          Clippy installs its required runtimes and libraries during first-run setup.
          They stay installed across normal launches and are not downloaded again unless
          an update or repair requires it. You do not need to manage Python, Node.js,
          FFmpeg, or GPU libraries yourself.
        </p>
      </div>

      <div className="space-y-4">
        <div className="flex items-start gap-2">
          <HardDrive size={15} className="text-brass mt-0.5 shrink-0" />
          <div>
            <h3 className="text-sm font-medium text-ink">Whisper speech recognition</h3>
            <p className="text-xs text-muted leading-relaxed mt-1">
              Choose a model to download, use one already stored by Clippy, or register
              a compatible faster-whisper model folder. Your saved choice is remembered.
            </p>
          </div>
        </div>

        <div className="rounded-input border border-rule bg-paper2 p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] uppercase tracking-wider text-muted">Saved active model</span>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium ${
              selectedModel?.installed ? 'bg-ok/10 text-ok' : selectedModel?.selected ? 'bg-warn/10 text-warn' : 'bg-paper3 text-muted'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                selectedModel?.installed ? 'bg-ok' : selectedModel?.selected ? 'bg-warn' : 'bg-muted'
              }`} />
              {selectionStatus}
            </span>
          </div>
          <div className="text-sm font-medium text-ink">{activeModelLabel}</div>
          <p className="text-xs text-muted leading-relaxed">
            {selectedModel?.installed
              ? 'The selected model files are present and structurally valid.'
              : selectedModel?.selected
                ? 'This choice is saved, but its model files are not installed yet.'
                : 'No explicit choice has been saved. Clippy uses Small as its default.'}
          </p>
          {selectedModel?.source === 'local' && (
            <p className="text-[11px] text-muted break-all pt-1 border-t border-rule">{selectedModel.model_path}</p>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <label className="block text-xs text-muted" htmlFor="clippy-whisper-size">Model to use</label>
            {selectionDirty && (
              <span className="text-[10px] font-medium text-warn">Unsaved choice</span>
            )}
          </div>
          <select
            id="clippy-whisper-size"
            value={modelSize}
            onChange={(e) => handleModelSizeChange(e.target.value)}
            disabled={busy}
            className="input-field w-full"
          >
            {(data?.models || MODEL_SIZES.map((id) => ({ id, label: id }))).map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}{model.selected ? ' · active' : ''}{model.downloaded ? ' · downloaded' : ' · not downloaded'}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted">
            {selectedCatalogModel?.description || 'Choose the balance of speed, accuracy and memory use.'}
          </p>
          <p className="text-[11px] text-muted">
            Changing this menu does not switch models until you save the choice or use the model below.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={downloadModel}
            disabled={busy || Boolean(activeDownload)}
            className="btn-primary px-4 py-2 text-xs"
          >
            {busy
              ? <><Loader2 size={14} className="animate-spin" /> Working…</>
              : selectedAlreadyDownloaded
                ? <><CheckCircle2 size={14} /> Use downloaded model</>
                : <><Download size={14} /> Download &amp; use model</>}
          </button>
          <button
            type="button"
            onClick={saveCatalogModel}
            disabled={busy}
            className="btn-quiet px-4 py-2 text-xs"
          >
            Save selection
          </button>
          <button
            type="button"
            onClick={verifyModel}
            disabled={verifying || !selectedModel?.installed}
            className="btn-quiet px-4 py-2 text-xs"
          >
            {verifying
              ? <><Loader2 size={14} className="animate-spin" /> Testing model…</>
              : <><CheckCircle2 size={14} /> Test model load</>}
          </button>
        </div>
      </div>

      {activeDownload && (
        <div className="rounded-input border border-brass/30 bg-paper2 p-3 space-y-2" aria-live="polite">
          <div className="flex items-center gap-2">
            <Loader2 size={15} className="animate-spin text-brass shrink-0" />
            <strong className="text-xs text-ink">
              Whisper {modelLabel(data?.models, activeDownload.model_size)} · {
                activeDownload.status === 'queued' ? 'Queued'
                  : activeDownload.status === 'verifying' ? 'Verifying files'
                    : 'Downloading'
              }
            </strong>
            <span className="ml-auto text-[10px] text-muted">
              {activeDownload.status === 'verifying' ? 'Final check' : 'In progress'}
            </span>
          </div>
          <p className="text-xs text-muted leading-relaxed">
            {activeDownload.message || 'The model is being prepared.'}
            {' '}Your currently saved model remains available while this operation runs.
          </p>
          <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
            <div className={`h-full rounded-full bg-brass transition-all ${
              activeDownload.status === 'verifying' ? 'w-full' : 'w-2/5 animate-pulse'
            }`} />
          </div>
        </div>
      )}

      {!activeDownload && latestFinishedDownload?.status === 'complete' && (
        <div className="rounded-input border border-ok/25 bg-paper2 p-3 text-xs space-y-1" aria-live="polite">
          <div className="flex items-center gap-2 text-ok font-medium">
            <CheckCircle2 size={14} />
            Whisper {latestFinishedDownload.model_size} downloaded and verified
          </div>
          <p className="text-muted">
            {latestFinishedDownload.activated
              ? 'It is now the saved active model.'
              : 'Your newer saved selection was preserved. The downloaded model is available to select.'}
          </p>
        </div>
      )}

      {!activeDownload && latestFinishedDownload?.status === 'failed' && (
        <div className="rounded-input border border-warn/25 bg-paper2 p-3 text-xs space-y-1" aria-live="polite">
          <div className="flex items-center gap-2 text-warn font-medium">
            <AlertCircle size={14} /> Whisper download failed
          </div>
          <p className="text-muted break-words">{latestFinishedDownload.message}</p>
        </div>
      )}

      {verification?.ok && (
        <div className="rounded-input border border-ok/30 bg-paper2 p-3 text-xs text-ok space-y-1">
          <div className="flex items-center gap-2 font-medium"><CheckCircle2 size={14} /> Model loaded successfully</div>
          <p>{verification.message}</p>
          <p className="break-all text-muted">{verification.model_path}</p>
        </div>
      )}

      <div className="border-t border-rule pt-5 space-y-3">
        <div className="flex items-center gap-2">
          <FolderOpen size={15} className="text-brass" />
          <h3 className="text-sm font-medium text-ink">Use an existing model</h3>
        </div>
        <p className="text-xs text-muted leading-relaxed">
          Enter the full path to a faster-whisper model folder, or directly to its model.bin file.
          The folder must contain model.bin, config.json, tokenizer.json and vocabulary.json.
        </p>
        <input
          type="text"
          value={modelPath}
          onChange={(e) => setModelPath(e.target.value)}
          disabled={busy}
          className="input-field w-full"
          placeholder="D:\AI\Models\faster-whisper-small"
          aria-label="Existing Whisper model path"
        />
        <button
          type="button"
          onClick={useLocalFolder}
          disabled={busy || !modelPath.trim()}
          className="btn-quiet px-4 py-2 text-xs"
        >
          <CheckCircle2 size={14} /> Validate &amp; use existing model
        </button>
      </div>

      {message && (
        <div className="flex items-start gap-2 text-xs text-ok" role="status">
          <CheckCircle2 size={14} className="shrink-0 mt-0.5" /> {message}
        </div>
      )}
      {error && (
        <div className="flex items-start gap-2 text-xs text-warn" role="alert">
          <AlertCircle size={14} className="shrink-0 mt-0.5" /> {error}
        </div>
      )}

      <div className="text-[11px] text-muted flex items-start gap-2 border-t border-rule pt-3">
        <RefreshCw size={13} className="mt-0.5 shrink-0" />
        <span>
          Models stay separate from Clippy's application files and survive normal application updates.
          {data?.model_storage ? <> Storage: <span className="break-all">{data.model_storage}</span></> : null}
        </span>
      </div>
    </section>
  );
}
