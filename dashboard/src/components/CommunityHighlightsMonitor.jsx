import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, Loader2, MessageCircle, Square, Radio, Trash2 } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import {
  COMMUNITY_HIGHLIGHTS_TERMINAL_SESSION_STATES,
  communityHighlightsGeminiHeaders,
  isCommunityHighlightsProviderConnected,
  isCommunityHighlightsSessionActive,
  isCommunityHighlightsWorkflowActive,
  parseCommunityHighlightsStreamUrl,
  shouldContinueCommunityHighlightsStatusPolling,
} from '../lib/communityHighlights';

const TERMINAL_SESSION_STATES = COMMUNITY_HIGHLIGHTS_TERMINAL_SESSION_STATES;

const statusLabel = (status) => ({
  connecting: 'Connecting',
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  error: 'Needs attention',
  ended: 'Chat ended',
  stopped: 'Stopped',
  interrupted: 'Interrupted',
}[status] || status || 'Unknown');

const formatDuration = (seconds) => {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

export default function CommunityHighlightsMonitor({ connections, onOpenJob, geminiApiKey }) {
  const [streamUrl, setStreamUrl] = useState('');
  const [sessions, setSessions] = useState([]);
  const [captures, setCaptures] = useState([]);
  const [statusLoadFailed, setStatusLoadFailed] = useState(false);
  const [captureSettings, setCaptureSettings] = useState({ segment_seconds: 4, retention_seconds: 180, max_buffer_size_mb: 512, quality: 'best' });
  const [candidates, setCandidates] = useState([]);
  const [triggerSettings, setTriggerSettings] = useState({ phrases: ['clip it', 'clip that'], mode: 'either', min_messages: 12, min_unique_users: 5, window_seconds: 10, cooldown_seconds: 60, pre_seconds: 45, post_seconds: 45 });
  const [savedTriggerSettings, setSavedTriggerSettings] = useState(triggerSettings);
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
  const [pendingApprovalCandidateId, setPendingApprovalCandidateId] = useState('');
  const [pendingDeleteCandidateId, setPendingDeleteCandidateId] = useState('');
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
    && isCommunityHighlightsSessionActive(session)
  ));
  const matchingCaptureSession = streamReference && captures.find((capture) => (
    capture.provider === streamReference.provider
    && capture.stream_id === streamReference.streamId
    && isCommunityHighlightsSessionActive(capture)
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

  const workflowSessionsPresent = Boolean(matchingChatSession && matchingCaptureSession);
  const workflowActive = isCommunityHighlightsWorkflowActive(matchingChatSession, matchingCaptureSession);
  const workflowPartial = Boolean(matchingChatSession || matchingCaptureSession) && !workflowSessionsPresent;
  const triggerSettingsDirty = JSON.stringify(triggerSettings) !== JSON.stringify(savedTriggerSettings);

  const hasActiveWork = (
    sessions.some((session) => !TERMINAL_SESSION_STATES.has(session.status))
    || captures.some((capture) => !TERMINAL_SESSION_STATES.has(capture.status))
    || candidates.some((candidate) => candidate.status === 'capturing')
  );

  const refreshSessions = useCallback(async () => {
    try {
      const [chatResult, captureResult, candidateResult] = await Promise.all([
        apiJson('/api/community-highlights/sessions'),
        apiJson('/api/community-highlights/captures'),
        apiJson('/api/community-highlights/candidates'),
      ]);
      setSessions(chatResult.sessions || []);
      setCaptures(captureResult.sessions || []);
      setCandidates(candidateResult.candidates || []);
      setStatusLoadFailed(false);
    } catch (requestError) {
      setStatusLoadFailed(true);
      throw requestError;
    }
  }, []);

  useEffect(() => {
    // No readable provider status means the protected feature API cannot be
    // used. Avoid hammering it every three seconds in an unavailable state.
    if (!connections) return undefined;

    let active = true;
    const refresh = async () => {
      try {
        await refreshSessions();
      } catch (requestError) {
        if (active) setError(requestError?.detail || 'Could not load Community Highlights status.');
      }
    };

    refresh();
    const shouldPoll = shouldContinueCommunityHighlightsStatusPolling(
      hasActiveWork,
      statusLoadFailed,
    );
    const interval = shouldPoll ? setInterval(refresh, 3000) : null;
    return () => {
      active = false;
      if (interval) clearInterval(interval);
    };
  }, [connections, hasActiveWork, statusLoadFailed, refreshSessions]);

  useEffect(() => {
    if (!connections) return undefined;
    let active = true;
    apiJson('/api/community-highlights/triggers/settings')
      .then((settings) => {
        if (active) {
          setTriggerSettings(settings);
          setSavedTriggerSettings(settings);
        }
      })
      .catch((requestError) => { if (active) setError(requestError?.detail || 'Could not load trigger settings.'); });
    return () => { active = false; };
  }, [connections]);

  const startHighlighting = async () => {
    if (!streamReference || !providerConnected || connections == null) {
      setError(connectionGuidance);
      return;
    }

    setError('');
    setStartingAction('workflow');
    try {
      // Capture and chat starts are both idempotent. Do not attempt rollback if
      // chat start fails: the returned capture ID does not tell us whether this
      // click created the buffer or reused an existing one.
      if (!matchingCaptureSession) {
        await apiJson('/api/community-highlights/captures', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stream_url: streamUrl.trim(), ...captureSettings }),
        });
      }

      if (!matchingChatSession) {
        await apiJson('/api/community-highlights/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stream_url: streamUrl.trim() }),
        });
      }

      await refreshSessions().catch((refreshError) => {
        setError(refreshError?.detail || 'Highlighting started, but Clippy could not refresh the current status.');
      });
    } catch (requestError) {
      setError(requestError?.detail || requestError.message || 'Could not start Community Highlights.');
      await refreshSessions().catch(() => {});
    } finally {
      setStartingAction('');
    }
  };

  const stopOtherSession = async (item) => {
    if (sessionActionBusy) return;
    setSessionActionBusy(`other-stop:${item.id}`);
    setError('');
    try {
      const endpoint = item.type === 'chat' ? 'sessions' : 'captures';
      await apiJson(`/api/community-highlights/${endpoint}/${encodeURIComponent(item.id)}`, {
        method: 'DELETE',
      });
      await refreshSessions();
    } catch (stopError) {
      setError(stopError?.detail || `Could not stop the other ${item.type} session.`);
    } finally {
      setSessionActionBusy('');
    }
  };

  const stopHighlighting = async () => {
    if (sessionActionBusy) return;
    setSessionActionBusy('workflow-stop');
    setError('');
    const failures = [];

    if (matchingChatSession) {
      try {
        await apiJson(`/api/community-highlights/sessions/${encodeURIComponent(matchingChatSession.session_id)}`, {
          method: 'DELETE',
        });
      } catch (stopError) {
        failures.push(stopError?.detail || 'Could not stop chat monitoring.');
      }
    }

    if (matchingCaptureSession) {
      try {
        await apiJson(`/api/community-highlights/captures/${encodeURIComponent(matchingCaptureSession.session_id)}`, {
          method: 'DELETE',
        });
      } catch (stopError) {
        failures.push(stopError?.detail || 'Could not stop the rolling buffer.');
      }
    }

    await refreshSessions().catch(() => {});
    if (failures.length) setError(failures.join(' '));
    setSessionActionBusy('');
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
      setSavedTriggerSettings(saved);
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

  const decideCandidate = async (candidateId, approved, confirmed = false) => {
    if (approved && !confirmed) {
      setPendingApprovalCandidateId(candidateId);
      return;
    }

    setPendingApprovalCandidateId('');
    setReviewBusy(candidateId);
    setError('');
    try {
      if (approved) {
        const result = await apiJson('/api/process', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...communityHighlightsGeminiHeaders(geminiApiKey),
          },
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

  const deleteCandidate = async (candidateId, confirmed = false) => {
    if (!confirmed) {
      setPendingDeleteCandidateId(candidateId);
      return;
    }
    setPendingDeleteCandidateId('');
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
        body: JSON.stringify({ pre_seconds: savedTriggerSettings.pre_seconds, post_seconds: savedTriggerSettings.post_seconds, reason: 'manual' }),
      });
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not create a highlight candidate.');
    } finally {
      setSessionActionBusy('');
    }
  };

  const otherActiveSessions = [
    ...sessions.filter((session) => !TERMINAL_SESSION_STATES.has(session.status)
      && session.session_id !== matchingChatSession?.session_id).map((session) => ({
      id: session.session_id, provider: session.provider, stream_id: session.stream_id,
      type: 'chat', status: session.status,
    })),
    ...captures.filter((capture) => !TERMINAL_SESSION_STATES.has(capture.status)
      && capture.session_id !== matchingCaptureSession?.session_id).map((capture) => ({
      id: capture.session_id, provider: capture.provider, stream_id: capture.stream_id,
      type: 'buffer', status: capture.status,
    })),
  ];

  return (
    <div className="space-y-5">
      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-card border border-warn/30 bg-paper2 px-4 py-3 text-sm text-warn">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <section className="card p-5 sm:p-6 space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow mb-1">Live stream</p>
            <h2 className="text-lg font-medium text-ink">Start highlighting</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted">
              One start action connects chat and begins the rolling recording for the same stream.
            </p>
          </div>
          {workflowActive && <span className="badge-ok">● Highlighting</span>}
          {workflowSessionsPresent && !workflowActive && <span className="badge-warn">Not fully active</span>}
          {workflowPartial && <span className="badge-warn">Setup incomplete</span>}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="min-w-0 flex-1">
            <span className="mb-1.5 block text-xs font-medium text-ink2">Twitch channel or YouTube live/video URL</span>
            <input
              value={streamUrl}
              onChange={(event) => setStreamUrl(event.target.value)}
              disabled={workflowSessionsPresent || workflowPartial || busy}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && streamUrl.trim() && !busy && !workflowSessionsPresent) startHighlighting();
              }}
              placeholder="Paste stream link"
              aria-label="Twitch or YouTube stream URL"
              className="input-field"
            />
          </label>
          <button
            type="button"
            disabled={busy || !!sessionActionBusy || !streamReference || (!workflowSessionsPresent && (connections == null || !providerConnected))}
            onClick={workflowSessionsPresent ? stopHighlighting : startHighlighting}
            className={workflowSessionsPresent ? 'btn-ghost w-full sm:w-auto' : 'btn-primary w-full sm:w-auto'}
            title={!providerConnected && !workflowSessionsPresent ? connectionGuidance : undefined}
          >
            {busy || sessionActionBusy ? <Loader2 size={15} className="animate-spin" /> : workflowSessionsPresent ? <Square size={14} /> : <Activity size={15} />}
            {busy ? 'Starting…' : sessionActionBusy ? 'Stopping…' : workflowSessionsPresent ? 'Stop highlighting' : workflowPartial ? 'Finish setup' : 'Start highlighting'}
          </button>
        </div>

        <p
          role={streamUrl.trim() && (!streamReference || (connections !== undefined && !providerConnected && !workflowSessionsPresent)) ? 'alert' : 'status'}
          className={streamUrl.trim() && (!streamReference || (connections !== undefined && !providerConnected && !workflowSessionsPresent))
            ? 'rounded-input border border-warn/30 bg-paper2 px-3 py-2 text-xs text-warn'
            : 'text-xs leading-relaxed text-muted'}
        >
          {workflowActive
            ? 'Chat and recording are both active for this stream.'
            : workflowSessionsPresent
              ? 'Both sessions are present, but the workflow is not fully active. Check the chat and recording statuses below.'
              : workflowPartial
              ? 'One part is running. Finish setup to enable automatic highlights.'
              : connectionGuidance}
        </p>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="rounded-card border border-rule bg-paper2 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-sm font-medium text-ink">
                <MessageCircle size={15} className="text-muted" /> Chat
              </span>
              <span className={matchingChatSession?.status === 'connected' ? 'badge-ok' : matchingChatSession ? 'badge-warn' : 'readout'}>
                {matchingChatSession ? statusLabel(matchingChatSession.status) : 'Not started'}
              </span>
            </div>
            {matchingChatSession?.error && <p className="mt-2 text-xs text-warn">{matchingChatSession.error}</p>}
          </div>
          <div className="rounded-card border border-rule bg-paper2 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-sm font-medium text-ink">
                <Radio size={15} className="text-muted" /> Rolling buffer
              </span>
              <span className={matchingCaptureSession?.status === 'recording' ? 'badge-ok' : matchingCaptureSession ? 'badge-warn' : 'readout'}>
                {matchingCaptureSession?.status || 'Not started'}
              </span>
            </div>
            {matchingCaptureSession && (
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted">
                  {matchingCaptureSession.retention_seconds}s retained · {matchingCaptureSession.segment_seconds}s segments
                </p>
                {matchingCaptureSession.status === 'recording' && (
                  <button type="button" onClick={() => triggerNow(matchingCaptureSession.session_id)}
                    disabled={!!sessionActionBusy} className="btn-ghost text-xs">
                    Clip now
                  </button>
                )}
              </div>
            )}
            {matchingCaptureSession?.error && <p className="mt-2 text-xs text-warn">{matchingCaptureSession.error}</p>}
          </div>
        </div>

        {workflowPartial && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-3">
            <p className="text-xs text-muted">One part is already running. Finish setup to enable automatic highlights, or stop the active part.</p>
            <button type="button" onClick={stopHighlighting} disabled={!!sessionActionBusy} className="btn-ghost text-xs">
              Stop active sessions
            </button>
          </div>
        )}

        {otherActiveSessions.length > 0 && (
          <details className="border-t border-rule pt-3">
            <summary className="cursor-pointer text-xs font-medium text-muted">
              Other active streams ({otherActiveSessions.length})
            </summary>
            <div className="mt-3 space-y-2">
              {otherActiveSessions.map((item) => (
                <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="text-ink2">{item.provider === 'twitch' ? 'Twitch' : 'YouTube'} · {item.stream_id} · {item.type}</span>
                  <div className="flex items-center gap-2">
                    <span className="readout">{item.status}</span>
                    {item.type === 'buffer' && item.status === 'recording' && (
                      <button type="button" onClick={() => triggerNow(item.id)} disabled={!!sessionActionBusy}
                        className="text-xs text-muted underline underline-offset-2">Clip now</button>
                    )}
                    <button type="button" onClick={() => stopOtherSession(item)} disabled={!!sessionActionBusy}
                      className="text-xs text-muted underline underline-offset-2">Stop</button>
                  </div>
                </div>
              ))}
            </div>
          </details>
        )}

        <details className="border-t border-rule pt-3">
          <summary className="cursor-pointer text-sm font-medium text-ink">Capture quality and storage</summary>
          <p className="mt-2 text-xs text-muted">These settings apply when the next rolling buffer starts. They do not change an active recording.</p>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['segment_seconds', 'Segment length', 1, 60],
              ['retention_seconds', 'Buffer retention', 8, 3600],
              ['max_buffer_size_mb', 'Buffer cap (MB)', 16, 8192],
            ].map(([key, label, min, max]) => (
              <label key={key} className="text-xs text-muted">
                <span className="mb-1 block">{label}</span>
                <input type="number" min={min} max={max} value={captureSettings[key]}
                  onChange={(event) => setCaptureSettings((current) => ({ ...current, [key]: Number(event.target.value) }))}
                  className="input-field" />
              </label>
            ))}
            <label className="text-xs text-muted">
              <span className="mb-1 block">Stream quality</span>
              <select value={captureSettings.quality}
                onChange={(event) => setCaptureSettings((current) => ({ ...current, quality: event.target.value }))}
                className="input-field">
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
        </details>
      </section>

      <section className="card p-5 sm:p-6 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow mb-1">Preferences</p>
            <h2 className="text-lg font-medium text-ink">Trigger rules</h2>
            <p className="mt-1 text-sm text-muted">Choose what creates a highlight and how much footage to keep around it.</p>
          </div>
          {triggerSettingsDirty ? <span className="badge-warn">Unsaved changes</span> : <span className="badge-ok">Saved</span>}
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="text-xs text-muted">
            <span className="mb-1.5 block font-medium text-ink2">Create a highlight when</span>
            <select value={triggerSettings.mode || 'either'}
              onChange={(event) => setTriggerSettings((current) => ({ ...current, mode: event.target.value }))}
              className="input-field">
              <option value="either">A phrase matches or chat activity spikes</option>
              <option value="phrases">A configured phrase matches only</option>
              <option value="chat_volume">Chat activity reaches its threshold only</option>
            </select>
          </label>
          {triggerSettings.mode !== 'chat_volume' && (
            <label className="text-xs text-muted">
              <span className="mb-1.5 block font-medium text-ink2">Trigger phrases</span>
              <input
                value={Array.isArray(triggerSettings.phrases) ? triggerSettings.phrases.join(', ') : triggerSettings.phrases}
                onChange={(event) => setTriggerSettings((current) => ({ ...current, phrases: event.target.value }))}
                placeholder="clip it, clip that"
                className="input-field"
              />
            </label>
          )}
        </div>

        {triggerSettings.mode !== 'phrases' && (
          <div className="rounded-card border border-rule bg-paper2 p-4">
            <p className="text-sm font-medium text-ink">Chat activity threshold</p>
            <p className="mb-3 mt-1 text-xs text-muted">A burst must reach both the message and unique-viewer thresholds inside this window.</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {[
                ['min_messages', 'Messages', 2, 500],
                ['min_unique_users', 'Unique viewers', 1, 500],
                ['window_seconds', 'Window (seconds)', 1, 120],
              ].map(([key, label, min, max]) => (
                <label key={key} className="text-xs text-muted">
                  <span className="mb-1 block">{label}</span>
                  <input type="number" min={min} max={max} value={triggerSettings[key]}
                    onChange={(event) => setTriggerSettings((current) => ({ ...current, [key]: Number(event.target.value) }))}
                    className="input-field" />
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[
            ['pre_seconds', 'Footage before (seconds)', 0, 300],
            ['post_seconds', 'Footage after (seconds)', 0, 300],
            ['cooldown_seconds', 'Cooldown (seconds)', 0, 3600],
          ].map(([key, label, min, max]) => (
            <label key={key} className="text-xs text-muted">
              <span className="mb-1 block">{label}</span>
              <input type="number" min={min} max={max} value={triggerSettings[key]}
                onChange={(event) => setTriggerSettings((current) => ({ ...current, [key]: Number(event.target.value) }))}
                className="input-field" />
            </label>
          ))}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-3">
          <p className="text-xs text-muted">
            {triggerSettingsDirty
              ? 'Save changes before they are used by automatic triggers. Clip now uses the last saved window.'
              : 'Saved settings apply to new triggers, including triggers from an active chat.'}
          </p>
          <button type="button" onClick={saveTriggerSettings} disabled={settingsBusy || !triggerSettingsDirty} className="btn-ghost">
            {settingsBusy ? <Loader2 size={14} className="animate-spin" /> : null}
            {settingsBusy ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </section>

      <section className="card p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow mb-1">Review</p>
            <h2 className="text-lg font-medium text-ink">Highlights</h2>
          </div>
          <span className="readout">{candidates.filter((candidate) => candidate.status === 'ready').length} ready · {candidates.length} total</span>
        </div>

        {candidates.length === 0 ? (
          <div className="mt-4 rounded-card border border-dashed border-rule px-5 py-8 text-center">
            <Radio size={20} className="mx-auto text-muted" />
            <p className="mt-2 text-sm font-medium text-ink">No highlights yet</p>
            <p className="mt-1 text-xs text-muted">Start a stream above. New candidates will appear here when chat activity matches your rules.</p>
          </div>
        ) : (
          <div className="mt-4 divide-y divide-rule">
            {[...candidates].sort((a, b) => String(b.triggered_at).localeCompare(String(a.triggered_at))).map((candidate) => {
              const sourceSession = captures.find((capture) => capture.session_id === candidate.capture_session_id);
              const triggerCount = Math.max(1, Number(candidate.trigger_count) || 1);
              const preSeconds = Number(candidate.pre_seconds) || 0;
              const postSeconds = Number(candidate.post_seconds) || 0;
              const measuredDuration = Number(candidate.actual_duration_seconds);
              const measuredDurationLabel = Number.isFinite(measuredDuration) && measuredDuration > 0
                ? `Actual MP4: ${measuredDuration.toFixed(1)}s`
                : 'Actual duration unavailable';
              const reason = candidate.reason === 'phrase'
                ? 'Phrase matched'
                : candidate.reason === 'chat_volume'
                  ? 'Chat activity'
                  : 'Manual highlight';
              return (
                <article key={candidate.candidate_id} className="py-4 first:pt-4 last:pb-0">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{reason}</span>
                        <span className={candidate.status === 'ready' ? 'badge-ok' : candidate.status === 'error' ? 'badge-danger' : 'readout'}>
                          {candidate.status === 'ready' ? 'Ready to review' : candidate.status}
                        </span>
                        {triggerCount > 1 && <span className="readout">{triggerCount} triggers merged</span>}
                      </div>
                      <p className="mt-1 text-xs text-muted">
                        {sourceSession ? `${sourceSession.provider === 'twitch' ? 'Twitch' : 'YouTube'} · ${sourceSession.stream_id}` : 'Stream details unavailable'}
                        {' · '}Window: {formatDuration(preSeconds)} before + {formatDuration(postSeconds)} after
                        {' · '}{measuredDurationLabel}
                        {' · '}{candidate.segment_count || 0} segments
                      </p>
                      {candidate.error && <p className="mt-2 text-xs text-warn">{candidate.error}</p>}
                      {candidate.generation_error && <p className="mt-1 text-xs text-warn">{candidate.generation_error}</p>}
                      {candidate.generation_status === 'completed' && <p className="mt-1 text-xs text-ok">Short generated</p>}
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {candidate.status === 'ready' && candidate.review_status !== 'rejected' && (
                        <>
                          <button type="button" onClick={() => openCandidatePreview(candidate.candidate_id)}
                            disabled={!!previewBusy || reviewBusy === candidate.candidate_id} className="btn-ghost text-xs">
                            {previewBusy === candidate.candidate_id ? <Loader2 size={14} className="animate-spin" /> : null}
                            {previewBusy === candidate.candidate_id ? 'Loading' : 'Preview'}
                          </button>
                          <button type="button" onClick={() => downloadCandidate(candidate.candidate_id)}
                            disabled={reviewBusy === candidate.candidate_id} className="btn-ghost text-xs">Download</button>
                        </>
                      )}
                      {candidate.status === 'ready' && candidate.review_status === 'pending' && (
                        <>
                          <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)}
                            disabled={reviewBusy === candidate.candidate_id} className="btn-primary text-xs">Approve & generate</button>
                          <button type="button" onClick={() => decideCandidate(candidate.candidate_id, false)}
                            disabled={reviewBusy === candidate.candidate_id} className="btn-ghost text-xs">Reject</button>
                        </>
                      )}
                      {candidate.review_status === 'approved' && candidate.generation_status === 'not_started' && (
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)}
                          disabled={reviewBusy === candidate.candidate_id} className="btn-primary text-xs">Generate Short</button>
                      )}
                      {['staging', 'queued', 'processing'].includes(candidate.generation_status) && (
                        <span className="readout">{candidate.generation_status === 'staging' ? 'Preparing source' : 'Generating Short'}</span>
                      )}
                      {candidate.generation_status === 'failed' && (
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true)}
                          disabled={reviewBusy === candidate.candidate_id} className="btn-ghost text-xs">Retry Short</button>
                      )}
                      {candidate.generation_status === 'completed' && candidate.generation_job_id && (
                        <button type="button" onClick={() => {
                          openedGenerationJobs.current.add(candidate.generation_job_id);
                          onOpenJob?.(candidate.generation_job_id);
                        }} className="btn-ghost text-xs">Open Short</button>
                      )}
                      <button type="button" onClick={() => deleteCandidate(candidate.candidate_id)}
                        disabled={reviewBusy === candidate.candidate_id || candidate.status === 'capturing' || ['staging', 'queued', 'processing'].includes(candidate.generation_status)}
                        title="Delete highlight and local video" aria-label="Delete highlight"
                        className="btn-ghost !px-3 text-xs"><Trash2 size={14} /></button>
                    </div>
                  </div>

                  {pendingApprovalCandidateId === candidate.candidate_id && (
                    <div className="mt-3 rounded-card border border-rule bg-paper2 p-3">
                      <p className="text-sm text-ink">Approve this highlight and generate one vertical Short?</p>
                      <p className="mt-1 text-xs text-muted">Confirm that you own this content or have permission to process it.</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button type="button" onClick={() => decideCandidate(candidate.candidate_id, true, true)}
                          disabled={reviewBusy === candidate.candidate_id} className="btn-primary text-xs">Confirm & generate</button>
                        <button type="button" onClick={() => setPendingApprovalCandidateId('')} className="btn-ghost text-xs">Cancel</button>
                      </div>
                    </div>
                  )}

                  {pendingDeleteCandidateId === candidate.candidate_id && (
                    <div className="mt-3 rounded-card border border-rule bg-paper2 p-3">
                      <p className="text-sm text-ink">Delete this highlight and its local video?</p>
                      <p className="mt-1 text-xs text-muted">This cannot be undone.</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button type="button" onClick={() => deleteCandidate(candidate.candidate_id, true)}
                          disabled={reviewBusy === candidate.candidate_id} className="btn-danger text-xs">Delete highlight</button>
                        <button type="button" onClick={() => setPendingDeleteCandidateId('')} className="btn-ghost text-xs">Keep it</button>
                      </div>
                    </div>
                  )}

                  {previewCandidateId === candidate.candidate_id && (
                    <div className="mt-4 rounded-card border border-rule bg-paper2 p-3">
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <span className="text-sm font-medium text-ink">Preview</span>
                        <button type="button" onClick={closeCandidatePreview} className="text-xs text-muted underline underline-offset-2">Close</button>
                      </div>
                      {previewUrl ? (
                        <video key={previewUrl} src={previewUrl} controls playsInline preload="metadata"
                          className="max-h-[420px] w-full rounded-input bg-black" />
                      ) : (
                        <p className="text-xs text-muted">{previewBusy === candidate.candidate_id ? 'Preparing preview…' : 'Preview unavailable.'}</p>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        <p className="mt-4 border-t border-rule pt-3 text-xs text-muted">
          Approving a highlight creates one vertical Short in Clippy. Publishing remains a separate action.
        </p>
      </section>

      <details className="card p-4">
        <summary className="cursor-pointer text-sm font-medium text-ink">Live chat messages and diagnostics</summary>
        <div className="mt-3 space-y-4">
          {sessions.length === 0 ? (
            <p className="text-xs text-muted">No chat sessions are currently visible.</p>
          ) : sessions.map((session) => (
            <div key={session.session_id} className="border-t border-rule pt-3 first:border-0 first:pt-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-ink2">{session.provider === 'twitch' ? 'Twitch' : 'YouTube'} · {session.stream_id}</p>
                <span className="readout">{statusLabel(session.status)} · {session.message_count || 0} messages</span>
              </div>
              {session.error && <p className="mt-1 text-xs text-warn">{session.error}</p>}
              {session.diagnostic && (
                <p className="mt-1 text-xs text-muted">
                  {session.diagnostic.operation} · HTTP {session.diagnostic.http_status} · {session.diagnostic.reason}
                </p>
              )}
              {session.messages?.length ? (
                <div className="mt-2 max-h-40 space-y-1 overflow-y-auto pr-1">
                  {session.messages.slice(-8).map((message) => (
                    <p key={message.message_id} className="break-words text-xs text-muted">
                      <span className="font-medium text-ink2">{message.sender_name}: </span>{message.text}
                    </p>
                  ))}
                </div>
              ) : <p className="mt-2 text-xs text-muted">Waiting for messages.</p>}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
