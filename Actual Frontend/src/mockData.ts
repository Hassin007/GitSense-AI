import { ConnectedRepo, CommitListItem, CommitDetail, UserProfile } from './types';

export const INITIAL_USER: UserProfile = {
  id: 101,
  username: 'engineering-lead',
  avatar_url: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
  email: 'lead@acme-corp.dev',
};

export const INITIAL_REPOS: ConnectedRepo[] = [
  {
    id: 1,
    repo_full_name: 'acme/core-service',
    branch: 'main',
    webhook_active: true,
    created_at: '2026-07-15T09:30:00Z',
  },
  {
    id: 2,
    repo_full_name: 'acme/billing-gateway',
    branch: 'main',
    webhook_active: true,
    created_at: '2026-07-20T14:15:00Z',
  },
  {
    id: 3,
    repo_full_name: 'acme/infra-terraform',
    branch: 'production',
    webhook_active: true,
    created_at: '2026-08-01T11:00:00Z',
  },
];

export const INITIAL_COMMITS: CommitListItem[] = [
  {
    id: 1001,
    sha: 'a7d9f2e',
    message: 'fix(auth): update user permission check in API route',
    author: 'dev-alex',
    repo_full_name: 'acme/core-service',
    status: 'completed',
    status_detail: null,
    risk_score: 9.2,
    timestamp: '2026-08-10T00:48:12Z',
  },
  {
    id: 1002,
    sha: 'c3b1a8f',
    message: 'refactor(billing): rename Stripe Customer ID field to account_id',
    author: 'sarah-eng',
    repo_full_name: 'acme/billing-gateway',
    status: 'completed',
    status_detail: null,
    risk_score: 6.8,
    timestamp: '2026-08-09T22:15:00Z',
  },
  {
    id: 1003,
    sha: 'f901c3d',
    message: 'feat(payment): integrate multi-currency checkout pipeline',
    author: 'dev-alex',
    repo_full_name: 'acme/billing-gateway',
    status: 'analyzing',
    status_detail: 'LangGraph orchestrator processing 4 modified files (2 worker agents active)',
    risk_score: null,
    timestamp: '2026-08-10T01:05:00Z',
  },
  {
    id: 1004,
    sha: 'e4f8d21',
    message: 'test(e2e): add regression tests for user profile update flow',
    author: 'michael-q',
    repo_full_name: 'acme/core-service',
    status: 'completed',
    status_detail: null,
    risk_score: 1.4,
    timestamp: '2026-08-09T18:30:00Z',
  },
  {
    id: 1005,
    sha: 'b823e11',
    message: 'chore(deps): bump gunicorn from 20.1.0 to 22.0.0',
    author: 'dependabot[bot]',
    repo_full_name: 'acme/core-service',
    status: 'failed',
    status_detail: 'Provider rate-limit tier-exhaustion during security agent review. Click retry to re-queue.',
    risk_score: null,
    timestamp: '2026-08-09T14:10:00Z',
  },
  {
    id: 1006,
    sha: '7a21f9c',
    message: 'feat(db): auto-generated database migration for v3.4 schema',
    author: 'ci-bot',
    repo_full_name: 'acme/core-service',
    status: 'skipped',
    status_detail: 'Auto-generated migration file exceeds 2,500 lines threshold.',
    risk_score: null,
    timestamp: '2026-08-08T19:40:00Z',
  },
  {
    id: 1007,
    sha: 'd1902ee',
    message: 'feat(infra): update production terraform module for cloud run ingress',
    author: 'dev-ops-sam',
    repo_full_name: 'acme/infra-terraform',
    status: 'completed',
    status_detail: null,
    risk_score: 4.2,
    timestamp: '2026-08-08T11:20:00Z',
  },
];

export const MOCK_COMMIT_DETAILS: Record<number, CommitDetail> = {
  1001: {
    id: 1001,
    sha: 'a7d9f2e4b3c10921fe88912304918231',
    message: 'fix(auth): update user permission check in API route',
    author: 'dev-alex',
    repo_full_name: 'acme/core-service',
    branch: 'main',
    status: 'completed',
    status_detail: null,
    skip_reason: null,
    timestamp: '2026-08-10T00:48:12Z',
    report: {
      summary:
        'This commit modifies the core RBAC authorization query in backend/auth/permissions.py. Analysis detected a critical SQL injection vulnerability caused by unsafe raw string formatting in string queries, alongside a tenant isolation bypass that allows cross-organization permission lookups if the tenant ID is omitted from parameter inputs.',
      change_type: 'bug_fix',
      risk_score: 9.2,
      analysis_tier: 'full',
      documentation_needed: true,
      documentation_reason:
        'The tenant isolation lookup logic was modified, changing the fallback behavior when organization context headers are absent.',
      documentation_suggestion:
        'Update section 4.2 of docs/security/rbac-architecture.md to document the strict tenant ID enforcement policy.',
      scope_metrics: {
        files_changed: 2,
        additions: 38,
        deletions: 14,
      },
      recommendations: [
        'Replace all raw SQL string interpolations with parameterized query arguments using SQLAlchemy bindparams.',
        'Enforce mandatory non-null tenant_id validation at the FastAPI middleware layer before reaching database queries.',
        'Add isolated unit test cases covering cross-tenant data access attempts.',
      ],
      issues: [
        {
          title: 'SQL Injection via Unsanitized String Formatting',
          severity: 'critical',
          explanation:
            'User-controlled `user_role` input is directly formatted into the SQL query string using Python f-strings instead of parameterized bindings. An attacker crafting a custom HTTP request could bypass permission checks or extract arbitrary database records.',
          suggested_fix:
            'Refactor the SQL query execution to pass parameters as a dictionary or tuple parameter list to SQLAlchemy text() execution.',
          filepath: 'backend/auth/permissions.py',
          line_start: 42,
          line_end: 48,
          confidence: 'high',
          source_agent: 'security_review_worker',
          affected_modules: {
            confirmed: [
              {
                module_path: 'backend/api/users.py',
                is_broken_call_site: true,
                impact_type: 'direct',
              },
              {
                module_path: 'backend/services/rbac.py',
                is_broken_call_site: false,
                impact_type: 'transitive_dependency',
              },
            ],
            direct: [
              {
                module_path: 'backend/api/users.py',
                is_broken_call_site: true,
                impact_type: 'direct',
              },
            ],
            transitive_count: 3,
            truncated: false,
          },
          code_fix: `--- a/backend/auth/permissions.py
+++ b/backend/auth/permissions.py
@@ -42,7 +42,7 @@ async function check_user_permission(db: Session, user_id: str, role: str):
-    query = f"SELECT * FROM permissions WHERE user_id = '{user_id}' AND role = '{role}'"
-    result = await db.execute(text(query))
+    query = text("SELECT * FROM permissions WHERE user_id = :user_id AND role = :role")
+    result = await db.execute(query, {"user_id": user_id, "role": role})
     return result.fetchall()`,
        },
        {
          title: 'Multi-Tenant Isolation Guard Bypass on Null Context',
          severity: 'high',
          explanation:
            'When `tenant_id` is passed as None or empty string, the filter condition is silently omitted rather than throwing an Unauthorized Exception, defaulting to an all-tenants lookup.',
          suggested_fix:
            'Explicitly validate that `tenant_id` is a non-empty string; raise `PermissionDeniedException` if absent.',
          filepath: 'backend/auth/permissions.py',
          line_start: 52,
          line_end: 58,
          confidence: 'high',
          source_agent: 'security_review_worker',
          affected_modules: {
            confirmed: [
              {
                module_path: 'backend/api/organization.py',
                is_broken_call_site: true,
                impact_type: 'direct',
              },
            ],
            direct: [],
            transitive_count: 1,
            truncated: false,
          },
          code_fix: `--- a/backend/auth/permissions.py
+++ b/backend/auth/permissions.py
@@ -52,5 +52,8 @@ async function get_tenant_permissions(tenant_id: Optional[str]):
-    if not tenant_id:
-        return await fetch_default_permissions()
+    if not tenant_id or not tenant_id.strip():
+        raise PermissionDeniedException("Tenant ID header 'X-Tenant-ID' is required")
+    return await fetch_tenant_permissions_by_id(tenant_id)`,
        },
      ],
    },
  },

  1002: {
    id: 1002,
    sha: 'c3b1a8f90234a1892830192310123891',
    message: 'refactor(billing): rename Stripe Customer ID field to account_id',
    author: 'sarah-eng',
    repo_full_name: 'acme/billing-gateway',
    branch: 'main',
    status: 'completed',
    status_detail: null,
    skip_reason: null,
    timestamp: '2026-08-09T22:15:00Z',
    report: {
      summary:
        'This refactoring renames the `stripe_customer_id` parameter to `account_id` across the billing service interface. While internal models were updated, downstream webhook payload handlers in `handlers/webhook.ts` still expect the old key name, which will cause runtime KeyError exceptions on incoming Stripe webhooks.',
      change_type: 'refactor',
      risk_score: 6.8,
      analysis_tier: 'full',
      documentation_needed: false,
      scope_metrics: {
        files_changed: 3,
        additions: 19,
        deletions: 22,
      },
      recommendations: [
        'Add backward-compatibility parameter alias in `services/stripe.ts` for at least one release cycle.',
        'Update webhook body parser tests to verify both payload formats.',
      ],
      issues: [
        {
          title: 'Unhandled Field Name Mismatch in Webhook Ingestion',
          severity: 'medium',
          explanation:
            'The webhook handler accesses `data["stripe_customer_id"]` directly without checking for the new `account_id` alias, causing unhandled 500 errors on incoming webhook events from Stripe.',
          suggested_fix:
            'Use fallback dict getter `data.get("account_id") or data.get("stripe_customer_id")` during the migration period.',
          filepath: 'handlers/webhook.ts',
          line_start: 88,
          line_end: 95,
          confidence: 'high',
          source_agent: 'bug_prediction_worker',
          code_fix: `--- a/handlers/webhook.ts
+++ b/handlers/webhook.ts
@@ -88,3 +88,3 @@ export async function handleStripeWebhook(event: StripeEvent) {
-  const accountId = event.data.object.stripe_customer_id;
+  const accountId = event.data.object.account_id || event.data.object.stripe_customer_id;
   if (!accountId) throw new Error("Missing customer account identifier in webhook");`,
        },
      ],
    },
  },

  1004: {
    id: 1004,
    sha: 'e4f8d21a902341908231023120391203',
    message: 'test(e2e): add regression tests for user profile update flow',
    author: 'michael-q',
    repo_full_name: 'acme/core-service',
    branch: 'main',
    status: 'completed',
    status_detail: null,
    skip_reason: null,
    timestamp: '2026-08-09T18:30:00Z',
    report: {
      summary:
        'Clean testing commit. Added comprehensive Cypress and Jest unit tests for user profile field validations, avatar upload constraints, and email change confirmation tokens. No security vulnerabilities or architectural risks detected.',
      change_type: 'test',
      risk_score: 1.4,
      analysis_tier: 'full',
      documentation_needed: false,
      scope_metrics: {
        files_changed: 4,
        additions: 142,
        deletions: 0,
      },
      recommendations: [
        'Maintain high test coverage for profile mutation routes.',
      ],
      issues: [],
    },
  },

  1005: {
    id: 1005,
    sha: 'b823e110293810293810293812093120',
    message: 'chore(deps): bump gunicorn from 20.1.0 to 22.0.0',
    author: 'dependabot[bot]',
    repo_full_name: 'acme/core-service',
    branch: 'main',
    status: 'failed',
    status_detail:
      'Provider rate-limit tier-exhaustion during security agent review. Click retry to re-queue.',
    skip_reason: null,
    timestamp: '2026-08-09T14:10:00Z',
    report: null,
  },

  1006: {
    id: 1006,
    sha: '7a21f9c1029381029381029381029381',
    message: 'feat(db): auto-generated database migration for v3.4 schema',
    author: 'ci-bot',
    repo_full_name: 'acme/core-service',
    branch: 'main',
    status: 'skipped',
    status_detail: 'Auto-generated migration file exceeds 2,500 lines threshold.',
    skip_reason:
      'Auto-generated database migration containing 2,840 changed lines exceeds max single-commit whole-diff analysis window (2,000 lines max). Per-file agents bypassed to prevent system memory overload.',
    timestamp: '2026-08-08T19:40:00Z',
    report: {
      summary:
        'Whole-diff LLM analysis was skipped because this commit exceeds the 2,000 changed lines threshold. 1 large SQL migration file detected.',
      change_type: 'config',
      risk_score: 5.0,
      analysis_tier: 'skipped',
      whole_diff_skipped: true,
      analysis_gaps: [
        'Whole-diff agents (Change Classification, Breaking Change, Documentation Impact) skipped due to line count limit (2,840 lines > 2,000 lines).',
      ],
      documentation_needed: false,
      scope_metrics: {
        files_changed: 1,
        additions: 2840,
        deletions: 12,
      },
      recommendations: [
        'Review database migration scripts manually or run dry-run SQL migration tests in staging.',
      ],
      issues: [],
    },
  },

  1007: {
    id: 1007,
    sha: 'd1902ee0192381029381029381029381',
    message: 'feat(infra): update production terraform module for cloud run ingress',
    author: 'dev-ops-sam',
    repo_full_name: 'acme/infra-terraform',
    branch: 'production',
    status: 'completed',
    status_detail: null,
    skip_reason: null,
    timestamp: '2026-08-08T11:20:00Z',
    report: {
      summary:
        'Terraform infrastructure update modifying ingress rules for the production Cloud Run deployment. Configured internal-and-cloud-load-balancing ingress mode and updated CORS whitelist bindings.',
      change_type: 'config',
      risk_score: 4.2,
      analysis_tier: 'full',
      documentation_needed: true,
      documentation_reason: 'Network ingress routing and load balancing scope changed.',
      documentation_suggestion: 'Update terraform architecture deployment diagrams.',
      scope_metrics: {
        files_changed: 2,
        additions: 18,
        deletions: 6,
      },
      recommendations: [
        'Ensure Cloud Run IAM bindings are verified in staging prior to production terraform apply.',
      ],
      issues: [
        {
          title: 'Wildcard Origin Binding in Terraformed CORS Configuration',
          severity: 'low',
          explanation:
            'The ingress Terraform module specifies `allow_origins = ["*"]` for internal microservice routes, which allows any web page to issue cross-origin requests to internal endpoints if cookies are sent.',
          suggested_fix: 'Restrict `allow_origins` strictly to trusted internal application domains.',
          filepath: 'terraform/modules/cloud_run/main.tf',
          line_start: 24,
          line_end: 28,
          confidence: 'medium',
          source_agent: 'security_review_worker',
          code_fix: `--- a/terraform/modules/cloud_run/main.tf
+++ b/terraform/modules/cloud_run/main.tf
@@ -24,3 +24,3 @@ resource "google_cloud_run_service" "app" {
-        allow_origins = ["*"]
+        allow_origins = ["https://app.acme-corp.com", "https://admin.acme-corp.com"]
         allow_methods = ["GET", "POST", "PUT", "DELETE"]`,
        },
      ],
    },
  },
};
