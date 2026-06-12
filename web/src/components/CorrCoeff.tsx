/**
 * CorrCoeff.tsx — Pearson r badge with a plain-language strength label.
 *
 * Shows the correlation coefficient, colour-coded by sign and strength, plus the
 * best-lag hint from the API. Keeps the interpretation honest: a null r (too few
 * aligned points or a flat series) is shown as "—", not a fake number.
 */

interface Props {
  r: number | null
  n: number
  bestLag: number
  bestLagR: number | null
}

/** Plain-language strength bucket for |r|. */
function strength(r: number): string {
  const a = Math.abs(r)
  if (a >= 0.8) return 'very strong'
  if (a >= 0.6) return 'strong'
  if (a >= 0.4) return 'moderate'
  if (a >= 0.2) return 'weak'
  return 'negligible'
}

function colorFor(r: number | null): string {
  if (r === null) return '#8892a4'
  // Green for positive, red for negative; intensity tracks magnitude.
  return r >= 0 ? '#2f9e44' : '#e03131'
}

export default function CorrCoeff({ r, n, bestLag, bestLagR }: Props) {
  return (
    <div className="corr-coeff">
      <div className="corr-coeff__value" style={{ color: colorFor(r) }}>
        {r === null ? '—' : (r >= 0 ? '+' : '') + r.toFixed(2)}
      </div>
      <div className="corr-coeff__meta">
        <span className="corr-coeff__label">Pearson r</span>
        <span className="corr-coeff__strength">
          {r === null ? `not enough overlap (n=${n})` : `${strength(r)} · n=${n}`}
        </span>
        {r !== null && bestLag !== 0 && bestLagR !== null && (
          <span className="corr-coeff__lag">
            best at lag {bestLag > 0 ? `+${bestLag}` : bestLag} (r={bestLagR.toFixed(2)})
          </span>
        )}
      </div>
    </div>
  )
}
