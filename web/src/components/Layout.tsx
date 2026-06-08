/**
 * Layout.tsx — app shell with top nav + tab bar.
 *
 * Three-panel layout on wide viewports (≥1024px):
 *   Left sidebar (280px) — controls injected by child panels
 *   Centre          — main content
 *   Right panel (320px) — secondary info
 *
 * On narrow viewports (< 768px) collapses to single column.
 * The tab bar and header are always full-width.
 */

import type { ReactNode } from 'react'
import './Layout.css'

type Tab = { id: string; label: string }

interface Props {
  tabs: Tab[]
  activeTab: string
  onTabChange: (id: string) => void
  children: ReactNode
}

export default function Layout({ tabs, activeTab, onTabChange, children }: Props) {
  return (
    <div className="layout">
      <header className="layout__header">
        <div className="layout__brand">
          <span className="layout__brand-flag">🇮🇳</span>
          <span className="layout__brand-name">India FinData</span>
          <span className="layout__brand-sub">Macro · Markets · Analytics</span>
        </div>
      </header>

      <nav className="layout__tabs">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`layout__tab ${activeTab === tab.id ? 'layout__tab--active' : ''}`}
            onClick={() => onTabChange(tab.id)}
            aria-selected={activeTab === tab.id}
            role="tab"
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="layout__content">
        {children}
      </main>
    </div>
  )
}
