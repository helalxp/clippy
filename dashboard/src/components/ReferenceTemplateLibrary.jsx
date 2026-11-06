import React, { useCallback, useEffect, useState } from 'react';
import { FileVideo, Loader2, Plus, RefreshCw, Sparkles } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';

const formatSeconds = (value) => {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return 'Unknown duration';
  const minutes = Math.floor(seconds / 60);
  return `${minutes ? `${minutes}m ` : ''}${Math.round(seconds % 60)}s`;
};

export default function ReferenceTemplateLibrary() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [category, setCategory] = useState('');
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiJson('/api/reference-templates');
      setTemplates(data.templates || []);
    } catch (e) {
      setError(e?.message || 'Could not load the reference template library.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submit = async (event) => {
    event.preventDefault();
    if (!file || uploading) return;
    setUploading(true);
    setError('');
    try {
      const body = new FormData();
      body.append('video', file);
      if (name.trim()) body.append('name', name.trim());
      if (category.trim()) body.append('category', category.trim());
      const response = await apiFetch('/api/reference-templates', { method: 'POST', body });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Reference analysis could not be completed.');
      }
      const created = await response.json();
      setTemplates((current) => [created, ...current]);
      setFile(null);
      setName('');
      setCategory('');
      const input = document.getElementById('reference-template-file');
      if (input) input.value = '';
    } catch (e) {
      setError(e?.message || 'Reference analysis could not be completed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-8">
        <div>
          <p className="eyebrow text-brass mb-2">WORKSPACE · REFERENCE STYLES</p>
          <h1 className="font-display text-3xl text-ink">Templates</h1>
          <p className="text-muted mt-2 max-w-2xl">Add a finished reference once. Clippy saves its source video, preview, and deterministic edit-rhythm analysis as a reusable local style record.</p>
        </div>
        <button onClick={load} disabled={loading} className="btn-ghost px-4 py-2 text-sm"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh</button>
      </div>

      <form onSubmit={submit} className="card p-5 sm:p-6 mb-6">
        <div className="flex items-center gap-3 mb-4"><div className="w-9 h-9 rounded-input bg-brass/15 flex items-center justify-center"><Plus size={18} className="text-brass" /></div><div><h2 className="text-base font-medium text-ink">Create from a reference video</h2><p className="text-xs text-muted mt-0.5">No LLM call: technical details and hard-cut rhythm are extracted locally.</p></div></div>
        <div className="grid md:grid-cols-[1.3fr_1fr_1fr_auto] gap-3 items-end">
          <label className="block"><span className="eyebrow mb-1.5 block">Reference video</span><input id="reference-template-file" type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo,.mp4,.mov,.mkv,.webm,.m4v,.avi" onChange={(e) => setFile(e.target.files?.[0] || null)} className="input-field !py-2.5" required /></label>
          <label className="block"><span className="eyebrow mb-1.5 block">Template name</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fast gaming commentary" className="input-field !py-2.5" /></label>
          <label className="block"><span className="eyebrow mb-1.5 block">Category</span><input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Gaming, podcast…" className="input-field !py-2.5" /></label>
          <button type="submit" disabled={!file || uploading} className="btn-primary px-4 py-2.5 text-sm">{uploading ? <><Loader2 size={15} className="animate-spin" /> Analyzing</> : <><Sparkles size={15} /> Analyze reference</>}</button>
        </div>
      </form>

      {error && <div className="mb-6 rounded-input border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</div>}
      {loading && <div className="py-16 flex justify-center"><Loader2 className="animate-spin text-brass" /></div>}
      {!loading && !templates.length && !error && <div className="card py-16 px-6 text-center"><FileVideo size={32} className="mx-auto text-brass mb-4" /><p className="text-ink font-medium">Your reference style library is empty.</p><p className="text-sm text-muted mt-2">Upload a finished gaming, podcast, motivational, or commentary clip to turn it into a reusable starting point.</p></div>}
      <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {templates.map((template) => {
          const technical = template.analysis?.technical || {};
          const pacing = template.analysis?.pacing || {};
          return <article key={template.id} className="card overflow-hidden">
            <div className="aspect-video bg-paper relative">
              {template.media?.poster_url ? <img src={getApiUrl(template.media.poster_url)} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full grid place-items-center"><FileVideo className="text-muted" /></div>}
              <span className="absolute top-3 left-3 badge-brass">Reference-derived</span>
            </div>
            <div className="p-4">
              <p className="text-sm font-medium text-ink truncate" title={template.name}>{template.name}</p>
              <p className="readout mt-1">{template.category || 'Uncategorized'} · {technical.aspect_ratio || 'unknown'}</p>
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-input bg-paper p-2.5"><span className="text-muted block">Reference</span><span className="text-ink mt-1 block">{formatSeconds(technical.duration_seconds)}</span></div>
                <div className="rounded-input bg-paper p-2.5"><span className="text-muted block">Pacing</span><span className="text-ink mt-1 block capitalize">{pacing.classification || 'Unknown'}</span></div>
                <div className="rounded-input bg-paper p-2.5"><span className="text-muted block">Hard cuts</span><span className="text-ink mt-1 block">{pacing.hard_cut_count ?? '—'}</span></div>
                <div className="rounded-input bg-paper p-2.5"><span className="text-muted block">Avg. shot</span><span className="text-ink mt-1 block">{pacing.average_shot_seconds ? `${pacing.average_shot_seconds}s` : '—'}</span></div>
              </div>
              <p className="text-xs text-muted mt-4 leading-relaxed">Framing, captions, background, and watermark analysis will be added to this saved blueprint next; nothing has been falsely applied yet.</p>
            </div>
          </article>;
        })}
      </div>
    </div>
  );
}
