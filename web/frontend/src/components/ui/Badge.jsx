import React from 'react';

const variants = {
  success: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  warning: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  danger: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  info: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  neutral: 'bg-slate-800 text-slate-300 border-slate-700',
  purple: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
};

export function Badge({ children, variant = 'neutral', className = '' }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${variants[variant] || variants.neutral} ${className}`}>
      {children}
    </span>
  );
}
