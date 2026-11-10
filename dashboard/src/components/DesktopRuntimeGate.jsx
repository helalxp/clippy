import { useCallback, useEffect, useState } from 'react';

function getDesktopInvoke() {
  return window.__TAURI__?.core?.invoke;
}

/**
 * The web build remains unchanged. In the native build, do not expose API-driven
 * screens until the Rust supervisor has confirmed that both local services are
 * healthy. This turns confusing fetch/model-download failures into a clear
 * first-run dependency message.
 */
export default function DesktopRuntimeGate({ children }) {
  const invoke = getDesktopInvoke();
  const isDesktop = typeof invoke === 'function';
  const [state, setState] = useState({ status: isDesktop ? 'starting' : 'ready', error: '' });
  const [attempt, setAttempt] = useState(0);

  const start = useCallback(async () => {
    if (!isDesktop) return;
    setState({ status: 'starting', error: '' });
    try {
      await invoke('start_services');
      setState({ status: 'ready', error: '' });
    } catch (error) {
      setState({
        status: 'setup-required',
        error: typeof error === 'string' ? error : error?.message || String(error),
      });
    }
  }, [invoke, isDesktop]);

  useEffect(() => {
    start();
  }, [start, attempt]);

  if (!isDesktop || state.status === 'ready') return children;

  return (
    <main className="min-h-screen bg-paper text-ink2 flex items-center justify-center p-6">
      <section className="card w-full max-w-2xl p-6 sm:p-8">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center text-brass font-semibold">C</div>
          <div>
            <h1 className="text-xl font-semibold text-ink">Clippy setup</h1>
            <p className="text-xs text-muted">Preparing local services</p>
          </div>
        </div>
        {state.status === 'starting' ? (
          <p className="text-sm text-muted">Starting the local backend and video renderer…</p>
        ) : (
          <>
            <div className="rounded-input border border-rule bg-paper2 p-4 mb-4">
              <h2 className="text-sm font-semibold text-ink mb-2">One-time runtime setup is still required</h2>
              <p className="text-sm text-muted leading-relaxed">
                The desktop interface is installed, but Clippy's Python backend, Node renderer,
                and application files are not installed yet. API connections and Whisper model
                downloads will not work until those components are installed.
              </p>
            </div>
            <details className="mb-5">
              <summary className="text-xs text-muted cursor-pointer">Technical details</summary>
              <pre className="mt-2 p-3 rounded-input bg-paper2 border border-rule text-xs whitespace-pre-wrap break-words text-warn">{state.error}</pre>
            </details>
            <button
              type="button"
              onClick={() => setAttempt((value) => value + 1)}
              className="btn-primary px-4 py-2 text-sm"
            >
              Retry service startup
            </button>
          </>
        )}
      </section>
    </main>
  );
}
