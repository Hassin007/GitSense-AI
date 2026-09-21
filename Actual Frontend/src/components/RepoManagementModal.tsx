import React, { useState } from 'react';
import { ConnectedRepo, ConnectRepoRequest } from '../types';
import {
  X,
  FolderGit2,
  Key,
  Eye,
  EyeOff,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  RotateCw,
  GitBranch,
} from 'lucide-react';

interface RepoManagementModalProps {
  repos: ConnectedRepo[];
  isOpen: boolean;
  onClose: () => void;
  onConnectRepo: (data: ConnectRepoRequest) => Promise<void>;
  onDisconnectRepo: (id: number) => Promise<void>;
}

export const RepoManagementModal: React.FC<RepoManagementModalProps> = ({
  repos,
  isOpen,
  onClose,
  onConnectRepo,
  onDisconnectRepo,
}) => {
  const [githubPat, setGithubPat] = useState('');
  const [repoFullName, setRepoFullName] = useState('');
  const [branch, setBranch] = useState('main');
  const [showPat, setShowPat] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [disconnectingId, setDisconnectingId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  if (!isOpen) return null;

  const handleSubmitConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!githubPat.trim() || !repoFullName.trim()) {
      setFeedback({ type: 'error', message: 'GitHub PAT and Repository name are required.' });
      return;
    }

    setIsSubmitting(true);
    setFeedback(null);

    try {
      await onConnectRepo({
        github_pat: githubPat.trim(),
        repo_full_name: repoFullName.trim(),
        branch: branch.trim() || 'main',
      });
      setFeedback({
        type: 'success',
        message: `Successfully connected ${repoFullName} and registered GitHub push webhook!`,
      });
      setGithubPat('');
      setRepoFullName('');
      setBranch('main');
    } catch (err: any) {
      setFeedback({
        type: 'error',
        message: err.message || 'Failed to connect repository. Please verify PAT permissions.',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDisconnect = async (id: number, repoName: string) => {
    if (!window.confirm(`Are you sure you want to disconnect ${repoName}? This will unregister the GitHub webhook.`)) {
      return;
    }

    setDisconnectingId(id);
    setFeedback(null);
    try {
      await onDisconnectRepo(id);
      setFeedback({
        type: 'success',
        message: `Disconnected ${repoName} and unregistered webhook.`,
      });
    } catch (err: any) {
      setFeedback({
        type: 'error',
        message: err.message || 'Failed to disconnect repository.',
      });
    } finally {
      setDisconnectingId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-3xl bg-white dark:bg-[#1A1A19] rounded-xl shadow-2xl border border-[#E5E2D9] dark:border-[#3A3A36] overflow-hidden text-[#1A1A1A] dark:text-[#DEDACF] font-sans">
        {/* Modal Header */}
        <div className="px-6 py-4 bg-[#FCFAF7] dark:bg-[#252523] border-b border-[#E5E2D9] dark:border-[#3A3A36] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FolderGit2 className="w-5 h-5 text-[#10B981]" />
            <h3 className="font-semibold text-sm text-[#1A1A1A] dark:text-white">
              Repository Management & Webhooks
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[#F1EFE9] dark:hover:bg-[#3A3A36] text-[#AFA99E] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6 max-h-[80vh] overflow-y-auto">
          {/* Feedback Alert Banner */}
          {feedback && (
            <div
              className={`p-3.5 rounded-lg text-xs font-mono flex items-start gap-2 ${
                feedback.type === 'success'
                  ? 'bg-[#ECFDF5] text-[#10B981] border border-[#10B981]/30'
                  : 'bg-[#FEF2F2] text-[#DC2626] border border-[#DC2626]/30'
              }`}
            >
              {feedback.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 text-[#10B981] shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="w-4 h-4 text-[#DC2626] shrink-0 mt-0.5" />
              )}
              <span>{feedback.message}</span>
            </div>
          )}

          {/* Form: Connect New Repository */}
          <div className="rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] p-5 space-y-4">
            <h4 className="font-bold text-xs uppercase tracking-wider text-[#7A7468] flex items-center gap-2">
              <Plus className="w-4 h-4 text-[#10B981]" />
              Connect New GitHub Repository
            </h4>

            <form onSubmit={handleSubmitConnect} className="space-y-3 font-sans text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {/* Repo Full Name */}
                <div>
                  <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                    Repository Full Name <span className="text-[#DC2626]">*</span>
                  </label>
                  <input
                    type="text"
                    value={repoFullName}
                    onChange={(e) => setRepoFullName(e.target.value)}
                    placeholder="e.g. owner/repository"
                    required
                    className="w-full px-3 py-2 bg-white dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs"
                  />
                </div>

                {/* Branch */}
                <div>
                  <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                    Monitored Branch
                  </label>
                  <div className="relative">
                    <GitBranch className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#AFA99E]" />
                    <input
                      type="text"
                      value={branch}
                      onChange={(e) => setBranch(e.target.value)}
                      placeholder="main"
                      className="w-full pl-9 pr-3 py-2 bg-white dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs"
                    />
                  </div>
                </div>
              </div>

              {/* GitHub PAT */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[10px] font-bold text-[#7A7468] uppercase tracking-widest">
                    GitHub Personal Access Token (PAT) <span className="text-[#DC2626]">*</span>
                  </label>
                  <span className="text-[10px] text-[#AFA99E]">
                    Requires <code className="text-[#2563EB]">repo</code> & <code className="text-[#2563EB]">admin:repo_hook</code>
                  </span>
                </div>
                <div className="relative">
                  <Key className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#AFA99E]" />
                  <input
                    type={showPat ? 'text' : 'password'}
                    value={githubPat}
                    onChange={(e) => setGithubPat(e.target.value)}
                    placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                    required
                    className="w-full pl-9 pr-10 py-2 bg-white dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPat(!showPat)}
                    className="absolute right-3 top-2.5 text-[#AFA99E] hover:text-[#1A1A1A] dark:hover:text-white"
                  >
                    {showPat ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 bg-[#1A1A1A] dark:bg-white text-white dark:text-[#1A1A1A] hover:bg-black dark:hover:bg-[#E5E2D9] font-bold text-xs rounded-md shadow transition-colors flex items-center gap-1.5 disabled:opacity-50"
                >
                  {isSubmitting ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Registering Webhook...</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-3.5 h-3.5" />
                      <span>Connect Repository</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>

          {/* Connected Repositories Table */}
          <div className="space-y-3">
            <h4 className="font-bold text-xs uppercase tracking-widest text-[#7A7468]">
              Connected Repositories ({repos.length})
            </h4>

            {repos.length === 0 ? (
              <p className="text-center py-6 text-xs text-[#AFA99E]">
                No repositories connected yet. Fill out the form above to register your first repository.
              </p>
            ) : (
              <div className="rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] overflow-hidden">
                <table className="w-full text-left text-xs border-collapse font-sans">
                  <thead>
                    <tr className="bg-[#FCFAF7] dark:bg-[#252523] text-[#7A7468] border-b border-[#E5E2D9] dark:border-[#3A3A36] text-[10px] uppercase font-bold tracking-widest">
                      <th className="px-4 py-2.5">Repository</th>
                      <th className="px-4 py-2.5">Branch</th>
                      <th className="px-4 py-2.5">Webhook Status</th>
                      <th className="px-4 py-2.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F1EFE9] dark:divide-[#2A2724]">
                    {repos.map((repo) => (
                      <tr key={repo.id} className="hover:bg-[#FBF9F4] dark:hover:bg-[#252523] transition-colors">
                        <td className="px-4 py-3 font-semibold text-[#1A1A1A] dark:text-white">
                          {repo.repo_full_name}
                        </td>
                        <td className="px-4 py-3 text-[#5C574F] dark:text-[#AFA99E] font-mono text-[11px]">
                          {repo.branch}
                        </td>
                        <td className="px-4 py-3">
                          {repo.webhook_active ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-[#ECFDF5] text-[#10B981] border border-[#10B981]/20 font-bold uppercase tracking-tighter">
                              <span className="w-1.5 h-1.5 rounded-full bg-[#10B981]"></span>
                              Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-[#F3F4F6] text-[#6B7280] font-bold uppercase tracking-tighter">
                              Inactive
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => handleDisconnect(repo.id, repo.repo_full_name)}
                            disabled={disconnectingId === repo.id}
                            className="p-1.5 rounded hover:bg-[#FEF2F2] text-[#DC2626] transition-colors"
                            title="Disconnect repository and unregister webhook"
                          >
                            {disconnectingId === repo.id ? (
                              <RotateCw className="w-4 h-4 animate-spin" />
                            ) : (
                              <Trash2 className="w-4 h-4" />
                            )}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
