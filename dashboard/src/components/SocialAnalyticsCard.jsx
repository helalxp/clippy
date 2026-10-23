import React, { useEffect, useState } from 'react';
import { BarChart3, ExternalLink } from 'lucide-react';
import { apiJson } from '../lib/api';

const fmtNum = (n) => new Intl.NumberFormat('en-US', {
  notation: (n || 0) >= 10000 ? 'compact' : 'standard',
  maximumFractionDigits: 1,
}).format(n || 0);

const fmtDay = (iso) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : '';
};

// Post-publication analytics: what the clips published from OpenShorts did out
// there. The server keeps only posts that went out through Upload-Post in the
// last 30 days (the vendor cache also holds the creator's native posts, with
// lifetime views), so every number is "views so far" on those posts, as of the
// cache's last snapshot. Paid-only by nature (social posting itself is paid in
// cloud): a 402 or any other failure simply hides the card.
export default function SocialAnalyticsCard() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    apiJson('/api/social/analytics/impressions?period=last_month')
      .then((imp) => { if (alive) setData(imp); })
      .catch(() => { /* free plan, nothing connected, or vendor hiccup — stay hidden */ });
    return () => { alive = false; };
  }, []);

  if (!data) return null;

  const total = data.total_impressions || 0;
  const perPlatform = Object.entries(data.per_platform || {})
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  const top = data.top_posts || [];

  return (
    <div className="card p-6">
      <div className="flex items-baseline justify-between gap-4 mb-1">
        <h3 className="font-display lowercase text-lg text-ink flex items-center gap-2">
          <BarChart3 size={16} className="text-brass" /> Your posts
        </h3>
        <span className="text-muted text-xs lowercase">
          posted in the last 30 days
          {data.refreshing ? ' · updating, reload in a minute'
            : data.updated_at ? ` · updated ${fmtDay(data.updated_at)}` : ''}
        </span>
      </div>

      {!data.posts_count ? (
        <p className="text-muted text-sm lowercase">
          Nothing published yet. Post a clip from your results and its views show up here.
        </p>
      ) : (
        <>
          <div className="flex items-end gap-3 mb-3">
            <span className="readout text-2xl text-ink">{fmtNum(total)}</span>
            <span className="text-muted text-sm lowercase mb-0.5">
              views on {data.posts_count} post{data.posts_count === 1 ? '' : 's'}
            </span>
          </div>

          {perPlatform.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 mb-4 text-sm">
              {perPlatform.map(([platform, v]) => (
                <span key={platform} className="text-ink2 lowercase">
                  {platform} <span className="text-brass">{fmtNum(Number(v))}</span>
                </span>
              ))}
            </div>
          )}

          {top.length > 0 && (
            <div className="space-y-2 border-t border-rule pt-3">
              {top.map((p, i) => (
                <div key={p.post_url || i}
                     className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-ink2 truncate lowercase">
                    {p.platform} · {fmtDay(p.published_at)}
                    {/^https?:\/\//.test(p.post_url || '') && (
                      <a href={p.post_url} target="_blank" rel="noreferrer"
                         className="inline-flex align-middle ml-1.5 text-muted hover:text-ink">
                        <ExternalLink size={12} />
                      </a>
                    )}
                  </span>
                  <span className="text-ink shrink-0">{fmtNum(p.views)} views</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
