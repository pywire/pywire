import React, { useMemo, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { TutorialStep } from './types';
import { ChevronDown, ChevronRight, Check, BookOpen, X } from 'lucide-react';

interface TutorialHierarchyProps {
    allSteps: TutorialStep[];
    currentSlug: string;
    getStepUrl: (slug: string) => string;
    isOpen: boolean;
    onClose: () => void;
}

type Hierarchy = Record<string, { // Tutorial Name
    sections: Record<string, { // Section Name
        steps: TutorialStep[]
    }>
}>;

export const TutorialHierarchy: React.FC<TutorialHierarchyProps> = ({
    allSteps,
    currentSlug,
    getStepUrl,
    isOpen,
    onClose
}) => {
    // Group steps
    const hierarchy = useMemo(() => {
        const root: Hierarchy = {};

        allSteps.forEach(step => {
            const tutorialName = step.tutorial || 'General';
            const sectionName = step.section || 'Uncategorized';

            if (!root[tutorialName]) {
                root[tutorialName] = { sections: {} };
            }
            if (!root[tutorialName].sections[sectionName]) {
                root[tutorialName].sections[sectionName] = { steps: [] };
            }

            root[tutorialName].sections[sectionName].steps.push(step);
        });

        return root;
    }, [allSteps]);

    // Local state for expanded sections
    const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({});

    const toggleSection = (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        setExpandedSections(prev => ({ ...prev, [id]: !prev[id] }));
    };

    // Close on Escape key
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && isOpen) {
                onClose();
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, onClose]);

    if (!isOpen) return null;

    // Use React Portal to render to document.body - this escapes ALL parent containers
    const content = (
        <>
            {/* Backdrop - full screen overlay */}
            <div
                style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.5)',
                    zIndex: 9998,
                }}
                onClick={onClose}
            />
            {/* Dropdown Panel */}
            <div
                style={{
                    position: 'fixed',
                    top: '64px', // Below Starlight nav
                    left: '16px',
                    width: '320px',
                    maxHeight: 'calc(100vh - 80px)',
                    overflowY: 'auto',
                    backgroundColor: 'var(--pw-bg-panel, #1a1d2e)',
                    border: '1px solid var(--pw-border, #2a2d3d)',
                    borderRadius: '8px',
                    boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
                    zIndex: 9999,
                }}
            >
                <div style={{
                    padding: '16px',
                    borderBottom: '1px solid var(--pw-border, #2a2d3d)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    position: 'sticky',
                    top: 0,
                    backgroundColor: 'var(--pw-bg-panel, #1a1d2e)',
                }}>
                    <h2 style={{
                        margin: 0,
                        fontWeight: 600,
                        fontSize: '0.75rem',
                        color: 'var(--pw-accent, #22d3ee)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                    }}>Table of Contents</h2>
                    <button
                        onClick={onClose}
                        style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--pw-text-dim, #9ca3af)',
                            cursor: 'pointer',
                            padding: '4px',
                        }}
                    >
                        <X size={16} />
                    </button>
                </div>

                <div style={{ padding: '8px' }}>
                    {Object.entries(hierarchy).map(([tutName, tutData]) => (
                        <div key={tutName} style={{ marginBottom: '16px' }}>
                            <div style={{
                                padding: '4px 8px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                color: 'var(--pw-text-bright, #e5e7eb)',
                                fontWeight: 700,
                                marginBottom: '4px',
                            }}>
                                <BookOpen size={14} />
                                <span>{tutName}</span>
                            </div>

                            <div style={{
                                paddingLeft: '8px',
                                borderLeft: '1px solid var(--pw-border, #2a2d3d)',
                                marginLeft: '10px',
                            }}>
                                {Object.entries(tutData.sections).map(([secName, secData]) => {
                                    const sectionId = `${tutName}-${secName}`;
                                    const isExpanded = expandedSections[sectionId] !== false;

                                    return (
                                        <div key={secName} style={{ marginBottom: '8px' }}>
                                            <button
                                                onClick={(e) => toggleSection(sectionId, e)}
                                                style={{
                                                    width: '100%',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '6px',
                                                    padding: '6px 8px',
                                                    fontSize: '0.75rem',
                                                    fontWeight: 600,
                                                    color: 'var(--pw-text-dim, #9ca3af)',
                                                    background: 'none',
                                                    border: 'none',
                                                    cursor: 'pointer',
                                                    textAlign: 'left',
                                                    borderRadius: '6px',
                                                }}
                                            >
                                                {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                                {secName}
                                            </button>

                                            {isExpanded && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginTop: '2px', marginLeft: '4px' }}>
                                                    {secData.steps.map(step => {
                                                        const isActive = step.slug === currentSlug;
                                                        return (
                                                            <a
                                                                key={step.slug}
                                                                href={getStepUrl(step.slug)}
                                                                onClick={() => {
                                                                    if (!isActive) {
                                                                        onClose(); // Just close, let browser navigate
                                                                    }
                                                                }}
                                                                data-astro-reload
                                                                style={{
                                                                    display: 'flex',
                                                                    alignItems: 'center',
                                                                    gap: '8px',
                                                                    padding: '6px 12px',
                                                                    fontSize: '0.875rem',
                                                                    borderRadius: '6px',
                                                                    textAlign: 'left',
                                                                    border: 'none',
                                                                    cursor: 'pointer',
                                                                    background: isActive ? 'rgba(34,211,238,0.1)' : 'transparent',
                                                                    color: isActive ? 'var(--pw-accent, #22d3ee)' : 'var(--pw-text-dim, #9ca3af)',
                                                                    fontWeight: isActive ? 500 : 400,
                                                                    textDecoration: 'none'
                                                                }}
                                                            >
                                                                <div style={{ width: '16px', flexShrink: 0 }}>
                                                                    {isActive && <Check size={12} />}
                                                                </div>
                                                                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{step.title}</span>
                                                            </a>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </>
    );

    // Render via Portal to document.body - completely escapes parent containers
    return createPortal(content, document.body);
};
