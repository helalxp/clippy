import React, { useState, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { apiJson } from '../lib/api';
import Modal from './ui/Modal';

// Mirror cloud/onboarding.SOURCES / GOALS / ROLES.
const SOURCES = [
  ['google', 'Google search'],
  ['ai_assistant', 'ChatGPT, Claude or another AI'],
  ['youtube', 'YouTube'],
  ['tiktok_instagram', 'TikTok or Instagram'],
  ['x_twitter', 'X (Twitter)'],
  ['reddit', 'Reddit'],
  ['github', 'GitHub'],
  ['friend', 'A friend or colleague'],
  ['directory', 'Product Hunt or a tools directory'],
  ['newsletter_blog', 'A newsletter or blog'],
  ['other', 'Somewhere else'],
];

const GOALS = [
  ['clips_from_long_videos', 'Clips from my long videos'],
  ['ai_avatar_videos', 'AI avatar / UGC videos'],
  ['autopilot_posting', 'Auto-posting to my socials'],
  ['thumbnails', 'YouTube titles & thumbnails'],
  ['subtitles', 'Subtitles'],
  ['dubbing', 'Dubbing into other languages'],
  ['api_agents', 'API / AI agent integration'],
  ['self_host', 'Self-hosting OpenShorts'],
];

const ROLES = [
  ['creator', 'Creator / YouTuber'],
  ['podcaster', 'Podcaster'],
  ['streamer_gamer', 'Streamer / gamer'],
  ['agency', 'Agency or freelancer'],
  ['business_marketing', 'Business / marketing team'],
  ['educator', 'Educator / coach'],
  ['developer', 'Developer'],
  ['other', 'Other'],
];

const chip = (on) => `rounded-full border px-3 py-1.5 text-xs transition-colors ${
  on ? 'border-brass bg-brass/10 text-ink' : 'border-rule text-ink2 hover:border-brass/60'}`;

// Asked once, right after sign-up, before the clip tutorial (backend:
// cloud/onboarding.py). One screen, every question optional, skippable: it
// must cost the new user seconds, not their first clip.
export default function OnboardingSurvey({ onDone }) {
  const [source, setSource] = useState('');
  const [sourceOther, setSourceOther] = useState('');
  const [goals, setGoals] = useState([]);
  const [role, setRole] = useState('');
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);

  const toggleGoal = (g) => setGoals((cur) => (cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g]));
  const answered = !!(source || goals.length || role);

  const send = async (skipped) => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    const body = skipped ? { skipped: true } : {
      source: source || undefined,
      source_other: source === 'other' ? sourceOther.trim() || undefined : undefined,
      goals,
      role: role || undefined,
    };
    try {
      await apiJson('/api/onboarding/survey', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
    } catch (_) { /* never block onboarding on the survey */ }
    // SignupSurveyAnswered is emitted server-side (cloud/onboarding.py) when
    // the answers are saved; tracking it here too counted every answer twice.
    onDone();
  };

  return (
    <Modal isOpen onClose={busy ? undefined : () => send(true)} eyebrow="WELCOME · 3 QUICK QUESTIONS"
           title="Help us build what you need" size="lg"
           footer={(
             <div className="flex items-center justify-between gap-2">
               <button onClick={() => send(true)} disabled={busy} className="btn-quiet">Skip</button>
               <button onClick={() => send(false)} disabled={busy || !answered} className="btn-primary px-4 py-2 text-xs">
                 {busy && <Loader2 size={14} className="animate-spin" />} Continue
               </button>
             </div>
           )}>
      <div className="space-y-6">
        <section>
          <h3 className="text-sm text-ink mb-2">What do you want to make with OpenShorts? <span className="text-muted">(pick any)</span></h3>
          <div className="flex flex-wrap gap-2">
            {GOALS.map(([value, label]) => (
              <button key={value} type="button" onClick={() => toggleGoal(value)} className={chip(goals.includes(value))}>
                {label}
              </button>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-sm text-ink mb-2">How did you hear about us?</h3>
          <div className="flex flex-wrap gap-2">
            {SOURCES.map(([value, label]) => (
              <button key={value} type="button" onClick={() => setSource(source === value ? '' : value)} className={chip(source === value)}>
                {label}
              </button>
            ))}
          </div>
          {source === 'other' && (
            <input value={sourceOther} onChange={(e) => setSourceOther(e.target.value)} maxLength={120}
                   placeholder="Where?" className="input-field w-full text-sm mt-2" />
          )}
        </section>

        <section>
          <h3 className="text-sm text-ink mb-2">What describes you best?</h3>
          <div className="flex flex-wrap gap-2">
            {ROLES.map(([value, label]) => (
              <button key={value} type="button" onClick={() => setRole(role === value ? '' : value)} className={chip(role === value)}>
                {label}
              </button>
            ))}
          </div>
        </section>
      </div>
    </Modal>
  );
}
