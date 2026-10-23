"""Turn Upload-Post's cached post analytics into "what your clips did".

The cache (``/uploadposts/post-analytics/cached?user=``) is scoped to the
profile, but three things about it made the account page's "your posts, last 30
days" card wrong by a wide margin:

* ``since`` filters by the date the snapshot was TAKEN, not when the post went
  out. One snapshot holds every post the connected accounts have, each with its
  lifetime views, so "last 30 days" meant "everything, ever".
* It is account-wide, not OpenShorts-wide: the creator's native posts come along
  too. Only rows with an ``upload_timestamp`` went out through Upload-Post; the
  rest were never ours, and on an active creator they are most of the views.
* Snapshots repeat a post. Summing every row would count it once per capture.

``summarise`` keeps the latest snapshot of each post that was published through
Upload-Post inside the window, and reports when that snapshot was taken so the
page can say how fresh the numbers are.
"""
from datetime import datetime, timedelta, timezone

# The cache only fills when a post's metrics are read LIVE (Upload-Post dropped
# its daily sweep: it cost hundreds of thousands of platform calls a day), and
# nothing here read them live, so a profile's numbers froze at whatever day
# someone last looked. The account page now asks for a live read of its own
# recent posts when the newest snapshot is older than this.
REFRESH_AFTER = timedelta(hours=20)

# Live reads share one rate budget for the whole managed account (100 per 5
# minutes across every OpenShorts user), so one refresh reads at most this many
# posts. Newest first: the ones still gaining views.
MAX_LIVE_READS = 40


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def row_views(row):
    """Views of one cached row; platforms name the count differently."""
    metrics = row.get("post_metrics") or row.get("metrics") or row
    for key in ("views", "impressions", "plays"):
        value = metrics.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def summarise(rows, since, top_n=3):
    """Totals and top posts for posts published at or after ``since``.

    ``rows`` are raw cache rows (any number of snapshots); ``since`` an aware
    datetime. Views are each post's views so far, from its latest snapshot.
    """
    latest = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        published = _parse(row.get("upload_timestamp"))
        if published is None or published < since:
            continue
        key = (row.get("platform"), row.get("post_id") or row.get("post_url"))
        captured = _parse(row.get("captured_at")) or published
        kept = latest.get(key)
        if kept is None or captured > kept[0]:
            latest[key] = (captured, published, row)

    total = 0.0
    per_platform = {}
    posts = []
    for captured, published, row in latest.values():
        views = row_views(row)
        total += views
        name = row.get("platform")
        if name:
            per_platform[name] = per_platform.get(name, 0) + views
        posts.append({
            "platform": name,
            "published_at": published.isoformat(),
            "post_url": row.get("post_url"),
            "views": round(views),
        })
    posts.sort(key=lambda p: -p["views"])
    captured_at = max((c for c, _p, _r in latest.values()), default=None)
    return {
        "total_impressions": round(total),
        "per_platform": {k: round(v) for k, v in per_platform.items()},
        "posts_count": len(posts),
        "top_posts": posts[:top_n],
        "updated_at": captured_at.isoformat() if captured_at else None,
    }


def refresh_due(updated_at, now=None):
    """True when the newest snapshot is missing or older than REFRESH_AFTER."""
    now = now or datetime.now(timezone.utc)
    captured = _parse(updated_at)
    return captured is None or now - captured > REFRESH_AFTER


def request_ids_to_refresh(history_rows, since, limit=MAX_LIVE_READS):
    """Upload-Post request ids of successful posts published since ``since``.

    One request id covers every platform that post went to, so a live read per
    id refreshes all of them. Newest first, deduplicated, capped at ``limit``.
    """
    seen, out = set(), []
    rows = sorted((r for r in history_rows if isinstance(r, dict)),
                  key=lambda r: str(r.get("upload_timestamp") or ""), reverse=True)
    for row in rows:
        rid = row.get("request_id")
        published = _parse(row.get("upload_timestamp"))
        if not rid or rid in seen or not row.get("success"):
            continue
        if published is None or published < since:
            continue
        seen.add(rid)
        out.append(rid)
        if len(out) >= limit:
            break
    return out
