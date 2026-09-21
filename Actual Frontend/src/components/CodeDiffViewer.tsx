import React, { useState } from 'react';
import { Copy, Check, Columns, AlignJustify, Code2 } from 'lucide-react';

interface CodeDiffViewerProps {
  diffText: string;
  filepath?: string;
}

interface ParsedDiffLine {
  type: 'add' | 'delete' | 'header' | 'normal';
  content: string;
  oldLineNo?: number;
  newLineNo?: number;
}

export const CodeDiffViewer: React.FC<CodeDiffViewerProps> = ({ diffText, filepath }) => {
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<'unified' | 'split'>('unified');

  const handleCopy = () => {
    navigator.clipboard.writeText(diffText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const parseDiff = (raw: string): ParsedDiffLine[] => {
    const lines = raw.split('\n');
    const result: ParsedDiffLine[] = [];
    let oldNo = 1;
    let newNo = 1;

    for (const line of lines) {
      if (line.startsWith('@@')) {
        // Extract line numbers if present e.g. @@ -42,7 +42,7 @@
        const match = line.match(/@@ -(\d+),?\d* \+(\d+),?\d* @@/);
        if (match) {
          oldNo = parseInt(match[1], 10);
          newNo = parseInt(match[2], 10);
        }
        result.push({ type: 'header', content: line });
      } else if (line.startsWith('+') && !line.startsWith('+++')) {
        result.push({ type: 'add', content: line.substring(1), newLineNo: newNo });
        newNo++;
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        result.push({ type: 'delete', content: line.substring(1), oldLineNo: oldNo });
        oldNo++;
      } else if (!line.startsWith('---') && !line.startsWith('+++')) {
        result.push({
          type: 'normal',
          content: line.startsWith(' ') ? line.substring(1) : line,
          oldLineNo: oldNo,
          newLineNo: newNo,
        });
        oldNo++;
        newNo++;
      }
    }
    return result;
  };

  const parsedLines = parseDiff(diffText);

  return (
    <div className="rounded-lg border border-stone-300 dark:border-[#38322d] bg-stone-900 dark:bg-[#12100e] text-stone-100 font-mono text-xs overflow-hidden shadow-sm">
      {/* Diff Header Bar */}
      <div className="flex items-center justify-between px-3.5 py-2 bg-stone-850 dark:bg-[#1b1816] border-b border-stone-800 dark:border-[#2b2622] text-stone-300">
        <div className="flex items-center gap-2 truncate">
          <Code2 className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span className="font-semibold text-stone-200 truncate">
            {filepath || 'Suggested Code Patch'}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* View Toggle */}
          <div className="flex items-center bg-stone-950 dark:bg-[#12100e] rounded p-0.5 border border-stone-800 dark:border-[#2b2622]">
            <button
              onClick={() => setViewMode('unified')}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[11px] transition-colors ${
                viewMode === 'unified'
                  ? 'bg-amber-600/30 text-amber-300 font-medium'
                  : 'text-stone-400 hover:text-stone-200'
              }`}
              title="Unified View"
            >
              <AlignJustify className="w-3 h-3" />
              Unified
            </button>
            <button
              onClick={() => setViewMode('split')}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[11px] transition-colors ${
                viewMode === 'split'
                  ? 'bg-amber-600/30 text-amber-300 font-medium'
                  : 'text-stone-400 hover:text-stone-200'
              }`}
              title="Split View"
            >
              <Columns className="w-3 h-3" />
              Split
            </button>
          </div>

          {/* Copy Button */}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-stone-800 dark:bg-[#28231f] hover:bg-stone-700 dark:hover:bg-[#332d28] text-stone-200 text-[11px] font-sans font-medium transition-colors border border-stone-700 dark:border-[#38322d]"
          >
            {copied ? (
              <>
                <Check className="w-3 h-3 text-emerald-400" />
                <span className="text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3" />
                <span>Copy Patch</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Code Body */}
      <div className="overflow-x-auto max-h-[360px] p-2 leading-relaxed">
        {viewMode === 'unified' ? (
          <table className="w-full text-left border-collapse font-mono">
            <tbody>
              {parsedLines.map((line, idx) => {
                if (line.type === 'header') {
                  return (
                    <tr key={idx} className="bg-stone-950/70 dark:bg-[#12100e] text-stone-400 select-none">
                      <td colSpan={3} className="px-3 py-1 text-[11px] italic border-y border-stone-800/80">
                        {line.content}
                      </td>
                    </tr>
                  );
                }

                const isAdd = line.type === 'add';
                const isDel = line.type === 'delete';

                return (
                  <tr
                    key={idx}
                    className={`hover:bg-stone-800/40 dark:hover:bg-[#25201c]/60 ${
                      isAdd
                        ? 'bg-emerald-950/40 text-emerald-300'
                        : isDel
                        ? 'bg-rose-950/40 text-rose-300'
                        : 'text-stone-300'
                    }`}
                  >
                    <td className="w-10 px-2 py-0.5 text-right select-none text-stone-500 border-r border-stone-800/60 font-sans text-[10px]">
                      {line.oldLineNo || ''}
                    </td>
                    <td className="w-10 px-2 py-0.5 text-right select-none text-stone-500 border-r border-stone-800/60 font-sans text-[10px]">
                      {line.newLineNo || ''}
                    </td>
                    <td className="px-3 py-0.5 whitespace-pre font-mono">
                      <span className="inline-block w-4 select-none font-bold">
                        {isAdd ? '+' : isDel ? '-' : ' '}
                      </span>
                      {line.content}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          /* Split View Table */
          <table className="w-full text-left border-collapse font-mono">
            <thead>
              <tr className="text-stone-400 text-[10px] border-b border-stone-800">
                <th colSpan={2} className="px-3 py-1 font-semibold text-rose-400 bg-rose-950/20 w-1/2">
                  Original Code
                </th>
                <th colSpan={2} className="px-3 py-1 font-semibold text-emerald-400 bg-emerald-950/20 w-1/2">
                  Suggested Fix Patch
                </th>
              </tr>
            </thead>
            <tbody>
              {parsedLines.map((line, idx) => {
                if (line.type === 'header') {
                  return (
                    <tr key={idx} className="bg-stone-950/70 text-stone-400 select-none">
                      <td colSpan={4} className="px-3 py-1 text-[11px] italic border-y border-stone-800">
                        {line.content}
                      </td>
                    </tr>
                  );
                }

                if (line.type === 'delete') {
                  return (
                    <tr key={idx} className="bg-rose-950/30">
                      <td className="w-8 px-2 py-0.5 text-right text-stone-500 border-r border-stone-800 text-[10px]">
                        {line.oldLineNo}
                      </td>
                      <td className="px-2 py-0.5 whitespace-pre text-rose-300 border-r border-stone-800 w-1/2 font-mono">
                        - {line.content}
                      </td>
                      <td className="w-8 px-2 py-0.5 text-right text-stone-600 border-r border-stone-800 text-[10px]"></td>
                      <td className="px-2 py-0.5 bg-stone-950/40 w-1/2"></td>
                    </tr>
                  );
                }

                if (line.type === 'add') {
                  return (
                    <tr key={idx} className="bg-emerald-950/30">
                      <td className="w-8 px-2 py-0.5 text-right text-stone-600 border-r border-stone-800 text-[10px]"></td>
                      <td className="px-2 py-0.5 bg-stone-950/40 border-r border-stone-800 w-1/2"></td>
                      <td className="w-8 px-2 py-0.5 text-right text-stone-500 border-r border-stone-800 text-[10px]">
                        {line.newLineNo}
                      </td>
                      <td className="px-2 py-0.5 whitespace-pre text-emerald-300 w-1/2 font-mono">
                        + {line.content}
                      </td>
                    </tr>
                  );
                }

                return (
                  <tr key={idx} className="text-stone-300 hover:bg-stone-800/30">
                    <td className="w-8 px-2 py-0.5 text-right text-stone-500 border-r border-stone-800 text-[10px]">
                      {line.oldLineNo}
                    </td>
                    <td className="px-2 py-0.5 whitespace-pre border-r border-stone-800 w-1/2">
                      {line.content}
                    </td>
                    <td className="w-8 px-2 py-0.5 text-right text-stone-500 border-r border-stone-800 text-[10px]">
                      {line.newLineNo}
                    </td>
                    <td className="px-2 py-0.5 whitespace-pre w-1/2">{line.content}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
