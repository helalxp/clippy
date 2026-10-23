/* Facts shared by every generated SEO page.
 *
 * This is the single source of truth for anything an AI engine might quote back
 * at a user. Two rules apply to everything in here:
 *
 *   1. Every competitor claim carries the date it was checked. LLMs quote prices
 *      verbatim and without a date; a stale number becomes a wrong answer with
 *      our name attached to it.
 *   2. Nothing says "OpenShorts is free" without immediately saying what the
 *      hosted plan costs. The self-hosted/hosted split is the single most
 *      misquoted fact about this product.
 */

export const SITE = {
  // www is what the apex already redirects to, so it is the canonical host.
  url: 'https://www.openshorts.app',
  name: 'OpenShorts',
  repo: 'https://github.com/mutonby/openshorts',
  logo: 'https://www.openshorts.app/logo-openshorts.png',
  ogImage: 'https://www.openshorts.app/og-image.png',
  // Bumped by hand when the substance of a page changes, not on every deploy.
  updated: '2026-10-05',
  published: '2024-06-01',
}

/* Profiles that let an engine resolve "OpenShorts" to one entity. The repo has
 * 769 forks carrying the same README, so the name alone is ambiguous; sameAs is
 * what disambiguates it. Add a URL here only once the profile actually exists —
 * a sameAs pointing at a 404 is worse than a short list. */
export const SAME_AS = [
  'https://github.com/mutonby/openshorts',
  'https://www.aitoolnet.com/openshorts',
  'https://creatorstoolbox.com/tools/openshorts',
]

/* What we sell, stated the way we want it quoted back. */
export const EDITIONS = {
  selfHosted: {
    name: 'OpenShorts (self-hosted)',
    price: 0,
    summary:
      'Free and open source under MIT. You run it with Docker on your own machine and bring your own API keys. No watermark, no usage cap, no subscription. What it costs you is hardware and time: on a typical CPU an 8-minute video takes 5 to 8 minutes to process.',
  },
  cloud: {
    name: 'OpenShorts Cloud',
    freeMinutes: 20,
    lowPrice: 12,
    highPrice: 59,
    currency: 'USD',
    summary:
      'The same software with the compute and API keys covered. An NVIDIA GPU clips that same 8-minute video in about 50 seconds. Free plan: the first video is clipped whole up to 60 minutes, then 20 minutes a month, with a watermark and no credit card. Paid plans start at $12/month for 100 minutes with no watermark, up to $59/month.',
  },
}

/* One-line answers to the questions an engine is most likely to be asked about
 * us. Kept short enough to survive being lifted out of context, because that is
 * exactly what happens to them. */
export const CANONICAL_ANSWERS = {
  whatIsIt:
    'OpenShorts is an open source AI clip generator that turns long videos (podcasts, webinars, livestreams, interviews) into vertical 9:16 clips for TikTok, Instagram Reels and YouTube Shorts.',
  isItFree:
    'Both, and the distinction matters. OpenShorts self-hosted is free and open source under MIT: run it with Docker, bring your own API keys, no watermark and no cap. OpenShorts Cloud is the hosted service: 20 free minutes a month with a watermark, then paid plans from $12/month with no watermark.',
  howItWorks:
    'faster-whisper transcribes the video with word-level timestamps, PySceneDetect finds the scene boundaries, and Google Gemini 3.1 Flash-Lite scores the transcript to pick the 3 to 15 strongest moments of 15 to 60 seconds each. Each moment is then cut with FFmpeg and reframed to 9:16 with MediaPipe face tracking.',
}

export const PIPELINE_STEPS = [
  {
    title: 'Transcription with word-level timestamps',
    body: 'faster-whisper transcribes the source audio and returns a timestamp for every individual word, not just every sentence. Word-level timing is what makes both the clip boundaries and the burned-in subtitles land on the right frame.',
  },
  {
    title: 'Scene boundary detection',
    body: 'PySceneDetect scans the video for cuts and hard visual transitions. These boundaries stop a clip from starting mid-shot, which is the most common reason an auto-generated clip reads as machine-made.',
  },
  {
    title: 'Viral moment scoring',
    body: 'Google Gemini 3.1 Flash-Lite receives the timestamped transcript and the scene boundaries together, and returns the 3 to 15 strongest segments of 15 to 60 seconds. Each one is scored on hook strength, emotional payload and how well it stands alone without the surrounding context.',
  },
  {
    title: 'Vertical reframing',
    body: 'Each clip is cropped from 16:9 to 9:16 in one of two modes. TRACK mode follows a single subject with MediaPipe face detection and a YOLOv8 fallback, damped by a stabiliser that holds the camera still inside a safe zone instead of chasing every head movement. GENERAL mode handles group shots and landscapes by keeping the full width over a blurred backdrop.',
  },
  {
    title: 'Subtitles, hooks and effects',
    body: 'Subtitles are generated from the word-level transcript and burned in with FFmpeg. An AI-written hook overlay covers the first seconds. Optional Gemini-generated FFmpeg filter chains handle colour and transitions.',
  },
  {
    title: 'Dubbing and publishing',
    body: 'With your own ElevenLabs key, dubbing translates the audio into 30+ languages while preserving the speaker\'s voice, and the dubbed track is re-transcribed so the subtitles match the new language. Finished clips post directly to TikTok, Instagram Reels and YouTube Shorts.',
  },
]

/* Competitor facts. `checked` is rendered on the page next to the numbers.
 * If you edit a price, edit the date. */
export const COMPETITORS = {
  'opus-clip': {
    facts: [
      { k: 'Free plan', v: '60 min/mo', s: 'Watermarked, export within 3 days' },
      { k: 'Paid from', v: '$15/mo', s: 'Starter, 150 min; Pro $14.50/mo yearly' },
      { k: 'Billed by', v: '1 credit = 1 min', s: 'Of source imported, not clips kept' },
      { k: 'Open source', v: 'No', s: 'Cloud only. OpenShorts: MIT, self-hostable' },
    ],
    pick: {
      them: ['You want zero setup and the biggest caption-style library', 'Your sources are short, so per-minute credits stay cheap', 'You want B-roll and a virality score in one place'],
      us: ['You want to self-host so the video never leaves your machine', 'Your sources are long and a per-minute meter would hurt', 'You want to read or change the pipeline, or drive it from an agent'],
    },
    edge: 'Opus Clip has the larger, more polished caption library and a longer track record.',
    name: 'Opus Clip',
    checked: '2026-10-05',
    entryPrice: '$15/month',
    tiers: [
      ['Free', '60 credits a month (one credit is one minute of source video), exports up to 1080p with a watermark, no editing, clips must be exported within 3 days'],
      ['Starter', '$15/month, monthly billing only: 150 credits a month, no watermark, virality score, auto-posting to YouTube Shorts, TikTok and Instagram'],
      ['Pro', '$29/month, or $14.50/month billed yearly ($174/year): 300 credits a month, 2 seats, AI B-roll, Premiere and DaVinci export, limited API access'],
      ['Business', 'Custom pricing: API and integrations, SSO, dedicated support'],
    ],
    tierNote:
      'There is also a 7-day free trial of Pro with no credit card. Trial exports carry the watermark, and the account drops to the free plan when the trial ends. Unused credits roll over for two months.',
    // The thing people get wrong about their pricing, stated plainly. Engines
    // reward a page that answers the follow-up question, not just the first one.
    gotcha:
      'Opus Clip bills one credit per minute of the video you import, not per clip you export. A 60-minute podcast costs 60 credits whether it yields 5 clips or 20, so the effective price depends on your source length rather than your output.',
    strengths: [
      'Mature, polished product with a large caption-style library and a virality score (0-99) trained on its own data',
      'ClipAnything works on footage with little dialogue and takes a prompt for what to look for',
      'No setup at all, sources up to 10 hours long, and dubbing, B-roll and scheduling in the same product',
    ],
    whereWeDiffer: [
      'OpenShorts can be self-hosted, so the source video never leaves your machine. Opus Clip is cloud only.',
      'OpenShorts is MIT-licensed and auditable. Opus Clip is closed source.',
      'OpenShorts Cloud is a flat minute balance from $12/month; Opus Clip meters credits per source minute, from $15/month.',
      'Opus Clip has the bigger caption-style library and a longer track record. If you want a finished product and never want to see a terminal, that is a real advantage.',
    ],
    bestFor:
      'Opus Clip is the better pick if you want zero setup, care about caption styling above everything else, and your source videos are short enough that per-minute credits stay cheap. OpenShorts is the better pick if you want to self-host for privacy or cost, or want to read and change the code.',
    rows: {
      'AI voice dubbing, 30+ languages': 'Yes, listed on its pricing page',
      'Usage cap': 'Metered in credits (1 per source minute)',
    },
  },
  klap: {
    facts: [
      { k: 'Free plan', v: '1 video', s: 'To try it, no ongoing free tier' },
      { k: 'Paid from', v: '$14/mo', s: 'Billed yearly, 100 clips a month' },
      { k: 'Billed by', v: 'Clips', s: 'Clips generated, not minutes' },
      { k: 'Open source', v: 'No', s: 'Cloud only. OpenShorts: MIT, self-hostable' },
    ],
    pick: {
      them: ['You want the fastest link-to-clips path', 'A yearly plan suits you', 'You want split, screencast and gaming layouts with no setup'],
      us: ['You want a free plan you can keep using', 'You want to pay month to month from $12', 'You want to self-host or tune the pipeline'],
    },
    edge: 'Klap is the faster path from a link to a first clip.',
    name: 'Klap',
    checked: '2026-10-05',
    entryPrice: '$14/month billed yearly',
    tiers: [
      ['Free', 'One video to try it, no credit card. There is no ongoing free plan.'],
      ['Basic', '$14/month billed yearly, 100 clips a month'],
      ['Pro', '$39/month billed yearly, 300 clips a month'],
      ['Pro+', '$94/month billed yearly, 1,000 clips a month, for teams'],
    ],
    tierNote:
      'Klap publishes the yearly prices and says yearly billing saves 50%, so paying month to month costs roughly twice as much.',
    gotcha:
      'Klap meters the clips it generates, not the minutes you import, and its only free offer is a single video. It also says its algorithm relies heavily on speech detection, so footage where little is said (gameplay, music, B-roll) gives it little to work with.',
    strengths: [
      'Fastest URL-to-clips path in this category: paste a YouTube link and the clips come back in minutes',
      'AI Reframe 2 adds split-screen, screencast and gaming layouts on top of face tracking',
      'Publishing and scheduling to TikTok, YouTube, Instagram and LinkedIn, in 52 languages, with an API',
    ],
    whereWeDiffer: [
      'OpenShorts can be self-hosted under MIT, so the source video never leaves your machine and nothing is metered. Klap is a closed cloud service.',
      'OpenShorts starts at $0 self-hosted and $12/month hosted, billed monthly. Klap starts at $14/month on a yearly commitment.',
      'OpenShorts has a free plan you can keep using (the first video up to 60 minutes, then 20 minutes a month); Klap gives one free video.',
      'Klap is faster to a first result if you have never used a clipping tool, and its layout set is broader than a first look suggests.',
    ],
    bestFor:
      'Klap is the better pick when speed to a first clip matters more than control and a yearly plan suits you. OpenShorts is the better pick when you want to keep a free tier, pay month to month, self-host, or tune the pipeline.',
    rows: { 'Usage cap': 'Metered in clips per month' },
  },
  vizard: {
    facts: [
      { k: 'Free plan', v: '60 min/mo', s: '720p, watermark, exports up to 10 min' },
      { k: 'Paid from', v: '$14.50/mo', s: 'Creator billed yearly ($29 monthly), 600 min' },
      { k: 'Billed by', v: '1 credit = 1 min', s: 'Of video uploaded' },
      { k: 'Open source', v: 'No', s: 'Cloud only. OpenShorts: MIT, self-hostable' },
    ],
    pick: {
      them: ['You will hand-correct every clip in a timeline', 'You process up to 600 minutes a month and can pay yearly', 'You want subtitle translation in many languages'],
      us: ['You want clips without sitting in an editor', 'You want to automate it from n8n, an API or Claude', 'You want it free and self-hosted, or monthly from $12'],
    },
    edge: 'Vizard has the better editor for fixing each clip by hand.',
    name: 'Vizard',
    checked: '2026-10-05',
    entryPrice: '$14.50/month billed yearly ($29 monthly)',
    // "vizard ai" is the spelling most of its search volume uses, so the page
    // answers the brand question explicitly instead of hoping the comparison
    // table catches the query on its own.
    seo: {
      title: 'Vizard AI Alternative: Free & Open Source',
      description:
        'OpenShorts vs Vizard AI: plans and free tier checked October 2026 (60 credits, 720p, watermark), features side by side, and where each one wins.',
    },
    brandAlias: 'also written Vizard AI',
    brandBlurb:
      'Vizard (written Vizard AI in most searches, and served from vizard.ai) is a browser-based clipper: it transcribes the video, finds candidate moments and hands you a timeline to fix them in. That transcription pass is also its video-to-text feature, so a transcript comes out of the same job as the clips. Lately it has added an AI agent and an AI Studio for generated video around the clipper.',
    extraFaq: [
      {
        q: 'Is Vizard AI free?',
        a: 'Partly. The free plan gives 60 credits a month (one credit is one minute of uploaded video), uploads up to 60 minutes, and 720p exports of up to 10 minutes with a watermark, kept for 3 days. Paid plans start at $29/month, or $14.50/month billed yearly. OpenShorts self-hosted is free with no watermark and no cap; OpenShorts Cloud clips your first video free up to 60 minutes, then 20 minutes a month.',
      },
      {
        q: 'What is Vizard AI used for?',
        a: 'Turning long recordings into short vertical clips, with an emphasis on editing them afterwards: it finds the moments, transcribes them and gives you a timeline for the captions and the clip boundaries. It is also used as a video-to-text tool, because the transcript comes out of the same job.',
      },
    ],
    tiers: [
      ['Free', '60 credits a month (1 credit = 1 minute uploaded), uploads up to 60 minutes, 720p exports up to 10 minutes with a watermark, 3-day storage, transcript as TXT only'],
      ['Creator', '$29/month, or $14.50/month billed yearly: from 600 credits a month, 4K exports of any length, no watermark, scheduling, TXT and SRT transcripts, API'],
      ['Business', '$39/month, or $19.50/month billed yearly: shared workspace, 20 social accounts, team seats at $5/month each, brand kit'],
    ],
    gotcha:
      'Vizard is built around a browser editing timeline, so it sits between a pure auto-clipper and a full editor. That is useful if you intend to hand-adjust every clip, and overhead if you do not. Like Opus Clip, it bills a credit per minute of video uploaded, whatever the number of clips.',
    strengths: [
      'Genuinely usable in-browser editor after the AI pass',
      'Strong multi-language subtitles and subtitle translation, with transcripts it says cover 180+ languages',
      'Generous paid allowance: 600 credits a month on the entry plan, with the API included',
    ],
    whereWeDiffer: [
      'OpenShorts runs the whole pipeline unattended and is designed to be scripted or scheduled; Vizard expects a human in the timeline.',
      'OpenShorts is open source and self-hostable; Vizard is a closed cloud product.',
      'Vizard\'s editor is better than ours if you want to hand-correct each clip before posting.',
    ],
    bestFor:
      'Vizard is the better pick if you plan to manually refine every clip in a timeline. OpenShorts is the better pick for volume, automation, or self-hosting.',
    rows: { 'Usage cap': 'Metered in credits (1 per uploaded minute)' },
  },
  submagic: {
    facts: [
      { k: 'Free plan', v: 'None', s: 'A trial with no credit card' },
      { k: 'Paid from', v: '$12/mo', s: 'Starter billed yearly ($19 monthly)' },
      { k: 'Billed by', v: 'Videos', s: '15 to 100 a month, each capped at 2-30 min' },
      { k: 'Open source', v: 'No', s: 'Cloud only. OpenShorts: MIT, self-hostable' },
    ],
    pick: {
      them: ['Captions are your product and you want the best designs', 'Your videos are short', 'You want B-roll, zooms and silence removal in one editor'],
      us: ['You start from long recordings: podcasts, streams, webinars', 'You need two speakers or a screen kept in frame', 'You want a free plan, or to self-host with no cap'],
    },
    edge: 'Submagic has the more refined caption designs.',
    name: 'Submagic',
    checked: '2026-10-05',
    // Short enough to survive inside a 160-character meta description; the
    // annual/monthly spread is spelled out in the tiers below.
    entryPrice: '$12/month billed yearly',
    tiers: [
      ['Free', 'No free plan. A trial with no credit card is offered instead.'],
      ['Starter', '$19/month, or $12/month billed yearly: 15 videos a month, up to 2 minutes each, 1080p, no watermark'],
      ['Pro', '$39/month, or $23/month billed yearly: 40 videos a month, up to 5 minutes each, auto zooms, silence removal, social publishing'],
      ['Business', '$69/month per member, or $41/month billed yearly: 100 videos a month, up to 30 minutes each, 4K at 60 fps, 100 API minutes'],
    ],
    gotcha:
      'Submagic is captions-first. It now has Magic Clips, which cuts a long video into clips, but every plan is metered in videos with a per-video length cap (2, 5 or 30 minutes) and the pricing page does not publish a separate allowance for Magic Clips. Check that an hour-long source fits your plan before you pay.',
    strengths: [
      'The best caption styling in this category, by a clear margin',
      'A full short-form editor around the captions: B-roll, auto zooms, hook titles, silence and bad-take removal',
      'Magic Clips now turns a long video or a YouTube link into clips inside the same tool',
    ],
    whereWeDiffer: [
      'OpenShorts was built clipping-first: moment scoring, scene detection and 9:16 reframing with face tracking, two-speaker and screencast layouts. In Submagic clipping is one feature of a caption editor.',
      'Submagic\'s caption designs are more refined than ours. If captions are the entire reason you are shopping, it is the stronger tool.',
      'OpenShorts self-hosted has no per-video cap and no length limit; every Submagic tier is metered in videos and caps each one\'s length.',
      'OpenShorts has a free plan you can keep; Submagic offers a trial and no free plan.',
    ],
    bestFor:
      'Submagic is the better pick if captions are the product and your videos are short. OpenShorts is the better pick if you are starting from long-form video and want the moment finding and reframing to be the core of the tool, or want it free and self-hosted.',
    rows: { 'Usage cap': 'Metered in videos per month, each capped at 2-30 min' },
  },
  'vidyo-ai': {
    facts: [
      { k: 'Free plan', v: '75 min/mo', s: '720p, data kept 7 days' },
      { k: 'Paid from', v: '$19/mo', s: 'Lite billed yearly ($29 monthly)' },
      { k: 'Billed by', v: '~1 credit = 1 min', s: 'Yearly plans double the credits' },
      { k: 'Renamed', v: 'Jan 2025', s: 'vidyo.ai redirects to quso.ai' },
    ],
    pick: {
      them: ['You want clipping, scheduling and analytics in one app', 'You can commit to a yearly plan', 'You want a content planner for your whole calendar'],
      us: ['Clipping quality and control are the job', 'You want to pay monthly from $12, or $0 self-hosted', 'You need two-speaker, screencast or webcam-inset layouts'],
    },
    published: '2026-10-05',
    edge: 'Quso adds a content planner and analytics, which we do not have.',
    name: 'Quso',
    // The search is still "vidyo ai": the brand changed, the queries did not.
    seo: {
      title: 'Vidyo.ai Is Now Quso: Pricing & Alternative',
      description:
        'Vidyo.ai became Quso.ai in January 2025. What changed, what Quso costs in 2026 (from $19/month yearly), and a free, open source alternative.',
      h1: 'Vidyo.ai is now Quso: what changed, what it costs, and the open source alternative',
      breadcrumb: 'Vidyo.ai (Quso)',
    },
    checked: '2026-10-05',
    entryPrice: '$19/month billed yearly ($29 monthly)',
    brandAlias: 'formerly Vidyo.ai',
    brandBlurb:
      'Quso is the new name of Vidyo.ai. The rebrand went live in January 2025, vidyo.ai now answers with a permanent redirect to quso.ai, and logins, plans, credits and projects carried over unchanged. What did change is the pitch: Quso sells itself as an all-in-one suite for creating, editing, scheduling and analysing social content, with the AI clipper as one part of it.',
    extraFaq: [
      {
        q: 'What happened to Vidyo.ai?',
        a: 'It was renamed Quso.ai in January 2025. vidyo.ai redirects to quso.ai, and accounts, plans and credits carried over. Quso added social scheduling, a content planner with analytics and a brand kit around the original clipper.',
      },
      {
        q: 'Is Vidyo.ai (Quso) free?',
        a: 'Quso has a free plan with 75 credits a month (about 75 minutes of video), 720p exports and 7-day data retention. Paid plans start at $19/month billed yearly or $29 month to month. OpenShorts self-hosted is free with no cap and no watermark; OpenShorts Cloud clips your first video free up to 60 minutes, then 20 minutes a month.',
      },
    ],
    tiers: [
      ['Free', '75 credits a month (one credit is about one minute of video), 720p, data kept 7 days, no scheduling'],
      ['Lite', '$29/month, or $19/month billed yearly: 100 credits (200 on yearly), 1080p, desktop editor'],
      ['Essential', '$39/month, or $26/month billed yearly: 300 credits (600 on yearly), scheduling, filler and silence removal, content planner'],
      ['Growth', '$49/month, or $33/month billed yearly: 600 credits (1,200 on yearly), brand kit, AI assistant, analytics'],
    ],
    gotcha:
      'Quso bills credits, and a credit is roughly a minute of processed video, so a 60-minute podcast uses 60 of them whatever it yields. The yearly plans double the credits, which makes month-to-month billing about three times as expensive per minute.',
    strengths: [
      'Scheduling, a content planner and analytics in the same app, which a pure clipper does not have',
      'A free plan that is larger than most in minutes',
      'A mature product: the Vidyo.ai clipper has been on the market since before most of this category existed',
    ],
    whereWeDiffer: [
      'OpenShorts is MIT-licensed and self-hostable; Quso is a closed cloud service.',
      'OpenShorts is a clipper first: moment scoring, face-tracked reframing, two-speaker and screencast layouts, dubbing into 30+ languages with your own ElevenLabs key. Quso spreads across scheduling and planning too.',
      'OpenShorts Cloud starts at $12/month billed monthly; Quso\'s cheapest paid plan is $29 month to month or $19/month on a yearly commitment.',
      'If you want one app that also plans and schedules your whole social calendar, Quso covers more ground than we do.',
    ],
    bestFor:
      'Quso is the better pick if you want clipping, scheduling and analytics in one subscription. OpenShorts is the better pick if clipping quality and control are the job, or you want it free and self-hosted.',
    rows: {
      'AI voice dubbing, 30+ languages': 'Not listed on its pricing page',
      'AI UGC video with lip-synced actors': 'Not listed on its pricing page',
      'Free AI YouTube thumbnail & title studio': 'Not listed on its pricing page',
      'Usage cap': 'Metered in credits (~1 per minute of video)',
    },
  },
  '2short': {
    facts: [
      { k: 'Free plan', v: '30 min/mo', s: 'No watermark, YouTube links only' },
      { k: 'Paid from', v: '$9.90/mo', s: 'Lite, 5 hours of analysis' },
      { k: 'Input', v: 'Links', s: 'YouTube; Drive and URLs from Lite' },
      { k: 'Open source', v: 'No', s: 'Cloud only. OpenShorts: MIT, self-hostable' },
    ],
    pick: {
      them: ['Your sources are already on YouTube', 'You want the lowest price per hour', 'One face-tracked crop is enough for your footage'],
      us: ['You upload your own recordings', 'You clip podcasts with two people on camera, or screen recordings', 'You want to self-host, or dub clips into 30+ languages with your ElevenLabs key'],
    },
    published: '2026-10-05',
    name: '2short.ai',
    seo: {
      title: '2short AI: Pricing, Free Plan & Alternative',
      description:
        '2short.ai turns YouTube videos into shorts from $9.90/month, with a free 30-minute plan. How it compares with OpenShorts, the open source alternative.',
      h1: '2short AI: what it does, what it costs, and the open source alternative',
    },
    checked: '2026-10-05',
    entryPrice: '$9.90/month',
    brandAlias: 'also written 2short AI',
    brandBlurb:
      '2short.ai is a web app that turns long YouTube videos into Shorts, TikToks and Reels. It finds the moments, keeps the speaker centred with face tracking ("center stage"), adds animated subtitles and brand presets, and exports vertical, square or horizontal. On the free plan it takes YouTube links only; paid plans add Google Drive and public URL imports.',
    extraFaq: [
      {
        q: 'Is 2short AI free?',
        a: 'It has a free Starter plan with 30 minutes of AI analysis a month, YouTube links only, and no watermark. Paid plans run from $9.90/month (5 hours) to $49.90/month (50 hours). OpenShorts self-hosted is free with no cap; OpenShorts Cloud clips your first video free up to 60 minutes, then 20 minutes a month.',
      },
      {
        q: 'Can 2short AI clip a video I recorded myself?',
        a: 'Its pricing page lists YouTube links on every plan and Google Drive or public URLs from the Lite plan up; uploading a local file is not listed there. OpenShorts accepts a YouTube link or a direct upload on every plan, including the free one.',
      },
    ],
    tiers: [
      ['Starter (free)', '30 minutes of AI analysis a month, YouTube links only, no watermark, 1080p'],
      ['Lite', '$9.90/month: 5 hours of analysis, 60 minutes of exports on fast servers, Google Drive and URL import'],
      ['Pro', '$19.90/month: 15 hours of analysis, unlimited exports'],
      ['Premium', '$49.90/month: 50 hours of analysis, unlimited exports, priority support'],
    ],
    gotcha:
      'The meter is hours of video analysed, and the input is a link: YouTube on every plan, Google Drive and public URLs from Lite. If your recordings live on your disk rather than on YouTube or Drive, check the import path before you subscribe.',
    strengths: [
      'Cheap per hour: 5 hours of source a month for $9.90 is one of the lowest prices in this category',
      'No watermark even on the free plan, with 1080p exports',
      'A focused YouTube-to-Shorts workflow with face tracking and brand presets',
    ],
    whereWeDiffer: [
      'OpenShorts is MIT-licensed and self-hostable; 2short.ai is a closed cloud service.',
      'OpenShorts takes a local upload on every plan; 2short.ai lists link imports (YouTube, Drive, URL).',
      'OpenShorts adds layouts a single centred crop cannot do: two speakers stacked, screen recordings over the presenter, a webcam inset enlarged. It also dubs into 30+ languages with your own ElevenLabs key.',
      '2short.ai is cheaper per hour of source than OpenShorts Cloud and keeps its free exports unwatermarked, which ours are not. That is a real advantage.',
    ],
    bestFor:
      '2short.ai is the better pick if your sources are YouTube videos, you want the lowest price per hour and a single face-tracked crop is enough. OpenShorts is the better pick for uploads, podcasts with two people on camera, screen recordings, or a free self-hosted setup.',
    tldr: [
      '2short.ai is a YouTube-to-Shorts web app from $9.90/month, with a free plan of 30 minutes a month and no watermark. OpenShorts is open source: free when you run it yourself, or hosted from $12/month.',
      'Both find the moments and reframe them to 9:16 with face tracking. OpenShorts adds two-speaker, screencast and webcam-inset layouts, dubbing into 30+ languages with your own ElevenLabs key, and direct uploads on every plan.',
      'Pick 2short.ai for the lowest price per hour on YouTube sources. Pick OpenShorts for uploads, multi-person footage, self-hosting or changing the pipeline.',
    ],
    rows: { 'Usage cap': 'Metered in hours of analysis per month' },
  },
  sendshort: {
    facts: [
      { k: 'Free plan', v: 'None', s: '3 free videos at sign-up' },
      { k: 'Clipping from', v: '$29/mo', s: 'Professional ($23 yearly); Starter has none' },
      { k: 'Billed by', v: 'Shorts', s: '20, 50 or unlimited a month' },
      { k: 'Open source', v: 'No', s: 'Cloud only. OpenShorts: MIT, self-hostable' },
    ],
    pick: {
      them: ['You want faceless, avatar and prompt-to-video shorts too', 'You want captions translated into 100+ languages', 'One subscription for many formats matters more than depth'],
      us: ['The job is clipping your own long recordings', 'You want clipping on every plan, the free one included', 'You want to self-host or keep the cost near zero'],
    },
    published: '2026-10-05',
    name: 'SendShort',
    seo: {
      title: 'SendShort AI: Pricing & Open Source Alternative',
      description:
        'SendShort costs $19 to $59 a month and only clips long videos from the $29 plan up. What you get on each plan, and a free, open source alternative.',
      h1: 'SendShort AI: plans, limits, and the open source alternative',
    },
    checked: '2026-10-05',
    entryPrice: '$19/month ($15 billed yearly)',
    brandAlias: 'sendshort.ai',
    brandBlurb:
      'SendShort is a short-form video suite rather than a pure clipper. It cuts long videos into shorts, and also makes faceless videos from a text prompt, AI avatar videos, music videos and TikTok slideshows, with word-by-word captions, caption translation, AI voice-over, a scheduler for TikTok and YouTube, and an API.',
    extraFaq: [
      {
        q: 'Is SendShort free?',
        a: 'There is no free plan: SendShort gives 3 free videos at sign-up and offers a refund within 24 hours of paying. Plans cost $19, $29 and $59 a month, or $15, $23 and $47 billed yearly, and clipping long videos starts on the $29 Professional plan. OpenShorts self-hosted is free; OpenShorts Cloud clips your first video free up to 60 minutes, then 20 minutes a month.',
      },
    ],
    tiers: [
      ['Free', 'No free plan. 3 free videos at sign-up, refund within 24 hours of paying.'],
      ['Starter', '$19/month, or $15/month billed yearly: 20 shorts a month up to 90 seconds, 1080p, no watermark. Long-video clipping is not included.'],
      ['Professional', '$29/month, or $23/month billed yearly: 50 shorts a month up to 3 minutes, long-video clipping, avatars, auto-translate, AI hooks, B-roll, voice-over'],
      ['Business', '$59/month, or $47/month billed yearly: unlimited shorts up to 10 minutes, 4K at 60 fps'],
    ],
    gotcha:
      'The entry price is not the clipping price. Turning a long video into clips starts on the Professional plan at $29/month ($23 billed yearly); Starter is for shorts made from prompts and templates.',
    strengths: [
      'Covers more formats than a clipper: faceless prompt-to-video, avatars, slideshows and music videos',
      'Captions and caption translation in 100+ languages, plus AI voice-over',
      'An API and an agent interface for Claude, ChatGPT and Grok',
    ],
    whereWeDiffer: [
      'OpenShorts is MIT-licensed and self-hostable; SendShort is a closed cloud service.',
      'OpenShorts clips long videos on every plan, the free one included; SendShort starts long-video clipping at $29/month.',
      'OpenShorts reframes with face tracking plus two-speaker, screencast and webcam-inset layouts, which is the hard part of clipping a podcast or a stream.',
      'SendShort makes more kinds of short video than we do. If faceless or prompt-to-video content is the plan, it covers that and we do not.',
    ],
    bestFor:
      'SendShort is the better pick if you want one subscription for faceless videos, avatars and clips. OpenShorts is the better pick if the job is turning your own long recordings into clips, cheaply or self-hosted.',
    tldr: [
      'SendShort is a short-form video suite from $19/month ($15 yearly), but clipping long videos starts on the $29/month plan. OpenShorts is open source: free when you run it yourself, or hosted from $12/month with clipping on every plan.',
      'SendShort covers faceless videos, avatars and caption translation into 100+ languages. OpenShorts goes deeper on the clipping itself: moment scoring, face tracking, two-speaker and screencast layouts, dubbing into 30+ languages.',
      'Pick SendShort for many formats in one tool. Pick OpenShorts to clip your own long recordings, self-host, or keep the cost down.',
    ],
    rows: {
      'AI voice dubbing, 30+ languages': 'Caption translation and AI voice-over ($29 plan and up)',
      'AI UGC video with lip-synced actors': 'AI avatar videos ($29 plan and up)',
      'Usage cap': 'Metered in shorts per month',
    },
  },
}

/* Rows for the head-to-head table. `os` values are deliberately honest about the
 * hosted/self-hosted split rather than collapsing to "free". */
export const COMPARISON_ROWS = [
  {
    feature: 'Entry price',
    os: '$0 self-hosted · $0 hosted for 20 min/mo · $12/mo hosted without watermark',
    key: 'entryPrice',
  },
  { feature: 'Open source', os: 'Yes, MIT', vendor: 'No' },
  { feature: 'Self-hostable', os: 'Yes, Docker Compose', vendor: 'No, cloud only' },
  { feature: 'Source video stays on your machine', os: 'Yes when self-hosted', vendor: 'No' },
  { feature: 'AI viral moment detection', os: 'Yes, Gemini 3.1 Flash-Lite', vendor: 'Yes' },
  { feature: 'Face-tracked 9:16 reframing', os: 'Yes, MediaPipe + YOLOv8', vendor: 'Yes' },
  { feature: 'Word-level auto subtitles', os: 'Yes, faster-whisper', vendor: 'Yes' },
  { feature: 'AI voice dubbing, 30+ languages', os: 'Yes, with your own ElevenLabs key', vendor: 'No' },
  { feature: 'AI UGC video with lip-synced actors', os: 'Yes, from $0.65/video', vendor: 'No' },
  { feature: 'Free AI YouTube thumbnail & title studio', os: 'Yes', vendor: 'No' },
  { feature: 'Usage cap', os: 'None when self-hosted · metered on Cloud', vendor: 'Metered on every tier' },
]

/* Third-party figures used across the pages. Every one is attributed inline,
 * because sourced statistics are among the few things that reliably survive
 * into a generated answer. */
export const CITED_STATS = [
  {
    claim: 'Short-form video delivers the highest ROI of any content format.',
    source: 'HubSpot, State of Marketing 2025',
  },
  {
    claim: '91% of businesses use video as a marketing tool.',
    source: 'Wyzowl, Video Marketing Statistics 2025',
  },
]

/* Plans as the cost calculator needs them: minutes of source video covered per
 * month and the monthly price, on monthly and on yearly billing. Only tools
 * that bill by source minutes are here; Klap (per clip), Submagic (per video)
 * and SendShort (per short) cannot be priced on the same axis, and pretending
 * otherwise would be the kind of number this file exists to avoid. */
export const PRICE_MODELS = {
  // The edition the hosted plans are a convenience over: same pipeline, your
  // machine, no meter. Shown as its own bar so the calculator never implies the
  // hosted price is the only OpenShorts price.
  'openshorts-self': {
    name: 'OpenShorts self-hosted',
    unit: 'your machine, MIT',
    plans: [{ name: 'Docker, no watermark, no cap', monthly: { minutes: 1e9, price: 0 } }],
  },
  openshorts: {
    name: 'OpenShorts Cloud',
    unit: 'per source minute',
    checked: '2026-10-05',
    plans: [
      { name: 'Free', watermark: true, monthly: { minutes: 20, price: 0 } },
      { name: 'Starter', monthly: { minutes: 100, price: 12 }, yearly: { minutes: 100, price: 10 } },
      { name: 'Creator', monthly: { minutes: 300, price: 29 }, yearly: { minutes: 300, price: 24.17 } },
      { name: 'Pro', monthly: { minutes: 750, price: 59 }, yearly: { minutes: 750, price: 49.17 } },
      // Pro plus top-ups of 200 minutes at $25.
      { name: 'Pro + 200 min', monthly: { minutes: 950, price: 84 }, yearly: { minutes: 950, price: 74.17 } },
      { name: 'Pro + 400 min', monthly: { minutes: 1150, price: 109 }, yearly: { minutes: 1150, price: 99.17 } },
      { name: 'Pro + 600 min', monthly: { minutes: 1350, price: 134 }, yearly: { minutes: 1350, price: 124.17 } },
      { name: 'Pro + 800 min', monthly: { minutes: 1550, price: 159 }, yearly: { minutes: 1550, price: 149.17 } },
    ],
  },
  'opus-clip': {
    name: 'Opus Clip',
    unit: '1 credit per source minute',
    checked: '2026-10-05',
    plans: [
      { name: 'Free', watermark: true, monthly: { minutes: 60, price: 0 } },
      { name: 'Starter', monthly: { minutes: 150, price: 15 } },
      { name: 'Pro', monthly: { minutes: 300, price: 29 }, yearly: { minutes: 300, price: 14.5 } },
      { name: 'Pro, 2 packs', monthly: { minutes: 600, price: 58 }, yearly: { minutes: 600, price: 29 } },
    ],
  },
  vizard: {
    name: 'Vizard',
    unit: '1 credit per uploaded minute',
    checked: '2026-10-05',
    plans: [
      { name: 'Free', watermark: true, monthly: { minutes: 60, price: 0 } },
      { name: 'Creator', monthly: { minutes: 600, price: 29 }, yearly: { minutes: 600, price: 14.5 } },
    ],
  },
  'vidyo-ai': {
    name: 'Quso (Vidyo.ai)',
    unit: '~1 credit per minute',
    checked: '2026-10-05',
    plans: [
      { name: 'Free (720p)', monthly: { minutes: 75, price: 0 } },
      { name: 'Lite', monthly: { minutes: 100, price: 29 }, yearly: { minutes: 200, price: 19 } },
      { name: 'Essential', monthly: { minutes: 300, price: 39 }, yearly: { minutes: 600, price: 26 } },
      { name: 'Growth', monthly: { minutes: 600, price: 49 }, yearly: { minutes: 1200, price: 33 } },
    ],
  },
  '2short': {
    name: '2short.ai',
    unit: 'hours of video analysed',
    checked: '2026-10-05',
    plans: [
      { name: 'Free', monthly: { minutes: 30, price: 0 } },
      { name: 'Lite', monthly: { minutes: 300, price: 9.9 } },
      { name: 'Pro', monthly: { minutes: 900, price: 19.9 } },
      { name: 'Premium', monthly: { minutes: 3000, price: 49.9 } },
    ],
  },
}
