import { describe, it, expect, beforeEach } from 'vitest'
import { DOMUpdater } from './dom-updater'

// Uses the REAL morphdom (no mock) to verify the design claim: `data-pw-pending`
// never exists in server HTML, so the arriving patch strips it — and a wrongly
// predicted class auto-reverts because the server HTML lacks it. The morph is the
// only reconciler on the success path.
describe('DOMUpdater — optimistic reconciliation via morphdom', () => {
  let updater: DOMUpdater

  const pendingButton =
    '<button id="btn" data-on-click="doIt" ' +
    'data-modifiers-click="optimistic optimistic-class-done" ' +
    'data-pw-pending="" data-pw-pending-disabled="" class="done" disabled>Go</button>'

  beforeEach(() => {
    updater = new DOMUpdater()
    document.body.innerHTML = `<div data-pw-region="r1">${pendingButton}</div>`
  })

  it('strips pending markers and reverts a wrong prediction (server lacks the class)', () => {
    const before = document.getElementById('btn') as HTMLButtonElement
    expect(before.hasAttribute('data-pw-pending')).toBe(true)
    expect(before.classList.contains('done')).toBe(true)

    updater.updateRegion(
      'r1',
      '<div data-pw-region="r1"><button id="btn" data-on-click="doIt" ' +
        'data-modifiers-click="optimistic optimistic-class-done">Go</button></div>'
    )

    const after = document.getElementById('btn') as HTMLButtonElement
    expect(after.hasAttribute('data-pw-pending')).toBe(false)
    expect(after.hasAttribute('data-pw-pending-disabled')).toBe(false)
    expect(after.disabled).toBe(false)
    expect(after.classList.contains('done')).toBe(false)
  })

  it('keeps a correct prediction when the server HTML carries the class', () => {
    updater.updateRegion(
      'r1',
      '<div data-pw-region="r1"><button id="btn" class="done" data-on-click="doIt" ' +
        'data-modifiers-click="optimistic optimistic-class-done">Go</button></div>'
    )

    const after = document.getElementById('btn') as HTMLButtonElement
    expect(after.hasAttribute('data-pw-pending')).toBe(false)
    expect(after.classList.contains('done')).toBe(true)
  })
})
