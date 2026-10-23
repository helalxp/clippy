import React, { useEffect, useState } from 'react';
import Modal from './ui/Modal';
import { apiJson } from '../lib/api';
import { track } from '../lib/analytics';

const DISMISS_KEY = 'os_watermark_notice_dismissed';
const SEEN_PREFIX = 'os_watermark_noticed_';

// eslint-disable-next-line react-refresh/only-export-components
export function watermarkNoticeDismissed(jobId = null) {
  try {
    if (localStorage.getItem(DISMISS_KEY) === '1') return true;
    // Once per job: the results view shows it when the clips land, so the
    // first download of the same job must not show it a second time.
    return !!(jobId && sessionStorage.getItem(SEEN_PREFIX + jobId) === '1');
  } catch { return false; }
}

// eslint-disable-next-line react-refresh/only-export-components
export function markWatermarkNoticed(jobId) {
  try { if (jobId) sessionStorage.setItem(SEEN_PREFIX + jobId, '1'); } catch { /* ignore */ }
}

// Shown to free users when their clips land (source="results") and, if they
// skipped that, before their first download (source="download"). The promise
// is literal since 30-sep-2026: the pipeline keeps a clean twin of every free
// clip and paying re-points the library at it, so the clips on screen lose
// the mark on the spot. Dismissible for good, like OpusClip's.
//
// The upgrade button names its price (a bare "Remove the watermark" reads as a
// free action) and opens our plan picker with starter put forward. From 5 to 7
// Oct 2026 it went straight to the Starter checkout instead: Stripe Checkout
// is a payment form, not a sales page, and for a click made on the way to a
// download far fewer of those checkouts were paid. From a
// download, the clip is downloaded first either way: the user asked for it.
export default function WatermarkModal({ onClose, onContinue, onUpgrade, previewSrc = null,
                                         source = 'download', jobId = null }) {
  const [dontShow, setDontShow] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [starter, setStarter] = useState(null);

  useEffect(() => {
    markWatermarkNoticed(jobId);
    track('WatermarkNoticeSeen', { props: { source } });
  }, [jobId, source]);

  useEffect(() => {
    apiJson('/api/billing/plans')
      .then((d) => setStarter((d.plans || []).find((p) => p.plan === 'starter' && p.interval === 'month') || null))
      .catch(() => {});
  }, []);

  const close = (proceed) => {
    if (dontShow) {
      try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* ignore */ }
    }
    if (proceed) onContinue?.();
    onClose();
  };

  const upgrade = () => {
    track('WatermarkNoticeUpgrade', { props: { source } });
    if (source === 'download') onContinue?.();
    close(false);
    if (onUpgrade) onUpgrade({ source: 'watermark', highlight: 'starter' });
    else window.location.hash = '#/pricing';
  };

  const price = starter && new Intl.NumberFormat('en-US', {
    style: 'currency', currency: (starter.currency || 'usd').toUpperCase(), maximumFractionDigits: 0,
  }).format((starter.amount || 0) / 100);

  const src = previewSrc && !previewFailed ? previewSrc : '/demo/clip-vertical.mp4';

  return (
    <Modal isOpen onClose={() => close(false)} eyebrow="FREE PLAN" title="Want the watermark off?" size="md">
      <p className="text-muted text-sm mb-4">
        Clips on the free plan carry the OpenShorts mark and are deleted after 7 days.
        Upgrade and <b className="text-ink font-medium">these exact clips lose the mark on the spot</b>,
        no re-render, and stay in your library for good.
      </p>

      <div className="rounded-card border border-rule overflow-hidden bg-paper mb-5">
        <video
          key={src}
          src={src}
          autoPlay
          muted
          loop
          playsInline
          onError={() => setPreviewFailed(true)}
          className="w-full max-h-56 object-cover"
        />
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
          <input
            type="checkbox"
            checked={dontShow}
            onChange={(e) => setDontShow(e.target.checked)}
            className="accent-brass"
          />
          Don't show this again
        </label>
        <div className="flex items-center gap-2">
          <button onClick={() => close(true)} className="btn-ghost px-4 py-2 text-sm">
            {source === 'download' ? 'Download anyway' : 'Keep the watermark'}
          </button>
          <button onClick={upgrade} className="btn-primary px-4 py-2 text-sm">
            {price ? `Remove the watermark · from ${price}/mo` : 'Remove the watermark'}
          </button>
        </div>
      </div>
    </Modal>
  );
}
