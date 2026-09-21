import React, { useState, useEffect, useCallback } from 'react';
import { UserProfile, ConnectedRepo, CommitListItem, CommitDetail } from './types';
import { api, setStoredToken, clearStoredToken } from './services/api';
import { Navbar } from './components/Navbar';
import { MetricsOverview } from './components/MetricsOverview';
import { CommitFeed } from './components/CommitFeed';
import { CommitReportDrawer } from './components/CommitReportDrawer';
import { RepoManagementModal } from './components/RepoManagementModal';
import { SimulateCommitModal } from './components/SimulateCommitModal';
import { AuthLanding } from './components/AuthLanding';

export default function App() {
  // Theme state: 'light' or 'dark' (brownish dark mode)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('gitsense_theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  // User Authentication state
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [authLoading, setAuthLoading] = useState<boolean>(true);

  // Core Data
  const [repos, setRepos] = useState<ConnectedRepo[]>([]);
  const [commits, setCommits] = useState<CommitListItem[]>([]);

  // Filters & Controls
  const [selectedRepoId, setSelectedRepoId] = useState<number | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Polling State
  const [autoRefreshInterval, setAutoRefreshInterval] = useState<number>(10);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // Selected Commit Report Drawer
  const [selectedCommitId, setSelectedCommitId] = useState<number | null>(null);
  const [commitDetail, setCommitDetail] = useState<CommitDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);

  // Modals
  const [isConnectModalOpen, setIsConnectModalOpen] = useState<boolean>(false);
  const [isSimulateModalOpen, setIsSimulateModalOpen] = useState<boolean>(false);

  // Toggle Theme Class on Root Document
  useEffect(() => {
    localStorage.setItem('gitsense_theme', theme);
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  // Token Ingestion & Auth Check on Page Mount
  useEffect(() => {
    const initAuth = async () => {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        const queryToken = urlParams.get('token');

        if (queryToken) {
          setStoredToken(queryToken);
          // Remove query param from URL bar without page reload
          window.history.replaceState({}, document.title, window.location.pathname);
        }

        // Fetch User Info
        const profile = await api.getAuthUser();
        if (profile) {
          setUser(profile);
          setIsAuthenticated(true);
        } else {
          setIsAuthenticated(false);
          setUser(null);
        }
      } catch (err) {
        console.warn('Auth validation failed:', err);
        setIsAuthenticated(false);
        setUser(null);
      } finally {
        setAuthLoading(false);
      }
    };

    initAuth();
  }, []);

  // Fetch Repositories
  const fetchRepos = useCallback(async () => {
    try {
      const data = await api.getConnectedRepos();
      setRepos(data);
    } catch (err) {
      console.error('Failed to fetch repositories:', err);
    }
  }, []);

  // Fetch Commits
  const fetchCommits = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const data = await api.getCommits(selectedRepoId, selectedStatus);
      setCommits(data);
    } catch (err) {
      console.error('Failed to fetch commits:', err);
    } finally {
      setIsRefreshing(false);
    }
  }, [selectedRepoId, selectedStatus]);

  // Load Initial Data once authenticated
  useEffect(() => {
    if (isAuthenticated) {
      fetchRepos();
      fetchCommits();
    }
  }, [isAuthenticated, fetchRepos, fetchCommits]);

  // Fetch Commit Report Detail when a commit is selected
  useEffect(() => {
    if (!selectedCommitId) {
      setCommitDetail(null);
      return;
    }

    const fetchReport = async () => {
      setDetailLoading(true);
      try {
        const detail = await api.getCommitReport(selectedCommitId);
        setCommitDetail(detail);
      } catch (err) {
        console.error('Failed to fetch commit report detail:', err);
      } finally {
        setDetailLoading(false);
      }
    };

    fetchReport();
  }, [selectedCommitId]);

  // Filter commits locally by search query
  const filteredCommits = commits.filter((c) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return c.sha.toLowerCase().includes(q) || c.message.toLowerCase().includes(q) || c.author.toLowerCase().includes(q);
  });

  const handleSignIn = () => {
    const backendUrl = 'http://localhost:8000';
    const redirectUrl = encodeURIComponent(window.location.origin);
    window.location.href = `${backendUrl}/auth/login?redirect_url=${redirectUrl}`;
  };

  const handleLogout = () => {
    clearStoredToken();
    setIsAuthenticated(false);
    setUser(null);
  };

  const handleConnectRepo = async (data: any) => {
    await api.connectRepo(data);
    await fetchRepos();
  };

  const handleDisconnectRepo = async (id: number) => {
    await api.disconnectRepo(id);
    if (selectedRepoId === id) {
      setSelectedRepoId(null);
    }
    await fetchRepos();
    await fetchCommits();
  };

  const handleRetryAnalysis = async (commitId: number) => {
    await api.retryCommitAnalysis(commitId);
    await fetchCommits();
    if (selectedCommitId === commitId) {
      const updated = await api.getCommitReport(commitId);
      setCommitDetail(updated);
    }
  };

  const handleSimulatePush = async (payload: any) => {
    await api.simulateCommitPush(payload);
    await fetchCommits();
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-[#FBF9F4] dark:bg-[#1A1A19] text-[#1A1A1A] dark:text-[#DEDACF] flex items-center justify-center font-sans text-xs">
        Initializing GitSense AI...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <AuthLanding onSignIn={handleSignIn} />;
  }

  return (
    <div className="min-h-screen bg-[#FBF9F4] dark:bg-[#1A1A19] text-[#1A1A1A] dark:text-[#DEDACF] font-sans transition-colors pb-16">
      {/* Navbar */}
      <Navbar
        user={user}
        repos={repos}
        selectedRepoId={selectedRepoId}
        onSelectRepo={setSelectedRepoId}
        autoRefreshInterval={autoRefreshInterval}
        onSetAutoRefresh={setAutoRefreshInterval}
        onManualRefresh={fetchCommits}
        isRefreshing={isRefreshing}
        onOpenConnectModal={() => setIsConnectModalOpen(true)}
        onOpenSimulateModal={() => setIsSimulateModalOpen(true)}
        theme={theme}
        onToggleTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')}
        onLogout={handleLogout}
      />

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        {/* Metrics Summary Cards Grid */}
        <MetricsOverview commits={commits} repos={repos} />

        {/* Commit Feed & Filter Bar Section */}
        <CommitFeed
          commits={filteredCommits}
          repos={repos}
          selectedRepoId={selectedRepoId}
          onSelectRepo={setSelectedRepoId}
          selectedStatus={selectedStatus}
          onSelectStatus={setSelectedStatus}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onSelectCommit={setSelectedCommitId}
          onRetryAnalysis={handleRetryAnalysis}
          onRefresh={fetchCommits}
        />
      </main>

      {/* Commit Detail Report Drawer */}
      <CommitReportDrawer
        commitDetail={commitDetail}
        isLoading={detailLoading}
        onClose={() => setSelectedCommitId(null)}
        onRetry={handleRetryAnalysis}
      />

      {/* Repository Management Modal */}
      <RepoManagementModal
        repos={repos}
        isOpen={isConnectModalOpen}
        onClose={() => setIsConnectModalOpen(false)}
        onConnectRepo={handleConnectRepo}
        onDisconnectRepo={handleDisconnectRepo}
      />

      {/* Custom Commit Push Simulator Modal */}
      <SimulateCommitModal
        isOpen={isSimulateModalOpen}
        repos={repos}
        onClose={() => setIsSimulateModalOpen(false)}
        onSimulatePush={handleSimulatePush}
      />
    </div>
  );
}
