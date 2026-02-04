export interface TutorialStep {
    slug: string;
    title: string;
    description?: string;
    initialCode: string;
    files: string[];
    content: string; // markdown body
}

export interface TutorialData {
    steps: TutorialStep[];
}
