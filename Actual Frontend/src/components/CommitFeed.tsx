import React, { useState } from 'react';
import {
  CommitListItem,
  ConnectedRepo,
  CommitStatus,
} from '../types';
import {
  Search,
  Filter,
  CheckCircle2,
  AlertTriangle,
  Clock,
  RotateCw,
  GitCommit,
  Copy,
  Check,
  ChevronRight,
  ExternalLink,
  ShieldAlert,
  ArrowUpDown,
  RefreshCw,
} from 'lucide-react';

interface CommitFeedProps {
  commits: CommitListItem[];
  repos: ConnectedRepo[];
  selectedRepoId: number | null;
  onSelectRepo: (id: number | null) => void;
  selectedStatus: string;
  onSelectStatus: (status: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onSelectCommit: (commitId: number) => void;
  onRetryAnalysis: (commitId: number) => void;
  onRefresh: () => void;
}

export const CommitFeed: React.FC<CommitFeedProps> = ({
  commits,
  repos,
  selectedRepoId,
  onSelectRepo,
  selectedStatus,
  onSelectStatus,
  searchQuery,
  onSearchChange,
  onSelectCommit,
  onRetryAnalysis,
  onRefresh,
}) => {
  const [copiedSha, setCopiedSha] = useState<string | null>(null);

  const handleCopySha = (e: React.MouseEvent, sha: string) => {
    e.stopPropagation();
    navigator.clipboard.writeText(sha);
    setCopiedSha(sha);
    setTimeout(() => setCopiedSha(null), 2000);
  };

  const statusOptions: { id: string; label: string }[] = [
    { id: 'all', label: 'All Commits' },
    { id: 'completed', label: 'Completed' },
    { id: 'analyzing', label: 'Analyzing' },
    { id: 'pending', label: 'Pending' },
    { id: 'retrying', label: 'Retrying' },
    { id: 'skipped', label: 'Skipped' },
    { id: 'failed', label: 'Failed' },
  ];

  // Helper relative time formatter
  const formatTimeAgo = (isoString: string) => {
    try {
      const date = new Date(isoString);
      const now = new Date();
      const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
      if (seconds < 60) return 'Just now';
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      const days = Math.floor(hours / 24);
      return `${days}d ago`;
    } catch {
      return isoString;
    }
  };

  const getStatusBadge = (status: CommitStatus, detail: string | null) => {
    switch (status) {
      case 'completed':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#ECFDF5] text-[#10B981] uppercase tracking-tighter border border-[#10B981] border-opacity-20">
            ✓ Completed
          </span>
        );
      case 'analyzing':
      case 'pending':
      case 'retrying':
        return (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#EFF6FF] text-[#2563EB] uppercase tracking-tighter border border-[#2563EB] border-opacity-20"
            title={detail || 'Orchestrator active'}
          >
            <RotateCw className="w-2.5 h-2.5 mr-1 animate-spin" />
            {status === 'analyzing' ? 'Analyzing' : status === 'retrying' ? 'Retrying' : 'Pending'}
          </span>
        );
      case 'skipped':
        return (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#F3F4F6] text-[#6B7280] dark:bg-[#2a2826] dark:text-[#AFA99E] uppercase tracking-tighter border border-[#E5E7EB] dark:border-[#38322d]"
            title={detail || 'Skipped threshold'}
          >
            ⊘ Skipped
          </span>
        );
      case 'failed':
        return (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#FEE2E2] text-[#DC2626] uppercase tracking-tighter border border-[#DC2626] border-opacity-20"
            title={detail || 'Analysis error'}
          >
            ⚠ Failed
          </span>
        );
      default:
        return null;
    }
  };

  const getRiskScorePill = (score: number | null, status: CommitStatus) => {
    if (score === null || status !== 'completed') {
      return (
        <span className="font-mono text-xs font-bold px-2 py-1 bg-[#F1EFE9] dark:bg-[#2a2826] text-[#AFA99E] rounded">
          --
        </span>
      );
    }

    if (score >= 8.0) {
      return (
        <span className="font-mono text-xs font-bold px-2 py-1 bg-[#DC2626] text-white rounded shadow-sm">
          {score.toFixed(1)}
        </span>
      );
    }

    return (
      <span className="font-mono text-xs font-bold px-2 py-1 bg-[#F1EFE9] dark:bg-[#2a2826] text-[#1A1A1A] dark:text-[#DEDACF] rounded">
        {score.toFixed(1)}
      </span>
    );
  };

  return (
    <div className="bg-white dark:bg-[#221F1C] rounded-xl border border-[#E5E2D9] dark:border-[#38322d] shadow-sm transition-colors overflow-hidden">
      {/* Controls & Filter Bar */}
      <div className="p-4 border-b border-[#E5E2D9] dark:border-[#38322d] bg-[#FCFAF7] dark:bg-[#252320] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {/* Status Filter Chips */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 sm:pb-0">
          {statusOptions.map((opt) => {
            const isActive = selectedStatus === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => onSelectStatus(opt.id)}
                className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors shrink-0 ${
                  isActive
                    ? 'bg-[#1A1A1A] text-white dark:bg-white dark:text-[#1A1A1A]'
                    : 'text-[#5C574F] dark:text-[#AFA99E] hover:bg-[#F1EFE9] dark:hover:bg-[#2E2A26]'
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        {/* Search & Repo Selectors */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1 sm:flex-initial">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search SHA or message..."
              className="pl-8 pr-3 py-1.5 text-xs bg-[#F1EFE9] dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white border-none rounded-md w-full sm:w-56 outline-none font-sans"
            />
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2 text-[#AFA99E]" />
          </div>

          <button
            onClick={onRefresh}
            className="p-1.5 rounded-md text-[#5C574F] dark:text-[#AFA99E] hover:bg-[#F1EFE9] dark:hover:bg-[#2E2A26] transition-colors"
            title="Refresh feed"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Table Feed View */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-[#FCFAF7] dark:bg-[#252320] border-b border-[#E5E2D9] dark:border-[#38322d] text-[10px] uppercase font-bold text-[#AFA99E] tracking-widest">
              <th className="py-3 px-4">Commit</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4">Risk</th>
              <th className="py-3 px-4 text-right">Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1EFE9] dark:divide-[#2E2A26]">
            {commits.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-12 text-center text-[#AFA99E] font-sans text-xs">
                  <GitCommit className="w-8 h-8 mx-auto mb-2 text-[#AFA99E] opacity-60" />
                  <p className="font-semibold text-[#1A1A1A] dark:text-[#DEDACF] mb-1">
                    No commits found matching filters
                  </p>
                  <p className="text-[11px]">
                    Try adjusting search query or trigger a simulated commit push.
                  </p>
                </td>
              </tr>
            ) : (
              commits.map((commit) => {
                const isHighRisk = commit.risk_score !== null && commit.risk_score >= 8.0;

                return (
                  <tr
                    key={commit.id}
                    onClick={() => onSelectCommit(commit.id)}
                    className={`cursor-pointer transition-colors group ${
                      isHighRisk
                        ? 'bg-[#FEF2F2] hover:bg-[#FEE2E2] dark:bg-[#2c1717] dark:hover:bg-[#381c1c] border-l-4 border-[#DC2626]'
                        : 'hover:bg-[#FBF9F4] dark:hover:bg-[#282522]'
                    }`}
                  >
                    {/* Commit Message & Metadata */}
                    <td className="py-3.5 px-4">
                      <div className="flex flex-col">
                        <span className={`text-sm font-semibold transition-colors line-clamp-1 ${
                          isHighRisk
                            ? 'text-[#1A1A1A] dark:text-white font-bold'
                            : 'text-[#1A1A1A] dark:text-[#FBF9F4] group-hover:text-[#2563EB]'
                        }`}>
                          {commit.message}
                        </span>
                        <div className="flex items-center gap-2 font-mono text-[11px] text-[#AFA99E] mt-1 flex-wrap">
                          <button
                            onClick={(e) => handleCopySha(e, commit.sha)}
                            className="hover:underline flex items-center gap-1 font-bold text-[#5C574F] dark:text-[#DEDACF]"
                            title="Copy SHA"
                          >
                            <span>{commit.sha.substring(0, 7)}</span>
                            {copiedSha === commit.sha ? (
                              <Check className="w-3 h-3 text-[#10B981]" />
                            ) : (
                              <Copy className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100" />
                            )}
                          </button>
                          <span>·</span>
                          <span className="truncate max-w-[150px]">{commit.repo_full_name}</span>
                          <span>·</span>
                          <span>{commit.author}</span>
                        </div>
                      </div>
                    </td>

                    {/* Status Badge */}
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      {getStatusBadge(commit.status, commit.status_detail)}
                    </td>

                    {/* Risk Score */}
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      {getRiskScorePill(commit.risk_score, commit.status)}
                    </td>

                    {/* Time */}
                    <td className="py-3.5 px-4 text-right whitespace-nowrap text-xs font-medium text-[#AFA99E]">
                      {commit.status === 'failed' ? (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onRetryAnalysis(commit.id);
                          }}
                          className="px-2 py-0.5 rounded bg-[#DC2626] text-white text-[10px] font-bold uppercase tracking-wider hover:bg-rose-700 transition-colors"
                        >
                          Retry
                        </button>
                      ) : (
                        formatTimeAgo(commit.timestamp)
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
