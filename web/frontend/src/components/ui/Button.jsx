import React from 'react';

const variants = {
  primary: 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/20 border-transparent',
  secondary: 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700',
  danger: 'bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-600/20 border-transparent',
  ghost: 'bg-transparent hover:bg-slate-800/60 text-slate-400 hover:text-slate-200 border-transparent',
};

const sizes = {
  sm: 'px-2.5 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-2.5 text-base',
};

export function Button({ 
  children, 
  variant = 'primary', 
  size = 'md', 
  className = '', 
  disabled = false, 
  icon: Icon,
  ...props 
}) {
  return (
    <button
      disabled={disabled}
      className={`inline-flex items-center justify-center font-medium rounded-lg border transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {Icon && <Icon className={`mr-2 ${size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'}`} />}
      {children}
    </button>
  );
}
