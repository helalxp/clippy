import React, { useCallback, useEffect, useState } from 'react';
import { Archive, ChevronLeft, Download, Film, FolderOpen, Loader2, Pencil, Save, Trash2, X } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';

const PLATFORM_KEYS = ['youtube', 'instagram', 'tiktok'];
const invoke = (...args) => window.__TAURI__?.core?.invoke?.(...args);
const isDesktop = () => typeof window !== 'undefined' && typeof window.__TAURI__?.core?.invoke === 'function';

function prettySize(bytes = 0) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

async function saveResponse(response, filename) {
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(detail || `Download failed (HTTP ${response.status}).`);
  }
  const nativeInvoke = window.__TAURI__?.core?.invoke;
  if (typeof nativeInvoke !== 'function') {
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    return 'your browser Downloads folder';
  }

  let target = null;
  let received = 0;
  const expected = Number(response.headers.get('content-length')) || 0;
  try {
    target = await nativeInvoke('begin_file_download', { filename });
    const reader = response.body?.getReader?.();
    if (reader) {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (let offset = 0; offset < value.length; offset += 256 * 1024) {
          const part = value.subarray(offset, Math.min(offset + 256 * 1024, value.length));
          await nativeInvoke('append_file_download_chunk', { path: target.path, bytes: Array.from(part) });
          received += part.length;
        }
      }
    } else {
      const bytes = new Uint8Array(await response.arrayBuffer());
      for (let offset = 0; offset < bytes.length; offset += 256 * 1024) {
        const part = bytes.subarray(offset, Math.min(offset + 256 * 1024, bytes.length));
        await nativeInvoke('append_file_download_chunk', { path: target.path, bytes: Array.from(part) });
        received += part.length;
      }
    }
    if (expected && received !== expected) {
      throw new Error(`The download was incomplete (${received} of ${expected} bytes).`);
    }
    return await nativeInvoke('finish_file_download', { path: target.path });
  } catch (error) {
    if (target?.path) {
      await nativeInvoke('cancel_file_download', { path: target.path }).catch(() => {});
    }
    throw error;
  }
}

export default function LocalLibraryTab() {
  const [projects, setProjects] = useState(null);
  const [selected, setSelected] = useState(null);
  const [captions, setCaptions] = useState({});
  const [loadingClip, setLoadingClip] = useState(null);
  const [savingClip, setSavingClip] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [renaming, setRenaming] = useState(false);
  const [downloadPath, setDownloadPath] = useState('');
  const [keepSourceDefault, setKeepSourceDefault] = useState(false);
  const [savingRetention, setSavingRetention] = useState(false);

  const loadProjects = useCallback(async () => {
    setError('');
    try {
      const [data, settings] = await Promise.all([
        apiJson('/api/library/projects'),
        apiJson('/api/library/settings').catch(() => ({ keep_source_default: false })),
      ]);
      setProjects(data.projects || []);
      setKeepSourceDefault(!!settings.keep_source_default);
    } catch (err) {
      setError(err?.message || 'Could not load the local Library.');
      setProjects([]);
    }
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  const updateSourceRetention = async (enabled) => {
    const previous = keepSourceDefault;
    setKeepSourceDefault(enabled);
    setSavingRetention(true);
    setError('');
    try {
      const settings = await apiJson('/api/library/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep_source_default: enabled }),
      });
      setKeepSourceDefault(!!settings.keep_source_default);
    } catch (err) {
      setKeepSourceDefault(previous);
      setError(err?.message || 'Could not update source retention.');
    } finally {
      setSavingRetention(false);
    }
  };

  const openProject = async (project) => {
    setSelected(project);
    setRenameValue(project.title || '');
    setCaptions({});
    setDownloadPath('');
    setError('');
    setNotice('');
    setLoadingClip('all');
    try {
      const detail = await apiJson(`/api/library/projects/${project.project_id}`);
      setSelected(detail);
      setRenameValue(detail.title || '');
      const entries = await Promise.all((detail.clips || []).map(async (clip) => {
        try {
          const data = await apiJson(`/api/library/projects/${detail.project_id}/clips/${clip.clip_id}/captions`);
          return [clip.clip_id, data];
        } catch { return [clip.clip_id, { platforms: {} }]; }
      }));
      setCaptions(Object.fromEntries(entries));
    } catch (err) {
      setError(err?.message || 'Could not open this project.');
    } finally {
      setLoadingClip(null);
    }
  };

  const showInFolder = async (path) => {
    if (!isDesktop()) return;
    try {
      await invoke('reveal_library_path', { path });
    } catch (err) {
      setError(err?.message || 'Could not open this location in File Explorer.');
    }
  };

  const updatePlatform = (clipId, platform, field, value) => {
    setCaptions((current) => {
      const next = { ...current };
      const entry = { ...(next[clipId] || { platforms: {} }) };
      entry.platforms = { ...(entry.platforms || {}) };
      entry.platforms[platform] = { ...(entry.platforms[platform] || {}), [field]: value };
      next[clipId] = entry;
      return next;
    });
  };

  const saveClipCaptions = async (clipId) => {
    setSavingClip(clipId);
    setError('');
    try {
      await apiJson(`/api/library/projects/${selected.project_id}/clips/${clipId}/captions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platforms: captions[clipId]?.platforms || {} }),
      });
      setNotice('Captions saved.');
    } catch (err) {
      setError(err?.message || 'Could not save captions.');
    } finally {
      setSavingClip(null);
    }
  };

  const renameProject = async () => {
    if (!renameValue.trim()) return;
    setBusy('rename');
    try {
      const updated = await apiJson(`/api/library/projects/${selected.project_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: renameValue.trim() }),
      });
      setSelected(updated);
      setNotice('Project renamed.');
      await loadProjects();
    } catch (err) {
      setError(err?.message || 'Could not rename project.');
    } finally {
      setBusy('');
      setRenaming(false);
    }
  };

  const deleteProject = async () => {
    if (!selected || !window.confirm(`Delete “${selected.title}” and all of its archived clips? This cannot be undone.`)) return;
    setBusy('delete');
    try {
      await apiJson(`/api/library/projects/${selected.project_id}`, { method: 'DELETE' });
      setSelected(null);
      setNotice('Project deleted.');
      await loadProjects();
    } catch (err) {
      setError(err?.message || 'Could not delete project.');
    } finally {
      setBusy('');
    }
  };

  const deleteClip = async (clip) => {
    if (!window.confirm(`Delete clip ${clip.index + 1} from this project? This cannot be undone.`)) return;
    setBusy(`delete:${clip.clip_id}`);
    setError('');
    try {
      const response = await apiJson(`/api/library/projects/${selected.project_id}/clips/${clip.clip_id}`, { method: 'DELETE' });
      setSelected(response.project);
      setCaptions((current) => {
        const next = { ...current };
        delete next[clip.clip_id];
        return next;
      });
      setNotice('Clip deleted.');
      await loadProjects();
    } catch (err) {
      setError(err?.message || 'Could not delete this clip.');
    } finally {
      setBusy('');
    }
  };

  const downloadClip = async (clip) => {
    setBusy(`clip:${clip.clip_id}`);
    setError('');
    try {
      const response = await apiFetch(`/api/library/projects/${selected.project_id}/clips/${clip.clip_id}/video`);
      const path = await saveResponse(response, `${selected.title}-clip-${String(clip.index + 1).padStart(2, '0')}.mp4`);
      setDownloadPath(path);
      setNotice(path === 'your browser Downloads folder' ? 'Download started in your browser.' : `Saved: ${path}`);
    } catch (err) {
      setError(err?.message || 'Could not download this clip.');
    } finally {
      setBusy('');
    }
  };

  const downloadAll = async () => {
    setBusy('zip');
    setError('');
    try {
      const response = await apiFetch(`/api/library/projects/${selected.project_id}/download-all`);
      const safeTitle = (selected.title || 'project').replace(/[^a-z0-9-_ ]/gi, '').trim().slice(0, 60) || 'project';
      const path = await saveResponse(response, `Clippy-${safeTitle}.zip`);
      setDownloadPath(path);
      setNotice(path === 'your browser Downloads folder' ? 'ZIP download started in your browser.' : `Saved: ${path}`);
    } catch (err) {
      setError(err?.message || 'Could not export this project.');
    } finally {
      setBusy('');
    }
  };

  if (selected) {
    return (
      <div className="h-full overflow-y-auto p-4 sm:p-6 md:p-8 max-w-6xl mx-auto">
        <button onClick={() => { setSelected(null); setNotice(''); setError(''); }} className="btn-ghost px-3 py-2 text-xs mb-5">
          <ChevronLeft size={15} /> all projects
        </button>
        <div className="flex flex-wrap items-start justify-between gap-4 mb-7">
          <div className="min-w-0 flex-1">
            {renaming ? (
              <div className="flex gap-2 max-w-xl">
                <input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} maxLength={120} className="flex-1 min-w-0 bg-paper3 border border-rule rounded-input px-3 py-2 text-sm text-ink focus:outline-none focus:border-brass" autoFocus />
                <button onClick={renameProject} disabled={busy === 'rename'} className="btn-primary px-3"><Save size={15} /></button>
                <button onClick={() => { setRenaming(false); setRenameValue(selected.title); }} className="btn-ghost px-3"><X size={15} /></button>
              </div>
            ) : (
              <h1 className="font-display text-2xl text-ink break-words">{selected.title}</h1>
            )}
            <p className="text-muted text-sm mt-1">{selected.clip_count} clips · {selected.status} · {selected.source_video?.retained ? 'original source retained' : 'original source not retained'}</p>
            {selected.source_video?.retention_warning && (
              <p className="text-danger text-xs mt-2">{selected.source_video.retention_warning}</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setRenaming(true)} className="btn-ghost px-3 py-2 text-xs"><Pencil size={14} /> rename</button>
            {isDesktop() && <button onClick={() => showInFolder(selected.storage_path)} className="btn-ghost px-3 py-2 text-xs"><FolderOpen size={14} /> show in folder</button>}
            <button onClick={downloadAll} disabled={busy !== '' || !(selected.clips || []).length} className="btn-ghost px-3 py-2 text-xs">
              {busy === 'zip' ? <Loader2 size={14} className="animate-spin" /> : <Archive size={14} />} download project
            </button>
            <button onClick={deleteProject} disabled={busy !== ''} className="btn-ghost px-3 py-2 text-xs text-danger"><Trash2 size={14} /> delete</button>
          </div>
        </div>

        {error && <p className="text-danger text-sm mb-4">{error}</p>}
        {notice && <p className="text-sm text-brass mb-4">{notice}</p>}
        {downloadPath && downloadPath !== 'your browser Downloads folder' && isDesktop() && (
          <button onClick={() => invoke('reveal_file_download', { path: downloadPath }).catch((e) => setError(e.message))} className="text-xs text-brass hover:text-ink mb-4 flex items-center gap-2">
            <FolderOpen size={14} /> show downloaded file in folder
          </button>
        )}

        {(!selected.clips || selected.clips.length === 0) && (
          <div className="card p-8 text-center text-muted">
            <Film size={34} className="mx-auto mb-3" />
            <p className="text-sm text-ink">
              {selected.status === 'queued' || selected.status === 'processing'
                ? 'This project is still being generated. Its clips will appear here when they are ready.'
                : selected.status === 'interrupted'
                  ? 'Generation was interrupted. The project record is preserved, but no completed clips were archived.'
                  : selected.status === 'failed'
                    ? 'Generation failed before any clips could be saved.'
                    : selected.status === 'archive_failed'
                      ? 'Clips were generated, but archiving failed. Return to the active project and retry the Library sync.'
                      : 'No clips remain in this project.'}
            </p>
          </div>
        )}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {(selected.clips || []).map((clip) => {
            const data = captions[clip.clip_id] || { platforms: {} };
            return (
              <article key={clip.clip_id} className="card overflow-hidden">
                <div className="grid grid-cols-[minmax(120px,0.7fr)_minmax(0,1.3fr)] gap-4 p-4">
                  <div className="bg-black rounded-input overflow-hidden aspect-[9/16]">
                    <video controls preload="metadata" src={getApiUrl(`/api/library/projects/${selected.project_id}/clips/${clip.clip_id}/video`)} className="w-full h-full object-contain" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm text-ink font-medium">{clip.title || `Clip ${clip.index + 1}`}</p>
                    <p className="readout mt-1">{clip.start != null && clip.end != null ? `${Number(clip.start).toFixed(1)}s – ${Number(clip.end).toFixed(1)}s` : `Clip ${clip.index + 1}`}</p>
                    <div className="flex flex-wrap gap-2 mt-4">
                      <button onClick={() => downloadClip(clip)} disabled={busy !== ''} className="btn-ghost px-3 py-2 text-xs">
                        {busy === `clip:${clip.clip_id}` ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} download
                      </button>
                      {isDesktop() && (
                        <button onClick={() => showInFolder(`${selected.storage_path}/${clip.video_path}`)} className="btn-ghost px-3 py-2 text-xs">
                          <FolderOpen size={14} /> show in folder
                        </button>
                      )}
                      <button onClick={() => deleteClip(clip)} disabled={busy !== ''} className="btn-ghost px-3 py-2 text-xs text-danger">
                        {busy === `delete:${clip.clip_id}` ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} delete clip
                      </button>
                    </div>
                  </div>
                </div>
                <div className="border-t border-rule p-4 space-y-4">
                  <p className="text-xs uppercase tracking-wider text-muted">Platform captions</p>
                  {PLATFORM_KEYS.map((platform) => {
                    const value = data.platforms?.[platform] || {};
                    return (
                      <div key={platform} className="space-y-2">
                        <label className="text-xs text-ink capitalize">{platform}</label>
                        {platform === 'youtube' && (
                          <input value={value.title || ''} onChange={(e) => updatePlatform(clip.clip_id, platform, 'title', e.target.value)} placeholder="Short title" maxLength={100} className="w-full bg-paper3 border border-rule rounded-input px-3 py-2 text-sm text-ink focus:outline-none focus:border-brass" />
                        )}
                        <textarea value={value.caption || ''} onChange={(e) => updatePlatform(clip.clip_id, platform, 'caption', e.target.value)} placeholder={`${platform} caption`} rows={2} className="w-full bg-paper3 border border-rule rounded-input px-3 py-2 text-sm text-ink focus:outline-none focus:border-brass resize-y" />
                        <input value={Array.isArray(value.hashtags) ? value.hashtags.join(' ') : (value.hashtags || '')} onChange={(e) => updatePlatform(clip.clip_id, platform, 'hashtags', e.target.value.split(/\\s+/).filter(Boolean))} placeholder="#hashtags" className="w-full bg-paper3 border border-rule rounded-input px-3 py-2 text-sm text-ink focus:outline-none focus:border-brass" />
                      </div>
                    );
                  })}
                  <div className="flex justify-end">
                    <button onClick={() => saveClipCaptions(clip.clip_id)} disabled={savingClip === clip.clip_id} className="btn-primary px-3 py-2 text-xs">
                      {savingClip === clip.clip_id ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} save captions
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
        {loadingClip && <p className="text-muted text-sm mt-4 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> loading project…</p>}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 md:p-8 max-w-6xl mx-auto animate-fade">
      <p className="eyebrow mb-1.5">WORKSPACE · LIBRARY</p>
      <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
        <div>
          <h1 className="font-display lowercase text-2xl text-ink">your library</h1>
          <p className="text-muted text-sm mt-1">Your projects, clips and platform captions. Stored on this device.</p>
        </div>
        <button onClick={loadProjects} className="btn-ghost px-3 py-2 text-xs">refresh</button>
      </div>
      {error && <p className="text-danger text-sm my-4">{error}</p>}
      {notice && <p className="text-brass text-sm my-4">{notice}</p>}
      <div className="card p-4 mt-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-ink font-medium">Keep original footage for future re-editing</p>
          <p className="text-xs text-muted mt-1">Off by default. When enabled, Clippy copies the source into each new project's Library folder. Your original file is never moved or deleted. Uses additional disk space.</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink shrink-0">
          <input type="checkbox" checked={keepSourceDefault} disabled={savingRetention} onChange={(e) => updateSourceRetention(e.target.checked)} />
          {savingRetention ? 'saving…' : keepSourceDefault ? 'enabled for new projects' : 'disabled'}
        </label>
      </div>
      {projects === null ? (
        <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brass" /></div>
      ) : projects.length === 0 ? (
        <div className="text-center py-20 text-muted">
          <Film size={42} className="mx-auto mb-4" />
          <p>No projects in your Library yet.</p>
          <p className="text-xs mt-2">Completed projects are saved here automatically.</p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4 mt-7">
          {projects.map((project) => (
            <article key={project.project_id} className="card card-hover p-4">
              <button onClick={() => openProject(project)} className="text-left w-full min-w-0">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-11 h-11 rounded-input bg-paper3 flex items-center justify-center text-brass"><Film size={20} /></div>
                  <div className="min-w-0">
                    <h2 className="text-sm text-ink font-medium truncate">{project.title}</h2>
                    <p className="readout">{project.clip_count} clips · {project.status}</p>
                  </div>
                </div>
                <p className="text-xs text-muted">{project.created_at ? new Date(project.created_at).toLocaleDateString() : ''}</p>
              </button>
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-rule">
                <span className="readout">{prettySize(project.storage_size_bytes || 0)}</span>
                {isDesktop() && (
                  <button onClick={() => showInFolder(project.storage_path)} className="text-xs text-brass hover:text-ink flex items-center gap-1">
                    <FolderOpen size={13} /> show in folder
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
