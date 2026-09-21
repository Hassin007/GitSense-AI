import React, { useState } from 'react';
import { ConnectedRepo } from '../types';
import { X, Activity, Sparkles, RotateCw, Code2, Play } from 'lucide-react';

interface SimulateCommitModalProps {
  isOpen: boolean;
  repos: ConnectedRepo[];
  onClose: () => void;
  onSimulatePush: (data: {
    repo_full_name: string;
    message: string;
    author: string;
    file_path: string;
    code_diff: string;
  }) => Promise<void>;
}

const PRESETS = [
  {
    name: '🔴 SQL Injection in User Auth Query',
    message: 'fix(auth): update user role permission query in auth service',
    filePath: 'backend/auth/permissions.py',
    diff: `--- a/backend/auth/permissions.py
+++ b/backend/auth/permissions.py
@@ -42,3 +42,3 @@ async function check_permission(user_id, role):
-    query = "SELECT * FROM permissions WHERE user_id = '" + user_id + "' AND role = '" + role + "'"
+    query = f"SELECT * FROM permissions WHERE user_id = '{user_id}' AND role = '{role}'"
     return await db.execute(query)`,
  },
  {
    name: '🟠 Breaking API Signature in Stripe Billing',
    message: 'refactor(stripe): rename customer identifier to account_id',
    filePath: 'services/stripe_client.ts',
    diff: `--- a/services/stripe_client.ts
+++ b/services/stripe_client.ts
@@ -14,3 +14,3 @@ export function getCustomerProfile(stripe_customer_id: string) {
-  return stripe.customers.retrieve(stripe_customer_id);
+export function getCustomerProfile(account_id: string) {
+  return stripe.customers.retrieve(account_id);`,
  },
  {
    name: '🟢 Clean Unit Test Commit',
    message: 'test(auth): add unit test cases for token expiration guard',
    filePath: 'tests/auth.test.ts',
    diff: `--- a/tests/auth.test.ts
+++ b/tests/auth.test.ts
@@ -88,0 +89,8 @@ describe("JWT Token Guard", () => {
+  it("should reject expired token with 401 Unauthorized", async () => {
+    const expiredToken = generateTestToken({ exp: Date.now() - 3600 });
+    const res = await request(app).get("/api/auth/me").set("Authorization", \`Bearer \${expiredToken}\`);
+    expect(res.status).toBe(401);
+  });
+});`,
  },
];

export const SimulateCommitModal: React.FC<SimulateCommitModalProps> = ({
  isOpen,
  repos,
  onClose,
  onSimulatePush,
}) => {
  const [repoFullName, setRepoFullName] = useState(repos[0]?.repo_full_name || 'acme/core-service');
  const [message, setMessage] = useState(PRESETS[0].message);
  const [author, setAuthor] = useState('dev-alex');
  const [filePath, setFilePath] = useState(PRESETS[0].filePath);
  const [codeDiff, setCodeDiff] = useState(PRESETS[0].diff);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleApplyPreset = (preset: (typeof PRESETS)[0]) => {
    setMessage(preset.message);
    setFilePath(preset.filePath);
    setCodeDiff(preset.diff);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim() || !codeDiff.trim()) {
      setError('Commit message and code diff are required.');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onSimulatePush({
        repo_full_name: repoFullName,
        message: message.trim(),
        author: author.trim() || 'dev-user',
        file_path: filePath.trim() || 'src/main.ts',
        code_diff: codeDiff.trim(),
      });
      onClose();
    } catch (err: any) {
      setError(err.message || 'Simulation failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-white dark:bg-[#1A1A19] rounded-xl shadow-2xl border border-[#E5E2D9] dark:border-[#3A3A36] overflow-hidden text-[#1A1A1A] dark:text-[#DEDACF] font-sans">
        {/* Modal Header */}
        <div className="px-6 py-4 bg-[#FCFAF7] dark:bg-[#252523] border-b border-[#E5E2D9] dark:border-[#3A3A36] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-[#10B981]" />
            <h3 className="font-semibold text-sm text-[#1A1A1A] dark:text-white">
              Simulate Git Push Webhook
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[#F1EFE9] dark:hover:bg-[#3A3A36] text-[#AFA99E] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
          {error && (
            <div className="p-3 rounded-lg bg-[#FEF2F2] dark:bg-[#2c1717] text-[#DC2626] dark:text-[#FEE2E2] border border-[#DC2626]/30 text-xs font-mono">
              {error}
            </div>
          )}

          {/* Quick Presets */}
          <div className="space-y-1.5 font-sans text-xs">
            <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest">
              Quick Test Presets
            </label>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => handleApplyPreset(p)}
                  className="px-2.5 py-1 rounded bg-[#F1EFE9] dark:bg-[#252523] hover:bg-[#1A1A1A] hover:text-white dark:hover:bg-white dark:hover:text-[#1A1A1A] text-[#5C574F] dark:text-[#AFA99E] border border-[#E5E2D9] dark:border-[#3A3A36] transition-colors font-medium text-[11px]"
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3 font-sans text-xs">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Repository */}
              <div>
                <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                  Repository
                </label>
                <select
                  value={repoFullName}
                  onChange={(e) => setRepoFullName(e.target.value)}
                  className="w-full px-3 py-2 bg-[#F1EFE9] dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs"
                >
                  {repos.map((r) => (
                    <option key={r.id} value={r.repo_full_name}>
                      {r.repo_full_name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Author */}
              <div>
                <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                  Author Username
                </label>
                <input
                  type="text"
                  value={author}
                  onChange={(e) => setAuthor(e.target.value)}
                  placeholder="e.g. dev-alex"
                  className="w-full px-3 py-2 bg-[#F1EFE9] dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs"
                />
              </div>
            </div>

            {/* Commit Message */}
            <div>
              <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                Commit Message <span className="text-[#DC2626]">*</span>
              </label>
              <input
                type="text"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="e.g. fix(auth): update user role check query"
                required
                className="w-full px-3 py-2 bg-[#F1EFE9] dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs"
              />
            </div>

            {/* File Path */}
            <div>
              <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                Modified File Path
              </label>
              <input
                type="text"
                value={filePath}
                onChange={(e) => setFilePath(e.target.value)}
                placeholder="e.g. backend/auth/permissions.py"
                className="w-full px-3 py-2 bg-[#F1EFE9] dark:bg-[#1C1A18] text-[#1A1A1A] dark:text-white rounded-md border border-[#DEDACF] dark:border-[#3A3832] focus:outline-none text-xs"
              />
            </div>

            {/* Unified Code Diff */}
            <div>
              <label className="block text-[10px] font-bold text-[#7A7468] uppercase tracking-widest mb-1">
                Git Diff Snippet <span className="text-[#DC2626]">*</span>
              </label>
              <textarea
                value={codeDiff}
                onChange={(e) => setCodeDiff(e.target.value)}
                rows={6}
                required
                placeholder="Paste git diff patch e.g. --- a/file.ts +++ b/file.ts"
                className="w-full p-3 font-mono text-xs bg-[#0A0A09] text-white rounded-md border border-[#3A3832] focus:outline-none leading-relaxed"
              ></textarea>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={isSubmitting}
                className="px-5 py-2.5 bg-[#1A1A1A] dark:bg-white text-white dark:text-[#1A1A1A] hover:bg-black dark:hover:bg-[#E5E2D9] font-bold text-xs rounded-md shadow transition-colors flex items-center gap-1.5 disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <RotateCw className="w-4 h-4 animate-spin text-[#10B981]" />
                    <span>Analyzing Diff via LLM Agents...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Trigger Commit Analysis</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
