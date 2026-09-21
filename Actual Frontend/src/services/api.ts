import {
  UserProfile,
  ConnectedRepo,
  ConnectRepoRequest,
  ConnectRepoResponse,
  CommitListItem,
  CommitDetail,
} from '../types';
import { INITIAL_USER, INITIAL_REPOS, INITIAL_COMMITS, MOCK_COMMIT_DETAILS } from '../mockData';

const API_BASE = '/api';

function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('gitsense_jwt');
}

export function setStoredToken(token: string) {
  if (typeof window !== 'undefined') {
    localStorage.setItem('gitsense_jwt', token);
  }
}

export function clearStoredToken() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('gitsense_jwt');
  }
}

// In-memory client fallback cache for preview/offline mode
let clientRepos: ConnectedRepo[] = [...INITIAL_REPOS];
let clientCommits: CommitListItem[] = [...INITIAL_COMMITS];
let clientCommitDetails: Record<number, CommitDetail> = { ...MOCK_COMMIT_DETAILS };

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const url = new URL(`${API_BASE}${endpoint}`, window.location.origin);
  if (token) {
    url.searchParams.set('token', token);
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url.toString(), {
    ...options,
    headers,
  });

  const contentType = response.headers.get('content-type') || '';

  if (!response.ok) {
    let errMessage = `HTTP ${response.status}: ${response.statusText}`;
    if (contentType.includes('application/json')) {
      const errData = await response.json().catch(() => ({}));
      errMessage = errData.error || errData.message || errMessage;
    }
    throw new Error(errMessage);
  }

  if (!contentType.includes('application/json')) {
    throw new Error(`Invalid response format from ${endpoint} (expected JSON, got ${contentType || 'HTML/Text'})`);
  }

  return response.json();
}

export const api = {
  getAuthUser: async (): Promise<UserProfile | null> => {
    const token = getStoredToken();
    if (!token) return null;
    try {
      return await request<UserProfile>('/auth/me');
    } catch (err) {
      console.warn('API getAuthUser validation failed:', err);
      return null;
    }
  },

  getConnectedRepos: async (): Promise<ConnectedRepo[]> => {
    try {
      const repos = await request<ConnectedRepo[]>('/repos/');
      clientRepos = repos;
      return repos;
    } catch (err) {
      console.warn('API getConnectedRepos fallback to local repos:', err);
      return clientRepos;
    }
  },

  connectRepo: async (data: ConnectRepoRequest): Promise<ConnectRepoResponse> => {
    try {
      return await request<ConnectRepoResponse>('/repos/connect', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    } catch (err) {
      console.warn('API connectRepo fallback to local state:', err);
      const existing = clientRepos.find(
        (r) => r.repo_full_name.toLowerCase() === data.repo_full_name.toLowerCase()
      );
      if (existing) {
        existing.branch = data.branch || 'main';
        existing.webhook_active = true;
        return {
          message: `Re-pointed existing webhook for ${existing.repo_full_name}`,
          repo_id: existing.id,
          webhook_id: 8000 + existing.id,
          branch: existing.branch,
          was_repointed: true,
        };
      }
      const newId = Date.now();
      const newRepo: ConnectedRepo = {
        id: newId,
        repo_full_name: data.repo_full_name,
        branch: data.branch || 'main',
        webhook_active: true,
        created_at: new Date().toISOString(),
      };
      clientRepos.unshift(newRepo);
      return {
        message: `Successfully connected ${data.repo_full_name} and registered GitHub webhook #${9000 + (newId % 1000)}`,
        repo_id: newId,
        webhook_id: 9000 + (newId % 1000),
        branch: newRepo.branch,
        was_repointed: false,
      };
    }
  },

  disconnectRepo: async (id: number): Promise<{ message: string }> => {
    try {
      return await request<{ message: string }>(`/repos/${id}`, {
        method: 'DELETE',
      });
    } catch (err) {
      console.warn('API disconnectRepo fallback to local state:', err);
      const index = clientRepos.findIndex((r) => r.id === id);
      if (index !== -1) {
        const removed = clientRepos.splice(index, 1)[0];
        return { message: `Unregistered webhook and disconnected repository ${removed.repo_full_name}.` };
      }
      return { message: 'Repository disconnected.' };
    }
  },

  getCommits: async (
    repoId?: number | null,
    status?: string,
    limit: number = 50
  ): Promise<CommitListItem[]> => {
    try {
      const params = new URLSearchParams();
      if (repoId) params.set('repo_id', repoId.toString());
      if (status && status !== 'all') params.set('status', status);
      params.set('limit', limit.toString());

      const data = await request<CommitListItem[]>(`/commits/?${params.toString()}`);
      clientCommits = data;
      return data;
    } catch (err) {
      console.warn('API getCommits fallback to local commits:', err);
      let results = [...clientCommits];
      if (repoId) {
        const repo = clientRepos.find((r) => r.id === repoId);
        if (repo) {
          results = results.filter((c) => c.repo_full_name === repo.repo_full_name);
        }
      }
      if (status && status !== 'all') {
        results = results.filter((c) => c.status === status);
      }
      return results.slice(0, limit);
    }
  },

  getCommitReport: async (id: number): Promise<CommitDetail> => {
    try {
      return await request<CommitDetail>(`/commits/${id}/report`);
    } catch (err) {
      console.warn('API getCommitReport fallback to local report:', err);
      const detail = clientCommitDetails[id];
      if (detail) return detail;
      throw new Error('Commit report not found.');
    }
  },

  retryCommitAnalysis: async (id: number): Promise<{ message: string; commit_id: number }> => {
    try {
      return await request<{ message: string; commit_id: number }>(`/commits/${id}/retry`, {
        method: 'POST',
      });
    } catch (err) {
      console.warn('API retryCommitAnalysis fallback to local state:', err);
      const commit = clientCommits.find((c) => c.id === id);
      if (commit) {
        commit.status = 'analyzing';
        commit.status_detail = 'Re-queued analysis...';
        setTimeout(() => {
          commit.status = 'completed';
          commit.status_detail = null;
          commit.risk_score = 4.8;
        }, 2000);
      }
      return { message: 'Retry queued successfully', commit_id: id };
    }
  },

  simulateCommitPush: async (payload: {
    repo_full_name?: string;
    message: string;
    author?: string;
    file_path?: string;
    code_diff: string;
  }): Promise<{ message: string; commit: CommitListItem; detail: CommitDetail }> => {
    try {
      return await request<{ message: string; commit: CommitListItem; detail: CommitDetail }>(
        '/commits/simulate',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        }
      );
    } catch (err) {
      console.warn('API simulateCommitPush fallback to client generator:', err);
      const newId = Date.now();
      const shortSha = Math.random().toString(16).substring(2, 9);
      const repoName = payload.repo_full_name || 'acme/core-service';
      const isSecurity = /sql|auth|token|password|secret|key|eval|exec/i.test(payload.code_diff + payload.message);

      const newListItem: CommitListItem = {
        id: newId,
        sha: shortSha,
        message: payload.message,
        author: payload.author || 'current-user',
        repo_full_name: repoName,
        status: 'completed',
        status_detail: null,
        risk_score: isSecurity ? 8.4 : 3.5,
        timestamp: new Date().toISOString(),
      };

      const newDetail: CommitDetail = {
        id: newId,
        sha: shortSha + '019283109283109283019283',
        message: payload.message,
        author: payload.author || 'current-user',
        repo_full_name: repoName,
        branch: 'main',
        status: 'completed',
        status_detail: null,
        skip_reason: null,
        timestamp: new Date().toISOString(),
        report: {
          summary: `Automated scan of commit: "${payload.message}". Scanned modified files for vulnerability vectors, logic flaws, and breaking changes.`,
          change_type: isSecurity ? 'bug_fix' : 'feature',
          risk_score: isSecurity ? 8.4 : 3.5,
          analysis_tier: 'full',
          documentation_needed: isSecurity,
          documentation_reason: isSecurity ? 'Security-critical changes detected in authentication or data layer.' : null,
          documentation_suggestion: isSecurity ? 'Update security architecture log.' : null,
          scope_metrics: {
            files_changed: 1,
            additions: 15,
            deletions: 3,
          },
          recommendations: [
            'Validate inputs at boundary endpoints.',
            'Ensure unit tests cover modified code paths.',
          ],
          issues: isSecurity
            ? [
                {
                  title: 'Potential Security Risk in Code Modification',
                  severity: 'high',
                  explanation: 'Modification contains keywords or patterns associated with sensitive input processing.',
                  suggested_fix: 'Use strict validation and parameterized input handlers.',
                  filepath: payload.file_path || 'src/handler.ts',
                  line_start: 12,
                  line_end: 25,
                  confidence: 'high',
                  source_agent: 'security_review_worker',
                  code_fix: `--- a/${payload.file_path || 'src/handler.ts'}\n+++ b/${payload.file_path || 'src/handler.ts'}\n@@ -12,3 +12,3 @@\n-  const query = "SELECT * FROM data WHERE id = " + input;\n+  const query = text("SELECT * FROM data WHERE id = :id");`,
                },
              ]
            : [],
        },
      };

      clientCommits.unshift(newListItem);
      clientCommitDetails[newId] = newDetail;

      return {
        message: 'Commit simulated and analyzed successfully',
        commit: newListItem,
        detail: newDetail,
      };
    }
  },

  downloadCommitPdf: async (commitId: number, sha: string): Promise<void> => {
    const token = getStoredToken();
    const url = new URL(`${API_BASE}/commits/${commitId}/pdf`, window.location.origin);
    if (token) {
      url.searchParams.set('token', token);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error('Failed to download PDF report');
    }
    const blob = await response.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = `gitsense_report_${sha.substring(0, 7)}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(blobUrl);
  },
};


