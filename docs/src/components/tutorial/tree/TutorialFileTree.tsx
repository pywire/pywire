import React, { useMemo } from 'react';
import { FileCode, FolderClosed, FolderOpen, ChevronDown, ChevronRight } from 'lucide-react';

interface FileNode {
    name: string;
    path: string;
    isOpen?: boolean;
    children?: Record<string, FileNode>;
}

interface TutorialFileTreeProps {
    files: string[];
    activeFile: string;
    onFileSelect: (path: string) => void;
}

export const TutorialFileTree: React.FC<TutorialFileTreeProps> = ({ files, activeFile, onFileSelect }) => {
    const tree = useMemo(() => {
        const root: Record<string, FileNode> = {};

        files.forEach(filePath => {
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
                        children: isFile ? undefined : {},
                        isOpen: true // Default to open for tutorial
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
        const isFile = !node.children;
        const isActive = node.path === activeFile;

        if (isFile) {
            return (
                <div
                    key={node.path}
                    className={`pw-filetree-file ${isActive ? 'active' : ''}`}
                    style={{ paddingLeft: `${depth * 12 + 12}px` }}
                    onClick={() => onFileSelect(node.path)}
                >
                    <FileCode size={14} color={isActive ? '#22d3ee' : '#9ca3af'} style={{ flexShrink: 0 }} />
                    <span className="pw-filetree-text">{node.name}</span>
                </div>
            );
        }

        return (
            <div key={node.path}>
                <div
                    className="pw-filetree-folder"
                    style={{ paddingLeft: `${depth * 12}px` }}
                >
                    <ChevronDown size={14} style={{ flexShrink: 0 }} />
                    <FolderOpen size={14} color="#60a5fa" style={{ flexShrink: 0 }} />
                    <span className="pw-filetree-text">{node.name}</span>
                </div>
                <div>
                    {Object.values(node.children!).sort((a, b) => {
                        // Dir first, then file
                        if (!!a.children !== !!b.children) return a.children ? -1 : 1;
                        return a.name.localeCompare(b.name);
                    }).map(child => renderNode(child, depth + 1))}
                </div>
            </div>
        );
    };

    return (
        <div className="pw-panel-bg" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div className="pw-filetree-header">
                <FolderClosed size={14} />
                <span>FILES</span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto' }}>
                {Object.values(tree).sort((a, b) => {
                    if (!!a.children !== !!b.children) return a.children ? -1 : 1;
                    return a.name.localeCompare(b.name);
                }).map(node => renderNode(node, 0))}
            </div>
        </div>
    );
};
