import React from 'react';

export function Card({ children, className = '', title, subtitle, action, ...props }) {
  return (
    <div 
      className={`glass-panel rounded-xl p-5 shadow-xl transition-all duration-200 border border-slate-800/80 hover:border-slate-700/60 ${className}`}
      {...props}
    >
      {(title || action) && (
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800/60">
          <div>
            {title && <h3 className="text-base font-semibold text-slate-100 tracking-tight">{title}</h3>}
            {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
