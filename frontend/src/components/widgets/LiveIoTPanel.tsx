'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Gauge, Thermometer, Wifi, WifiOff, Zap } from 'lucide-react';
import { BentoCard } from './BentoCard';
import {
  acknowledgeIotAlert, getIotAlerts, getLiveTelemetry, IotAlert, LiveTelemetry,
} from '@/lib/api';

const POLL_MS = 3000;

export const STATUS_STYLE: Record<string, string> = {
  SAFE: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  WARNING: 'bg-amber-50 text-amber-700 border-amber-100',
  CRITICAL: 'bg-red-50 text-red-700 border-red-100',
};

export function connectionOf(ageSeconds: number): 'ONLINE' | 'STALE' | 'OFFLINE' {
  if (ageSeconds <= 10) return 'ONLINE';
  if (ageSeconds <= 60) return 'STALE';
  return 'OFFLINE';
}

export function Tile({ icon, label, value, unit }: { icon: React.ReactNode; label: string; value: number; unit: string }) {
  return (
    <div className="bg-slate-50 border border-slate-100 rounded-xl p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        {icon} {label}
      </div>
      <div className="mt-1 text-2xl font-extrabold text-slate-900">
        {value.toFixed(1)} <span className="text-xs font-semibold text-slate-400">{unit}</span>
      </div>
    </div>
  );
}

export function LiveIoTPanel() {
  const [readings, setReadings] = useState<LiveTelemetry[]>([]);
  const [alerts, setAlerts] = useState<IotAlert[]>([]);
  const [fetchedAt, setFetchedAt] = useState<number>(Date.now());
  const [now, setNow] = useState<number>(Date.now());
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    try {
      const [live, all] = await Promise.all([getLiveTelemetry(), getIotAlerts('all')]);
      setReadings(live);
      setAlerts(all);
      setFetchedAt(Date.now());
      setError(null);
    } catch {
      setError('Cannot reach the backend. Retrying…');
    }
  }, []);

  // Poll every 3 s; pause while the tab is hidden.
  useEffect(() => {
    load();
    const poll = setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [load]);

  const acknowledge = async (id: string) => {
    try {
      await acknowledgeIotAlert(id);
      load();
    } catch (e) {
      console.error('Failed to acknowledge alert', e);
    }
  };

  const open = alerts.filter((a) => a.resolved_at === null);
  const sinceFetch = (now - fetchedAt) / 1000;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Live readings */}
      <BentoCard
        title="Latest IoT Monitoring"
        className="p-5"
        action={
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Activity size={12} className="text-primary animate-pulse" /> refreshes every 3 s
            </span>
            <Link
              href={readings[0] ? `/ml-analytics?transformer=${encodeURIComponent(readings[0].transformer_code)}` : '/ml-analytics'}
              className="text-xs font-bold text-primary hover:text-blue-700 flex items-center gap-1"
            >
              View full <ArrowRight size={12} />
            </Link>
          </div>
        }
      >
        {error && <p className="text-xs font-semibold text-red-600 mb-3">{error}</p>}
        {readings.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-slate-400 py-10">
            <WifiOff size={28} className="mb-2 opacity-50" />
            <p className="text-sm font-medium">No device readings yet</p>
            <p className="text-xs mt-1">Start the Wokwi simulation to see live data.</p>
          </div>
        ) : (
          <div className="space-y-5">
            {readings.map((r) => {
              const age = r.age_seconds + sinceFetch;
              const conn = error ? 'OFFLINE' : connectionOf(age);
              return (
                <div key={r.transformer_id}>
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-bold text-slate-800 text-sm">{r.transformer_code}</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${STATUS_STYLE[r.status]}`}>
                        {r.status}
                      </span>
                      <span className={`text-[10px] font-bold flex items-center gap-1 ${
                        conn === 'ONLINE' ? 'text-emerald-600' : conn === 'STALE' ? 'text-amber-600' : 'text-red-600'
                      }`}>
                        {conn === 'OFFLINE' ? <WifiOff size={12} /> : <Wifi size={12} />}
                        {conn === 'ONLINE' ? 'Device online' : conn === 'STALE' ? 'Delayed' : 'Device offline'}
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <Tile icon={<Zap size={12} />} label="Voltage" value={r.voltage_v} unit="V" />
                    <Tile icon={<Gauge size={12} />} label="Current" value={r.current_a} unit="A" />
                    <Tile icon={<Thermometer size={12} />} label="Temperature" value={r.temperature_c} unit="°C" />
                  </div>
                  <p className="text-[11px] text-slate-400 mt-2">
                    Last update {new Date(r.received_at).toLocaleTimeString('en-IN')} · {Math.round(age)} s ago
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </BentoCard>

      {/* Emergency alerts */}
      <BentoCard
        title="Emergency Alerts"
        className="p-5"
        action={
          <button
            onClick={() => setShowHistory((s) => !s)}
            className="text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded-lg transition-colors"
          >
            {showHistory ? 'Show active' : `History (${alerts.length})`}
          </button>
        }
      >
        {!showHistory ? (
          open.length === 0 ? (
            <div className="flex flex-col items-center justify-center text-slate-400 py-10">
              <CheckCircle2 size={28} className="mb-2 text-emerald-500 opacity-60" />
              <p className="text-sm font-medium">No active emergency alerts</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
              {open.map((a) => (
                <div key={a.id} className="border border-red-100 bg-red-50/50 rounded-xl p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-1.5 text-xs font-extrabold text-red-700">
                        <AlertTriangle size={13} /> {a.transformer_code} · {a.fault_type.replace(/_/g, ' ')}
                      </div>
                      <p className="text-xs text-slate-700 mt-1">{a.message}</p>
                      <p className="text-[11px] text-slate-500 mt-1">
                        Reading <b>{a.actual_value.toFixed(1)} {a.unit}</b> · limit {a.threshold_value} {a.unit} ·{' '}
                        {new Date(a.triggered_at).toLocaleTimeString('en-IN')}
                      </p>
                      <p className="text-[11px] text-slate-500 mt-1"><b>Action:</b> {a.recommended_action}</p>
                    </div>
                    {a.status === 'ACTIVE' ? (
                      <button
                        onClick={() => acknowledge(a.id)}
                        className="shrink-0 text-[10px] font-bold text-red-700 bg-white hover:bg-red-100 border border-red-200 px-2 py-1 rounded transition-colors"
                      >
                        Acknowledge
                      </button>
                    ) : (
                      <span className="shrink-0 text-[10px] font-bold text-slate-500 bg-white border border-slate-200 px-2 py-1 rounded">
                        Acknowledged
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          <div className="max-h-[300px] overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-100">
                  <th className="pb-2">Time</th><th className="pb-2">Transformer</th>
                  <th className="pb-2">Fault</th><th className="pb-2">Reading</th><th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {alerts.map((a) => (
                  <tr key={a.id}>
                    <td className="py-2 text-slate-500">{new Date(a.triggered_at).toLocaleTimeString('en-IN')}</td>
                    <td className="py-2 font-semibold text-slate-800">{a.transformer_code}</td>
                    <td className="py-2 text-slate-600">{a.fault_type.replace(/_/g, ' ')}</td>
                    <td className="py-2 text-slate-600">{a.actual_value.toFixed(1)} {a.unit}</td>
                    <td className="py-2">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        a.status === 'RESOLVED' ? 'bg-emerald-50 text-emerald-700'
                          : a.status === 'ACKNOWLEDGED' ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'
                      }`}>{a.status}</span>
                    </td>
                  </tr>
                ))}
                {alerts.length === 0 && (
                  <tr><td colSpan={5} className="py-6 text-center text-slate-400">No alerts recorded yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </BentoCard>
    </div>
  );
}
