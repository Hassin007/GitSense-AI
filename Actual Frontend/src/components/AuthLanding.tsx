import React from 'react';
import { ShieldCheck, Zap, Code2, ArrowRight, Github } from 'lucide-react';
import { GitSenseLogo } from './GitSenseLogo';

interface AuthLandingProps {
  onSignIn: () => void;
}

export const AuthLanding: React.FC<AuthLandingProps> = ({ onSignIn }) => {
  return (
    <div className="min-h-screen bg-[#FBF9F4] dark:bg-[#1A1A19] text-[#1A1A1A] dark:text-[#DEDACF] flex flex-col justify-between p-6 transition-colors font-sans">
      <div className="max-w-4xl mx-auto w-full my-auto space-y-10 py-12">
        {/* Header Hero */}
        <div className="text-center space-y-4">
          <div className="flex items-center justify-center">
            <GitSenseLogo size="xl" showText={true} />
          </div>

          <p className="text-[#5C574F] dark:text-[#AFA99E] text-sm sm:text-base max-w-xl mx-auto font-sans leading-relaxed">
            Automated commit diff risk analysis, multi-agent security scans, and copy-pasteable code patches delivered on every GitHub push.
          </p>
        </div>

        {/* Value Proposition Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="p-5 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-white dark:bg-[#252523] space-y-2 shadow-sm">
            <div className="w-8 h-8 rounded-lg bg-[#EFF6FF] text-[#2563EB] flex items-center justify-center font-bold">
              <Zap className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-sm text-[#1A1A1A] dark:text-white">
              Instant LLM Diff Ingestion
            </h3>
            <p className="text-xs text-[#5C574F] dark:text-[#AFA99E] leading-relaxed">
              Webhook-driven processing evaluates code pushes in seconds using multi-agent LLM orchestrators.
            </p>
          </div>

          <div className="p-5 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-white dark:bg-[#252523] space-y-2 shadow-sm">
            <div className="w-8 h-8 rounded-lg bg-[#FEF2F2] text-[#DC2626] flex items-center justify-center font-bold">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-sm text-[#1A1A1A] dark:text-white">
              Automated Risk Scoring
            </h3>
            <p className="text-xs text-[#5C574F] dark:text-[#AFA99E] leading-relaxed">
              Calculates architectural risk scores (0.0 - 10.0) and flags critical security vulnerabilities.
            </p>
          </div>

          <div className="p-5 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-white dark:bg-[#252523] space-y-2 shadow-sm">
            <div className="w-8 h-8 rounded-lg bg-[#ECFDF5] text-[#10B981] flex items-center justify-center font-bold">
              <Code2 className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-sm text-[#1A1A1A] dark:text-white">
              Copy-Paste Code Fixes
            </h3>
            <p className="text-xs text-[#5C574F] dark:text-[#AFA99E] leading-relaxed">
              Generates syntax-highlighted unified patch diffs ready to apply directly to your codebase.
            </p>
          </div>
        </div>

        {/* Primary CTA */}
        <div className="text-center space-y-3 pt-4">
          <button
            onClick={onSignIn}
            className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-[#1A1A1A] hover:bg-black dark:bg-white dark:hover:bg-[#E5E2D9] text-white dark:text-[#1A1A1A] font-bold text-sm shadow-md transition-all"
          >
            <Github className="w-4 h-4" />
            <span>Sign in with GitHub</span>
            <ArrowRight className="w-4 h-4 ml-1" />
          </button>
          <p className="text-xs text-[#AFA99E]">
            Click to sign in and launch the GitSense engineering intelligence workspace.
          </p>
        </div>
      </div>

      {/* Footer */}
      <div className="text-center text-xs text-[#AFA99E] py-4 border-t border-[#E5E2D9] dark:border-[#3A3A36]">
        GitSense AI • Engineering Intelligence Platform
      </div>
    </div>
  );
};
