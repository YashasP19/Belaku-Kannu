import axios from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';

export const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

import { supabase } from './supabaseClient';

// Interceptor for attaching auth tokens
apiClient.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.set('Authorization', `Bearer ${session.access_token}`);
  }
  return config;
});

// Interceptor for handling 401 Unauthorized responses globally
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      console.warn("Unauthorized request, signing out...");
      await supabase.auth.signOut();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// Transformers API Functions
export const getTransformers = async () => {
  const response = await apiClient.get('/transformers/');
  return response.data;
};

export const getTransformerRiskScore = async (id: string) => {
  const response = await apiClient.get(`/transformers/${id}/risk-score`);
  return response.data;
};

// Summary Stats API
export const getLatestAiRun = async () => {
  const response = await apiClient.get('/ai-runs/latest');
  return response.data;
};

// ─── IoT live monitoring (ESP32 / Wokwi) ──────────────────────────────────────
export interface LiveTelemetry {
  id: number;
  transformer_id: string;
  transformer_code: string;
  voltage_v: number;
  current_a: number;
  temperature_c: number;
  status: 'SAFE' | 'WARNING' | 'CRITICAL';
  received_at: string;
  age_seconds: number;
  connection: 'ONLINE' | 'STALE' | 'OFFLINE';
}

export interface IotAlert {
  id: string;
  transformer_id: string;
  transformer_code: string;
  fault_type: string;
  severity: string;
  actual_value: number;
  threshold_value: number;
  unit: string;
  message: string;
  recommended_action: string;
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED';
  triggered_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export const getLiveTelemetry = async (): Promise<LiveTelemetry[]> =>
  (await apiClient.get('/telemetry/latest')).data;

export const getIotAlerts = async (scope: 'active' | 'resolved' | 'all' = 'all'): Promise<IotAlert[]> =>
  (await apiClient.get('/iot-alerts', { params: { scope, limit: 50 } })).data;

export const acknowledgeIotAlert = async (id: string): Promise<IotAlert> =>
  (await apiClient.post(`/iot-alerts/${id}/acknowledge`)).data;

// ─── IoT inspection: run the existing ML models on live readings ──────────────
export interface InspectionModel {
  key: string; name: string; role: string;
  verdict: 'HEALTHY' | 'WARNING' | 'CRITICAL' | 'UNKNOWN';
  risk_score: number; weight: number; in_blend: boolean;
  expected_lifetime_days?: number | null;
}
export interface InspectionDriver {
  feature: string; label: string; value: number; impact: number; direction: string;
}
export interface InspectionRecommendation {
  priority: 'URGENT' | 'SOON' | 'ROUTINE'; action: string; reason: string;
}
export interface InspectionResult {
  transformer_id: string; transformer_code: string; run_at: string;
  health_score: number; risk_category: 'HEALTHY' | 'WARNING' | 'CRITICAL';
  failure_probability: number | null; expected_lifetime_days: number | null;
  models: InspectionModel[]; drivers: InspectionDriver[];
  protection: { status: string; open_alerts: number; faults: { fault_type: string; severity: string; message: string }[] };
  summary: string; recommendations: InspectionRecommendation[];
  inputs: {
    readings_used: number; window_seconds: number; data_age_seconds: number;
    rated_kva: number; age_years: number;
    avg_voltage_v: number; avg_current_a: number; avg_temperature_c: number;
    avg_voltage_lv_mapped: number; avg_load_pct_mapped: number; notes: string[];
  };
}

export const runIotInspection = async (transformerId: string): Promise<InspectionResult> =>
  (await apiClient.post('/iot-inspection', { transformer_id: transformerId })).data;

export const raiseIotInspectionTicket = async (body: {
  transformer_id: string; priority: 'CRITICAL' | 'HIGH'; summary: string; health_score?: number;
}) => (await apiClient.post('/iot-inspection/ticket', body)).data;
