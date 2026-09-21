import React from 'react';

interface GitSenseLogoProps {
  className?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showText?: boolean;
}

export const GitSenseLogo: React.FC<GitSenseLogoProps> = ({
  className = '',
  size = 'md',
  showText = false,
}) => {
  const dimensions = {
    sm: { box: 'w-7 h-7', icon: 28, text: 'text-base' },
    md: { box: 'w-8 h-8', icon: 32, text: 'text-lg' },
    lg: { box: 'w-12 h-12', icon: 48, text: 'text-2xl' },
    xl: { box: 'w-16 h-16', icon: 64, text: 'text-3xl' },
  }[size];

  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`}>
      {/* Custom Vector Mark */}
      <div
        className={`${dimensions.box} rounded-xl bg-[#1A1A1A] border border-[#3A3832] dark:border-[#4A4742] shadow-sm flex items-center justify-center shrink-0 relative overflow-hidden group`}
      >
        {/* Subtle background glow grid */}
        <div className="absolute inset-0 bg-gradient-to-br from-[#10B981]/20 via-transparent to-[#2563EB]/10 opacity-70 group-hover:opacity-100 transition-opacity" />

        <svg
          width={dimensions.icon * 0.7}
          height={dimensions.icon * 0.7}
          viewBox="0 0 32 32"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="relative z-10 text-white"
        >
          {/* Main Git Branch Line */}
          <path
            d="M9 6V26"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
          />

          {/* Curved Branching Path to AI Node */}
          <path
            d="M9 16C12 16 15 13 18 12M18 12C20 11.3 22 10.5 23 9"
            stroke="#10B981"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeDasharray="28"
            className="animate-[dash_3s_linear_infinite]"
          />

          {/* Lower Branching Patch Path */}
          <path
            d="M9 20C13 20 17 22 21 23"
            stroke="#10B981"
            strokeWidth="2"
            strokeLinecap="round"
            strokeOpacity="0.8"
          />

          {/* Git Source Commit Node */}
          <circle cx="9" cy="8" r="2.8" fill="#1A1A1A" stroke="currentColor" strokeWidth="2" />
          <circle cx="9" cy="8" r="1.2" fill="#10B981" />

          {/* Git Target Commit Node */}
          <circle cx="9" cy="24" r="2.8" fill="#1A1A1A" stroke="currentColor" strokeWidth="2" />

          {/* AI Intelligence Spark Diamond Node */}
          <g transform="translate(20, 10)">
            <path
              d="M0 -4.5L3.5 0L0 4.5L-3.5 0Z"
              fill="#10B981"
            />
            <circle cx="0" cy="0" r="1.2" fill="#FFFFFF" />
          </g>

          {/* Secondary Code Scan Node */}
          <circle cx="21" cy="23" r="2" fill="#1A1A1A" stroke="#10B981" strokeWidth="1.8" />
        </svg>
      </div>

      {/* Brand Text Header */}
      {showText && (
        <span className={`font-sans font-bold tracking-tight text-[#1A1A1A] dark:text-white ${dimensions.text}`}>
          GitSense<span className="text-[#10B981]">.AI</span>
        </span>
      )}
    </div>
  );
};
