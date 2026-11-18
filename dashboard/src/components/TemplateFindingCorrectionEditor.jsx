import React, { useEffect, useMemo, useState } from 'react';

const COMMON_BOX_FIELDS = [
  { path: 'box.x', label: 'Left (0–1)', type: 'number', step: '0.01', min: 0, max: 1 },
  { path: 'box.y', label: 'Top (0–1)', type: 'number', step: '0.01', min: 0, max: 1 },
  { path: 'box.width', label: 'Width (0–1)', type: 'number', step: '0.01', min: 0.001, max: 1 },
  { path: 'box.height', label: 'Height (0–1)', type: 'number', step: '0.01', min: 0.001, max: 1 },
];

const CORRECTION_FIELDS = {
  overview: [
    { path: 'summary', label: 'Summary', type: 'textarea' },
    { path: 'visual_identity', label: 'Visual identity', type: 'textarea' },
    { path: 'editorial_style', label: 'Editorial style', type: 'textarea' },
    { path: 'overall_pacing', label: 'Overall pacing', type: 'text' },
  ],
  color_palette: [
    { path: 'hex_color', label: 'Color', type: 'color' },
    { path: 'role', label: 'Color role', type: 'select', options: ['background', 'accent', 'caption', 'hook', 'overlay', 'dominant', 'other'] },
  ],
  backgrounds: [
    { path: 'kind', label: 'Treatment', type: 'select', options: ['original_footage', 'blurred_duplicate', 'solid_color', 'gradient', 'image', 'video', 'other', 'unknown'] },
    { path: 'description', label: 'Description', type: 'textarea' },
    { path: 'colors', label: 'Colors (comma-separated hex values)', type: 'text' },
  ],
  compositions: [
    { path: 'kind', label: 'Layout', type: 'select', options: ['single_subject', 'picture_in_picture', 'split_screen', 'side_by_side', 'stacked', 'screen_recording', 'collage', 'other', 'unknown'] },
    { path: 'framing', label: 'Framing', type: 'select', options: ['extreme_closeup', 'closeup', 'medium', 'wide', 'full_frame', 'unknown'] },
    { path: 'description', label: 'Description', type: 'textarea' },
  ],
  text_regions: [
    { path: 'role', label: 'Text role', type: 'select', options: ['caption', 'hook', 'title', 'lower_third', 'label', 'watermark_text', 'other'] },
    { path: 'visible_text', label: 'Visible text', type: 'textarea' },
    ...COMMON_BOX_FIELDS,
    { path: 'typography.font_family', label: 'Confirmed font family', type: 'text' },
    { path: 'typography.weight', label: 'Font weight', type: 'text' },
    { path: 'typography.style', label: 'Font style', type: 'select', options: ['normal', 'italic', 'oblique', 'unknown'] },
    { path: 'typography.size_ratio', label: 'Font size ratio', type: 'number', step: '0.001', min: 0.001, max: 0.3 },
    { path: 'typography.fill_color', label: 'Text color', type: 'color' },
    { path: 'typography.highlight_color', label: 'Highlight color', type: 'color' },
    { path: 'typography.outline_color', label: 'Outline color', type: 'color' },
    { path: 'typography.outline_strength', label: 'Outline strength', type: 'select', options: ['none', 'thin', 'medium', 'heavy', 'unknown'] },
    { path: 'typography.shadow', label: 'Shadow', type: 'select', options: ['none', 'subtle', 'strong', 'unknown'] },
    { path: 'typography.alignment', label: 'Text alignment', type: 'select', options: ['left', 'center', 'right', 'unknown'] },
    { path: 'typography.uppercase', label: 'Uppercase', type: 'select', options: ['true', 'false'] },
    { path: 'typography.line_count', label: 'Line count', type: 'number', step: '1', min: 1, max: 12, integer: true },
    { path: 'first_seen_ms', label: 'First visible (ms)', type: 'number', step: '1', min: 0, integer: true },
    { path: 'last_seen_ms', label: 'Last visible (ms)', type: 'number', step: '1', min: 0, integer: true },
    { path: 'animation', label: 'Text animation', type: 'select', options: ['none', 'fade', 'slide', 'pop', 'typewriter', 'word_by_word', 'karaoke_highlight', 'pulse', 'other', 'unknown'] },
    { path: 'animation_notes', label: 'Animation notes', type: 'textarea' },
    { path: 'notes', label: 'Finding notes', type: 'textarea' },
  ],
  graphic_overlays: [
    { path: 'kind', label: 'Overlay type', type: 'select', options: ['logo', 'watermark', 'image', 'badge', 'emoji', 'shape', 'frame', 'other'] },
    { path: 'description', label: 'Description', type: 'textarea' },
    ...COMMON_BOX_FIELDS,
    { path: 'opacity', label: 'Opacity', type: 'number', step: '0.01', min: 0, max: 1 },
  ],
  effects: [
    { path: 'kind', label: 'Effect', type: 'select', options: ['zoom', 'pan', 'shake', 'slow_motion', 'speed_ramp', 'blur', 'glitch', 'color_grade', 'vignette', 'grain', 'stabilization', 'other'] },
    { path: 'description', label: 'Description', type: 'textarea' },
    { path: 'start_ms', label: 'Start (ms)', type: 'number', step: '1', min: 0, integer: true },
    { path: 'end_ms', label: 'End (ms)', type: 'number', step: '1', min: 0, integer: true },
  ],
  transitions: [
    { path: 'kind', label: 'Transition', type: 'select', options: ['cut', 'fade', 'dissolve', 'wipe', 'slide', 'whip_pan', 'zoom', 'flash', 'match_cut', 'other', 'uncertain'] },
    { path: 'at_ms', label: 'Position (ms)', type: 'number', step: '1', min: 0, integer: true },
    { path: 'duration_ms', label: 'Duration (ms)', type: 'number', step: '1', min: 0, max: 10000, integer: true },
    { path: 'notes', label: 'Notes', type: 'textarea' },
  ],
  scenes: [
    { path: 'start_ms', label: 'Scene start (ms)', type: 'number', step: '1', min: 0, integer: true },
    { path: 'end_ms', label: 'Scene end (ms)', type: 'number', step: '1', min: 0, integer: true },
    { path: 'description', label: 'Description', type: 'textarea' },
    { path: 'content_type', label: 'Content type', type: 'text' },
    { path: 'mood', label: 'Mood', type: 'text' },
    { path: 'energy', label: 'Energy', type: 'select', options: ['low', 'medium', 'high', 'variable', 'unknown'] },
    { path: 'editorial_role', label: 'Editorial role', type: 'text' },
  ],
};

function readPath(object, path) {
  return path.split('.').reduce((value, key) => value == null ? undefined : value[key], object);
}

function initialFieldValue(finding, field) {
  if (field.path === 'typography.font_family') {
    return finding?.human_font_family || finding?.typography?.font_candidates?.[0]?.family || '';
  }
  const value = readPath(finding, field.path);
  if (field.path === 'colors' && Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined) return '';
  return String(value);
}

function setPath(object, path, value) {
  const parts = path.split('.');
  let current = object;
  parts.slice(0, -1).forEach((key) => {
    if (!current[key]) current[key] = {};
    current = current[key];
  });
  current[parts[parts.length - 1]] = value;
}

function makePatch(fields, baseline, draft) {
  const result = {};
  fields.forEach((field) => {
    const before = baseline[field.path] ?? '';
    const current = draft[field.path] ?? '';
    if (String(before) === String(current) || String(current).trim() === '') return;
    let value = current;
    if (field.type === 'number') {
      value = Number(current);
      if (!Number.isFinite(value)) return;
      if (field.integer) value = Math.round(value);
    } else if (field.path === 'typography.uppercase') {
      value = current === 'true';
    } else if (field.path === 'colors') {
      value = String(current).split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
    }
    setPath(result, field.path, value);
  });
  return result;
}

export default function TemplateFindingCorrectionEditor({
  targetType,
  finding,
  onSave,
  disabled = false,
}) {
  const fields = CORRECTION_FIELDS[targetType] || [];
  const [open, setOpen] = useState(false);
  const initial = useMemo(
    () => Object.fromEntries(fields.map((field) => [field.path, initialFieldValue(finding, field)])),
    [finding, targetType],
  );
  const [baseline, setBaseline] = useState(initial);
  const [draft, setDraft] = useState(initial);

  useEffect(() => {
    if (!open) {
      setBaseline(initial);
      setDraft(initial);
    }
  }, [initial, open]);

  const patch = useMemo(() => makePatch(fields, baseline, draft), [fields, baseline, draft]);
  const change = (path, value) => setDraft((current) => ({ ...current, [path]: value }));

  const save = async () => {
    if (disabled || !Object.keys(patch).length) return;
    const saved = await onSave(patch);
    if (saved) setOpen(false);
  };

  return (
    <div className="mt-3">
      <button
        type="button"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => {
          if (!open) {
            setBaseline(initial);
            setDraft(initial);
          }
          setOpen((value) => !value);
        }}
        className="text-xs font-medium text-brass hover:underline disabled:opacity-50"
      >
        {open ? 'Close correction editor' : 'Correct finding'}
      </button>
      {open && (
        <div className="mt-3 rounded-input border border-rule bg-paper2/50 p-3 space-y-3">
          <p className="text-xs text-muted">
            Human corrections are saved separately. The original AI analysis and its evidence are preserved.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {fields.map((field) => (
              <label key={field.path} className={field.type === 'textarea' ? 'sm:col-span-2 block' : 'block'}>
                <span className="eyebrow mb-1 block">{field.label}</span>
                {field.type === 'textarea' ? (
                  <textarea
                    value={draft[field.path] || ''}
                    onChange={(event) => change(field.path, event.target.value)}
                    rows={2}
                    maxLength={2000}
                    className="input-field text-xs resize-y"
                    disabled={disabled}
                  />
                ) : field.type === 'select' ? (
                  <select
                    value={draft[field.path] || ''}
                    onChange={(event) => change(field.path, event.target.value)}
                    className="input-field text-xs"
                    disabled={disabled}
                  >
                    <option value="">Keep current</option>
                    {field.options.map((option) => <option key={option} value={option}>{option.replaceAll('_', ' ')}</option>)}
                  </select>
                ) : (
                  <input
                    type={field.type === 'color' ? 'color' : field.type === 'number' ? 'number' : 'text'}
                    value={draft[field.path] || (field.type === 'color' ? '#ffffff' : '')}
                    onChange={(event) => change(field.path, event.target.value)}
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    placeholder={field.path === 'colors' ? '#FFFFFF, #000000' : ''}
                    className="input-field text-xs"
                    disabled={disabled}
                  />
                )}
              </label>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="readout">{Object.keys(patch).length ? 'Unsaved changes ready' : 'Change a field to create a correction'}</span>
            <button
              type="button"
              onClick={save}
              disabled={disabled || !Object.keys(patch).length}
              className="btn-primary px-3 py-1.5 text-xs disabled:opacity-50"
            >
              Save correction
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
