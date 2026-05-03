import React from 'react'

export const LoadingSpinner: React.FC<{ message?: string }> = ({ message }) => {
  return (
    <div className="pw-spinner-container">
      <div className="pw-spinner-wire" aria-label="Loading" role="status">
        <svg width="56" height="56" viewBox="0 0 56 56" className="pw-spinner-svg" aria-hidden="true">
          {/* Faint track ring */}
          <circle cx="28" cy="28" r="22" fill="none" stroke="currentColor" strokeOpacity="0.18" strokeWidth="2.5" />
          {/* Active arc — currentColor inherits from --pw-accent */}
          <circle
            cx="28"
            cy="28"
            r="22"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeDasharray="34 110"
            strokeLinecap="round"
          />
        </svg>
      </div>
      {message && <p className="pw-spinner-message">{message}</p>}
    </div>
  )
}
