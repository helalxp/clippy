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
      await invoke('install_app_payload');
      await invoke('setup_runtime');
      const runtimeStatus = await invoke('check_runtime');
      if (runtimeStatus?.error) throw new Error(runtimeStatus.error);
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
          <p className="text-sm text-muted">Installing Clippy's private runtimes and Python dependencies in the background. The first setup can take several minutes, and the window should remain responsive. Temporary installation files use the drive with the most free space. Detailed progress is saved to <code>%LOCALAPPDATA%\\Clippy\\logs\\runtime-setup.log</code>. If Windows requests permission to install a Microsoft runtime, approve it.</p>
        ) : (
          <>
            <div className="rounded-input border border-rule bg-paper2 p-4 mb-4">
              <h2 className="text-sm font-semibold text-ink mb-2">One-time runtime setup is still required</h2>
              <p className="text-sm text-muted leading-relaxed">
                Clippy could not finish its first-run setup. Clippy could not complete startup. The application payload, managed runtimes, or local
                services may need repair. Check the technical details and retry.
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
              Retry setup
            </button>
          </>
        )}
      </section>
    </main>
  );
}
