import React, { useState } from 'react';
import {
  FolderGit2,
  RefreshCw,
  Plus,
  Sun,
  Moon,
  LogOut,
  Activity,
} from 'lucide-react';
import { ConnectedRepo, UserProfile } from '../types';
import { GitSenseLogo } from './GitSenseLogo';

interface NavbarProps {
  user: UserProfile | null;
  repos: ConnectedRepo[];
  selectedRepoId: number | null;
  onSelectRepo: (repoId: number | null) => void;
  autoRefreshInterval: number;
  onSetAutoRefresh: (seconds: number) => void;
  onManualRefresh: () => void;
  isRefreshing: boolean;
  onOpenConnectModal: () => void;
  onOpenSimulateModal: () => void;
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  repos,
  selectedRepoId,
  onSelectRepo,
  autoRefreshInterval,
  onSetAutoRefresh,
  onManualRefresh,
  isRefreshing,
  onOpenConnectModal,
  onOpenSimulateModal,
  theme,
  onToggleTheme,
  onLogout,
}) => {
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);
  const [refreshDropdownOpen, setRefreshDropdownOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 w-full h-14 border-b border-[#E5E2D9] dark:border-[#332D28] bg-white dark:bg-[#1C1A18] px-4 sm:px-6 transition-colors">
      <div className="max-w-7xl mx-auto h-full flex items-center justify-between gap-4">
        {/* Brand & Repo Picker */}
        <div className="flex items-center space-x-4">
          <GitSenseLogo size="md" showText={true} />

          <div className="hidden sm:block h-5 w-[1px] bg-[#E5E2D9] dark:bg-[#332D28] mx-1"></div>

          {/* Repository Selector Dropdown */}
          <div className="relative flex items-center text-xs sm:text-sm font-medium text-[#5C574F] dark:text-[#DEDACF] bg-[#F1EFE9] dark:bg-[#252320] px-2.5 py-1 rounded-md border border-[#DEDACF] dark:border-[#3A3832]">
            <FolderGit2 className="w-3.5 h-3.5 text-[#7A7468] mr-1.5 shrink-0" />
            <select
              value={selectedRepoId || ''}
              onChange={(e) => onSelectRepo(e.target.value ? parseInt(e.target.value, 10) : null)}
              className="bg-transparent text-[#1A1A1A] dark:text-[#FBF9F4] text-xs font-medium focus:outline-none cursor-pointer pr-1"
            >
              <option value="" className="bg-white dark:bg-[#1C1A18]">All Connected Repos ({repos.length})</option>
              {repos.map((repo) => (
                <option key={repo.id} value={repo.id} className="bg-white dark:bg-[#1C1A18]">
                  {repo.repo_full_name} ({repo.branch})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-3">
          {/* Simulate Push */}
          <button
            onClick={onOpenSimulateModal}
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold text-[#5C574F] dark:text-[#DEDACF] bg-[#F1EFE9] hover:bg-[#E5E2D9] dark:bg-[#252320] dark:hover:bg-[#2e2a26] rounded-md transition-colors border border-[#DEDACF] dark:border-[#3A3832]"
            title="Simulate a custom commit push webhook"
          >
            <Activity className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
            <span>Simulate Commit</span>
          </button>

          {/* Connect Repo */}
          <button
            onClick={onOpenConnectModal}
            className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-[#1A1A1A] text-white hover:bg-black dark:bg-[#FBF9F4] dark:text-[#1A1A1A] dark:hover:bg-white rounded-md transition-colors shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Connect Repo</span>
          </button>

          {/* Refresh Control */}
          <button
            onClick={onManualRefresh}
            className="p-1.5 rounded-md text-[#5C574F] dark:text-[#DEDACF] bg-[#F1EFE9] dark:bg-[#252320] hover:bg-[#E5E2D9] dark:hover:bg-[#2e2a26] border border-[#DEDACF] dark:border-[#3A3832] transition-colors"
            title="Refresh commits manually"
            disabled={isRefreshing}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-[#10B981]' : ''}`} />
          </button>

          {/* Theme Toggle */}
          <button
            onClick={onToggleTheme}
            className="p-1.5 rounded-md text-[#5C574F] dark:text-[#DEDACF] bg-[#F1EFE9] dark:bg-[#252320] hover:bg-[#E5E2D9] dark:hover:bg-[#2e2a26] border border-[#DEDACF] dark:border-[#3A3832] transition-colors"
            title={`Switch theme`}
          >
            {theme === 'light' ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5 text-amber-400" />}
          </button>

          {/* User Profile */}
          {user && (
            <div className="relative">
              <button
                onClick={() => setUserDropdownOpen(!userDropdownOpen)}
                className="w-8 h-8 rounded-full bg-[#E5E2D9] dark:bg-[#3A3832] border-2 border-white dark:border-[#1C1A18] overflow-hidden flex items-center justify-center shrink-0 cursor-pointer"
              >
                {user.avatar_url ? (
                  <img src={user.avatar_url} alt={user.username} className="w-full h-full object-cover" />
                ) : (
                  <span className="text-xs font-bold text-[#1A1A1A] dark:text-white">
                    {user.username.substring(0, 2).toUpperCase()}
                  </span>
                )}
              </button>

              {userDropdownOpen && (
                <div className="absolute right-0 mt-1 w-48 rounded-md bg-white dark:bg-[#221F1C] border border-[#E5E2D9] dark:border-[#3A3832] shadow-lg py-1 z-40">
                  <div className="px-3 py-2 border-b border-[#E5E2D9] dark:border-[#3A3832]">
                    <div className="font-semibold text-xs text-[#1A1A1A] dark:text-white truncate">
                      {user.username}
                    </div>
                    {user.email && (
                      <div className="text-[11px] text-[#7A7468] truncate">{user.email}</div>
                    )}
                  </div>

                  <button
                    onClick={() => {
                      onLogout();
                      setUserDropdownOpen(false);
                    }}
                    className="w-full text-left px-3 py-2 text-xs text-[#DC2626] hover:bg-[#FEE2E2]/50 flex items-center gap-2 font-medium"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
