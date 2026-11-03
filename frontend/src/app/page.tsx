"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, LogIn, LogOut, Camera, Eye, ClipboardList } from "lucide-react";

const FEATURES = [
  { icon: Camera, title: "Photo Inspection", text: "Upload a transformer photo. Get an AI condition report." },
  { icon: Eye, title: "Explainable Risk", text: "See which readings drive each health score." },
  { icon: ClipboardList, title: "Auto Tickets", text: "Risky transformers raise maintenance tickets." },
];
import { supabase } from "@/lib/supabaseClient";

type AuthState = { status: "loading" } | { status: "out" } | { status: "in"; email: string };

export default function Home() {
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    const apply = (email?: string | null) => {
      if (active) setAuth(email ? { status: "in", email } : { status: "out" });
    };
    supabase.auth
      .getSession()
      .then(({ data }) => apply(data.session?.user?.email ?? (data.session ? "User" : null)))
      .catch(() => apply(null));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) =>
      apply(session?.user?.email ?? (session ? "User" : null))
    );
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const signOut = async () => {
    try {
      await supabase.auth.signOut();
    } catch {
      /* ignore */
    }
    setAuth({ status: "out" });
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-gradient-to-b from-white via-slate-50 to-blue-50/60 selection:bg-blue-200">
      <style>{`
        @keyframes bk-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
        @keyframes bk-fade-up { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes bk-orb { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(24px,-18px) scale(1.06); } }
        .bk-float { animation: bk-float 6s ease-in-out infinite; }
        .bk-orb { animation: bk-orb 14s ease-in-out infinite; }
        .bk-fade { opacity: 0; animation: bk-fade-up .8s cubic-bezier(.2,.7,.2,1) forwards; }
        .bk-d1 { animation-delay: .08s; } .bk-d2 { animation-delay: .18s; } .bk-d3 { animation-delay: .3s; } .bk-d4 { animation-delay: .42s; }
        @media (prefers-reduced-motion: reduce) { .bk-float,.bk-orb,.bk-fade { animation: none; opacity: 1; } }
      `}</style>

      {/* Background */}
      <div className="pointer-events-none absolute inset-0">
        <div className="bk-orb absolute -top-40 -left-32 h-[520px] w-[520px] rounded-full bg-blue-300/30 blur-[110px]" />
        <div className="bk-orb absolute -bottom-48 -right-32 h-[560px] w-[560px] rounded-full bg-indigo-300/25 blur-[120px]" style={{ animationDelay: "-6s" }} />
        <div className="absolute inset-0 opacity-60 [background-image:linear-gradient(to_right,#e2e8f0_1px,transparent_1px),linear-gradient(to_bottom,#e2e8f0_1px,transparent_1px)] [background-size:56px_56px] [mask-image:radial-gradient(ellipse_70%_55%_at_50%_40%,#000_55%,transparent_100%)]" />
      </div>

      {/* Slim glass status bar: signed in / signed out */}
      <div className="fixed left-1/2 top-4 z-50 -translate-x-1/2">
        <div className="flex items-center gap-3 rounded-full border border-white/70 bg-gradient-to-b from-white/80 to-white/50 py-1.5 pl-4 pr-1.5 text-xs shadow-[0_8px_32px_rgba(15,23,42,0.10),inset_0_1px_0_rgba(255,255,255,0.9)] ring-1 ring-slate-900/5 backdrop-blur-2xl backdrop-saturate-150">
          {auth.status === "loading" && <span className="py-1 pr-3 text-slate-400">Checking session…</span>}

          {auth.status === "in" && (
            <>
              <span className="flex items-center gap-2 font-medium text-slate-600">
                <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
                Signed in as <span className="max-w-[180px] truncate font-semibold text-slate-900">{auth.email}</span>
              </span>
              <button
                onClick={signOut}
                className="inline-flex items-center gap-1.5 rounded-full bg-slate-900/5 px-3 py-1.5 font-semibold text-slate-600 transition-colors hover:bg-red-50 hover:text-red-600"
              >
                <LogOut size={12} /> Sign out
              </button>
            </>
          )}

          {auth.status === "out" && (
            <>
              <span className="flex items-center gap-2 font-medium text-slate-500">
                <span className="h-2 w-2 rounded-full bg-slate-300" />
                Signed out
              </span>
              <Link
                href="/login"
                className="inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-blue-800 to-blue-600 px-3.5 py-1.5 font-semibold text-white shadow-md shadow-blue-600/25 transition-all hover:shadow-lg"
              >
                <LogIn size={12} /> Sign in
              </Link>
            </>
          )}
        </div>
      </div>

      {/* Hero: logo + title + one action */}
      <div className="relative z-10 mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 pb-16 pt-20 text-center">
        <div className="bk-fade bk-d1 relative">
          <div className="absolute inset-0 -z-10 scale-110 rounded-full bg-blue-400/20 blur-3xl" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="Belaku Kannu logo" className="bk-float h-36 w-auto drop-shadow-[0_12px_30px_rgba(30,64,175,0.25)] sm:h-44" />
        </div>

        <h1 className="bk-fade bk-d2 mt-8 font-heading text-5xl font-bold tracking-tight text-slate-900 sm:text-7xl">
          Belaku{" "}
          <span className="bg-gradient-to-r from-blue-700 via-blue-500 to-indigo-600 bg-clip-text text-transparent">Kannu</span>
        </h1>
        <p className="bk-fade bk-d2 mt-2 text-lg font-medium tracking-wide text-slate-400 sm:text-xl">ಬೆಳಕು ಕಣ್ಣು</p>

        <p className="bk-fade bk-d3 mt-6 max-w-xl text-balance text-base leading-relaxed text-slate-600 sm:text-lg">
          An AI eye on every distribution transformer.
        </p>

        <div className="bk-fade bk-d4 mt-9 flex flex-col items-center gap-3">
          <Link
            href={auth.status === "out" ? "/login" : "/dashboard"}
            className="group inline-flex items-center gap-3 rounded-full bg-gradient-to-r from-blue-800 to-blue-600 px-9 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/30 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-600/40 active:scale-[0.98]"
          >
            {auth.status === "out" ? "Sign in to continue" : "Enter Dashboard"}
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
          </Link>
          {auth.status === "out" && (
            <Link href="/dashboard" className="text-xs font-medium text-slate-400 transition-colors hover:text-blue-600">
              Continue as guest
            </Link>
          )}
        </div>

        {/* Slim feature row */}
        <div className="bk-fade bk-d4 mt-14 grid w-full max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div
              key={title}
              className="group flex flex-col items-center rounded-2xl border border-white/70 bg-white/60 p-4 text-center shadow-[0_6px_24px_rgba(15,23,42,0.05)] backdrop-blur-xl transition-all hover:-translate-y-1 hover:border-blue-100 hover:shadow-[0_12px_32px_rgba(37,99,235,0.12)]"
            >
              <div className="mb-2.5 flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-md shadow-blue-500/25">
                <Icon size={15} />
              </div>
              <h3 className="text-[13px] font-semibold text-slate-900">{title}</h3>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{text}</p>
            </div>
          ))}
        </div>
      </div>

      <p className="absolute bottom-5 left-0 right-0 text-center text-[11px] text-slate-400">
        BESCOM Power Hack 2026 &nbsp;·&nbsp; Presidency University
      </p>
    </main>
  );
}
