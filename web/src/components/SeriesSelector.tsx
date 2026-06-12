/**
 * SeriesSelector.tsx — dropdown for picking a (source, series) pair.
 *
 * The correlation explorer needs to choose two arbitrary series from across the
 * macro/markets/banking layers. Rather than fetch a dynamic catalogue, we list
 * the known series here — a small, curated set is clearer for an explorer UI and
 * avoids an extra endpoint. Each option carries both the `source` and `series`
 * the API needs, plus a human label.
 */

export interface SeriesOption {
  label: string
  source: string
  series: string
}

/** The series available to correlate (one per known source+series pair). */
export const SERIES_CATALOGUE: SeriesOption[] = [
  { label: 'CPI — General (inflation)', source: 'mospi_cpi', series: 'CPI_GENERAL' },
  { label: 'CPI — Food', source: 'mospi_cpi', series: 'CPI_FOOD' },
  { label: 'IIP — General', source: 'mospi_iip', series: 'IIP_GENERAL' },
  { label: 'GDP growth (YoY)', source: 'mospi_gdp', series: 'GDP_GROWTH_RATE' },
  { label: 'Repo rate', source: 'rbi_rates', series: 'REPO_RATE' },
  { label: 'Forex reserves', source: 'rbi_dbie', series: 'FOREX_RESERVES' },
  { label: 'M3 broad money', source: 'rbi_dbie', series: 'M3_MONEY_SUPPLY' },
  { label: 'Bank credit growth', source: 'rbi_dbie', series: 'BANK_CREDIT_GROWTH' },
  { label: 'Gross NPA ratio', source: 'rbi_dbie', series: 'GROSS_NPA_RATIO' },
  { label: 'FII net equity flow', source: 'fii_dii', series: 'FII_NET_EQUITY' },
  { label: 'DII net equity flow', source: 'fii_dii', series: 'DII_NET_EQUITY' },
]

interface Props {
  id: string
  label: string
  value: SeriesOption
  onChange: (opt: SeriesOption) => void
}

export default function SeriesSelector({ id, label, value, onChange }: Props) {
  return (
    <div className="series-selector">
      <label htmlFor={id} className="series-selector__label">
        {label}
      </label>
      <select
        id={id}
        className="series-selector__select"
        value={`${value.source}|${value.series}`}
        onChange={e => {
          const [source, series] = e.target.value.split('|')
          const opt = SERIES_CATALOGUE.find(o => o.source === source && o.series === series)
          if (opt) onChange(opt)
        }}
      >
        {SERIES_CATALOGUE.map(o => (
          <option key={`${o.source}|${o.series}`} value={`${o.source}|${o.series}`}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
