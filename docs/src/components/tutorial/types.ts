export interface TutorialFile {
    path: string;           // e.g. "index.wire", "components/button.wire"
    initialContent: string; // Starting content
    solutionContent?: string; // Expected solution (for "solve" button)
    editable?: boolean;     // Default true. Set false for read-only files
    deletable?: boolean;    // Can user delete this file? Default false
}

export interface AllowedBehavior {
    /**
     * Map of path patterns where files can be added.
     * Parent folder shows "+" button; new files must match the pattern.
     * Uses glob syntax: "components/*.wire", "pages/about.wire" (exact)
     * If the user tries to add a file that doesn't match, a modal error is shown.
     */
    canAddFiles?: Record<string, true>;  // e.g. { "components/*.wire": true }
    canDeleteFiles?: string[];           // Glob patterns of deletable files
    restrictedPaths?: string[];          // Protected paths user can't modify
}

export interface SuccessCriteria {
    type: 'file_exists' | 'file_contains' | 'browser_route_text' | 'browser_element' | 'custom';
    target?: string;        // File path or CSS selector
    pattern?: string;       // Content to match
    route?: string;         // For browser_route_text
    description?: string;   // Human-readable explanation shown on success
}

export interface TutorialStep {
    slug: string;
    title: string;
    tutorial?: string;
    section?: string;
    description?: string;
    content: string;                 // Markdown body
    files: TutorialFile[];           // Full file definitions
    behaviors?: AllowedBehavior;     // What the user can do
    successCriteria?: SuccessCriteria[]; // When is the step complete?
    hints?: string[];                // Optional progressive hints
    initialRoute?: string;           // Start browser on this path (default /)
    pagesDir?: string;               // e.g., "pages" - files here are served as routes
}

export interface TutorialData {
    steps: TutorialStep[];
}
