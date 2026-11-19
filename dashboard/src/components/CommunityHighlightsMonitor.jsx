import { useEffect, useState } from 'react';
import { Activity, CircleAlert, Loader2, MessageCircle, Square, Radio } from 'lucide-react';
import { apiJson } from '../lib/api';

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refreshSessions = async () => {
    const result = await apiJson('/api/community-highlights/sessions');
    setSessions(result.sessions || []);
  };

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const result = await apiJson('/api/community-highlights/sessions');
        if (active) setSessions(result.sessions || []);
      } catch (requestError) {
        if (active) setError(requestError?.detail || 'Could not load chat sessions.');
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
        body: JSON.stringify({ stream_url: streamUrl.trim() }),
      });
      setStreamUrl('');
      await refreshSessions();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not start chat monitoring.');
    } finally {
      setBusy(false);
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
            Paste a Twitch channel or YouTube live/video link. Clippy will connect to its chat and collect messages for the upcoming trigger-detection stage.
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
      <p className="mt-4 text-[11px] text-muted leading-relaxed">
        This milestone monitors chat only. Stream recording, rolling footage buffers, and automatic highlight capture are the next implementation stage.
      </p>
    </section>
  );
}
