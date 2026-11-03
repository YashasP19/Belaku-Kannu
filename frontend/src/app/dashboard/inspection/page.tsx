'use client';

import { useEffect, useRef, useState } from 'react';
import { Camera, UploadCloud, Loader2, ScanSearch, TicketPlus, AlertTriangle, CheckCircle2, X } from 'lucide-react';
import { apiClient } from '@/lib/api';

type Finding = { issue: string; detail: string; severity: 'LOW' | 'MEDIUM' | 'HIGH' };
type Report = {
  equipment: string;
  condition: 'GOOD' | 'FAIR' | 'POOR' | 'CRITICAL' | 'UNCLEAR';
  urgency: 'ROUTINE' | 'SOON' | 'URGENT' | 'IMMEDIATE';
  findings: Finding[];
  suggested_actions: string[];
  confidence: number;
  limitations?: string;
  transformer_code: string | null;
  disclaimer: string;
};

const MAX_BYTES = 5 * 1024 * 1024;
const TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

const CONDITION_STYLE: Record<Report['condition'], string> = {
  GOOD: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  FAIR: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  POOR: 'bg-orange-50 text-orange-700 border-orange-200',
  CRITICAL: 'bg-red-50 text-red-700 border-red-200',
  UNCLEAR: 'bg-slate-100 text-slate-600 border-slate-200',
};
const SEVERITY_STYLE: Record<Finding['severity'], string> = {
  LOW: 'bg-slate-100 text-slate-600',
  MEDIUM: 'bg-amber-100 text-amber-700',
  HIGH: 'bg-red-100 text-red-700',
};

function errorText(e: any): string {
  return e?.response?.data?.detail || e?.message || 'Something went wrong.';
}

export default function InspectionPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [notes, setNotes] = useState('');
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [ticketState, setTicketState] = useState<'idle' | 'saving' | 'done'>('idle');
  const [ticketMsg, setTicketMsg] = useState<string | null>(null);

  useEffect(() => {
    return () => { if (preview) URL.revokeObjectURL(preview); };
  }, [preview]);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    if (!TYPES.includes(f.type)) return setError('Please choose a JPEG, PNG, GIF or WebP image.');
    if (f.size > MAX_BYTES) return setError('Image is larger than 5 MB.');
    setError(null);
    setReport(null);
    setTicketState('idle');
    setTicketMsg(null);
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const clear = () => {
    setFile(null);
    setPreview(null);
    setReport(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const analyze = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setReport(null);
    setTicketState('idle');
    setTicketMsg(null);
    try {
      const form = new FormData();
      form.append('image', file);
      if (code.trim()) form.append('transformer_code', code.trim());
      if (notes.trim()) form.append('notes', notes.trim());
      const res = await apiClient.post<Report>('/inspection/analyze', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      });
      setReport(res.data);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  };

  const raiseTicket = async () => {
    if (!report || !report.transformer_code) return;
    setTicketState('saving');
    setTicketMsg(null);
    try {
      const priority = report.condition === 'CRITICAL' || report.urgency === 'IMMEDIATE' ? 'CRITICAL' : 'HIGH';
      const summary =
        `${report.equipment}: ${report.condition} (${report.urgency}). ` +
        report.findings.map((f) => `${f.issue} [${f.severity}]`).join('; ') +
        (report.suggested_actions.length ? `. Action: ${report.suggested_actions[0]}` : '');
      await apiClient.post('/inspection/ticket', {
        transformer_code: report.transformer_code,
        priority,
        summary,
      });
      setTicketState('done');
      setTicketMsg('Maintenance ticket created. See the Tickets page.');
    } catch (e) {
      setTicketState('idle');
      setTicketMsg(errorText(e));
    }
  };

  return (
    <div className="space-y-6">
      <div className="border-b border-slate-100 pb-5">
        <h1 className="flex items-center gap-2 font-heading text-2xl font-bold tracking-tight text-slate-900">
          <Camera className="text-blue-600" size={24} /> Photo Inspection
          <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-blue-600">Multimodal AI</span>
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a photo of a transformer (oil leak, rust, bushing damage, thermal image). The AI returns a condition report and next steps.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Upload */}
        <div className="bento-card p-5">
          {!preview ? (
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}
              className={`flex h-72 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed text-center transition-colors ${
                dragging ? 'border-blue-400 bg-blue-50' : 'border-slate-200 bg-slate-50 hover:border-blue-300 hover:bg-blue-50/50'
              }`}
            >
              <UploadCloud size={36} className="text-blue-500" />
              <p className="text-sm font-semibold text-slate-700">Drop a photo here, or click to browse</p>
              <p className="text-xs text-slate-400">JPEG, PNG, GIF or WebP · up to 5 MB</p>
            </div>
          ) : (
            <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-900">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={preview} alt="Selected transformer" className="mx-auto max-h-72 w-auto object-contain" />
              <button
                onClick={clear}
                className="absolute right-2 top-2 rounded-full bg-white/90 p-1.5 text-slate-600 shadow hover:text-red-600"
                aria-label="Remove image"
              >
                <X size={14} />
              </button>
            </div>
          )}
          <input ref={inputRef} type="file" accept={TYPES.join(',')} className="hidden" onChange={(e) => pick(e.target.files?.[0])} />

          <div className="mt-4 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600">Transformer code (optional, enables ticketing)</label>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="e.g. 100847"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600">Engineer's note (optional)</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                maxLength={500}
                placeholder="e.g. Humming noise, oil smell near the base"
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <button
              onClick={analyze}
              disabled={!file || loading}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-800 to-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-blue-600/25 transition-all hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <ScanSearch size={16} />}
              {loading ? 'Analysing photo…' : 'Analyse photo'}
            </button>
          </div>
        </div>

        {/* Result */}
        <div className="bento-card min-h-[24rem] p-5">
          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-xl border border-red-100 bg-red-50 p-3 text-sm text-red-700">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" /> <span>{error}</span>
            </div>
          )}

          {!report && !loading && !error && (
            <div className="flex h-full min-h-[20rem] flex-col items-center justify-center gap-2 text-center text-slate-400">
              <ScanSearch size={32} />
              <p className="text-sm">The condition report will appear here.</p>
            </div>
          )}

          {loading && (
            <div className="flex h-full min-h-[20rem] flex-col items-center justify-center gap-3 text-slate-500">
              <Loader2 size={28} className="animate-spin text-blue-600" />
              <p className="text-sm">Inspecting the photo…</p>
            </div>
          )}

          {report && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wider ${CONDITION_STYLE[report.condition]}`}>
                  {report.condition}
                </span>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">Urgency: {report.urgency}</span>
                <span className="ml-auto text-xs text-slate-400">Confidence {Math.round((report.confidence ?? 0) * 100)}%</span>
              </div>
              <p className="text-sm text-slate-600">{report.equipment}</p>

              <div>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Findings</h3>
                {report.findings?.length ? (
                  <ul className="space-y-2">
                    {report.findings.map((f, i) => (
                      <li key={i} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-800">{f.issue}</span>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.LOW}`}>{f.severity}</span>
                        </div>
                        <p className="mt-1 text-xs text-slate-500">{f.detail}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-slate-500">No issues identified in this photo.</p>
                )}
              </div>

              {report.suggested_actions?.length > 0 && (
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Suggested actions</h3>
                  <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
                    {report.suggested_actions.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}

              {report.limitations && <p className="text-xs text-slate-400">Could not assess: {report.limitations}</p>}

              <div className="border-t border-slate-100 pt-4">
                {report.transformer_code ? (
                  <button
                    onClick={raiseTicket}
                    disabled={ticketState !== 'idle'}
                    className="flex w-full items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-700 transition-colors hover:bg-blue-100 disabled:opacity-60"
                  >
                    {ticketState === 'saving' ? <Loader2 size={16} className="animate-spin" /> : ticketState === 'done' ? <CheckCircle2 size={16} /> : <TicketPlus size={16} />}
                    {ticketState === 'done' ? 'Ticket created' : `Raise ticket for ${report.transformer_code}`}
                  </button>
                ) : (
                  <p className="text-xs text-slate-400">Enter a transformer code before analysing to raise a ticket from this report.</p>
                )}
                {ticketMsg && <p className={`mt-2 text-xs ${ticketState === 'done' ? 'text-emerald-600' : 'text-red-600'}`}>{ticketMsg}</p>}
                <p className="mt-3 text-[11px] leading-snug text-slate-400">{report.disclaimer}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
