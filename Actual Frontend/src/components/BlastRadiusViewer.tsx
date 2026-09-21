import React, { useState } from 'react';
import { GitBranch, AlertTriangle, Layers, Copy, Check, ChevronDown, ChevronUp, Network } from 'lucide-react';

interface BlastRadiusViewerProps {
  mermaidDefinition: string;
}

export const BlastRadiusViewer: React.FC<BlastRadiusViewerProps> = ({ mermaidDefinition }) => {
  const [copied, setCopied] = useState(false);
  const [showRawMermaid, setShowRawMermaid] = useState(false);

  if (!mermaidDefinition) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(mermaidDefinition);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Parse lines to extract node definitions and node types for visual card rendering
  const parseMermaidNodes = (def: string) => {
    const lines = def.split('\n');
    const nodes: Array<{ id: string; label: string; isTarget: boolean; isBroken: boolean; isDirect: boolean; isTransitive: boolean }> = [];
    const connections: Array<{ from: string; to: string }> = [];

    lines.forEach((line) => {
      const lineTrim = line.trim();
      
      // Node match: N0["label"]
      const nodeMatch = lineTrim.match(/^([A-Za-z0-9_]+)\["([^"]+)"\]/);
      if (nodeMatch) {
        const [_, id, rawLabel] = nodeMatch;
        const isTarget = rawLabel.includes('(Changed File)');
        const isBroken = rawLabel.includes('🚨');
        const isDirect = rawLabel.includes('(Direct Importer)');
        const isTransitive = rawLabel.includes('Transitive');

        nodes.push({
          id,
          label: rawLabel,
          isTarget,
          isBroken,
          isDirect,
          isTransitive,
        });
      }

      // Connection match: N0 --> N1
      const connMatch = lineTrim.match(/^([A-Za-z0-9_]+)\s*--(?:>|\.->)\s*([A-Za-z0-9_]+)/);
      if (connMatch) {
        connections.push({ from: connMatch[1], to: connMatch[2] });
      }
    });

    return { nodes, connections };
  };

  const { nodes } = parseMermaidNodes(mermaidDefinition);
  const brokenCount = nodes.filter((n) => n.isBroken).length;
  const directCount = nodes.filter((n) => n.isDirect).length;
  const transitiveCount = nodes.filter((n) => n.isTransitive).length;

  return (
    <div className="rounded-xl border border-[#E5E2D9] dark:border-[#3A3A36] bg-[#FCFAF7] dark:bg-[#252523] p-4 space-y-4 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2 pb-3 border-b border-[#E5E2D9] dark:border-[#3A3A36]">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
            <Network className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#1A1A1A] dark:text-white flex items-center gap-2">
              Visual Blast Radius & Downstream Impact
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30">
                {nodes.length} Nodes
              </span>
            </h3>
            <p className="text-xs text-[#7A7468] dark:text-[#AFA99E]">
              Transitive dependency graph highlighting affected downstream modules
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowRawMermaid(!showRawMermaid)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-mono bg-[#F1EFE9] dark:bg-[#1A1A19] hover:bg-[#E5E2D9] dark:hover:bg-[#3A3A36] text-[#5C574F] dark:text-[#AFA99E] border border-[#E5E2D9] dark:border-[#3A3A36] transition-colors"
          >
            {showRawMermaid ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            <span>{showRawMermaid ? 'Hide Code' : 'View Code'}</span>
          </button>

          <button
            onClick={handleCopy}
            className="p-1.5 rounded text-xs bg-[#F1EFE9] dark:bg-[#1A1A19] hover:bg-[#E5E2D9] dark:hover:bg-[#3A3A36] text-[#5C574F] dark:text-[#AFA99E] border border-[#E5E2D9] dark:border-[#3A3A36] transition-colors"
            title="Copy Mermaid Code"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Metric Badges Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-xs">
        <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-700 dark:text-rose-300 flex items-center justify-between">
          <span>Broken Call Sites:</span>
          <strong className="font-bold">{brokenCount}</strong>
        </div>
        <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-300 flex items-center justify-between">
          <span>Direct Importers:</span>
          <strong className="font-bold">{directCount}</strong>
        </div>
        <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-700 dark:text-blue-300 flex items-center justify-between col-span-2 sm:col-span-1">
          <span>Transitive Importers:</span>
          <strong className="font-bold">{transitiveCount}</strong>
        </div>
      </div>

      {/* Visual Node Flow List */}
      <div className="space-y-2 pt-1">
        {nodes.map((node) => (
          <div
            key={node.id}
            className={`p-3 rounded-lg border text-xs font-mono transition-all flex items-center justify-between gap-3 ${
              node.isTarget
                ? 'bg-[#F1EFE9] dark:bg-[#1A1A19] border-[#D6D2C4] dark:border-[#4A4A45] text-[#1A1A1A] dark:text-white font-bold'
                : node.isBroken
                ? 'bg-rose-500/15 border-rose-500/40 text-rose-800 dark:text-rose-200 font-semibold'
                : node.isDirect
                ? 'bg-amber-500/10 border-amber-500/30 text-amber-900 dark:text-amber-200'
                : 'bg-blue-500/10 border-blue-500/25 text-blue-900 dark:text-blue-200'
            }`}
          >
            <div className="flex items-center gap-2 truncate">
              {node.isTarget && <GitBranch className="w-4 h-4 text-stone-500 shrink-0" />}
              {node.isBroken && <AlertTriangle className="w-4 h-4 text-rose-500 shrink-0 animate-pulse" />}
              {node.isDirect && <Layers className="w-4 h-4 text-amber-500 shrink-0" />}
              {node.isTransitive && <Network className="w-4 h-4 text-blue-500 shrink-0" />}
              <span className="truncate">{node.label}</span>
            </div>

            <span className="text-[10px] uppercase font-bold tracking-wider opacity-75 shrink-0">
              {node.isTarget
                ? 'Root File'
                : node.isBroken
                ? 'Broken Site'
                : node.isDirect
                ? 'Direct'
                : 'Transitive'}
            </span>
          </div>
        ))}
      </div>

      {/* Raw Mermaid Definition Collapse */}
      {showRawMermaid && (
        <div className="mt-3 pt-3 border-t border-[#E5E2D9] dark:border-[#3A3A36]">
          <pre className="p-3 rounded-lg bg-[#1A1A19] text-stone-300 font-mono text-[11px] overflow-x-auto border border-[#3A3A36]">
            {mermaidDefinition}
          </pre>
        </div>
      )}
    </div>
  );
};
