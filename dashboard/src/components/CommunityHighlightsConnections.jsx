import { useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, LockKeyhole, Twitch, Loader2, ExternalLink, Unplug } from 'lucide-react';
import { apiJson } from '../lib/api';
import {
  navigateAuthorizationWindow,
  openAuthorizationPlaceholder,
} from '../lib/externalAuthorization';

const PROVIDERS = [
  {
    id: 'twitch',
    name: 'Twitch',
    action: 'Sign in with Twitch',
    description: 'Authorize Clippy to read Twitch chat activity for the live streams you choose to monitor.',
  },
  {
    id: 'youtube',
    name: 'YouTube',
    action: 'Sign in with Google',
    description: 'Sign in to Google to authorize YouTube live-chat access for Community Highlights. This is separate from your Clippy account: it does not sign you into Clippy or request access to Gmail. Google’s read-only YouTube permission can also cover other YouTube account data.',
  },
];

function ProviderMark({ provider }) {
  if (provider === 'twitch') return <Twitch size={20} />;
  return <span aria-hidden="true" className="font-bold text-lg tracking-tight bg-gradient-to-r from-blue-500 via-red-500 to-yellow-500 bg-clip-text text-transparent">G</span>;
}

async function openAuthorizationUrl(url, pendingWindow = null) {
  const tauri = window.__TAURI__;
  if (tauri?.core?.invoke) {
    await tauri.core.invoke('open_external_url', { url });
    return;
  }
  // When the URL is already known (the reopen action), open a fresh blank
  // context synchronously and sever opener before navigating to the provider.
  const opened = pendingWindow || openAuthorizationPlaceholder();
  navigateAuthorizationWindow(opened, url);
}

export default function CommunityHighlightsConnections({ compact = false, onConnectionsChange }) {
  const [connections, setConnections] = useState(null);
  const [connectionsLoading, setConnectionsLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [flow, setFlow] = useState(null);
  const [flowMessage, setFlowMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [busyProvider, setBusyProvider] = useState('');
  const pollTimer = useRef(null);
  const activeFlow = useRef(null);

  const refreshConnections = async () => {
    setConnectionsLoading(true);
    try {
      const data = await apiJson('/api/community-highlights/connections');
      const providers = data?.providers || {};
      setConnections(providers);
      onConnectionsChange?.(providers);
      return providers;
    } catch (requestError) {
      setConnections(null);
      onConnectionsChange?.(null);
      throw requestError;
    } finally {
      setConnectionsLoading(false);
    }
  };

  const retryConnections = async () => {
    setError('');
    try {
      await refreshConnections();
    } catch (requestError) {
      setError(requestError?.detail || 'Could not load provider connection status.');
    }
  };

  useEffect(() => {
    let active = true;
    apiJson('/api/community-highlights/connections')
      .then((data) => {
        if (active) {
          const providers = data?.providers || {};
          setConnections(providers);
          setConnectionsLoading(false);
          onConnectionsChange?.(providers);
        }
      })
      .catch((requestError) => {
        if (active) {
          setConnections(null);
          setConnectionsLoading(false);
          onConnectionsChange?.(null);
          setError(requestError?.detail || 'Could not load provider connection status.');
        }
      });
    return () => {
      active = false;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [onConnectionsChange]);

  const stopPolling = () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  };

  const pollAuthorization = async (flowId, provider) => {
    try {
      const result = await apiJson(`/api/community-highlights/${provider}/authorize/${encodeURIComponent(flowId)}`);
      setFlowMessage(result.message || 'Waiting for provider authorization.');
      if (result.status === 'pending') {
        pollTimer.current = setTimeout(() => pollAuthorization(flowId, provider), 2500);
        return;
      }
      activeFlow.current = null;
      setFlow(null);
      setBusy(false);
      setBusyProvider('');
      if (result.status === 'connected') await refreshConnections();
      else setError(result.message || 'Provider sign-in did not complete.');
    } catch (requestError) {
      activeFlow.current = null;
      setFlow(null);
      setBusy(false);
      setBusyProvider('');
      setError(requestError?.detail || 'Could not check provider authorization status.');
    }
  };

  const connectProvider = async (provider) => {
    let pendingWindow = null;
    setError('');
    setNotice('');
    setBusy(true);
    setBusyProvider(provider);
    setFlowMessage(`Starting secure ${provider === 'twitch' ? 'Twitch' : 'Google'} sign-in…`);
    try {
      // This runs synchronously in the click handler, before the async API call,
      // so popup blockers do not discard the eventual provider navigation.
      if (!window.__TAURI__) pendingWindow = openAuthorizationPlaceholder();
      const started = await apiJson(`/api/community-highlights/${provider}/authorize`, { method: 'POST' });
      activeFlow.current = started.flow_id;
      setFlow({ ...started, provider });
      setFlowMessage('Complete authorization in your browser. Clippy will finish connecting automatically.');
      await openAuthorizationUrl(started.verification_url || started.authorization_url, pendingWindow);
      pollTimer.current = setTimeout(() => pollAuthorization(started.flow_id, provider), provider === 'twitch'
        ? Math.max(1500, started.poll_interval * 1000)
        : 1500);
    } catch (requestError) {
      const flowId = activeFlow.current;
      activeFlow.current = null;
      if (pendingWindow && !pendingWindow.closed) pendingWindow.close();
      if (flowId) {
        try {
          await apiJson(`/api/community-highlights/${provider}/authorize/${encodeURIComponent(flowId)}`, { method: 'DELETE' });
        } catch (_) { /* server-side expiry also clears abandoned flows */ }
      }
      setBusy(false);
      setBusyProvider('');
      setFlow(null);
      setError(requestError?.detail || requestError?.message || 'Could not start provider sign-in.');
    }
  };

  const reopenAuthorization = async (url) => {
    setError('');
    try {
      await openAuthorizationUrl(url);
    } catch (requestError) {
      setError(requestError?.message || 'Could not open provider authorization.');
    }
  };

  const cancelAuthorization = async () => {
    stopPolling();
    const flowId = activeFlow.current;
    const provider = flow?.provider || 'twitch';
    activeFlow.current = null;
    setFlow(null);
    setBusy(false);
    setBusyProvider('');
    setFlowMessage('');
    if (flowId) {
      try {
        await apiJson(`/api/community-highlights/${provider}/authorize/${encodeURIComponent(flowId)}`, { method: 'DELETE' });
      } catch (_) { /* flow expiry also clears server-side state */ }
    }
  };

  const disconnectProvider = async (provider) => {
    if (provider === 'youtube' && !window.confirm(
      'Disconnect Google from Community Highlights? Google documents that revoking a token removes OAuth scopes granted to the same Google Cloud project and invalidates tokens for its registered clients. Continue?'
    )) return;
    setError('');
    setNotice('');
    setBusy(true);
    setBusyProvider(provider);
    try {
      const result = await apiJson(`/api/community-highlights/connections/${provider}`, { method: 'DELETE' });
      await refreshConnections();
      if (result?.message && result.revocation_status !== 'not_connected') {
        setNotice(result.message);
      }
    } catch (requestError) {
      setError(requestError?.detail || `Could not disconnect ${provider}.`);
    } finally {
      setBusy(false);
      setBusyProvider('');
    }
  };

  return (
    <section id={compact ? undefined : 'community-highlights-connections'} className={compact ? 'card p-4 sm:p-6 mb-6' : 'card p-5 sm:p-7'}>
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center shrink-0 text-brass">
          <Activity size={19} />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-medium text-ink lowercase">
            {compact ? 'Community Highlights accounts' : 'Connect your streaming accounts'}
          </h2>
          <p className="text-xs sm:text-sm text-muted mt-1 leading-relaxed">
            Sign in with the provider you want to monitor. Twitch and YouTube can be connected independently.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {PROVIDERS.map((provider) => {
          const state = connections?.[provider.id];
          const connected = state?.connected === true;
          const authorizationAvailable = state?.authorization_available === true;
          return (
            <div key={provider.id} className="rounded-card border border-rule bg-paper2 p-4 flex flex-col min-w-0">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0 text-ink2">
                    <ProviderMark provider={provider.id} />
                  </div>
                  <span className="font-medium text-ink">{provider.name}</span>
                </div>
                <span className={connected ? 'badge-ok shrink-0' : 'readout shrink-0'}>
                  {connectionsLoading ? 'Checking…' : connections === null ? 'Status unavailable' : connected ? 'Connected' : state?.status === 'storage_unavailable' ? 'Unavailable' : 'Not connected'}
                </span>
              </div>
              <p className="text-xs text-muted leading-relaxed flex-1">{provider.description}</p>
              {connected ? (
                <button type="button" disabled={busy} onClick={() => disconnectProvider(provider.id)}
                  className="mt-4 w-full rounded-input border border-rule bg-paper3 px-4 py-2.5 text-sm text-ink2 hover:bg-paper3 disabled:opacity-50 flex items-center justify-center gap-2">
                  <Unplug size={15} /> Disconnect {provider.name}
                </button>
              ) : flow?.provider === provider.id ? (
                <div className="mt-4 space-y-2">
                  <button type="button" onClick={() => reopenAuthorization(flow.verification_url || flow.authorization_url)}
                    className="w-full rounded-input border border-rule bg-paper3 px-4 py-2.5 text-sm text-ink2 hover:bg-paper3 flex items-center justify-center gap-2">
                    <ExternalLink size={15} /> Open {provider.name} authorization
                  </button>
                  <button type="button" onClick={cancelAuthorization}
                    className="w-full rounded-input border border-rule px-4 py-2 text-xs text-muted hover:text-ink">Cancel sign-in</button>
                </div>
              ) : (
                <button type="button" disabled={connectionsLoading || connections === null || !authorizationAvailable || busy}
                  onClick={() => connectProvider(provider.id)}
                  title={connectionsLoading
                    ? 'Checking saved provider connection status.'
                    : connections === null
                      ? 'Could not check saved provider connection status. Use Retry below.'
                      : !authorizationAvailable
                        ? `${provider.name} sign-in is not configured or secure storage is unavailable.`
                        : undefined}
                  className="mt-4 w-full rounded-input border border-rule bg-paper3 px-4 py-2.5 text-sm text-ink2 hover:bg-paper3 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                  {busy && busyProvider === provider.id ? <Loader2 size={15} className="animate-spin" /> : null}
                  {provider.action}
                </button>
              )}
              <p className="mt-2 text-[11px] text-muted/80">
                {flow?.provider === provider.id ? flowMessage
                  : connectionsLoading
                    ? 'Checking saved connection status…'
                    : connections === null
                      ? 'Could not check saved connections. Use Retry below.'
                      : state?.status === 'storage_unavailable'
                    ? 'Windows Credential Manager is available only in the packaged Windows app.'
                    : state?.status === 'credential_error'
                      ? 'Saved credentials need attention. Disconnect and sign in again.'
                      : connected
                        ? 'Provider tokens are stored securely in Windows Credential Manager.'
                        : !authorizationAvailable
                          ? `${provider.name} sign-in needs its app registration ID and Windows Credential Manager.`
                          : 'Sign-in is available.'}
              </p>
            </div>
          );
        })}
      </div>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 text-xs text-warn">
          <AlertCircle size={14} className="shrink-0 mt-0.5" />
          <span className="flex-1">{error}</span>
          {connections === null && (
            <button type="button" onClick={retryConnections} disabled={connectionsLoading}
              className="shrink-0 underline underline-offset-2 disabled:opacity-50">
              {connectionsLoading ? 'Checking…' : 'Retry'}
            </button>
          )}
        </div>
      )}
      {notice && (
        <p role="status" className="mt-4 text-xs text-muted leading-relaxed">{notice}</p>
      )}
      <div className="mt-5 pt-4 border-t border-rule flex items-start gap-2 text-xs text-muted leading-relaxed">
        <LockKeyhole size={14} className="shrink-0 mt-0.5 text-brass" />
        <span>Provider authorization stays separate from your Clippy sign-in. Tokens are stored in Windows Credential Manager, not browser storage or the regular settings file.</span>
      </div>
    </section>
  );
}
