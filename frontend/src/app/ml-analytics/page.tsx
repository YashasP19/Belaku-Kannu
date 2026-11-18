"use client";

import React, { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  Activity, AlertTriangle, BarChart2, Brain, Camera, CheckCircle2, ChevronDown, Gauge, Play,
  Thermometer, Ticket, Wifi, WifiOff, Zap,
} from 'lucide-react';
import { BentoCard } from '@/components/widgets/BentoCard';
import { connectionOf, STATUS_STYLE, Tile } from '@/components/widgets/LiveIoTPanel';
import {
  getIotAlerts, getLiveTelemetry, InspectionResult, IotAlert, LiveTelemetry,
  raiseIotInspectionTicket, runIotInspection,
} from '@/lib/api';

const POLL_MS = 3000;

const VERDICT_STYLE: Record<string, string> = {
  HEALTHY: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  WARNING: 'bg-amber-50 text-amber-700 border-amber-100',
  CRITICAL: 'bg-red-50 text-red-700 border-red-100',
  UNKNOWN: 'bg-slate-100 text-slate-500 border-slate-200',
};
const VERDICT_BAR: Record<string, string> = {
  HEALTHY: 'bg-emerald-500', WARNING: 'bg-amber-500', CRITICAL: 'bg-red-500', UNKNOWN: 'bg-slate-400',
};
const PRIORITY_STYLE: Record<string, string> = {
  URGENT: 'bg-red-50 text-red-700 border-red-100',
  SOON: 'bg-amber-50 text-amber-700 border-amber-100',
  ROUTINE: 'bg-slate-100 text-slate-600 border-slate-200',
};
const MODEL_NAMES = ['Isolation Forest', 'XGBoost', 'Random Forest', 'Cox survival'];

function lifeText(days: number | null) {
  if (days === null || days === undefined) return '—';
  return days >= 730 ? `${(days / 365).toFixed(1)} years` : `${days} days`;
}

function AnalyticsContent() {
  const params = useSearchParams();
  const wanted = params.get('transformer');

  const [readings, setReadings] = useState<LiveTelemetry[]>([]);
  const [alerts, setAlerts] = useState<IotAlert[]>([]);
  const [selected, setSelected] = useState<string | null>(wanted);
  const [fetchedAt, setFetchedAt] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  const [offline, setOffline] = useState(false);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<InspectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticketMsg, setTicketMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [showInputs, setShowInputs] = useState(false);

  const load = useCallback(async () => {
    try {
      const [live, open] = await Promise.all([getLiveTelemetry(), getIotAlerts('active')]);
      setReadings(live);
      setAlerts(open);
      setFetchedAt(Date.now());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    load();
    const poll = setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [load]);

  // Pick a transformer once data arrives: the one in the URL if it is live, else the newest.
  useEffect(() => {
    if (readings.length === 0) return;
    if (!selected || !readings.some((r) => r.transformer_code === selected)) {
      setSelected(readings[0].transformer_code);
    }
  }, [readings, selected]);

  // A result belongs to one transformer: clear it when the user switches.
  useEffect(() => { setResult(null); setError(null); setTicketMsg(null); }, [selected]);

  const current = readings.find((r) => r.transformer_code === selected) ?? null;
  const myAlerts = alerts.filter((a) => a.transformer_code === selected);
  const age = current ? current.age_seconds + (now - fetchedAt) / 1000 : 0;
  const conn = offline ? 'OFFLINE' : connectionOf(age);

  const runInspection = async () => {
    if (!current) return;
    setRunning(true);
    setError(null);
    setTicketMsg(null);
    try {
      setResult(await runIotInspection(current.transformer_code));
    } catch (e: any) {
      setResult(null);
      setError(e?.response?.data?.detail || 'The inspection could not be completed. Is the backend running?');
    } finally {
      setRunning(false);
    }
  };

  const raiseTicket = async () => {
    if (!result) return;
    const critical = result.risk_category === 'CRITICAL' || result.protection.status === 'CRITICAL';
    const top = result.recommendations.filter((r) => r.priority !== 'ROUTINE').slice(0, 3).map((r) => r.action);
    try {
      const t = await raiseIotInspectionTicket({
        transformer_id: result.transformer_code,
        priority: critical ? 'CRITICAL' : 'HIGH',
        summary: `Health ${result.health_score.toFixed(0)}/100 (${result.risk_category}). ${result.summary} Actions: ${top.join(' ')}`,
        health_score: result.health_score,
      });
      setTicketMsg({ ok: true, text: `Ticket raised (${t.priority}). See the Tickets page.` });
    } catch (e: any) {
      setTicketMsg({ ok: false, text: e?.response?.data?.detail || 'Could not raise the ticket.' });
    }
  };

  const maxImpact = result ? Math.max(...result.drivers.map((d) => Math.abs(d.impact)), 0.0001) : 1;

  return (
    <div className="space-y-6 animate-in fade-in duration-500 max-w-7xl mx-auto px-4 pb-12">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-3 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-3xl font-heading font-extrabold text-slate-900 tracking-tight">AI Analytics</h1>
          <p className="text-slate-500 mt-1 flex items-center gap-2 text-sm font-medium">
            <Brain size={16} className="text-primary" />
            Live transformer inspection: instant protection alarms plus the four predictive models
          </p>
        </div>
        <Link
          href="/ml-analytics/performance"
          className="flex items-center gap-2 bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-1.5 rounded-full text-xs font-bold transition-colors"
        >
          <BarChart2 size={13} /> Model performance
        </Link>
      </div>

      {/* Live reading + Run Inspection */}
      <BentoCard
        title="Latest IoT Monitoring"
        className="p-5"
        action={
          readings.length > 1 ? (
            <select
              value={selected ?? ''}
              onChange={(e) => setSelected(e.target.value)}
              className="bg-slate-50 border border-slate-100 rounded-lg px-3 py-1.5 text-xs font-bold text-slate-700 focus:outline-none"
            >
              {readings.map((r) => <option key={r.transformer_id} value={r.transformer_code}>{r.transformer_code}</option>)}
            </select>
          ) : undefined
        }
      >
        {!current ? (
          <div className="flex flex-col items-center justify-center text-slate-400 py-10">
            <WifiOff size={28} className="mb-2 opacity-50" />
            <p className="text-sm font-medium">{offline ? 'Cannot reach the backend. Retrying…' : 'No device readings yet'}</p>
            <p className="text-xs mt-1">Start the Wokwi simulation, then run the inspection here.</p>
          </div>
        ) : (
          <div className="flex flex-col lg:flex-row lg:items-end gap-5">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-3">
                <span className="font-bold text-slate-800">{current.transformer_code}</span>
                <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${STATUS_STYLE[current.status]}`}>
                  {current.status}
                </span>
                <span className={`text-[10px] font-bold flex items-center gap-1 ${
                  conn === 'ONLINE' ? 'text-emerald-600' : conn === 'STALE' ? 'text-amber-600' : 'text-red-600'
                }`}>
                  {conn === 'OFFLINE' ? <WifiOff size={12} /> : <Wifi size={12} />}
                  {conn === 'ONLINE' ? 'Device online' : conn === 'STALE' ? 'Delayed' : 'Device offline'}
                </span>
                {myAlerts.length > 0 && (
                  <span className="text-[10px] font-bold text-red-600 flex items-center gap-1">
                    <AlertTriangle size={12} /> {myAlerts.length} active alarm{myAlerts.length > 1 ? 's' : ''}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Tile icon={<Zap size={12} />} label="Voltage" value={current.voltage_v} unit="V" />
                <Tile icon={<Gauge size={12} />} label="Current" value={current.current_a} unit="A" />
                <Tile icon={<Thermometer size={12} />} label="Temperature" value={current.temperature_c} unit="°C" />
              </div>
              <p className="text-[11px] text-slate-400 mt-2">
                Last update {new Date(current.received_at).toLocaleTimeString('en-IN')} · {Math.round(age)} s ago
              </p>
            </div>
            <button
              onClick={runInspection}
              disabled={running}
              className="flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-6 py-3 rounded-xl text-sm font-bold transition-colors lg:w-56"
            >
              <Play size={16} className={running ? 'animate-pulse' : ''} />
              {running ? 'Running models…' : 'Run Inspection'}
            </button>
          </div>
        )}
      </BentoCard>

      {error && (
        <div className="bg-red-50 border border-red-100 text-red-700 text-sm font-semibold rounded-xl px-4 py-3">{error}</div>
      )}

      {/* Models running */}
      {running && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {MODEL_NAMES.map((name) => (
            <div key={name} className="bento-card p-5 animate-pulse">
              <div className="text-xs font-bold uppercase tracking-wider text-slate-400">Running</div>
              <div className="text-lg font-extrabold text-slate-800 mt-1">{name}</div>
              <div className="h-2 bg-slate-100 rounded-full mt-4" />
            </div>
          ))}
        </div>
      )}

      {/* Results */}
      {result && !running && (
        <>
          {/* Health summary */}
          <BentoCard className="p-6">
            <div className="flex flex-col lg:flex-row gap-6 lg:items-center">
              <div className="flex items-center gap-5">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Health score</div>
                  <div className="text-6xl font-extrabold text-slate-900 leading-none mt-1">
                    {result.health_score.toFixed(0)}<span className="text-xl text-slate-400">/100</span>
                  </div>
                </div>
                <span className={`text-xs font-extrabold px-3 py-1 rounded-full border ${VERDICT_STYLE[result.risk_category]}`}>
                  {result.risk_category}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-6 lg:border-l lg:border-slate-100 lg:pl-6">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Failure probability</div>
                  <div className="text-2xl font-extrabold text-slate-800">
                    {result.failure_probability !== null ? `${result.failure_probability.toFixed(0)}%` : '—'}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Estimated remaining life</div>
                  <div className="text-2xl font-extrabold text-slate-800">{lifeText(result.expected_lifetime_days)}</div>
                </div>
              </div>
              <div className="flex-1 lg:border-l lg:border-slate-100 lg:pl-6">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Protection alarms</span>
                  <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${STATUS_STYLE[result.protection.status]}`}>
                    {result.protection.status}
                  </span>
                </div>
                <p className="text-sm text-slate-600">{result.summary}</p>
              </div>
            </div>
          </BentoCard>

          {/* The four models */}
          <div>
            <h2 className="font-heading font-semibold text-lg text-slate-800 mb-3">The four models</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {result.models.map((m) => (
                <div key={m.key} className="bento-card p-5 flex flex-col gap-3">
                  <div>
                    <div className="text-base font-extrabold text-slate-800">{m.name}</div>
                    <div className="text-xs text-slate-500">{m.role}</div>
                  </div>
                  <span className={`self-start text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${VERDICT_STYLE[m.verdict]}`}>
                    {m.verdict}
                  </span>
                  <div>
                    <div className="flex justify-between text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                      <span>Risk score</span><span>{m.risk_score.toFixed(0)}/100</span>
                    </div>
                    <div className="h-2 bg-slate-100 rounded-full mt-1 overflow-hidden">
                      <div className={`h-full rounded-full ${VERDICT_BAR[m.verdict]}`} style={{ width: `${Math.min(m.risk_score, 100)}%` }} />
                    </div>
                  </div>
                  <div className="text-[11px] text-slate-500">
                    {m.in_blend
                      ? `Counts for ${(m.weight * 100).toFixed(0)}% of the health score`
                      : 'Not counted: the more cautious classifier is used'}
                    {m.expected_lifetime_days !== undefined && m.expected_lifetime_days !== null && (
                      <div className="mt-0.5">Median life: {lifeText(m.expected_lifetime_days)}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Risk drivers (SHAP) */}
            <BentoCard title="Why: top risk drivers" className="p-5">
              <div className="space-y-3">
                {result.drivers.map((d) => (
                  <div key={d.feature}>
                    <div className="flex justify-between text-xs">
                      <span className="font-semibold text-slate-700">{d.label}</span>
                      <span className="text-slate-400">{d.value} · {d.direction}</span>
                    </div>
                    <div className="h-2 bg-slate-100 rounded-full mt-1 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${d.impact > 0 ? 'bg-red-500' : 'bg-emerald-500'}`}
                        style={{ width: `${(Math.abs(d.impact) / maxImpact) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
                <p className="text-[11px] text-slate-400 pt-1">
                  SHAP values from the XGBoost model. Red pushes the risk up; green pushes it down.
                </p>
              </div>
            </BentoCard>

            {/* What can be done */}
            <BentoCard title="What can be done" className="p-5">
              <div className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
                {result.recommendations.map((r, i) => (
                  <div key={i} className="flex gap-3">
                    <span className={`shrink-0 h-fit text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${PRIORITY_STYLE[r.priority]}`}>
                      {r.priority}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-slate-800">{r.action}</p>
                      <p className="text-[11px] text-slate-500">{r.reason}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-100">
                <button
                  onClick={raiseTicket}
                  className="flex items-center gap-1.5 text-xs font-bold text-white bg-slate-800 hover:bg-slate-900 px-3 py-2 rounded-lg transition-colors"
                >
                  <Ticket size={14} /> Raise maintenance ticket
                </button>
                <Link
                  href="/dashboard/inspection"
                  className="flex items-center gap-1.5 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-slate-200 px-3 py-2 rounded-lg transition-colors"
                >
                  <Camera size={14} /> Photo inspection
                </Link>
                {ticketMsg && (
                  <span className={`text-xs font-semibold flex items-center gap-1 ${ticketMsg.ok ? 'text-emerald-600' : 'text-red-600'}`}>
                    {ticketMsg.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} {ticketMsg.text}
                  </span>
                )}
              </div>
            </BentoCard>
          </div>

          {/* How the numbers were produced */}
          <div className="bento-card p-5">
            <button
              onClick={() => setShowInputs((s) => !s)}
              className="w-full flex items-center justify-between text-sm font-bold text-slate-700"
            >
              <span className="flex items-center gap-2"><Activity size={14} /> What the models were given</span>
              <ChevronDown size={16} className={`transition-transform ${showInputs ? 'rotate-180' : ''}`} />
            </button>
            {showInputs && (
              <div className="mt-4 space-y-3 text-xs text-slate-600">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {[
                    ['Readings used', `${result.inputs.readings_used} over ${result.inputs.window_seconds.toFixed(0)} s`],
                    ['Average voltage', `${result.inputs.avg_voltage_v} V → ${result.inputs.avg_voltage_lv_mapped} V (×√3)`],
                    ['Average current', `${result.inputs.avg_current_a} A → ${result.inputs.avg_load_pct_mapped}% load`],
                    ['Average temperature', `${result.inputs.avg_temperature_c} °C`],
                    ['Transformer rating', `${result.inputs.rated_kva} kVA`],
                    ['Transformer age', `${result.inputs.age_years} years`],
                    ['Data age at run', `${result.inputs.data_age_seconds.toFixed(0)} s`],
                  ].map(([k, v]) => (
                    <div key={k} className="bg-slate-50 border border-slate-100 rounded-lg p-2.5">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{k}</div>
                      <div className="font-semibold text-slate-800 mt-0.5">{v}</div>
                    </div>
                  ))}
                </div>
                <ul className="list-disc pl-5 space-y-1">
                  {result.inputs.notes.map((n) => <li key={n}>{n}</li>)}
                </ul>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default function MLAnalyticsPage() {
  return (
    <Suspense fallback={<div className="p-10 text-slate-400 text-sm">Loading…</div>}>
      <AnalyticsContent />
    </Suspense>
  );
}
