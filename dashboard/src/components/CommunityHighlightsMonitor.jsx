import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, Loader2, MessageCircle, Square, Radio, Trash2 } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import {
  isCommunityHighlightsProviderConnected,
  parseCommunityHighlightsStreamUrl,
} from '../lib/communityHighlights';

const TERMINAL_SESSION_STATES = new Set(['stopped', 'ended', 'error']);

const statusLabel = (status) => ({
  connecting: 'Connecting',
  connected: 'Monitoring chat',
  reconnecting: 'Reconnecting',
  error: 'Needs attention',
  ended: 'Chat ended',
  stopped: 'Stopped',
}[status] || status || 'Unknown');

export default function CommunityHighlightsMonitor({ connections, onOpenJob }) {
  const [streamUrl, setStreamUrl] = useState('');
  const [sessions, setSessions] = useState([]);
  const [captures, setCaptures] = useState([]);
  const [captureSettings, setCaptureSettings] = useState({ segment_seconds: 4, retention_seconds: 180, max_buffer_size_mb: 512, quality: 'best' });
  const [candidates, setCandidates] = useState([]);
  const [triggerSettings, setTriggerSettings] = useState({ phrases: ['clip it', 'clip that'], min_messages: 12, min_unique_users: 5, window_seconds: 10, cooldown_seconds: 60, pre_seconds: 45, post_seconds: 45 });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState('');
  const [previewCandidateId, setPreviewCandidateId] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewBusy, setPreviewBusy] = useState('');
  const previewObjectUrl = useRef(null);
  const previewAbort = useRef(null);
  const [startingAction, setStartingAction] = useState('');
  const [sessionActionBusy, setSessionActionBusy] = useState('');
  const [error, setError] = useState('');
  const requestedGenerationJobs = useRef(new Set());
  const openedGenerationJobs = useRef(new Set());

  useEffect(() => () => {
    previewAbort.current?.abort();
    previewAbort.current = null;
    if (previewObjectUrl.current) URL.revokeObjectURL(previewObjectUrl.current);
    previewObjectUrl.current = null;
  }, []);

  const closeCandidatePreview = useCallback(() => {
    previewAbort.current?.abort();
    previewAbort.current = null;
    if (previewObjectUrl.current) {
      URL.revokeObjectURL(previewObjectUrl.current);
      previewObjectUrl.current = null;
    }
    setPreviewUrl('');
    setPreviewCandidateId('');
    setPreviewBusy('');
  }, []);

  const openCandidatePreview = async (candidateId) => {
    if (previewAbort.current) return;
    setError('');
    setPreviewBusy(candidateId);
    setPreviewCandidateId(candidateId);
    setPreviewUrl('');
    if (previewObjectUrl.current) {
      URL.revokeObjectURL(previewObjectUrl.current);
      previewObjectUrl.current = null;
    }
    const controller = new AbortController();
    previewAbort.current = controller;
    try {
      const response = await apiFetch(
        '/api/community-highlights/candidates/' + encodeURIComponent(candidateId) + '/file',
        { signal: controller.signal },
      );
      if (!response.ok) throw new Error('The candidate preview is not ready.');
      const blob = await response.blob();
      if (controller.signal.aborted || previewAbort.current !== controller) return;
      const url = URL.createObjectURL(blob);
      previewObjectUrl.current = url;
      setPreviewUrl(url);
    } catch (requestError) {
      if (requestError?.name !== 'AbortError') {
        setError(requestError?.detail || requestError.message || 'Could not load the candidate preview.');
        setPreviewCandidateId('');
      }
    } finally {
      if (previewAbort.current === controller) {
        previewAbort.current = null;
        setPreviewBusy('');
      }
    }
  };

  useEffect(() => {
    if (previewCandidateId && !candidates.some((candidate) => candidate.candidate_id === previewCandidateId)) {
      closeCandidatePreview();
    }
  }, [candidates, previewCandidateId, closeCandidatePreview]);

  useEffect(() => {
    for (const candidate of candidates) {
      const jobId = candidate.generation_job_id;
      if (
        candidate.generation_status === 'completed'
        && jobId
        && requestedGenerationJobs.current.has(jobId)
        && !openedGenerationJobs.current.has(jobId)
      ) {
        openedGenerationJobs.current.add(jobId);
        onOpenJob?.(jobId);
        break;
      }
    }
  }, [candidates, onOpenJob]);

  const streamReference = parseCommunityHighlightsStreamUrl(streamUrl);
  const providerConnection = streamReference ? connections?.[streamReference.provider] : null;
  const providerName = streamReference?.provider === 'twitch' ? 'Twitch' : 'YouTube';
  const providerConnected = isCommunityHighlightsProviderConnected(streamReference, connections);
  const matchingChatSession = streamReference && sessions.find((session) => (
    session.provider === streamReference.provider
    && session.stream_id === streamReference.streamId
    && !['stopped', 'ended', 'error'].includes(session.status)
  ));
  const matchingCaptureSession = streamReference && captures.find((capture) => (
    capture.provider === streamReference.provider
    && capture.stream_id === streamReference.streamId
    && !['stopped', 'ended', 'error'].includes(capture.status)
  ));
  const busy = startingAction !== '';
  const connectionGuidance = !streamUrl.trim()
    ? 'Paste a Twitch channel or YouTube live/video URL. The matching provider account must be connected before you can start.'
    : !streamReference
      ? 'That link is not a supported Twitch channel or YouTube live/video URL.'
      : connections === undefined
        ? 'Checking saved streaming-account connections…'
        : connections === null
          ? 'Clippy could not verify the provider connection. Check the account-card error above; starting stays disabled until the status can be checked.'
          : providerConnected
            ? `${providerName} is connected. Start chat monitoring and rolling recording for this same stream.`
            : providerConnection?.status === 'storage_unavailable'
              ? 'Clippy cannot access Windows Credential Manager. Use the packaged Windows desktop app to connect a streaming account.'
              : providerConnection?.status === 'credential_error'
                ? `Clippy could not read the saved ${providerName} credentials. Reconnect that account in the card above.`
                : providerConnection?.authorization_available === false
                  ? `${providerName} sign-in is not configured for this installation. Check its OAuth app registration.`
                  : `Connect your ${streamReference.provider === 'youtube' ? 'Google account for YouTube' : 'Twitch account'} in the card above before starting this stream.`;

  const hasActiveWork = (
    sessions.some((session) => !TERMINAL_SESSION_STATES.has(session.status))
    || captures.some((capture) => !TERMINAL_SESSION_STATES.has(capture.status))
    || candidates.some((candidate) => candidate.status === 'capturing')
  );

  const refreshSessions = async () => {
    const [chatResult, captureResult, candidateResult] = await Promise.all([
      apiJson('/api/community-highlights/sessions'),
      apiJson('/api/community-highlights/captures'),
      apiJson('/api/community-highlights/candidates'),
    ]);
    setSessions(chatResult.sessions || []);
    setCaptures(captureResult.sessions || []);
    setCandidates(candidateResult.candidates || []);
  };

  useEffect(() => {
    // No readable provider status means the protected feature API cannot be
    // used. Avoid hammering it every three seconds in an unavailable state.
    if (!connections) return undefined;

    let active = true;
    const refresh = async () => {
      try {
        const [chatResult, captureResult, candidateResult] = await Promise.all([
          apiJson('/api/community-highlights/sessions'),
          apiJson('/api/community-highlights/captures'),
          apiJson('/api/community-highlights/candidates'),
        ]);
        if (active) {
          setSessions(chatResult.sessions || []);
          setCaptures(captureResult.sessions || []);
          setCandidates(candidateResult.candidates || []);
        }
      } catch (requestError) {
        if (active) setError(requestError?.detail || 'Could not load Community Highlights status.');
      }
    };

    refresh();
    const interval = hasActiveWork ? setInterval(refresh, 3000) : null;
    return () => {
      active = false;
      if (interval) clearInterval(interval);
    };
  }, [connections, hasActiveWork]);

  useEffect(() => {
    if (!connections) return undefined;
    let active = true;
    apiJson('/api/community-highlights/triggers/settings')
      .then((settings) => { if (active) setTriggerSettings(settings); })
      .catch((requestError) => { if (active) setError(requestError?.detail || 'Could not load trigger settings.'); });
    return () => { active = false; };
  }, [connections]);

  const startMonitoring = async () => {
    if (!streamReference || !providerConnected || connections == null) {
      setError(connectionGuidance);
      return;
    }
    if (matchingChatSession) {
      setError(`Chat monitoring is already active for this ${providerName} stream.`);
      return;
    }

    setError('');
    setStartingAction('chat');
    try {
      await apiJson('/api/community-highlights/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stream_url: streamUrl.trim() }),
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not start chat monitoring.');
    } finally {
      setStartingAction('');
    }
  };

  const startCapture = async () => {
    if (!streamReference || !providerConnected || connections == null) {
      setError(connectionGuidance);
      return;
    }
    if (matchingCaptureSession) {
      setError(`A rolling buffer is already running for this ${providerName} stream.`);
      return;
    }

    setError('');
    setStartingAction('capture');
    try {
      await apiJson('/api/community-highlights/captures', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stream_url: streamUrl.trim(), ...captureSettings }),
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not start rolling capture.');
    } finally {
      setStartingAction('');
    }
  };

  const stopCapture = async (sessionId) => {
    if (sessionActionBusy) return;
    setSessionActionBusy(`capture-stop:${sessionId}`);
    setError('');
    try {
      await apiJson(`/api/community-highlights/captures/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not stop rolling capture.');
    } finally {
      setSessionActionBusy('');
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
      anchor.download = `community-highlight-${candidateId}.mp4`;
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
    if (approved && !window.confirm(
      'Approve this highlight and generate one vertical Short? Confirm that you own this content or have permission to process it.'
    )) return;

    setReviewBusy(candidateId);
    setError('');
    try {
      if (approved) {
        const result = await apiJson('/api/process', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            community_candidate_id: candidateId,
            acknowledged: true,
            output_format: 'vertical',
            target_clips: 1,
          }),
        });
        if (!result?.job_id) throw new Error('Clippy did not return a generation job.');
        requestedGenerationJobs.current.add(result.job_id);
      } else {
        await apiJson(`/api/community-highlights/candidates/${encodeURIComponent(candidateId)}/decision`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approved: false }),
        });
      }
      if (previewCandidateId === candidateId) closeCandidatePreview();
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || requestError.message || (approved ? 'Could not generate a Short from this candidate.' : 'Could not reject the candidate.'));
      await refreshSessions().catch(() => {});
    } finally {
      setReviewBusy('');
    }
  };

  const deleteCandidate = async (candidateId) => {
    if (!window.confirm('Delete this highlight candidate and its local video file? This cannot be undone.')) return;
    if (previewCandidateId === candidateId) closeCandidatePreview();
    setReviewBusy(candidateId);
    setError('');
    try {
      await apiJson(`/api/community-highlights/candidates/${encodeURIComponent(candidateId)}`, {
        method: 'DELETE',
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not delete the highlight candidate.');
    } finally {
      setReviewBusy('');
    }
  };

  const triggerNow = async (sessionId) => {
    if (sessionActionBusy) return;
    setSessionActionBusy(`capture-trigger:${sessionId}`);
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
    } finally {
      setSessionActionBusy('');
    }
  };

  const stopMonitoring = async (sessionId) => {
    if (sessionActionBusy) return;
    setSessionActionBusy(`chat-stop:${sessionId}`);
    setError('');
    try {
      await apiJson(`/api/community-highlights/sessions/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not stop chat monitoring.');
    } finally {
      setSessionActionBusy('');
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
          disabled={!streamReference || !providerConnected || busy || !!matchingChatSession}
          onClick={startMonitoring}
          title={!providerConnected ? connectionGuidance : matchingChatSession ? 'Chat monitoring is already active for this stream.' : undefined}
          className="rounded-input bg-brass text-white px-5 py-2.5 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {startingAction === 'chat' ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />}
          {matchingChatSession ? 'Chat already active' : startingAction === 'chat' ? 'Starting…' : 'Monitor chat'}
        </button>
        <button
          type="button"
          disabled={!streamReference || !providerConnected || busy || !!matchingCaptureSession}
          onClick={startCapture}
          title={!providerConnected ? connectionGuidance : matchingCaptureSession ? 'A rolling buffer is already running for this stream.' : undefined}
          className="rounded-input border border-rule text-ink px-5 py-2.5 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {startingAction === 'capture' ? <Loader2 size={15} className="animate-spin" /> : <Radio size={15} />}
          {matchingCaptureSession ? 'Buffer already recording' : startingAction === 'capture' ? 'Starting…' : 'Record rolling buffer'}
        </button>
      </div>
      <p
        role={streamUrl.trim() && (!streamReference || (connections !== undefined && !providerConnected)) ? 'alert' : 'status'}
        className={`mt-3 text-xs leading-relaxed ${streamUrl.trim() && (!streamReference || (connections !== undefined && !providerConnected))
          ? 'rounded-input border border-rule bg-paper2 px-3 py-2 text-warn'
          : 'text-muted'}`}
      >
        {connectionGuidance}
      </p>
      <p className="text-[11px] text-muted mt-2">Capture settings apply to new rolling buffers. Keep the buffer longer than your combined pre/post-trigger window.</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          {[
            ['segment_seconds', 'Segment (s)', 1, 60],
            ['retention_seconds', 'Buffer (s)', 8, 3600],
            ['max_buffer_size_mb', 'Buffer cap (MB)', 16, 8192],
          ].map(([key, label, min, max]) => (
            <label key={key} className="text-xs text-muted">
              <span className="block mb-1">{key === 'segment_seconds' ? 'Segment length (s)' : key === 'retention_seconds' ? 'Buffer retention (s)' : label}</span>
              <input type="number" min={min} max={max} value={captureSettings[key]}
                onChange={(event) => setCaptureSettings((current) => ({ ...current, [key]: Number(event.target.value) }))}
                className="w-full rounded-input border border-rule bg-paper2 px-3 py-2 text-sm text-ink" />
            </label>
          ))}
          <label className="text-xs text-muted">
            <span className="block mb-1">Stream quality</span>
            <select value={captureSettings.quality}
              onChange={(event) => setCaptureSettings((current) => ({ ...current, quality: event.target.value }))}
              className="w-full rounded-input border border-rule bg-paper2 px-3 py-2 text-sm text-ink">
              <option value="best">Best available</option>
              <option value="1080p60">1080p60</option>
              <option value="1080p">1080p</option>
              <option value="720p60">720p60</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
              <option value="360p">360p</option>
              <option value="worst">Lowest available</option>
              <option value="audio_only">Audio only</option>
            </select>
          </label>
        </div>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 text-xs text-warn">
          <AlertCircle size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-5 space-y-3">
        {sessions.length === 0 ? (
          <div className="rounded-card border border-dashed border-rule p-5 text-center">
            <MessageCircle size={20} className="mx-auto text-muted mb-2" />
            <p className="text-sm text-ink2">No chats are being monitored.</p>
            <p className="text-xs text-muted mt-1">Connect the account for your stream above, then paste its Twitch channel or YouTube live/video URL.</p>
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
                {session.diagnostic && (
                  <p className="text-[11px] text-muted mt-1 break-words">
                    API diagnostic: {session.diagnostic.operation} · HTTP {session.diagnostic.http_status} · reason {session.diagnostic.reason}
                  </p>
                )}
              </div>
              <button type="button" onClick={() => stopMonitoring(session.session_id)}
                disabled={!!sessionActionBusy}
                className="shrink-0 rounded-input border border-rule px-3 py-2 text-xs text-muted hover:text-ink disabled:opacity-40 flex items-center gap-1.5">
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
        <h3 className="text-sm font-medium text-ink mb-1">Rolling recording buffers</h3>
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
                <div className="flex flex-wrap justify-end gap-2 max-w-full">
                  <button type="button" onClick={() => triggerNow(capture.session_id)}
                    disabled={capture.status !== 'recording' || !!sessionActionBusy}
                    className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">
                    Clip now
                  </button>
                  <button type="button" onClick={() => stopCapture(capture.session_id)}
                    disabled={['stopped', 'ended', 'error'].includes(capture.status) || !!sessionActionBusy}
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
        <h3 className="text-sm font-medium text-ink mb-2">Highlight trigger rules</h3>
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
        <h3 className="text-sm font-medium text-ink mb-3">Review highlights</h3>
        {candidates.length === 0 ? (
          <p className="text-xs text-muted">No candidates yet. Chat reactions will appear here when both monitoring and recording are active for the same stream.</p>
        ) : (
          <div className="space-y-2">
            {candidates.map((candidate) => (
              <div key={candidate.candidate_id} className="rounded-card border border-rule bg-paper2 p-3">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                  <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-ink">{candidate.reason === 'phrase' ? 'Chat phrase' : candidate.reason === 'chat_volume' ? 'Chat activity' : 'Manual clip'}</span>
                    <span className={candidate.status === 'ready' ? 'badge-ok' : 'readout'}>{candidate.status}</span>
                  </div>
                  <p className="text-xs text-muted mt-1">{candidate.pre_seconds}s before · {candidate.post_seconds}s after · {candidate.segment_count || 0} segments · {candidate.review_status || 'pending review'}</p>
                  {candidate.error && <p className="text-xs text-warn mt-1">{candidate.error}</p>}
                  {candidate.generation_error && <p className="text-xs text-warn mt-1">{candidate.generation_error}</p>}
                </div>
                <div className="flex gap-2 shrink-0">
                  {candidate.status === 'ready' && (
                    <>
                      {candidate.review_status !== 'rejected' && (
                        <>
                          <button type="button" onClick={() => openCandidatePreview(candidate.candidate_id)}
                            disabled={!!previewBusy || reviewBusy === candidate.candidate_id}
                            className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">
                            {previewBusy === candidate.candidate_id ? 'Loading…' : 'Preview'}
                          </button>
                          <button type="button" onClick={() => downloadCandidate(candidate.candidate_id)} disabled={reviewBusy === candidate.candidate_id}
                            className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">
                            {reviewBusy === candidate.candidate_id ? 'Working…' : 'Download'}
                          </button>
                        </>
                      )}
                      {candidate.review_status === 'pending' && (
                        <>
                          <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)} disabled={reviewBusy === candidate.candidate_id}
                            className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">
                            {reviewBusy === candidate.candidate_id ? 'Starting…' : 'Approve & Generate'}
                          </button>
                          <button type="button" onClick={() => decideCandidate(candidate.candidate_id, false)} disabled={reviewBusy === candidate.candidate_id}
                            className="rounded-input border border-rule px-3 py-2 text-xs text-muted disabled:opacity-40">Reject</button>
                        </>
                      )}
                      {candidate.review_status === 'approved' && candidate.generation_status === 'not_started' && (
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)} disabled={reviewBusy === candidate.candidate_id}
                          className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">Generate Short</button>
                      )}
                      {['staging', 'queued', 'processing'].includes(candidate.generation_status) && (
                        <span className="text-xs text-muted">{candidate.generation_status === 'staging' ? 'Preparing source…' : 'Generating Short…'}</span>
                      )}
                      {candidate.generation_status === 'failed' && (
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)} disabled={reviewBusy === candidate.candidate_id}
                          className="rounded-input border border-rule px-3 py-2 text-xs text-ink disabled:opacity-40">Retry Short</button>
                      )}
                      {candidate.generation_status === 'completed' && candidate.generation_job_id && (
                        <button type="button" onClick={() => { openedGenerationJobs.current.add(candidate.generation_job_id); onOpenJob?.(candidate.generation_job_id); }}
                          className="rounded-input border border-rule px-3 py-2 text-xs text-ink">Open Short</button>
                      )}
                    </>
                  )}
                  <button type="button" onClick={() => deleteCandidate(candidate.candidate_id)}
                    disabled={reviewBusy === candidate.candidate_id || candidate.status === 'capturing'}
                    title="Delete candidate and local file"
                    aria-label="Delete candidate"
                    className="rounded-input border border-rule px-3 py-2 text-xs text-muted hover:text-ink disabled:opacity-40">
                    <Trash2 size={13} />
                  </button>
                </div>
                </div>
                {previewCandidateId === candidate.candidate_id && (
                  <div className="mt-3 rounded-input border border-rule bg-paper3 p-3">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="text-xs font-medium text-ink">Clip preview</span>
                      <button type="button" onClick={closeCandidatePreview}
                        className="text-xs text-muted hover:text-ink">Close preview</button>
                    </div>
                    {previewUrl ? (
                      <video
                        key={previewUrl}
                        src={previewUrl}
                        controls
                        playsInline
                        preload="metadata"
                        className="w-full max-h-[420px] rounded-input bg-black"
                      />
                    ) : (
                      <p className="text-xs text-muted">{previewBusy === candidate.candidate_id ? 'Preparing preview…' : 'Preview unavailable.'}</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="mt-4 text-[11px] text-muted leading-relaxed">
        Completed highlights are saved as MP4 files for browser preview and download. Approving a candidate keeps it locally; rejecting or deleting it removes its media. Fine trimming and handoff to Clippy's main clip-generation pipeline are not available yet.
      </p>
    </section>
  );
}
