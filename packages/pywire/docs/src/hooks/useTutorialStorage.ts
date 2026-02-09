import { useState, useEffect, useCallback } from 'react'
import type { TutorialFile } from '../components/tutorial/types'

export function useTutorialStorage(stepId: string, initialFiles: TutorialFile[]) {
  const storageKey = `pywire-tutorial-files-${stepId}`

  const [files, setFiles] = useState<Record<string, string>>(() => {
    if (typeof window === 'undefined') {
      return Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent]))
    }
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) {
        const parsed = JSON.parse(saved)
        // Merge with initial files to ensure new files in the step are present
        const merged = {
          ...Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent])),
          ...parsed,
        }
        return merged
      }
    } catch (e) {
      console.warn('Failed to load from localStorage', e)
    }
    return Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent]))
  })

  // Reset files when stepId changes
  useEffect(() => {
    if (typeof window === 'undefined') return

    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) {
        const parsed = JSON.parse(saved)
        const merged = {
          ...Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent])),
          ...parsed,
        }
        setFiles(merged)
        return
      }
    } catch (e) {
      console.warn('Failed to load from localStorage', e)
    }

    setFiles(Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent])))
  }, [stepId, initialFiles, storageKey])

  // Update localStorage when files change
  useEffect(() => {
    if (typeof window === 'undefined') return

    const handler = setTimeout(() => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(files))
      } catch (e) {
        console.warn('Failed to save to localStorage', e)
      }
    }, 1000) // 1s debounce

    return () => clearTimeout(handler)
  }, [files, storageKey])

  const updateFile = useCallback((path: string, content: string) => {
    setFiles((prev) => ({ ...prev, [path]: content }))
  }, [])

  const addFile = useCallback((path: string, content: string = '') => {
    setFiles((prev) => ({ ...prev, [path]: content }))
  }, [])

  const deleteFile = useCallback((path: string) => {
    setFiles((prev) => {
      const newFiles = { ...prev }
      delete newFiles[path]
      return newFiles
    })
  }, [])

  const resetFiles = useCallback(() => {
    const reset = Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent]))
    setFiles(reset)
  }, [initialFiles])

  const resetAll = useCallback(() => {
    if (typeof window === 'undefined') return
    const keysToRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && (key.startsWith('pywire-tutorial-files-') || key === 'tutorial-current-slug')) {
        keysToRemove.push(key)
      }
    }
    keysToRemove.forEach((key) => localStorage.removeItem(key))
    // Also reset current files state
    const reset = Object.fromEntries(initialFiles.map((f) => [f.path, f.initialContent]))
    setFiles(reset)
  }, [initialFiles])

  const solveFiles = useCallback(() => {
    const solved = Object.fromEntries(
      initialFiles.map((f) => [
        f.path,
        f.solutionContent !== undefined ? f.solutionContent : f.initialContent,
      ]),
    )
    setFiles(solved)
  }, [initialFiles])

  return {
    files,
    updateFile,
    addFile,
    deleteFile,
    resetFiles,
    resetAll,
    solveFiles,
  }
}
