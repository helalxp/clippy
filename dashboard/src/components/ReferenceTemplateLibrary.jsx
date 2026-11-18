import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Clock3, FileVideo, Loader2, RefreshCw,
  Sparkles, Upload, XCircle,
} from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';

const VIDEO_ACCEPT = 'video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo,.mp4,.mov,.mkv,.webm,.m4v,.avi';

const formatSeconds = (value) => {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return 'Unknown';
  const minutes = Math.floor(seconds / 60);
  return (minutes ? minutes + 'm ' : '') + Math.round(seconds % 60) + 's';
};

const formatBytes = (value) => {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return '—';
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(2) + ' GB';
  if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(1) + ' MB';
  return Math.round(bytes / 1024) + ' KB';
};

const titleCase = (value) => String(value || 'unknown').replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());

const STATUS = {
  queued: { label: 'Queued', icon: Clock3, tone: 'text-muted' },
  running: { label: 'Analyzing', icon: Loader2, tone: 'text-brass' },
  completed: { label: 'Analysis complete', icon: CheckCircle2, tone: 'text-emerald-600' },
  partial: { label: 'Partial analysis', icon: AlertTriangle, tone: 'text-amber-600' },
  failed: { label: 'Analysis failed', icon: XCircle, tone: 'text-danger' },
  cancelled: { label: 'Cancelled', icon: XCircle, tone: 'text-muted' },
};

function Confidence({ value }) {
  const tone = value === 'high' ? 'text-emerald-700 bg-emerald-500/10' :
    value === 'medium' ? 'text-brass bg-brass/10' : 'text-muted bg-paper2';
  return <span className={'inline-flex rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ' + tone}>{value || 'unknown'} confidence</span>;
}

function BoxSummary({ box }) {
  if (!box) return <span className="readout">Position unavailable</span>;
  const pct = (value) => Math.round(Number(value || 0) * 100) + '%';
  return <span className="readout">X {pct(box.x)} · Y {pct(box.y)} · W {pct(box.width)} · H {pct(box.height)}</span>;
}

function EvidenceFrame({ jobId, sample }) {
  const url = getApiUrl('/api/template-analysis/jobs/' + jobId + '/evidence/' + sample.asset_id);
  return (
    <figure className="min-w-0">
      <div className="aspect-video bg-paper2 rounded-input overflow-hidden border border-rule">
        <img src={url} alt={'Reference frame at ' + formatSeconds(sample.timestamp_ms / 1000)} className="w-full h-full object-contain" loading="lazy" />
      </div>
      <figcaption className="readout mt-1.5">{formatSeconds(sample.timestamp_ms / 1000)}</figcaption>
    </figure>
  );
}

export default function ReferenceTemplateLibrary() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [category, setCategory] = useState('');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [geminiConsent, setGeminiConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const data = await apiJson('/api/template-analysis/jobs');
      const nextJobs = data.jobs || [];
      setJobs(nextJobs);
      setSelectedJobId((current) => current && nextJobs.some((job) => job.id === current)
        ? current : (nextJobs[0]?.id || null));
      setError('');
    } catch (e) {
      setError(e?.detail || e?.message || 'Could not load reference analyses.');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const hasActiveJobs = useMemo(
    () => jobs.some((job) => ['queued', 'running'].includes(job.status)),
    [jobs],
  );

  useEffect(() => {
    if (!hasActiveJobs) return undefined;
    const timer = window.setInterval(() => load(true), 1800);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, load]);

  const selectedJob = jobs.find((job) => job.id === selectedJobId) || null;
  const report = selectedJob?.report || null;
  const deterministic = report?.deterministic || null;
  const visual = report?.ai_report || null;
  const samples = deterministic?.samples || [];
  const measurements = deterministic?.visual_measurements || [];

  const submit = async (event) => {
    event.preventDefault();
    if (!file || submitting || !rightsConfirmed) return;
    setSubmitting(true);
    setError('');
    try {
      const body = new FormData();
      body.append('video', file);
      body.append('name', name.trim());
      body.append('category', category.trim());
      body.append('rights_confirmed', 'true');
      body.append('gemini_consent', geminiConsent ? 'true' : 'false');
      const response = await apiFetch('/api/template-analysis/jobs', { method: 'POST', body });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Could not start reference analysis.');
      const job = payload.job;
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setSelectedJobId(job.id);
      setFile(null);
      setName('');
      setCategory('');
      setRightsConfirmed(false);
      const input = document.getElementById('template-reference-upload');
      if (input) input.value = '';
    } catch (e) {
      setError(e?.detail || e?.message || 'Could not start reference analysis.');
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async (jobId) => {
    try {
      const data = await apiJson('/api/template-analysis/jobs/' + jobId + '/cancel', { method: 'POST' });
      setJobs((current) => current.map((item) => item.id === jobId ? data.job : item));
    } catch (e) {
      setError(e?.detail || e?.message || 'Could not cancel analysis.');
    }
  };

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-8">
        <div>
          <p className="eyebrow text-brass mb-2">WORKSPACE · REFERENCE ANALYSIS</p>
          <h1 className="font-display text-3xl text-ink">Templates</h1>
          <p className="text-muted mt-2 max-w-3xl">
            Upload an already-edited video. Clippy extracts media facts, samples frames,
            measures visual properties and can ask Gemini to describe the editing treatment.
            This workbench analyzes references only; it does not change clip generation.
          </p>
        </div>
        <button onClick={() => load()} disabled={loading} className="btn-ghost px-4 py-2 text-sm shrink-0">
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <form onSubmit={submit} className="card p-5 sm:p-6 mb-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-input bg-brass/15 flex items-center justify-center">
            <Upload size={18} className="text-brass" />
          </div>
          <div>
            <h2 className="text-base font-medium text-ink">Analyze a finished reference video</h2>
            <p className="text-xs text-muted mt-0.5">Creates a durable analysis job. You can leave the page while it runs.</p>
          </div>
        </div>

        <div className="grid md:grid-cols-[1.4fr_1fr_1fr] gap-3">
          <label className="block">
            <span className="eyebrow mb-1.5 block">Reference video</span>
            <input id="template-reference-upload" type="file" accept={VIDEO_ACCEPT}
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              className="input-field !py-2.5" required />
            {file && <span className="readout mt-1.5 block">{file.name} · {formatBytes(file.size)}</span>}
          </label>
          <label className="block">
            <span className="eyebrow mb-1.5 block">Template name (optional)</span>
            <input value={name} onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Fast podcast captions" className="input-field !py-2.5" maxLength={120} />
          </label>
          <label className="block">
            <span className="eyebrow mb-1.5 block">Category (optional)</span>
            <input value={category} onChange={(event) => setCategory(event.target.value)}
              placeholder="Podcast, education, gaming…" className="input-field !py-2.5" maxLength={80} />
          </label>
        </div>

        <div className="mt-4 grid gap-3">
          <label className="flex items-start gap-3 text-sm text-ink2">
            <input type="checkbox" checked={rightsConfirmed}
              onChange={(event) => setRightsConfirmed(event.target.checked)} className="mt-1 accent-brass" />
            <span>I own this reference video or have permission to analyze it as an editing reference.</span>
          </label>
          <label className="flex items-start gap-3 text-sm text-ink2">
            <input type="checkbox" checked={geminiConsent}
              onChange={(event) => setGeminiConsent(event.target.checked)} className="mt-1 accent-brass" />
            <span>
              <span className="font-medium">Enable Gemini visual analysis.</span>
              <span className="block text-xs text-muted mt-0.5">
                Clippy sends bounded, resized sample frames and timestamps to Google, not the full source video.
                Without this consent, only deterministic media and pixel measurements run.
              </span>
            </span>
          </label>
        </div>

        <div className="mt-5 flex flex-col sm:flex-row sm:items-center gap-3">
          <button type="submit" disabled={!file || !rightsConfirmed || submitting}
            className="btn-primary px-5 py-2.5 text-sm disabled:opacity-50">
            {submitting ? <><Loader2 size={15} className="animate-spin" /> Uploading reference</> : <><Sparkles size={15} /> Start analysis</>}
          </button>
          <span className="text-xs text-muted">Fonts are ranked visual candidates, not verified original font-file identification.</span>
        </div>
      </form>

      {error && <div className="mb-6 rounded-input border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</div>}

      <div className="grid xl:grid-cols-[340px_minmax(0,1fr)] gap-5 items-start">
        <aside className="card p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink">Reference analyses</h2>
            <span className="readout">{jobs.length} jobs</span>
          </div>
          {loading && !jobs.length && <div className="py-10 flex justify-center"><Loader2 className="animate-spin text-brass" /></div>}
          {!loading && !jobs.length && (
            <div className="py-10 text-center">
              <FileVideo size={28} className="mx-auto text-brass mb-3" />
              <p className="text-sm text-ink font-medium">No reference analyses yet</p>
              <p className="text-xs text-muted mt-1">Upload a finished clip to create your first report.</p>
            </div>
          )}
          <div className="space-y-2">
            {jobs.map((job) => {
              const status = STATUS[job.status] || STATUS.queued;
              const Icon = status.icon;
              const active = ['queued', 'running'].includes(job.status);
              return (
                <button key={job.id} type="button" onClick={() => setSelectedJobId(job.id)}
                  className={'w-full text-left rounded-input border p-3 transition-colors ' + (selectedJobId === job.id ? 'border-brass bg-brass/5' : 'border-rule hover:bg-paper2')}>
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-ink truncate">{job.name || job.original_filename}</span>
                    <Icon size={14} className={status.tone + ' shrink-0 ' + (job.status === 'running' ? 'animate-spin' : '')} />
                  </span>
                  <span className="readout mt-1 block truncate">{job.category} · {formatBytes(job.source_size_bytes)}</span>
                  <span className={'text-[11px] mt-2 block ' + status.tone}>{status.label}{active ? ' · ' + (job.progress || 0) + '%' : ''}</span>
                  {active && <span className="block h-1 rounded-full bg-paper2 mt-2 overflow-hidden"><span className="block h-full bg-brass" style={{ width: Math.max(0, Math.min(100, job.progress || 0)) + '%' }} /></span>}
                </button>
              );
            })}
          </div>
        </aside>

        <section className="min-w-0 space-y-5">
          {!selectedJob && <div className="card p-10 text-center text-sm text-muted">Choose an analysis job to inspect its report.</div>}
          {selectedJob && (
            <>
              <div className="card p-5">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                  <div className="min-w-0">
                    <p className="eyebrow text-brass">ANALYSIS JOB</p>
                    <h2 className="text-xl font-semibold text-ink mt-1 break-words">{selectedJob.name || selectedJob.original_filename}</h2>
                    <p className="readout mt-1">{selectedJob.original_filename} · {formatBytes(selectedJob.source_size_bytes)}</p>
                    <video
                      className="mt-4 w-full max-h-[520px] rounded-input bg-black"
                      controls
                      playsInline
                      preload="metadata"
                      src={getApiUrl('/api/template-analysis/jobs/' + selectedJob.id + '/source')}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={'text-xs font-medium ' + ((STATUS[selectedJob.status] || STATUS.queued).tone)}>
                      {(STATUS[selectedJob.status] || STATUS.queued).label}
                    </span>
                    {['queued', 'running'].includes(selectedJob.status) && (
                      <button onClick={() => cancel(selectedJob.id)} className="btn-ghost px-3 py-1.5 text-xs">Cancel</button>
                    )}
                  </div>
                </div>
                {['queued', 'running'].includes(selectedJob.status) && (
                  <div className="mt-4">
                    <div className="flex justify-between readout"><span>{titleCase(selectedJob.stage)}</span><span>{selectedJob.progress || 0}%</span></div>
                    <div className="h-1.5 bg-paper2 rounded-full overflow-hidden mt-2"><div className="h-full bg-brass transition-all" style={{ width: Math.max(1, Math.min(100, selectedJob.progress || 1)) + '%' }} /></div>
                  </div>
                )}
                {selectedJob.error && <p className="mt-3 text-sm text-danger">{selectedJob.error}</p>}
              </div>

              {deterministic && (
                <>
                  <div className="card p-5">
                    <div className="flex items-center justify-between gap-3 mb-4">
                      <h3 className="font-semibold text-ink">Technical analysis</h3>
                      <span className="readout uppercase">{deterministic.status || 'unknown'} deterministic pass</span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                      {[
                        ['Duration', formatSeconds(deterministic.technical?.duration_seconds)],
                        ['Resolution', (deterministic.technical?.width || '—') + ' × ' + (deterministic.technical?.height || '—')],
                        ['Frame rate', deterministic.technical?.frame_rate ? deterministic.technical.frame_rate.toFixed(2) + ' fps' : '—'],
                        ['Codec', deterministic.technical?.video_codec || '—'],
                        ['Hard-cut candidates', (deterministic.scene_boundaries_seconds || []).length],
                        ['Frames sampled', samples.length],
                        ['Audio', deterministic.technical?.has_audio ? 'Present' : 'Not detected'],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-input bg-paper2 p-3">
                          <span className="readout block">{label}</span>
                          <span className="text-sm text-ink font-medium mt-1 block">{value}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4">
                      <p className="eyebrow mb-2">Analysis coverage</p>
                      <div className="grid sm:grid-cols-2 gap-2">
                        {Object.entries(deterministic.coverage || {}).map(([key, value]) => (
                          <div key={key} className="flex items-center gap-3 text-xs">
                            <span className="text-muted w-36 shrink-0">{titleCase(key)}</span>
                            <span className="h-1.5 bg-paper2 rounded-full flex-1 overflow-hidden"><span className="block h-full bg-brass" style={{ width: Math.round(value * 100) + '%' }} /></span>
                            <span className="readout w-10 text-right">{Math.round(value * 100)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  {samples.length > 0 && (
                    <div className="card p-5">
                      <h3 className="font-semibold text-ink mb-3">Sampled evidence frames</h3>
                      <p className="text-xs text-muted mb-4">These are the actual frames used by analysis. Every AI finding must cite this evidence set.</p>
                      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                        {samples.map((sample) => <EvidenceFrame key={sample.asset_id} jobId={selectedJob.id} sample={sample} />)}
                      </div>
                    </div>
                  )}

                  {measurements.length > 0 && (
                    <div className="card p-5">
                      <h3 className="font-semibold text-ink mb-3">Measured visual properties</h3>
                      <div className="space-y-3">
                        {measurements.map((measurement) => (
                          <div key={measurement.timestamp_ms} className="flex flex-wrap items-center gap-3 border-b border-rule last:border-0 pb-3 last:pb-0">
                            <span className="readout w-16">{formatSeconds(measurement.timestamp_ms / 1000)}</span>
                            <div className="flex gap-1.5">
                              {(measurement.dominant_colors || []).map((color) => (
                                <span key={color.hex_color} title={color.hex_color + ' · ' + Math.round(color.proportion * 100) + '%'}
                                  className="w-6 h-6 rounded-full border border-black/10" style={{ backgroundColor: color.hex_color }} />
                              ))}
                            </div>
                            <span className="readout">Luminance {Math.round((measurement.mean_luminance || 0) * 100)}%</span>
                            <span className="readout">Saturation {Math.round((measurement.mean_saturation || 0) * 100)}%</span>
                            <span className="readout">Edge density {Math.round((measurement.edge_density || 0) * 100)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {report && (
                <div className="card p-5 space-y-5">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="font-semibold text-ink">AI editing breakdown</h3>
                    <span className={'text-xs ' + (report.ai_status === 'complete' ? 'text-emerald-700' : report.ai_status === 'failed' ? 'text-danger' : 'text-muted')}>
                      {titleCase(report.ai_status)}
                    </span>
                  </div>
                  {visual ? (
                    <>
                      <div>
                        <p className="text-sm text-ink leading-relaxed">{visual.summary || 'No summary returned.'}</p>
                        {visual.visual_identity && <p className="text-sm text-muted mt-2">{visual.visual_identity}</p>}
                        {visual.editorial_style && <p className="text-sm text-muted mt-2">{visual.editorial_style}</p>}
                        {visual.overall_pacing && <p className="text-sm text-muted mt-2"><strong className="text-ink2">Pacing:</strong> {visual.overall_pacing}</p>}
                      </div>

                      {visual.text_regions?.length > 0 && (
                        <div>
                          <h4 className="text-sm font-semibold text-ink mb-3">Typography and text placement ({visual.text_regions.length})</h4>
                          <div className="space-y-3">
                            {visual.text_regions.map((region) => (
                              <article key={region.id} className="rounded-input border border-rule p-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="text-sm font-medium text-ink">{titleCase(region.role)}{region.visible_text ? ' · “' + region.visible_text + '”' : ''}</span>
                                  <Confidence value={region.confidence} />
                                </div>
                                <div className="mt-2 grid sm:grid-cols-2 gap-3">
                                  <div><span className="eyebrow block mb-1">Estimated frame position</span><BoxSummary box={region.box} /></div>
                                  <div><span className="eyebrow block mb-1">Typography</span><span className="text-xs text-ink2">{region.typography?.weight || 'Unknown weight'} · {region.typography?.style || 'unknown style'} · {region.typography?.size_ratio ? (region.typography.size_ratio * 100).toFixed(1) + '% frame height' : 'size unknown'}</span></div>
                                </div>
                                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                                  {region.typography?.fill_color && <span className="readout">Fill {region.typography.fill_color}</span>}
                                  {region.typography?.outline_color && <span className="readout">Outline {region.typography.outline_color}</span>}
                                  <span className="readout">Stroke {region.typography?.outline_strength || 'unknown'}</span>
                                  <span className="readout">Shadow {region.typography?.shadow || 'unknown'}</span>
                                  <span className="readout">Alignment {region.typography?.alignment || 'unknown'}</span>
                                </div>
                                {region.typography?.font_candidates?.length > 0 && (
                                  <div className="mt-3">
                                    <span className="eyebrow block mb-1">Likely font candidates, ranked</span>
                                    <div className="flex flex-wrap gap-2">
                                      {region.typography.font_candidates.map((font, index) => (
                                        <span key={font.family + index} className="rounded-input bg-paper2 px-2.5 py-1 text-xs text-ink2">{font.family} · {font.confidence}</span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                                {region.notes && <p className="text-xs text-muted mt-2">{region.notes}</p>}
                                <p className="readout mt-2">Evidence: {(region.evidence || []).map((item) => formatSeconds(item.timestamp_ms / 1000)).join(', ')}</p>
                              </article>
                            ))}
                          </div>
                        </div>
                      )}

                      {visual.graphic_overlays?.length > 0 && (
                        <div>
                          <h4 className="text-sm font-semibold text-ink mb-3">Logos and graphic overlays ({visual.graphic_overlays.length})</h4>
                          <div className="space-y-2">
                            {visual.graphic_overlays.map((item) => (
                              <div key={item.id} className="rounded-input border border-rule p-3">
                                <div className="flex justify-between gap-2"><span className="text-sm font-medium text-ink">{titleCase(item.kind)}</span><Confidence value={item.confidence} /></div>
                                <p className="text-xs text-muted mt-1">{item.description}</p>
                                <BoxSummary box={item.box} />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {visual.effects?.length > 0 && (
                        <div>
                          <h4 className="text-sm font-semibold text-ink mb-3">Effects and motion ({visual.effects.length})</h4>
                          <div className="space-y-2">
                            {visual.effects.map((item) => (
                              <div key={item.id} className="rounded-input border border-rule p-3">
                                <div className="flex justify-between gap-2"><span className="text-sm font-medium text-ink">{titleCase(item.kind)}</span><Confidence value={item.confidence} /></div>
                                <p className="text-xs text-muted mt-1">{item.description}</p>
                                {item.start_ms != null && item.end_ms != null && <p className="readout mt-2">{formatSeconds(item.start_ms / 1000)}–{formatSeconds(item.end_ms / 1000)}</p>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {visual.transitions?.length > 0 && (
                        <div>
                          <h4 className="text-sm font-semibold text-ink mb-3">Transitions ({visual.transitions.length})</h4>
                          <div className="space-y-2">
                            {visual.transitions.map((item) => (
                              <div key={item.id} className="rounded-input border border-rule p-3 flex items-start justify-between gap-3">
                                <div><span className="text-sm font-medium text-ink">{titleCase(item.kind)}</span><p className="readout mt-1">Around {formatSeconds(item.at_ms / 1000)} {item.duration_ms != null ? '· ' + item.duration_ms + ' ms' : ''}</p>{item.notes && <p className="text-xs text-muted mt-1">{item.notes}</p>}</div>
                                <Confidence value={item.confidence} />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {visual.scenes?.length > 0 && (
                        <div>
                          <h4 className="text-sm font-semibold text-ink mb-3">Scene and editorial breakdown ({visual.scenes.length})</h4>
                          <div className="space-y-2">
                            {visual.scenes.map((scene) => (
                              <div key={scene.index + '-' + scene.start_ms} className="rounded-input border border-rule p-3">
                                <div className="flex justify-between gap-2"><span className="text-sm font-medium text-ink">Scene {scene.index + 1}</span><span className="readout">{formatSeconds(scene.start_ms / 1000)}–{formatSeconds(scene.end_ms / 1000)}</span></div>
                                <p className="text-xs text-muted mt-1">{scene.description}</p>
                                <p className="readout mt-2">{titleCase(scene.content_type)} · {titleCase(scene.mood)} mood · {titleCase(scene.energy)} energy · {titleCase(scene.editorial_role)}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {visual.audio_treatment?.length > 0 && (
                        <div><h4 className="text-sm font-semibold text-ink mb-2">Audio notes</h4><ul className="list-disc pl-5 text-xs text-muted space-y-1">{visual.audio_treatment.map((note, i) => <li key={i}>{note}</li>)}</ul></div>
                      )}
                      {visual.limitations?.length > 0 && (
                        <div className="rounded-input bg-amber-500/10 p-3">
                          <h4 className="text-xs font-semibold text-ink mb-2">AI analysis limitations</h4>
                          <ul className="list-disc pl-5 text-xs text-muted space-y-1">{visual.limitations.map((note, i) => <li key={i}>{note}</li>)}</ul>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-sm text-muted">
                      {report.ai_error || (report.ai_status === 'not_consented'
                        ? 'Gemini was not enabled for this job. Deterministic media analysis is still available above.'
                        : 'No AI report was produced for this job.')}
                    </div>
                  )}
                </div>
              )}

              {deterministic?.limitations?.length > 0 && (
                <div className="rounded-input bg-amber-500/10 p-4">
                  <h3 className="text-xs font-semibold text-ink mb-2">Deterministic analysis limitations</h3>
                  <ul className="list-disc pl-5 text-xs text-muted space-y-1">{deterministic.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
