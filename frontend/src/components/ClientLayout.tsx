'use client';

import { useState, useRef, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import { NotificationBell } from '@/components/layout/NotificationBell';
import { supabase } from '@/lib/supabaseClient';
import { UserCircle, LogOut, BookOpen, ChevronDown } from 'lucide-react';

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/map', label: 'Network Map' },
  { href: '/ml-analytics', label: 'AI Analytics' },
  { href: '/dashboard/inspection', label: 'Inspection' },
  { href: '/dashboard/tickets', label: 'Tickets' },
  { href: '/dashboard/settings', label: 'Settings' },
];

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname === '/login';
  
  const [profileOpen, setProfileOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setProfileOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSignOut = async () => {
    localStorage.removeItem("supabase_token");
    await supabase.auth.signOut();
    router.push("/login");
  };

  // Sliding glass indicator: follows the active nav link
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);
  const activeIndex = NAV_ITEMS.reduce((best, item, i) => {
    const matches = pathname === item.href || pathname.startsWith(item.href + '/');
    return matches && (best === -1 || item.href.length > NAV_ITEMS[best].href.length) ? i : best;
  }, -1);

  useEffect(() => {
    const measure = () => {
      const el = linkRefs.current[activeIndex];
      setPill(el ? { left: el.offsetLeft, width: el.offsetWidth } : null);
    };
    measure();
    window.addEventListener('resize', measure);
    document.fonts?.ready.then(measure);
    return () => window.removeEventListener('resize', measure);
  }, [activeIndex]);

  if (isLoginPage || pathname === '/') {
    return <>{children}</>;
  }

  return (
    <AuthGuard>
      {/* Navigation Bar (Floating Style) */}
      <nav className="fixed top-4 left-4 right-4 z-50 flex items-center justify-between rounded-2xl border border-white/70 bg-gradient-to-b from-white/80 to-white/50 px-5 py-2.5 shadow-[0_8px_32px_rgba(15,23,42,0.10),inset_0_1px_0_rgba(255,255,255,0.9)] ring-1 ring-slate-900/5 backdrop-blur-2xl backdrop-saturate-150 transition-all">
        {/* Brand */}
        <Link href="/dashboard" className="flex items-center gap-3 group cursor-pointer">
          <div className="w-10 h-10 flex items-center justify-center group-hover:scale-105 transition-transform">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="Belaku Kannu logo" className="w-full h-full object-contain" />
          </div>
          <div>
            <span className="font-bold text-xl tracking-tight text-slate-900 leading-none block group-hover:text-blue-600 transition-colors">Belaku <span className="text-blue-600">Kannu</span></span>
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest block">Command Center</span>
          </div>
        </Link>

        {/* Links */}
        <div className="relative hidden items-center gap-1 rounded-full border border-slate-200/70 bg-slate-100/60 p-1 shadow-inner backdrop-blur-md md:flex">
          {/* Sliding glass highlight */}
          {pill && (
            <span
              aria-hidden
              className="pointer-events-none absolute bottom-1 top-1 rounded-full border border-white bg-white/90 shadow-[0_2px_10px_rgba(37,99,235,0.18)] ring-1 ring-blue-500/10 transition-all duration-500 ease-[cubic-bezier(0.34,1.3,0.5,1)]"
              style={{ left: pill.left, width: pill.width }}
            />
          )}
          {NAV_ITEMS.map((item, i) => (
            <Link
              key={item.href}
              href={item.href}
              ref={(el) => { linkRefs.current[i] = el; }}
              className={`relative z-10 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-300 ${
                i === activeIndex ? 'text-blue-700' : 'text-slate-500 hover:text-slate-900'
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>

        {/* User / Actions */}
        <div className="flex items-center gap-4">
          <NotificationBell />
          
          <div className="relative" ref={dropdownRef}>
            <div 
              onClick={() => setProfileOpen(!profileOpen)}
              className="flex items-center gap-3 cursor-pointer p-1 pr-2 rounded-full hover:bg-slate-50 transition-colors border border-transparent hover:border-slate-200"
            >
              <div className="hidden sm:block text-right pl-2">
                <p className="text-sm font-bold text-slate-700 leading-tight">Admin User</p>
                <p className="text-[10px] font-semibold text-slate-400 uppercase">System Operator</p>
              </div>
              <div className="w-9 h-9 rounded-full bg-slate-100 border-2 border-white ring-1 ring-slate-200 flex items-center justify-center text-slate-600 shadow-sm">
                <UserCircle size={20} />
              </div>
              <ChevronDown size={14} className={`text-slate-400 transition-transform ${profileOpen ? 'rotate-180' : ''}`} />
            </div>

            {/* Dropdown Menu */}
            {profileOpen && (
              <div className="absolute right-0 mt-2 w-56 bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden py-2 animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="px-4 py-3 border-b border-slate-100 mb-1">
                  <p className="text-sm font-bold text-slate-800">Admin User</p>
                  <p className="text-xs text-slate-500">admin@bescom.in</p>
                </div>
                
                <Link href="/dashboard/settings" onClick={() => setProfileOpen(false)} className="flex items-center gap-3 px-4 py-2 text-sm text-slate-600 hover:text-blue-600 hover:bg-blue-50 transition-colors">
                  <UserCircle size={16} />
                  My Profile
                </Link>
                
                <Link href="#" onClick={() => setProfileOpen(false)} className="flex items-center gap-3 px-4 py-2 text-sm text-slate-600 hover:text-blue-600 hover:bg-blue-50 transition-colors">
                  <BookOpen size={16} />
                  Documentation
                </Link>
                
                <div className="h-px bg-slate-100 my-1"></div>
                
                <button 
                  onClick={handleSignOut}
                  className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                >
                  <LogOut size={16} />
                  Sign Out
                </button>
              </div>
            )}
          </div>
        </div>
      </nav>
      
      {/* Main Content Area */}
      <main className="pt-24 pb-10 px-4 md:px-8 max-w-[1600px] mx-auto">
        {children}
      </main>
    </AuthGuard>
  );
}
