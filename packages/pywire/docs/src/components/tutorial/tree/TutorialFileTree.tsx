import React, { useMemo, useState } from 'react';
import { FileCode, FolderClosed, FolderOpen, FilePlus, FolderPlus, Trash2, Lock } from 'lucide-react';
import type { AllowedBehavior, TutorialFile } from '../types';

interface FileNode {
    name: string;
    path: string;
    isFolder?: boolean;
    children?: Record<string, FileNode>;
}

interface TutorialFileTreeProps {
    files: string[]; // Current paths in FS
    activeFile: string;
    onFileSelect: (path: string) => void;
    behaviors?: AllowedBehavior;
    originalFiles: TutorialFile[];
    onFileAdd?: (folderPath: string, isFolder?: boolean) => void;
    onFileDelete?: (path: string) => void;
}

export const TutorialFileTree: React.FC<TutorialFileTreeProps> = ({
    files,
    activeFile,
    onFileSelect,
    behaviors,
    originalFiles,
    onFileAdd,
    onFileDelete
}) => {
    // Track expanded folders locally
    const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({});

    const toggleFolder = (path: string) => {
        setExpandedPaths(prev => ({
            ...prev,
            [path]: !prev[path] // Toggle true/false (undefined defaults to falsy, so !undefined is true)
        }));
    };

    const tree = useMemo(() => {
        const root: Record<string, FileNode> = {};

        // Always show root-level add buttons if allowed

        files.forEach(filePath => {
            if (filePath.endsWith('.keep')) return; // Hide dotfiles used for folder persistence

            const parts = filePath.split('/');
            let current = root;
            let currentPath = '';

            parts.forEach((part, index) => {
                currentPath = currentPath ? `${currentPath}/${part}` : part;
                const isFile = index === parts.length - 1;

                if (!current[part]) {
                    current[part] = {
                        name: part,
                        path: currentPath,
                        isFolder: !isFile,
                        children: isFile ? undefined : {},
                    };
                }

                if (!isFile) {
                    current = current[part].children!;
                }
            });
        });

        return root;
    }, [files]);

    const renderNode = (node: FileNode, depth: number) => {
        const isFile = !node.isFolder;
        const isActive = node.path === activeFile;
        // Default to expanded for root folders if not explicitly set
        const isExpanded = expandedPaths[node.path] !== false; // Default true? or default false? 
        // Let's verify existing logic: `isOpen: true` was hardcoded before. 
        // We'll trust state, default to open for now to match prev behavior.
        const isOpen = expandedPaths[node.path] ?? true;

        // Find metadata for this file
        const meta = originalFiles.find(f => f.path === node.path);
        const isEditable = meta?.editable !== false;
        const isDeletable = meta?.deletable === true || (behaviors?.canDeleteFiles?.some(p => {
            const regex = new RegExp('^' + p.replace(/\*/g, '.*') + '$');
            return regex.test(node.path);
        }) ?? false);

        if (isFile) {
            return (
                <div
                    key={node.path}
                    className={`pw-filetree-file ${isActive ? 'active' : ''}`}
                    style={{ paddingLeft: `${depth * 16 + 12}px`, userSelect: 'none' }}
                    onClick={() => onFileSelect(node.path)}
                    onContextMenu={(e) => e.preventDefault()}
                >
                    <FileCode size={14} className={isActive ? 'text-accent' : 'text-dim'} style={{ flexShrink: 0 }} />
                    <span className="pw-filetree-text">{node.name}</span>
                    <div className="pw-filetree-actions">
                        {!isEditable && <Lock size={12} className="pw-file-locked" />}
                        {isDeletable && (
                            <button
                                className="pw-btn-tree-action delete"
                                onClick={(e) => { e.stopPropagation(); onFileDelete?.(node.path); }}
                                title="Delete file"
                            >
                                <Trash2 size={14} />
                            </button>
                        )}
                    </div>
                </div>
            );
        }

        // Folder Logic
        const canAddInFolder = behaviors?.canAddFiles && Object.keys(behaviors.canAddFiles).some(p => p.startsWith(node.path + '/') || p === node.path);

        return (
            <div key={node.path}>
                <div
                    className="pw-filetree-folder"
                    style={{ paddingLeft: `${depth * 16 + 12}px`, userSelect: 'none' }}
                    onClick={() => toggleFolder(node.path)}
                    onContextMenu={(e) => e.preventDefault()}
                >
                    {/* Icon changes based on state */}
                    {isOpen
                        ? <FolderOpen size={14} className="text-blue-400" style={{ flexShrink: 0 }} />
                        : <FolderClosed size={14} className="text-blue-400" style={{ flexShrink: 0 }} />
                    }
                    <span className="pw-filetree-text">{node.name}</span>

                    {/* Action Buttons */}
                    <div className="pw-filetree-actions">
                        {canAddInFolder && (
                            <>
                                <button
                                    className="pw-btn-tree-action"
                                    onClick={(e) => { e.stopPropagation(); onFileAdd?.(node.path, false); }}
                                    title="Add file"
                                >
                                    <FilePlus size={14} />
                                </button>
                                <button
                                    className="pw-btn-tree-action"
                                    onClick={(e) => { e.stopPropagation(); onFileAdd?.(node.path, true); }}
                                    title="Add folder"
                                >
                                    <FolderPlus size={14} />
                                </button>
                            </>
                        )}
                    </div>
                </div>
                {isOpen && (
                    <div>
                        {Object.values(node.children!).sort((a, b) => {
                            if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
                            return a.name.localeCompare(b.name);
                        }).map(child => renderNode(child, depth + 1))}
                    </div>
                )}
            </div>
        );
    };

    const rootCanAdd = behaviors?.canAddFiles && Object.keys(behaviors.canAddFiles).some(p => !p.includes('/'));

    return (
        <div className="pw-panel-bg" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div className="pw-filetree-header" style={{ userSelect: 'none' }} onContextMenu={(e) => e.preventDefault()}>
                <span className="font-bold text-xs tracking-wider text-muted-foreground pl-2">FILES</span>
                <div className="pw-filetree-actions">
                    {rootCanAdd && (
                        <>
                            <button
                                className="pw-btn-tree-action"
                                onClick={(e) => { e.stopPropagation(); onFileAdd?.('', false); }}
                                title="Add file to root"
                            >
                                <FilePlus size={14} />
                            </button>
                            <button
                                className="pw-btn-tree-action"
                                onClick={(e) => { e.stopPropagation(); onFileAdd?.('', true); }}
                                title="Add folder to root"
                            >
                                <FolderPlus size={14} />
                            </button>
                        </>
                    )}
                </div>
            </div>
            <div style={{ flex: 1, overflowY: 'auto' }}>
                {Object.values(tree).sort((a, b) => {
                    if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
                    return a.name.localeCompare(b.name);
                }).map(node => renderNode(node, 0))}
            </div>
        </div>
    );
};
