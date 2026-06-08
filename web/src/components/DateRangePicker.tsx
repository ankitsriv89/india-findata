/**
 * DateRangePicker.tsx — preset buttons + custom date inputs.
 *
 * Presets: 1Y | 3Y | 5Y | 10Y
 * Custom: type-in date inputs (ISO format YYYY-MM-DD)
 */

import { yearsAgo, today } from '../api/hooks'
import './DateRangePicker.css'

interface Props {
  from: string
  to: string
  onFromChange: (v: string) => void
  onToChange: (v: string) => void
}

const PRESETS = [
  { label: '1Y', years: 1 },
  { label: '3Y', years: 3 },
  { label: '5Y', years: 5 },
  { label: '10Y', years: 10 },
]

export default function DateRangePicker({ from, to, onFromChange, onToChange }: Props) {
  function applyPreset(years: number) {
    onFromChange(yearsAgo(years))
    onToChange(today())
  }

  return (
    <div className="drp">
      <div className="drp__presets">
        {PRESETS.map(p => (
          <button
            key={p.label}
            className="drp__preset"
            onClick={() => applyPreset(p.years)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="drp__inputs">
        <input
          type="date"
          className="drp__input"
          value={from}
          onChange={e => onFromChange(e.target.value)}
          aria-label="From date"
        />
        <span className="drp__sep">→</span>
        <input
          type="date"
          className="drp__input"
          value={to}
          onChange={e => onToChange(e.target.value)}
          aria-label="To date"
        />
      </div>
    </div>
  )
}
