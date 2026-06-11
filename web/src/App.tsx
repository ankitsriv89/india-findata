/**
 * App.tsx — root component with tab navigation.
 *
 * Four tabs: Macro | Markets | Correlation | Pipeline
 * Active tab is stored in the URL hash so links are shareable.
 * Phase 1 implements Macro + Pipeline; Markets and Correlation show
 * a "coming soon" placeholder.
 */

import { useState, useEffect } from 'react'
import Layout from './components/Layout'
import MacroPanel from './components/MacroPanel'
import PipelinePanel from './components/PipelinePanel'
import './styles/app.css'

type Tab = 'macro' | 'markets' | 'correlation' | 'pipeline'

const TABS: { id: Tab; label: string }[] = [
  { id: 'macro',       label: 'Macro' },
  { id: 'markets',     label: 'Markets' },
  { id: 'correlation', label: 'Correlation' },
  { id: 'pipeline',    label: 'Pipeline' },
]

function readTabFromHash(): Tab {
  const hash = window.location.hash.slice(1) as Tab
  return TABS.some(t => t.id === hash) ? hash : 'macro'
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>(readTabFromHash)

  // Keep URL hash in sync with active tab so links are shareable
  useEffect(() => {
    window.location.hash = activeTab
  }, [activeTab])

  // Handle browser back/forward navigation
  useEffect(() => {
    const onHash = () => setActiveTab(readTabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <Layout tabs={TABS} activeTab={activeTab} onTabChange={(id) => setActiveTab(id as Tab)}>
      {activeTab === 'macro'       && <MacroPanel />}
      {activeTab === 'markets'     && <ComingSoon label="Markets" note="Phase 2 — NSE/BSE bhavcopy, FII/DII flows" />}
      {activeTab === 'correlation' && <ComingSoon label="Correlation" note="Phase 4 — cross-domain correlation explorer" />}
      {activeTab === 'pipeline'    && <PipelinePanel />}
    </Layout>
  )
}

function ComingSoon({ label, note }: { label: string; note: string }) {
  return (
    <div className="coming-soon">
      <h2>{label}</h2>
      <p>{note}</p>
    </div>
  )
}
