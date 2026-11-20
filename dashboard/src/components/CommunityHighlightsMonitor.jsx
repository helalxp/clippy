import { useEffect, useState } from 'react';
import { Activity, CircleAlert, Loader2, MessageCircle, Square, Radio } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';

const statusLabel = (status) => ({
  connecting: 'Connecting',
  connected: 'Monitoring chat',
  reconnecting: 'Reconnecting',
  error: 'Needs attention',
  ended: 'Chat ended',
  stopped: 'Stopped',
}[status] || status || 'Unknown');

export default function CommunityHighlightsMonitor() {
  const [streamUrl, setStreamUrl] = useState('');
  const [sessions, setSessions] = useState([]);
  const [captures, setCaptures] = useState([]);
  const [captureSettings, setCaptureSettings] = useState({ segment_seconds: 4, retention_seconds: 180, max_buffer_size_mb: 512, quality: 'best' });
  const [candidates, setCandidates] = useState([]);
  const [triggerSettings, setTriggerSettings] = useState({ phrases: ['clip it', 'clip that'], min_messages: 12, min_unique_users: 5, window_seconds: 10, cooldown_seconds: 60, pre_seconds: 45, post_seconds: 45 });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refreshSessions = async () => {
    const [chatResult, captureResult, candidateResult, settingsResult] = await Promise.all([
      apiJson('/api/community-highlights/sessions'),
      apiJson('/api/community-highlights/captures'),
      apiJson('/api/community-highlights/candidates'),
      apiJson('/api/community-highlights/triggers/settings'),
    ]);
    setSessions(chatResult.sessions || []);
    setCaptures(captureResult.sessions || []);
    setCandidates(candidateResult.candidates || []);
    setTriggerSettings(settingsResult);
  };

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const [chatResult, captureResult, candidateResult, settingsResult] = await Promise.all([
          apiJson('/api/community-highlights/sessions'),
          apiJson('/api/community-highlights/captures'),
          apiJson('/api/community-highlights/candidates'),
          apiJson('/api/community-highlights/triggers/settings'),
        ]);
        if (active) {
          setSessions(chatResult.sessions || []);
          setCaptures(captureResult.sessions || []);
          setCandidates(candidateResult.candidates || []);
          setTriggerSettings(settingsResult);
        }
      } catch (requestError) {
        if (active) setError(requestError?.detail || 'Could not load Community Highlights status.');
      }
    };
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const startMonitoring = async () => {
    setError('');
    setBusy(true);
    try {
      await apiJson('/api/community-highlights/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stream_url: streamUrl.trim(), ...captureSettings }),
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not start chat monitoring.');
    } finally {
      setBusy(false);
    }
  };

  const startCapture = async () => {
    setError('');
    setBusy(true);
    try {
      await apiJson('/api/community-highlights/captures', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stream_url: streamUrl.trim() }),
      });
      setStreamUrl('');
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not start rolling capture.');
    } finally {
      setBusy(false);
    }
  };

  const stopCapture = async (sessionId) => {
    setError('');
    try {
      await apiJson(`/api/community-highlights/captures/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not stop rolling capture.');
    }
  };


  const saveTriggerSettings = async () => {
    setError('');
    setSettingsBusy(true);
    try {
      const payload = {
        ...triggerSettings,
        phrases: Array.isArray(triggerSettings.phrases)
          ? triggerSettings.phrases
          : String(triggerSettings.phrases || '').split(',').map((item) => item.trim()).filter(Boolean),
      };
      const saved = await apiJson('/api/community-highlights/triggers/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setTriggerSettings(saved);
    } catch (requestError) {
      setError(requestError?.detail || 'Could not save trigger settings.');
    } finally {
      setSettingsBusy(false);
    }
  };


  const downloadCandidate = async (candidateId) => {
    setReviewBusy(candidateId);
    setError('');
    try {
      const response = await apiFetch(`/api/community-highlights/candidates/${encodeURIComponent(candidateId)}/file`);
      if (!response.ok) throw new Error('The candidate file is not ready to download.');
      const blobUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = blobUrl;
      anchor.download = `community-highlight-${candidateId}.ts`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    } catch (requestError) {
      setError(requestError?.detail || requestError.message || 'Could not download the candidate.');
    } finally {
      setReviewBusy('');
    }
  };

  const decideCandidate = async (candidateId, approved) => {
    setReviewBusy(candidateId);
    setError('');
    try {
      await apiJson(`/api/community-highlights/candidates/${encodeURIComponent(candidateId)}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved }),
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not save the candidate decision.');
    } finally {
      setReviewBusy('');
    }
  };

  const triggerNow = async (sessionId) => {
    setError('');
    try {
      await apiJson(`/api/community-highlights/captures/${encodeURIComponent(sessionId)}/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pre_seconds: triggerSettings.pre_seconds, post_seconds: triggerSettings.post_seconds, reason: 'manual' }),
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not create a highlight candidate.');
    }
  };

  const stopMonitoring = async (sessionId) => {
    setError('');
    try {
      await apiJson(`/api/community-highlights/sessions/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not stop chat monitoring.');
    }
  };

  return (
    <section className="card p-5 sm:p-7">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center shrink-0 text-brass">
          <Radio size={19} />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-medium text-ink">Monitor a live chat</h2>
          <p className="text-xs sm:text-sm text-muted mt-1 leading-relaxed">
            Paste a Twitch channel or YouTube live/video link. Start both chat monitoring and the rolling buffer on the same stream to let chat reactions create highlight candidates.
          </p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <input
          value={streamUrl}
          onChange={(event) => setStreamUrl(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && streamUrl.trim() && !busy) startMonitoring(); }}
          placeholder="https://www.twitch.tv/channel or YouTube live URL"
          aria-label="Twitch or YouTube stream URL"
          className="min-w-0 flex-1 rounded-input border border-rule bg-paper2 px-3 py-2.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:border-brass"
        />
        <button
          type="button"
          disabled={!streamUrl.trim() || busy}
          onClick={startMonitoring}
          className="rounded-input bg-brass text-white px-5 py-2.5 text-sm font-medium disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />}
          Monitor chat
        </button>
        <button
          type="button"
          disabled={!streamUrl.trim() || busy}
          onClick={startCapture}
          className="rounded-input border border-rule text-ink px-5 py-2.5 text-sm font-medium disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Radio size={15} />}
          Record rolling buffer
        </button>
      </div>
      <p className="text-[11px] text-muted mt-2">Capture settings apply to new rolling buffers. Keep the buffer longer than your combined pre/post-trigger window.</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          {[
            ['segment_seconds', 'Segment (s)', 1, 60],
            ['retention_seconds', 'Buffer (s)', 8, 3600],
            ['max_buffer_size_mb', 'Buffer cap (MB)', 16, 8192],
          ].map(([key, label, min, max]) => (
            <label key={key} className="text-xs text-muted">
              <span className="block mb-1">{label}</span>
              <input type="number" min={min} max={max} value={captureSettings[key]}
                onChange={(event) => setCaptureSettings((current) => ({ ...current, [key]: Number(event.target.value) }))}
                className="w-full rounded-input border border-rule bg-paper2 px-3 py-2 text-sm text-ink" />
            </label>
          ))}
          <label className="text-xs text-muted">
            <span className="block mb-1">Stream quality</span>
            <input value={captureSettings.quality}
              onChange={(event) => setCaptureSettings((current) => ({ ...current, quality: event.target.value }))}
              placeholder="best / 720p"
              className="w-full rounded-input border border-rule bg-paper2 px-3 py-2 text-sm text-ink" />
          </label>
        </div>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 text-xs text-warn">
          <CircleAlert size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-5 space-y-3">
        {sessions.length === 0 ? (
          <div className="rounded-card border border-dashed border-rule p-5 text-center">
            <MessageCircle size={20} className="mx-auto text-muted mb-2" />
            <p className="text-sm text-ink2">No chats are being monitored.</p>
            <p className="text-xs text-muted mt-1">Connect Twitch or Google above, then paste a live stream link.</p>
          </div>
        ) : sessions.map((session) => (
          <div key={session.session_id} className="rounded-card border border-rule bg-paper2 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-ink">{session.provider === 'twitch' ? 'Twitch' : 'YouTube'}</span>
                  <span className={session.status === 'connected' ? 'badge-ok' : 'readout'}>{statusLabel(session.status)}</span>
                </div>
                <p className="text-xs text-muted mt-1 break-all">{session.stream_id}</p>
                {session.error && <p className="text-xs text-warn mt-2">{session.error}</p>}
              </div>
              <button type="button" onClick={() => stopMonitoring(session.session_id)}
                className="shrink-0 rounded-input border border-rule px-3 py-2 text-xs text-muted hover:text-ink flex items-center gap-1.5">
                <Square size={12} /> Stop
              </button>
            </div>
            <div className="mt-3 pt-3 border-t border-rule">
              <div className="flex items-center justify-between text-[11px] text-muted mb-2">
                <span>Recent chat messages</span>
                <span>{session.message_count || 0} buffered</span>
              </div>
              {session.messages?.length ? (
                <div className="max-h-52 overflow-y-auto space-y-2 pr-1">
                  {session.messages.slice(-12).map((message) => (
                    <div key={message.message_id} className="text-xs leading-relaxed">
                      <span className="font-medium text-ink2">{message.sender_name}: </span>
                      <span className="text-muted break-words">{message.text}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted">Waiting for the first message…</p>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-6 pt-5 border-t border-rule">
        <h3 className="text-sm font-medium text-ink mb-1">Rolling footage buffers</h3>
        <p className="text-xs text-muted mb-3 leading-relaxed">
          Streamlink and FFmpeg keep a bounded local buffer. When chat monitoring is active for the same stream, configured phrase or chat-volume triggers protect the pre-trigger footage and collect the post-trigger window.
        </p>
        {captures.length === 0 ? (
          <p className="text-xs text-muted">No rolling captures are running.</p>
        ) : (
          <div className="space-y-2">
            {captures.map((capture) => (
              <div key={capture.session_id} className="rounded-card border border-rule bg-paper2 p-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium text-ink">{capture.provider === 'twitch' ? 'Twitch' : 'YouTube'}</span>
                    <span className={capture.status === 'recording' ? 'badge-ok' : 'readout'}>{capture.status}</span>
                  </div>
                  <p className="text-xs text-muted mt-1">{capture.stream_id} · {capture.segment_seconds}s segments · {capture.retention_seconds}s buffer</p>
                  {capture.error && <p className="text-xs text-warn mt-1">{capture.error}</p>}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button type="button" onClick={() => triggerNow(capture.session_id)}
                    disabled={capture.status !== 'recording'}
                    className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">
                    Clip now
                  </button>
                  <button type="button" onClick={() => stopCapture(capture.session_id)}
                    disabled={['stopped', 'ended', 'error'].includes(capture.status)}
                    className="rounded-input border border-rule px-3 py-2 text-xs text-muted hover:text-ink disabled:opacity-40 flex items-center gap-1.5">
                    <Square size={12} /> Stop
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="mt-6 pt-5 border-t border-rule">
        <h3 className="text-sm font-medium text-ink mb-2">Chat trigger rules</h3>
        <p className="text-xs text-muted mb-3">A matching phrase or a burst of chat activity creates a candidate, but only when the same stream has an active rolling capture.</p>
        <label className="block text-xs text-muted mb-1">Trigger phrases, comma-separated</label>
        <input
          value={Array.isArray(triggerSettings.phrases) ? triggerSettings.phrases.join(', ') : triggerSettings.phrases}
          onChange={(event) => setTriggerSettings((current) => ({ ...current, phrases: event.target.value }))}
          className="w-full rounded-input border border-rule bg-paper2 px-3 py-2 text-sm text-ink mb-3"
        />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            ['min_messages', 'Messages', 2, 500],
            ['min_unique_users', 'Unique viewers', 1, 500],
            ['window_seconds', 'Chat window (s)', 1, 120],
            ['cooldown_seconds', 'Cooldown (s)', 0, 3600],
            ['pre_seconds', 'Seconds before', 0, 300],
            ['post_seconds', 'Seconds after', 0, 300],
          ].map(([key, label, min, max]) => (
            <label key={key} className="text-xs text-muted">
              <span className="block mb-1">{label}</span>
              <input type="number" min={min} max={max} value={triggerSettings[key]}
                onChange={(event) => setTriggerSettings((current) => ({ ...current, [key]: Number(event.target.value) }))}
                className="w-full rounded-input border border-rule bg-paper2 px-3 py-2 text-sm text-ink" />
            </label>
          ))}
        </div>
        <button type="button" onClick={saveTriggerSettings} disabled={settingsBusy}
          className="mt-3 rounded-input border border-rule px-4 py-2 text-xs text-ink disabled:opacity-50">
          {settingsBusy ? 'Saving…' : 'Save trigger settings'}
        </button>
      </div>
      <div className="mt-6 pt-5 border-t border-rule">
        <h3 className="text-sm font-medium text-ink mb-3">Highlight candidates</h3>
        {candidates.length === 0 ? (
          <p className="text-xs text-muted">No candidates yet. Chat reactions will appear here when both monitoring and recording are active for the same stream.</p>
        ) : (
          <div className="space-y-2">
            {candidates.map((candidate) => (
              <div key={candidate.candidate_id} className="rounded-card border border-rule bg-paper2 p-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-ink">{candidate.reason === 'phrase' ? 'Chat phrase' : candidate.reason === 'chat_volume' ? 'Chat activity' : 'Manual clip'}</span>
                    <span className={candidate.status === 'ready' ? 'badge-ok' : 'readout'}>{candidate.status}</span>
                  </div>
                  <p className="text-xs text-muted mt-1">{candidate.pre_seconds}s before · {candidate.post_seconds}s after · {candidate.segment_count || 0} segments · {candidate.review_status || 'pending review'}</p>
                  {candidate.error && <p className="text-xs text-warn mt-1">{candidate.error}</p>}
                </div>
                {candidate.status === 'ready' && (
                  <div className="flex gap-2 shrink-0">
                    <button type="button" onClick={() => downloadCandidate(candidate.candidate_id)} disabled={reviewBusy === candidate.candidate_id}
                      className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">
                      {reviewBusy === candidate.candidate_id ? 'Working…' : 'Download'}
                    </button>
                    {candidate.review_status === 'pending' ? (
                      <>
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)} disabled={reviewBusy === candidate.candidate_id}
                          className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">Approve</button>
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, false)} disabled={reviewBusy === candidate.candidate_id}
                          className="rounded-input border border-rule px-3 py-2 text-xs text-muted disabled:opacity-40">Reject</button>
                      </>
                    ) : (
                      <span className="text-xs text-muted capitalize">{candidate.review_status}</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="mt-4 text-[11px] text-muted leading-relaxed">
        Candidates are assembled as lossless MPEG-TS files. Fine trimming, approval/rejection workflow, and MP4 delivery are the next stage.
      </p>
    </section>
  );
}
