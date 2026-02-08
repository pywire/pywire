import type { SuccessCriteria } from './types'

export interface ValidationResult {
  passed: boolean
  description?: string
}

export class SuccessValidator {
  /**
   * Validates a set of success criteria against the current state.
   * @returns Array of validation results corresponding to the criteria order
   */
  static validate(
    files: Record<string, string>,
    criteria: SuccessCriteria[],
    browserHtml?: string,
  ): ValidationResult[] {
    if (!criteria || criteria.length === 0) return []

    return criteria.map((criterion) => {
      try {
        let passed = false
        switch (criterion.type) {
          case 'file_exists': {
            passed = criterion.target ? files[criterion.target] !== undefined : false
            break
          }

          case 'file_contains': {
            const content = files[criterion.target || '']
            passed = content?.includes(criterion.pattern || '') ?? false
            break
          }

          case 'browser_route_text': {
            // For now, simpler: check current browserHtml for pattern
            // (Full implementation would need to fetch specific routes)
            passed = browserHtml?.includes(criterion.pattern || '') ?? false
            break
          }

          case 'browser_element': {
            if (browserHtml && criterion.target) {
              const parser = new DOMParser()
              const doc = parser.parseFromString(browserHtml, 'text/html')
              passed = doc.querySelector(criterion.target) !== null
            }
            break
          }

          default:
            passed = false
        }

        return {
          passed,
          description: criterion.description,
        }
      } catch (e) {
        console.warn('Validation error:', e)
        return { passed: false, description: criterion.description }
      }
    })
  }
}
