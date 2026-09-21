export interface UserProfile {
  id: number;
  username: string;
  avatar_url: string | null;
  email: string | null;
}

export interface AuthTokenPayload {
  sub: string;
  username: string;
  exp: number;
}

export interface ConnectedRepo {
  id: number;
  repo_full_name: string;
  branch: string;
  webhook_active: boolean;
  created_at: string;
}

export interface ConnectRepoRequest {
  github_pat: string;
  repo_full_name: string;
  branch?: string;
}

export interface ConnectRepoResponse {
  message: string;
  repo_id: number;
  webhook_id: number;
  branch: string;
  was_repointed: boolean;
}

export type CommitStatus =
  | 'pending'
  | 'analyzing'
  | 'retrying'
  | 'completed'
  | 'skipped'
  | 'failed';

export interface CommitListItem {
  id: number;
  sha: string;
  message: string;
  author: string;
  repo_full_name: string;
  status: CommitStatus;
  status_detail: string | null;
  risk_score: number | null;
  timestamp: string;
}

export type IssueSeverity = 'critical' | 'high' | 'medium' | 'low';

export interface AffectedModuleItem {
  module_path?: string;
  is_broken_call_site?: boolean;
  impact_type?: string;
}

export interface AffectedModulesSummary {
  confirmed: AffectedModuleItem[];
  direct: AffectedModuleItem[];
  transitive_count: number;
  truncated: boolean;
}

export interface DetectedIssue {
  title: string;
  severity: IssueSeverity;
  explanation: string;
  suggested_fix: string;
  code_fix?: string | null;
  filepath?: string;
  line_start?: number | null;
  line_end?: number | null;
  evidence?: string | null;
  confidence?: 'high' | 'medium' | 'low';
  signature_diff?: Record<string, any> | null;
  affected_modules?: AffectedModulesSummary | AffectedModuleItem[] | Record<string, any>;
  source_agent?: string;
}

export type ChangeType =
  | 'feature'
  | 'bug_fix'
  | 'refactor'
  | 'docs'
  | 'config'
  | 'dependency_update'
  | 'test';

export interface ReportDetail {
  summary: string;
  change_type: ChangeType;
  risk_score: number;
  issues: DetectedIssue[];
  recommendations: string[];
  documentation_needed: boolean;
  documentation_reason?: string | null;
  documentation_suggestion?: string | null;
  analysis_tier: 'full' | 'lightweight' | 'skipped';
  analysis_gaps?: string[];
  whole_diff_skipped?: boolean;
  scope_metrics?: {
    files_changed?: number;
    additions?: number;
    deletions?: number;
    [key: string]: any;
  };
  blast_radius_mermaid?: string | null;
}

export interface CommitDetail {
  id: number;
  sha: string;
  message: string;
  author: string;
  repo_full_name: string;
  branch: string;
  status: CommitStatus;
  status_detail: string | null;
  skip_reason: string | null;
  timestamp: string;
  report: ReportDetail | null;
}
