import React, { useState } from 'react';
import { CommitDetail, IssueSeverity } from '../types';
import { api } from '../services/api';
import { CodeDiffViewer } from './CodeDiffViewer';
import { BlastRadiusViewer } from './BlastRadiusViewer';
import {
  X,
  ExternalLink,
  ShieldAlert,
  GitCommit,
  CheckCircle2,
  AlertTriangle,
  RotateCw,
  FileText,
  Layers,
  BookOpen,
  ArrowRight,
  Info,
  Check,
  Code2,
  Sparkles,
  Download,
  Loader2,
} from 'lucide-react';

interface CommitReportDrawerProps {
  commitDetail: CommitDetail | null;
  isLoading: boolean;
  onClose: () => void;
  onRetry: (commitId: number) => void;
}

export const CommitReportDrawer: React.FC<CommitReportDrawerProps> = ({
  commitDetail,
  isLoading,
  onClose,
  onRetry,
}) => {
  const [selectedSeverityFilter, setSelectedSeverityFilter] = useState<string>('all');
  const [isDownloadingPdf, setIsDownloadingPdf] = useState<boolean>(false);

  const handleDownloadPdf = async () => {
    if (!commitDetail) return;
    setIsDownloadingPdf(true);
    try {
      await api.downloadCommitPdf(commitDetail.id, commitDetail.sha);
    } catch (err) {
      console.error('Failed to download PDF report:', err);
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  if (!commitDetail && !isLoading) return null;

  const report = commitDetail?.report;

  // Filter issues by severity tab
  const filteredIssues =
    report?.issues.filter((issue) => {
      if (selectedSeverityFilter === 'all') return true;
      return issue.severity === selectedSeverityFilter;
    }) || [];

  const severityCounts = {
    critical: report?.issues.filter((i) => i.severity === 'critical').length || 0,
    high: report?.issues.filter((i) => i.severity === 'high').length || 0,
    medium: report?.issues.filter((i) => i.severity === 'medium').length || 0,
    low: report?.issues.filter((i) => i.severity === 'low').length || 0,
  };

  const getSeverityIcon = (severity: IssueSeverity) => {
    switch (severity) {
      case 'critical':
        return <ShieldAlert className="w-4 h-4 text-rose-600 dark:text-rose-400" />;
      case 'high':
        return <AlertTriangle className="w-4 h-4 text-rose-500" />;
      case 'medium':
        return <AlertTriangle className="w-4 h-4 text-amber-500" />;
      case 'low':
        return <Info className="w-4 h-4 text-stone-400" />;
    }
  };

  const getSeverityBadge = (severity: IssueSeverity) => {
    switch (severity) {
      case 'critical':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-500/30 uppercase">
            Critical
          </span>
        );
      case 'high':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/25 uppercase">
            High
          </span>
        );
      case 'medium':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/15 text-amber-800 dark:text-amber-300 border border-amber-500/25 uppercase">
            Medium
          </span>
        );
      case 'low':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-stone-200 dark:bg-[#28231f] text-stone-700 dark:text-stone-300 border border-stone-300 dark:border-[#3a332e] uppercase">
            Low
          </span>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/50 dark:bg-black/70 backdrop-blur-sm flex justify-end">
      <div className="w-full max-w-4xl bg-white dark:bg-[#1A1A19] text-[#1A1A1A] dark:text-[#DEDACF] h-full shadow-2xl flex flex-col border-l border-[#E5E2D9] dark:border-[#3A3A36] overflow-y-auto font-sans">
        {/* Drawer Header Bar */}
        <div className="sticky top-0 z-20 px-6 py-4 bg-[#FCFAF7] dark:bg-[#252523] border-b border-[#E5E2D9] dark:border-[#3A3A36] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
              Intelligence Report
            </span>
            {commitDetail && (
              <span className="font-mono text-xs text-[#5C574F] dark:text-[#AFA99E]">
                {commitDetail.sha.substring(0, 7)}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            {commitDetail && (
              <button
                onClick={handleDownloadPdf}
                disabled={isDownloadingPdf}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#10B981] hover:bg-[#059669] text-white text-xs font-semibold shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                title="Download PDF Report"
              >
                {isDownloadingPdf ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Download className="w-3.5 h-3.5" />
                )}
                <span>{isDownloadingPdf ? 'Generating PDF...' : 'Download PDF Report'}</span>
              </button>
            )}

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[#F1EFE9] dark:hover:bg-[#3A3A36] text-[#5C574F] dark:text-[#AFA99E] hover:text-[#1A1A1A] dark:hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {isLoading ? (
          <div className="p-12 text-center text-[#7A7468] dark:text-[#AFA99E] font-mono text-sm space-y-3">
            <RotateCw className="w-8 h-8 mx-auto text-[#10B981] animate-spin" />
            <p>Running multi-agent analysis engine...</p>
          </div>
        ) : !commitDetail ? (
          <div className="p-12 text-center text-[#7A7468] dark:text-[#AFA99E] font-mono text-sm">
            <p>Commit report unavailable.</p>
          </div>
        ) : (
          <div className="p-6 space-y-6">
            {/* 1. Commit Header & Overview */}
            <div className="p-5 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {report && (
                      <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                        report.risk_score >= 8.0
                          ? 'bg-[#DC2626] text-white'
                          : report.risk_score >= 4.0
                          ? 'bg-[#F59E0B] text-black'
                          : 'bg-[#10B981] text-white'
                      }`}>
                        {report.risk_score >= 8.0 ? 'CRITICAL RISK' : report.risk_score >= 4.0 ? 'MODERATE RISK' : 'LOW RISK'}
                      </span>
                    )}
                    <span className="text-[10px] font-mono bg-[#F1EFE9] dark:bg-[#1A1A19] text-[#5C574F] dark:text-[#AFA99E] px-2 py-0.5 rounded border border-[#E5E2D9] dark:border-[#3A3A36]">
                      {commitDetail.repo_full_name}
                    </span>
                  </div>
                  <h2 className="text-base sm:text-lg font-semibold text-[#1A1A1A] dark:text-white leading-snug pt-1">
                    {commitDetail.message}
                  </h2>
                  <div className="flex items-center gap-3 text-xs font-mono text-[#5C574F] dark:text-[#AFA99E] flex-wrap pt-1">
                    <span>Author: <strong className="text-[#1A1A1A] dark:text-white">{commitDetail.author}</strong></span>
                    <span>•</span>
                    <span>Branch: <strong className="text-[#10B981]">{commitDetail.branch}</strong></span>
                  </div>
                </div>

                <a
                  href={`https://github.com/${commitDetail.repo_full_name}/commit/${commitDetail.sha}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1A1A1A] hover:bg-black dark:bg-[#3A3A36] dark:hover:bg-[#4A4A45] text-white font-mono text-xs font-bold transition-colors shrink-0"
                >
                  <span>GitHub Commit</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>

              {/* Status Alert Banner */}
              {(commitDetail.status === 'failed' || commitDetail.status === 'skipped') && (
                <div className="p-3 rounded-lg bg-[#DC2626]/10 border border-[#DC2626]/30 text-[#DC2626] dark:text-[#FEE2E2] flex items-center justify-between gap-3 text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-[#DC2626] shrink-0" />
                    <span>{commitDetail.status_detail || commitDetail.skip_reason}</span>
                  </div>
                  <button
                    onClick={() => onRetry(commitDetail.id)}
                    className="px-3 py-1 rounded bg-[#DC2626] hover:bg-rose-700 text-white font-bold text-xs shrink-0 flex items-center gap-1 transition-colors"
                  >
                    <RotateCw className="w-3 h-3" />
                    Retry
                  </button>
                </div>
              )}
            </div>

            {/* 2. Executive Summary */}
            {report && (
              <section className="space-y-2">
                <h4 className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
                  Executive Summary
                </h4>
                <p className="text-xs sm:text-sm leading-relaxed text-[#5C574F] dark:text-[#AFA99E] bg-[#FCFAF7] dark:bg-[#252523] p-4 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36]">
                  {report.summary}
                </p>
              </section>
            )}

            {/* 3. Key Risk Score Gauge Cards */}
            {report && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="p-4 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] flex flex-col justify-between">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
                    Risk Score
                  </span>
                  <div className="flex items-baseline justify-between mt-2">
                    <h3 className="text-2xl font-light text-[#1A1A1A] dark:text-white font-mono">
                      {report.risk_score.toFixed(1)} <span className="text-xs text-[#AFA99E]">/ 10</span>
                    </h3>
                  </div>
                </div>

                <div className="p-4 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] flex flex-col justify-between">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
                    Change Type
                  </span>
                  <div className="mt-2 text-sm font-bold font-mono text-[#1A1A1A] dark:text-white uppercase">
                    {report.change_type.replace('_', ' ')}
                  </div>
                </div>

                <div className="p-4 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] flex flex-col justify-between">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
                    Diff Metrics
                  </span>
                  <div className="mt-2 flex items-center gap-2 text-xs font-mono">
                    <span className="text-[#10B981] font-bold">+{report.scope_metrics?.additions || 0}</span>
                    <span className="text-[#DC2626] font-bold">-{report.scope_metrics?.deletions || 0}</span>
                  </div>
                </div>
              </div>
            )}

            {/* 3.5 Visual Blast Radius & Transitive Impact Diagram */}
            {report?.blast_radius_mermaid && (
              <BlastRadiusViewer mermaidDefinition={report.blast_radius_mermaid} />
            )}

            {/* 4. Detected Vulnerabilities & Code Fixes */}
            {report && report.issues.length > 0 && (
              <section className="space-y-4 pt-2">
                <div className="flex items-center justify-between border-b border-[#E5E2D9] dark:border-[#3A3A36] pb-2">
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
                    Detected Security & Code Vulnerabilities ({report.issues.length})
                  </h4>
                </div>

                <div className="space-y-4">
                  {report.issues.map((issue, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] p-5 space-y-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          {getSeverityBadge(issue.severity)}
                          <h5 className="font-bold text-[#1A1A1A] dark:text-white text-sm">{issue.title}</h5>
                        </div>
                        <span className="text-[10px] font-mono text-[#7A7468] dark:text-[#AFA99E]">
                          {issue.filepath}:{issue.line_start ? `L${issue.line_start}` : ''}
                        </span>
                      </div>

                      <p className="text-xs text-[#5C574F] dark:text-[#AFA99E] leading-relaxed">
                        {issue.explanation}
                      </p>

                      {/* Code Fix Box */}
                      {issue.code_fix && (
                        <div className="p-3 bg-[#DC2626]/5 dark:bg-[#DC2626]/10 border border-[#DC2626]/20 dark:border-[#DC2626]/30 rounded-lg space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-[#DC2626]">Suggested Patch Fix</span>
                          </div>
                          <div className="bg-[#1A1A19] dark:bg-[#0A0A09] rounded p-3 font-mono text-[11px] leading-relaxed overflow-x-auto whitespace-pre text-white border border-[#3A3A36] dark:border-[#2E2A26]">
                            <CodeDiffViewer diffText={issue.code_fix} filepath={issue.filepath} />
                          </div>
                        </div>
                      )}

                      {/* Resolution Guidance */}
                      <div className="p-3 bg-[#F1EFE9] dark:bg-[#1A1A19] rounded-lg text-xs font-mono text-[#1A1A1A] dark:text-[#DEDACF] border border-[#E5E2D9] dark:border-[#3A3A36]">
                        <strong className="text-amber-600 dark:text-amber-500">Fix Guidance: </strong>
                        {issue.suggested_fix}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* 5. Recommendations */}
            {report?.recommendations && report.recommendations.length > 0 && (
              <section className="p-5 rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] space-y-3">
                <h4 className="text-[10px] font-bold uppercase tracking-widest text-[#7A7468] dark:text-[#AFA99E]">
                  Actionable Next Steps
                </h4>
                <ul className="space-y-2 text-xs font-mono text-[#1A1A1A] dark:text-[#DEDACF]">
                  {report.recommendations.map((rec, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-[#10B981] font-bold">✓</span>
                      <span>{rec}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
