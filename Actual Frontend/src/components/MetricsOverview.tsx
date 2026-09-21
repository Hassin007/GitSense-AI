import React from 'react';
import { CommitListItem, ConnectedRepo } from '../types';
import { GitCommit, ShieldAlert, FolderGit2, Gauge, TrendingUp, AlertTriangle } from 'lucide-react';

interface MetricsOverviewProps {
  commits: CommitListItem[];
  repos: ConnectedRepo[];
}

export const MetricsOverview: React.FC<MetricsOverviewProps> = ({ commits, repos }) => {
  const totalCommits = commits.length;
  
  const highRiskCommits = commits.filter(
    (c) => c.risk_score !== null && c.risk_score >= 8.0
  );

  const completedCommitsWithScore = commits.filter((c) => c.risk_score !== null);
  
  const avgRiskScore =
    completedCommitsWithScore.length > 0
      ? (
          completedCommitsWithScore.reduce((acc, c) => acc + (c.risk_score || 0), 0) /
          completedCommitsWithScore.length
        ).toFixed(1)
      : '0.0';

  const numAvg = parseFloat(avgRiskScore);

  // Color coding risk level
  const getRiskColor = (score: number) => {
    if (score >= 8.0) return 'text-rose-600 dark:text-rose-400 bg-rose-500/10 border-rose-500/20';
    if (score >= 4.0) return 'text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20';
    return 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {/* Card 1: Total Commits Analyzed */}
      <div className="bg-white dark:bg-[#221F1C] p-5 rounded-xl border border-[#E5E2D9] dark:border-[#38322d] shadow-sm transition-colors">
        <p className="text-xs font-bold text-[#7A7468] dark:text-[#AFA99E] uppercase tracking-widest font-sans">
          Analyzed Commits
        </p>
        <div className="flex items-end justify-between mt-2">
          <h2 className="text-3xl font-light text-[#1A1A1A] dark:text-white font-sans">
            {totalCommits}
          </h2>
          <span className="text-xs text-[#10B981] font-medium font-sans flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5" />
            +12% this week
          </span>
        </div>
      </div>

      {/* Card 2: High-Risk Alerts */}
      <div className={`bg-white dark:bg-[#221F1C] p-5 rounded-xl border border-[#E5E2D9] dark:border-[#38322d] shadow-sm transition-colors ${
        highRiskCommits.length > 0 ? 'ring-2 ring-[#FCA5A5] ring-opacity-30 dark:ring-rose-900/40' : ''
      }`}>
        <p className="text-xs font-bold text-[#7A7468] dark:text-[#AFA99E] uppercase tracking-widest font-sans">
          High-Risk Alerts
        </p>
        <div className="flex items-end justify-between mt-2">
          <h2 className={`text-3xl font-light font-sans ${
            highRiskCommits.length > 0 ? 'text-[#DC2626] font-normal' : 'text-[#1A1A1A] dark:text-white'
          }`}>
            {highRiskCommits.length < 10 && highRiskCommits.length > 0 ? `0${highRiskCommits.length}` : highRiskCommits.length}
          </h2>
          <span className={`text-xs font-medium font-sans ${
            highRiskCommits.length > 0 ? 'text-[#DC2626] animate-pulse' : 'text-[#10B981]'
          }`}>
            {highRiskCommits.length > 0 ? 'Action required' : 'System healthy'}
          </span>
        </div>
      </div>

      {/* Card 3: Active Repositories */}
      <div className="bg-white dark:bg-[#221F1C] p-5 rounded-xl border border-[#E5E2D9] dark:border-[#38322d] shadow-sm transition-colors">
        <p className="text-xs font-bold text-[#7A7468] dark:text-[#AFA99E] uppercase tracking-widest font-sans">
          Active Repos
        </p>
        <div className="flex items-end justify-between mt-2">
          <h2 className="text-3xl font-light text-[#1A1A1A] dark:text-white font-sans">
            {repos.length}
          </h2>
          <span className="text-xs text-[#7A7468] dark:text-[#AFA99E] font-medium font-sans">
            Webhooks active
          </span>
        </div>
      </div>

      {/* Card 4: Average Codebase Risk Score */}
      <div className="bg-white dark:bg-[#221F1C] p-5 rounded-xl border border-[#E5E2D9] dark:border-[#38322d] shadow-sm transition-colors">
        <p className="text-xs font-bold text-[#7A7468] dark:text-[#AFA99E] uppercase tracking-widest font-sans">
          Avg Risk Score
        </p>
        <div className="flex items-end justify-between mt-2">
          <h2 className="text-3xl font-light text-[#1A1A1A] dark:text-white font-sans">
            {avgRiskScore} <span className="text-lg text-[#AFA99E] font-normal">/ 10</span>
          </h2>
          <div className="w-16 h-2 bg-[#F1EFE9] dark:bg-[#38322d] rounded-full overflow-hidden mb-1.5">
            <div
              className={`h-full ${
                numAvg >= 8.0
                  ? 'bg-[#DC2626]'
                  : numAvg >= 4.0
                  ? 'bg-[#F59E0B]'
                  : 'bg-[#10B981]'
              }`}
              style={{ width: `${Math.min(100, (numAvg / 10) * 100)}%` }}
            ></div>
          </div>
        </div>
      </div>
    </div>
  );
};
