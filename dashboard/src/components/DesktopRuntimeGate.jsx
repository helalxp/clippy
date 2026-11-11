import { useCallback, useEffect, useState } from 'react';

function getDesktopApi() {
  return window.__TAURI__;
}

const LOG_PATH = '%LOCALAPPDATA%\\Clippy\\logs\\runtime-setup.log';

export default function DesktopRuntimeGate({ children }) {
  const tauri = getDesktopApi();
  const invoke = tauri?.core?.invoke;
  const isDesktop = typeof invoke === 'function';
  const [state, setState] = useState({
    status: isDesktop ? 'checking' : 'ready',
    phase: 'startup',
    stage: 'Checking your Clippy installation…',
    error: '',
    logPath: LOG_PATH,
  });
  const [attempt, setAttempt] = useState(0);

  const start = useCallback(async () => {
    if (!isDesktop) return;
    setState((current) => ({
      ...current,
      status: 'checking',
      phase: 'startup',
      stage: 'Checking your Clippy installation…',
      error: '',
    }));

    try {
      // The payload check is cheap and also applies a bundled app update when
      // its SHA-256 changes. Runtime validation must happen AFTER this step,
      // because it validates the requirements shipped in that payload.
      await invoke('install_app_payload');

      let runtimeStatus = await invoke('check_runtime');
      if (runtimeStatus?.error) {
        setState((current) => ({
          ...current,
          status: 'starting',
          phase: 'setup',
          stage: 'Preparing missing or outdated dependencies…',
        }));
        await invoke('setup_runtime');
        runtimeStatus = await invoke('check_runtime');
      }

      if (runtimeStatus?.error) {
        throw new Error(runtimeStatus.error);
      }

      setState((current) => ({
        ...current,
        status: 'starting',
        phase: 'startup',
        stage: 'Starting Clippy services…',
      }));
      await invoke('start_services');
      setState((current) => ({
        ...current,
        status: 'ready',
        phase: 'startup',
        stage: 'Ready',
        error: '',
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        status: 'setup-required',
        phase: current.phase === 'startup' ? 'setup' : current.phase,
        stage: 'Clippy could not finish preparing this computer.',
        error: typeof error === 'string' ? error : error?.message || String(error),
      }));
    }
  }, [invoke, isDesktop]);

  useEffect(() => {
    let active = true;
    let unlisten;
    const begin = async () => {
      try {
        unlisten = await tauri?.event?.listen?.('clippy://runtime-setup-progress', (event) => {
          if (!active) return;
          const payload = event.payload || {};
          setState((current) => ({
            ...current,
            phase: 'setup',
            stage: payload.stage || current.stage,
            logPath: payload.logPath || current.logPath,
          }));
        });
      } catch {
        // Setup still works if event streaming is unavailable. The log remains available.
      }
      if (active) start();
    };
    begin();
    return () => {
      active = false;
      if (typeof unlisten === 'function') unlisten();
    };
  }, [start, tauri, attempt]);

  if (!isDesktop || state.status === 'ready') return children;

  const failed = state.status === 'setup-required';
  const firstRun = state.phase === 'setup';

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#10100f] text-[#f2eee5] flex items-center justify-center p-5 sm:p-8">
      <div className="pointer-events-none absolute -top-48 left-1/2 h-[34rem] w-[44rem] -translate-x-1/2 rounded-full bg-amber-500/[0.08] blur-[110px]" />
      <div className="pointer-events-none absolute inset-0 opacity-[0.035]" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.5) 1px, transparent 1px)', backgroundSize: '42px 42px' }} />
      <section className="relative w-full max-w-xl overflow-hidden rounded-3xl border border-white/10 bg-[#191917]/95 shadow-2xl shadow-black/50">
        <div className="h-1 w-full bg-white/[0.06]">
          <div className={`h-full bg-gradient-to-r from-amber-700 via-amber-400 to-yellow-200 transition-all duration-700 ${failed ? 'w-full opacity-50' : 'w-2/3 animate-pulse'}`} />
        </div>
        <div className="p-7 sm:p-10">
          <div className="mb-9 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-amber-300/20 bg-amber-300/10 text-xl font-semibold text-amber-200">C</div>
            <div>
              <div className="text-lg font-semibold tracking-tight">Clippy</div>
              <div className="text-[10px] uppercase tracking-[0.24em] text-white/35">
                {firstRun ? 'First-run setup' : 'Desktop startup'}
              </div>
            </div>
            <div className="ml-auto rounded-full border border-white/10 px-3 py-1 text-[10px] uppercase tracking-widest text-white/45">
              {failed ? 'Action needed' : firstRun ? 'Preparing' : 'Starting'}
            </div>
          </div>

          <div className="mb-8">
            <div className="mb-3 flex items-center gap-3">
              {!failed && <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-amber-300 shadow-[0_0_18px_rgba(252,211,77,.8)]" />}
              {failed && <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />}
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-amber-200/80">
                {failed ? 'Setup paused' : firstRun ? 'Setting up your workspace' : 'Launching your workspace'}
              </span>
            </div>
            <h1 className="mb-3 text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
              {failed ? 'We need to fix one thing.' : firstRun ? 'Getting Clippy ready.' : 'Starting Clippy.'}
            </h1>
            <p className="min-h-12 text-sm leading-6 text-white/55">{state.stage}</p>
          </div>

          {!failed ? (
            <div className="space-y-4">
              <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                <div className="h-full w-1/3 animate-[setup-progress_2.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-amber-700 to-amber-200" />
              </div>
              {firstRun ? (
                <>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {['Private runtimes', 'AI dependencies', 'Local services'].map((label, index) => (
                      <div key={label} className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-2 py-3">
                        <div className="mb-1 text-[10px] text-amber-200/70">0{index + 1}</div>
                        <div className="text-[11px] text-white/55">{label}</div>
                      </div>
                    ))}
                  </div>
                  <p className="pt-2 text-xs leading-5 text-white/35">
                    Clippy is preparing the required runtimes in the background, without opening a command window.
                  </p>
                </>
              ) : (
                <p className="pt-2 text-xs leading-5 text-white/35">
                  Your installed components are being checked. No dependency downloads are performed when everything is already valid.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-2xl border border-rose-300/15 bg-rose-300/[0.06] p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-rose-200">Diagnostic details</div>
                <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-white/65">{state.error}</pre>
              </div>
              <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3">
                <div className="mb-1 text-[10px] uppercase tracking-widest text-white/35">Setup log</div>
                <code className="break-all text-xs text-amber-100/75">{state.logPath}</code>
              </div>
              <button type="button" onClick={() => setAttempt((value) => value + 1)} className="w-full rounded-full bg-amber-200 px-5 py-3 text-sm font-semibold text-[#211b10] transition hover:bg-amber-100">
                Retry setup
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-white/[0.07] px-7 py-4 text-[10px] uppercase tracking-widest text-white/25 sm:px-10">
          <span>Local-first · Private by design</span>
          <span>Clippy Desktop</span>
        </div>
      </section>
      <style>{`@keyframes setup-progress { 0% { transform: translateX(-110%); } 100% { transform: translateX(340%); } }`}</style>
    </main>
  );
}
