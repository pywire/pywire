import React from 'react'

export const LoadingSpinner: React.FC<{ message?: string }> = ({ message }) => {
  return (
    <div className="pw-spinner-container">
      <div style={{ position: 'relative', width: '80px', height: '80px' }}>
        <svg width="80" height="80" viewBox="0 0 80 80" className="pw-spinner-svg">
          {/* Outer circle */}
          <circle
            cx="40"
            cy="40"
            r="36"
            fill="none"
            stroke="rgba(34, 211, 238, 0.1)"
            strokeWidth="4"
          />
          <circle
            cx="40"
            cy="40"
            r="36"
            fill="none"
            stroke="#22d3ee"
            strokeWidth="4"
            strokeDasharray="50 150"
            strokeLinecap="round"
          />

          {/* Inner circle - counter-rotating */}
          <g className="pw-spinner-inner">
            <circle
              cx="40"
              cy="40"
              r="24"
              fill="none"
              stroke="rgba(59, 130, 246, 0.1)"
              strokeWidth="4"
            />
            <circle
              cx="40"
              cy="40"
              r="24"
              fill="none"
              stroke="#3b82f6"
              strokeWidth="4"
              strokeDasharray="40 120"
              strokeLinecap="round"
            />
          </g>
        </svg>
      </div>
      {message && <p className="pw-spinner-message">{message}</p>}
    </div>
  )
}
