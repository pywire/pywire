import { useState, useEffect } from 'react';

export function useTutorialStorage(stepId: string, initialCode: string) {
    const storageKey = `pywire-tutorial-${stepId}`;

    // Initialize state with value from localStorage or initialCode
    const [code, setCode] = useState(() => {
        if (typeof window === 'undefined') return initialCode;
        try {
            const saved = localStorage.getItem(storageKey);
            return saved !== null ? saved : initialCode;
        } catch (e) {
            console.warn('Failed to load from localStorage', e);
            return initialCode;
        }
    });

    // Update localStorage when code changes
    useEffect(() => {
        if (typeof window === 'undefined') return;

        const handler = setTimeout(() => {
            try {
                localStorage.setItem(storageKey, code);
            } catch (e) {
                console.warn('Failed to save to localStorage', e);
            }
        }, 1000); // 1s debounce

        return () => clearTimeout(handler);
    }, [code, storageKey]);

    // Handle cross-tab updates (optional but good)
    useEffect(() => {
        const handleStorageChange = (e: StorageEvent) => {
            if (e.key === storageKey && e.newValue !== null) {
                setCode(e.newValue);
            }
        };
        window.addEventListener('storage', handleStorageChange);
        return () => window.removeEventListener('storage', handleStorageChange);
    }, [storageKey]);

    return [code, setCode] as const;
}
