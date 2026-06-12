/**
 * App.tsx — root component with tab navigation.
 *
 * Five tabs: Macro | Markets | Banking | Correlation | Pipeline
 * Active tab is stored in the URL hash so links are shareable.
 * All tabs render real panels (Phases 1–4); charts show empty-states
 * until their pipeline source loads data.
 */

import { useState, useEffect } from 'react'
import Layout from './components/Layout'
import MacroPanel from './components/MacroPanel'
import MarketsPanel from './components/MarketsPanel'
import BankingPanel from './components/BankingPanel'
import CorrelationPanel from './components/CorrelationPanel'
import PipelinePanel from './components/PipelinePanel'
import './styles/app.css'

type Tab = 'macro' | 'markets' | 'banking' | 'correlation' | 'pipeline'

const TABS: { id: Tab; label: string }[] = [
  { id: 'macro',       label: 'Macro' },
  { id: 'markets',     label: 'Markets' },
  { id: 'banking',     label: 'Banking' },
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
      {activeTab === 'markets'     && <MarketsPanel />}
      {activeTab === 'banking'     && <BankingPanel />}
      {activeTab === 'correlation' && <CorrelationPanel />}
      {activeTab === 'pipeline'    && <PipelinePanel />}
    </Layout>
  )
}
