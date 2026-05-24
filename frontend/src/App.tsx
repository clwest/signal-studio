import { useState, useEffect } from 'react'
import { Activity, Zap, TrendingUp, Shield, Briefcase, ChevronRight, ArrowLeft, Star, ExternalLink, CheckCircle, Clock, BarChart3, Bell, X } from 'lucide-react'
import './App.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8003/api'

const CATEGORY_CONFIG: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  tech: { icon: <Zap size={14} />, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
  business: { icon: <TrendingUp size={14} />, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
  crypto: { icon: <Activity size={14} />, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
  career: { icon: <Briefcase size={14} />, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' },
  security: { icon: <Shield size={14} />, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
  general: { icon: <BarChart3 size={14} />, color: 'text-gray-400', bg: 'bg-gray-500/10 border-gray-500/20' },
}

interface Signal {
  id: string; title: string; summary: string; category: string
  confidence_score: number; source_count: number; signal_strength: number
  status: string; tags: string[]; created_at: string
  evidence_count: number; has_action: boolean
}

interface EvidenceCard {
  id: string; claim_text: string; excerpt: string; excerpt_is_quote: boolean
  source_title: string; source_domain: string; source_url: string
  confidence_score: number; citation_label: string; claim_type: string
}

interface SourceItem {
  id: string; title: string; url: string; domain: string
  snippet: string; spider_name: string; relevance_score: number
}

interface ActionCardData {
  id: string; title: string; steps: Array<{ step: string; priority: string }>
  action_type: string; status: string
}

interface Stats {
  total_signals: number; active_signals: number
  raw_pending?: number; rejected?: number
  categories: Record<string, number>; avg_confidence: number
  evidence_cards_total: number; action_cards_total: number
}

// Session 1131 Phase 2 — curated signals (SignalCuratorAgent top 10)
interface CuratedSignal {
  id: string; external_cluster_id: string | null
  rank: number; curated_score: number
  title: string; summary: string; category: string
  confidence_score: number; signal_strength: number
  source_count: number; tags: string[]
  created_at: string; evidence_count: number
}

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = pct >= 85 ? 'text-green-400 bg-green-500/10' : pct >= 70 ? 'text-blue-400 bg-blue-500/10' : pct >= 50 ? 'text-amber-400 bg-amber-500/10' : 'text-red-400 bg-red-500/10'
  return <span className={`text-xs font-mono px-2 py-0.5 rounded ${color}`}>{pct}%</span>
}

function SignalCard({ signal, onClick }: { signal: Signal; onClick: () => void }) {
  const cat = CATEGORY_CONFIG[signal.category] || CATEGORY_CONFIG.general
  return (
    <div onClick={onClick} className={`p-5 rounded-xl border ${cat.bg} hover:scale-[1.01] transition-all cursor-pointer group`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={cat.color}>{cat.icon}</span>
          <span className={`text-xs uppercase tracking-wide ${cat.color}`}>{signal.category}</span>
        </div>
        <ConfidenceBadge score={signal.confidence_score} />
      </div>
      <h3 className="text-white font-semibold text-sm leading-snug mb-2 group-hover:text-blue-300 transition-colors">
        {signal.title}
      </h3>
      <p className="text-gray-500 text-xs leading-relaxed mb-3">{signal.summary}</p>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-gray-600">
          <span className="flex items-center gap-1"><Star size={10} /> {signal.evidence_count} evidence</span>
          <span className="flex items-center gap-1"><ExternalLink size={10} /> {signal.source_count} sources</span>
        </div>
        <ChevronRight size={14} className="text-gray-600 group-hover:text-blue-400 transition-colors" />
      </div>
      {signal.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3">
          {signal.tags.slice(0, 4).map(tag => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800/50 text-gray-500">#{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function SignalDetail({ signalId, onBack }: { signalId: string; onBack: () => void }) {
  const [data, setData] = useState<{ signal: Signal; evidence_cards: EvidenceCard[]; sources: SourceItem[]; action_cards: ActionCardData[] } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`${API}/signals/${signalId}`).then(r => r.json()).then(d => { setData(d); setLoading(false) }).catch(() => setLoading(false))
  }, [signalId])

  if (loading) return <div className="flex items-center justify-center h-96 text-gray-500"><Clock className="animate-spin mr-2" size={16} /> Loading signal...</div>
  if (!data) return <div className="text-gray-500 text-center p-8">Signal not found</div>

  const { signal, evidence_cards, sources, action_cards } = data
  const cat = CATEGORY_CONFIG[signal.category] || CATEGORY_CONFIG.general

  return (
    <div className="max-w-4xl mx-auto">
      <button onClick={onBack} className="flex items-center gap-1 text-gray-500 hover:text-white mb-6 transition-colors text-sm">
        <ArrowLeft size={14} /> Back to signals
      </button>

      <div className={`p-6 rounded-xl border ${cat.bg} mb-6`}>
        <div className="flex items-center gap-2 mb-3">
          <span className={cat.color}>{cat.icon}</span>
          <span className={`text-xs uppercase tracking-wide ${cat.color}`}>{signal.category}</span>
          <ConfidenceBadge score={signal.confidence_score} />
          <span className="text-xs text-gray-600 ml-auto"><Clock size={10} className="inline mr-1" />{new Date(signal.created_at).toLocaleDateString()}</span>
        </div>
        <h1 className="text-xl font-bold text-white mb-3">{signal.title}</h1>
        <p className="text-gray-400 text-sm leading-relaxed">{signal.summary}</p>
        <div className="flex items-center gap-4 mt-4 text-xs text-gray-500">
          <span>{signal.source_count} sources</span>
          <span>{evidence_cards.length} evidence cards</span>
          <span>Signal strength: {Math.round(signal.signal_strength * 100)}%</span>
        </div>
      </div>

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-2">
          <Star size={14} /> Evidence Cards ({evidence_cards.length})
        </h2>
        <div className="space-y-3">
          {evidence_cards.map(card => (
            <div key={card.id} className="p-4 rounded-lg bg-gray-900/50 border border-gray-800 hover:border-gray-700 transition-colors">
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded">{card.citation_label}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    card.claim_type === 'statistic' ? 'bg-green-500/10 text-green-400' :
                    card.claim_type === 'quote' ? 'bg-purple-500/10 text-purple-400' :
                    card.claim_type === 'example' ? 'bg-amber-500/10 text-amber-400' :
                    'bg-gray-800 text-gray-500'
                  }`}>{card.claim_type}</span>
                </div>
                <ConfidenceBadge score={card.confidence_score} />
              </div>
              <p className="text-white text-sm font-medium mb-2">{card.claim_text}</p>
              <blockquote className="text-gray-400 text-xs italic border-l-2 border-gray-700 pl-3 mb-2">
                {card.excerpt_is_quote ? `"${card.excerpt}"` : card.excerpt}
              </blockquote>
              <a href={card.source_url} target="_blank" rel="noopener noreferrer"
                className="text-xs text-blue-500 hover:text-blue-400 flex items-center gap-1">
                <ExternalLink size={10} /> {card.source_title} — {card.source_domain}
              </a>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-2">
          <ExternalLink size={14} /> Sources ({sources.length})
        </h2>
        <div className="space-y-2">
          {sources.map(src => (
            <a key={src.id} href={src.url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-3 p-3 rounded-lg bg-gray-900/30 hover:bg-gray-900/60 transition-colors group">
              <div className="w-8 h-8 rounded bg-gray-800 flex items-center justify-center text-[10px] text-gray-500 font-mono">
                {src.domain.slice(0, 2).toUpperCase()}
              </div>
              <div className="flex-1">
                <div className="text-sm text-gray-300 group-hover:text-white transition-colors">{src.title}</div>
                <div className="text-xs text-gray-600">{src.domain}{src.spider_name ? ` via ${src.spider_name}` : ''}</div>
              </div>
              <ExternalLink size={12} className="text-gray-700 group-hover:text-blue-400 transition-colors" />
            </a>
          ))}
        </div>
      </div>

      {action_cards.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-2">
            <CheckCircle size={14} /> Action Plan
          </h2>
          {action_cards.map(ac => (
            <div key={ac.id} className="p-5 rounded-xl bg-gradient-to-br from-blue-950/40 to-purple-950/20 border border-blue-800/30">
              <h3 className="text-white font-semibold mb-3">{ac.title}</h3>
              <div className="space-y-2">
                {ac.steps.map((step, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded mt-0.5 ${
                      step.priority === 'high' ? 'bg-red-500/20 text-red-400' :
                      step.priority === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                      'bg-gray-800 text-gray-500'
                    }`}>{step.priority}</span>
                    <span className="text-sm text-gray-300">{step.step}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [signals, setSignals] = useState<Signal[]>([])
  const [curated, setCurated] = useState<CuratedSignal[]>([])
  const [curatedSnapshotId, setCuratedSnapshotId] = useState<string | null>(null)
  // Session 1132 (C) — SSE indicator. When a `curated:refreshed`
  // event lands while the user is on the Curated tab, this holds the
  // new snapshot_id; the UI shows a "🟢 New curated set — refresh"
  // pill the user can click to refetch.
  const [pendingSnapshotId, setPendingSnapshotId] = useState<string | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [selectedSignal, setSelectedSignal] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<'signals' | 'curated' | 'brain'>('signals')

  // Stable refetch helper so the SSE handler can call it without
  // chasing the useEffect dependency closure.
  const refetchCurated = () => {
    setLoading(true)
    fetch(`${API}/signals/curated`).then(r => r.json()).then(curData => {
      setCurated(curData.curated || [])
      setCuratedSnapshotId(curData.snapshot_id || null)
      setPendingSnapshotId(null)
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  useEffect(() => {
    if (view === 'brain') return
    setLoading(true)
    if (view === 'curated') {
      Promise.all([
        fetch(`${API}/signals/curated`).then(r => r.json()),
        fetch(`${API}/stats`).then(r => r.json()),
      ]).then(([curData, statsData]) => {
        setCurated(curData.curated || [])
        setCuratedSnapshotId(curData.snapshot_id || null)
        setPendingSnapshotId(null)
        setStats(statsData)
        setLoading(false)
      }).catch(() => setLoading(false))
    } else {
      Promise.all([
        fetch(`${API}/signals?category=${categoryFilter}`).then(r => r.json()),
        fetch(`${API}/stats`).then(r => r.json()),
      ]).then(([sigData, statsData]) => {
        setSignals(sigData.signals || [])
        setStats(statsData)
        setLoading(false)
      }).catch(() => setLoading(false))
    }
  }, [categoryFilter, view])

  // Session 1132 (C) — SSE subscription only while the Curated tab
  // is the active view. Closes the connection when the user navigates
  // away so we don't burn server fanout on a hidden tab.
  useEffect(() => {
    if (view !== 'curated') return
    const es = new EventSource(`${API}/signals/events`)
    es.addEventListener('curated:refreshed', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        const newId = data?.snapshot_id
        if (!newId) return
        // If the user already has the latest, no-op. Otherwise stash
        // the new id and show the refresh pill.
        setCuratedSnapshotId(current => {
          if (current === newId) return current
          setPendingSnapshotId(newId)
          return current
        })
      } catch {
        // Malformed payload — ignore. The user can refresh manually.
      }
    })
    // Hello + keep-alive events arrive but we don't need to handle
    // them; EventSource auto-reconnects on network drops.
    return () => { es.close() }
  }, [view])

  if (selectedSignal) {
    return (
      <div className="min-h-screen bg-gray-950 p-6">
        <SignalDetail signalId={selectedSignal} onBack={() => setSelectedSignal(null)} />
      </div>
    )
  }

  if (view === 'brain') {
    return (
      <div className="min-h-screen bg-gray-950 p-6">
        <div className="max-w-3xl mx-auto">
          <button onClick={() => setView('signals')} className="flex items-center gap-1 text-gray-500 hover:text-white mb-6 transition-colors text-sm">
            <ArrowLeft size={14} /> Back to signals
          </button>
          <BrainPage />
        </div>
      </div>
    )
  }

  const categories = ['all', 'tech', 'business', 'crypto', 'career', 'security']

  return (
    <div className="min-h-screen bg-gray-950 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Activity className="text-blue-400" size={24} />
              SignalStudio
            </h1>
            <p className="text-gray-500 text-sm mt-1">Real-time opportunity intelligence</p>
            <button onClick={() => setView('brain')} className="mt-2 text-xs text-blue-400 hover:text-blue-300 transition">→ Ask Rigby (u-d-b PA)</button>
          </div>
          {stats && (
            <div className="flex items-center gap-4 text-xs text-gray-500">
              <span className="flex items-center gap-1"><Activity size={12} className="text-green-400" /> {stats.active_signals} insight-grade</span>
              <span className="flex items-center gap-1"><Star size={12} className="text-blue-400" /> {stats.evidence_cards_total} evidence</span>
              <span className="flex items-center gap-1"><BarChart3 size={12} className="text-purple-400" /> {Math.round(stats.avg_confidence * 100)}% confidence</span>
            </div>
          )}
        </div>

        {/* Hero / value-prop block — explains what this is to a first-time visitor. */}
        <div className="mb-8 p-6 rounded-2xl bg-gradient-to-br from-blue-950/40 via-gray-900 to-purple-950/30 border border-blue-900/40">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="md:col-span-2 space-y-3">
              <h2 className="text-xl font-semibold text-white">
                What's actually happening across tech, finance, and the job market — in one place.
              </h2>
              <p className="text-sm text-gray-400 leading-relaxed">
                SignalStudio reads {stats?.evidence_cards_total ?? '600+'} headlines and articles a day across a fleet of feeds,
                clusters them by topic, and turns each cluster into one sentence you can act on.
                We hide noise; only insight-grade signals show below.
              </p>
              <div className="flex items-center gap-3 text-xs text-gray-500 pt-1">
                <span className="px-2 py-0.5 rounded bg-gray-800/60 border border-gray-700/50">demand spikes</span>
                <span className="px-2 py-0.5 rounded bg-gray-800/60 border border-gray-700/50">emerging trends</span>
                <span className="px-2 py-0.5 rounded bg-gray-800/60 border border-gray-700/50">opportunity windows</span>
                <span className="px-2 py-0.5 rounded bg-gray-800/60 border border-gray-700/50">sentiment shifts</span>
              </div>
            </div>
            <div className="bg-gray-950/50 rounded-xl p-4 border border-gray-800/50">
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">Today's pipeline</div>
              <div className="space-y-1.5 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Headlines processed</span>
                  <span className="text-white font-mono">{stats?.evidence_cards_total ?? '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Insight-grade signals</span>
                  <span className="text-emerald-400 font-mono">{stats?.active_signals ?? '—'}</span>
                </div>
                {typeof stats?.rejected === 'number' && (
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Filtered as noise</span>
                    <span className="text-gray-600 font-mono">{stats.rejected}</span>
                  </div>
                )}
                <div className="flex items-center justify-between pt-1.5 mt-1.5 border-t border-gray-800/50">
                  <span className="text-gray-400">Categories tracked</span>
                  <span className="text-white font-mono">{stats?.categories ? Object.keys(stats.categories).length : '—'}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Session 1131 Phase 2 — view toggle between All Signals + Curated Top 10 */}
        <div className="flex items-center gap-2 mb-4">
          <button onClick={() => setView('signals')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              view === 'signals' ? 'bg-blue-600 text-white' : 'bg-gray-900 text-gray-500 hover:text-gray-300 hover:bg-gray-800'
            }`}>
            All Signals
          </button>
          <button onClick={() => setView('curated')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${
              view === 'curated' ? 'bg-amber-600 text-white' : 'bg-gray-900 text-gray-500 hover:text-gray-300 hover:bg-gray-800'
            }`}>
            <Star size={12} /> Curated Top 10
          </button>
          {view === 'curated' && curatedSnapshotId && (
            <span className="text-xs text-gray-600 ml-2 font-mono">snapshot: {curatedSnapshotId.slice(0, 8)}</span>
          )}
          {view === 'curated' && pendingSnapshotId && pendingSnapshotId !== curatedSnapshotId && (
            <button
              onClick={refetchCurated}
              className="ml-3 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/30 transition-colors flex items-center gap-1.5"
              title={`New snapshot: ${pendingSnapshotId.slice(0, 8)}`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              New curated set — refresh
            </button>
          )}
        </div>

        {view === 'signals' && (
          <div className="flex items-center gap-2 mb-6">
            {categories.map(cat => {
              const config = CATEGORY_CONFIG[cat] || CATEGORY_CONFIG.general
              return (
                <button key={cat} onClick={() => setCategoryFilter(cat)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    categoryFilter === cat ? 'bg-blue-600 text-white' : 'bg-gray-900 text-gray-500 hover:text-gray-300 hover:bg-gray-800'
                  }`}>
                  {cat === 'all' ? 'All Signals' : <span className="flex items-center gap-1">{config.icon} {cat}</span>}
                </button>
              )
            })}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-64 text-gray-500">
            <Clock className="animate-spin mr-2" size={16} /> Loading {view === 'curated' ? 'curated set' : 'signals'}...
          </div>
        ) : view === 'curated' ? (
          curated.length === 0 ? (
            <div className="text-center p-12 text-gray-600">
              <div className="mb-2">No curated snapshot yet.</div>
              <div className="text-xs text-gray-700">
                SignalCuratorAgent runs daily at 6 AM MST. Once it fires,
                the top 10 curated signals appear here with rank + score.
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {curated.map(c => (
                <CuratedSignalCard
                  key={c.id}
                  signal={c}
                  onClick={() => setSelectedSignal(c.id)}
                />
              ))}
            </div>
          )
        ) : signals.length === 0 ? (
          <div className="text-center p-12 text-gray-600">
            <div className="mb-2">No insight-grade signals in this category yet.</div>
            <div className="text-xs text-gray-700">
              Backend pipeline is running. As new headlines cluster into coherent themes,
              they'll appear here. Try "All Signals" or come back tomorrow.
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {signals.map(signal => (
              <SignalCard key={signal.id} signal={signal} onClick={() => setSelectedSignal(signal.id)} />
            ))}
          </div>
        )}

        <PaidInterestForm />
      </div>
    </div>
  )
}


// Session 1131 Phase 2 — Curated card with rank badge + curated_score
function CuratedSignalCard({ signal, onClick }: { signal: CuratedSignal; onClick: () => void }) {
  const cat = CATEGORY_CONFIG[signal.category] || CATEGORY_CONFIG.general
  return (
    <div onClick={onClick} className={`relative p-5 rounded-xl border ${cat.bg} hover:scale-[1.01] transition-all cursor-pointer group`}>
      <div className="absolute -top-2 -left-2 w-8 h-8 rounded-full bg-amber-500 text-gray-950 font-bold text-sm flex items-center justify-center shadow-lg">
        {signal.rank}
      </div>
      <div className="flex items-start justify-between mb-3 ml-6">
        <div className="flex items-center gap-2">
          <span className={cat.color}>{cat.icon}</span>
          <span className={`text-xs uppercase tracking-wide ${cat.color}`}>{signal.category}</span>
        </div>
        <span className="text-xs font-mono text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded">
          score {signal.curated_score.toFixed(3)}
        </span>
      </div>
      <h3 className="text-white font-semibold text-sm leading-snug mb-2 group-hover:text-blue-300 transition-colors">
        {signal.title}
      </h3>
      <p className="text-gray-500 text-xs leading-relaxed mb-3">{signal.summary}</p>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-gray-600">
          <span className="flex items-center gap-1"><Star size={10} /> {signal.evidence_count} evidence</span>
          <span className="flex items-center gap-1"><ExternalLink size={10} /> {signal.source_count} sources</span>
        </div>
        <ChevronRight size={14} className="text-gray-600 group-hover:text-blue-400 transition-colors" />
      </div>
      {signal.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3">
          {signal.tags.slice(0, 4).map(tag => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800/50 text-gray-500">#{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Paid-interest form (Session 1138 — Decision 13 demand-gate) ───────────
// Honest claims per UDB_TRANSLATION_LAYER §2:
//   - "We'll email you when paid launches" (true)
//   - "We may reach out individually if your use case is interesting" (true)
//   - NO promise of a launch date, discount, or that paid will ever launch.

type FormState = 'collapsed' | 'expanded' | 'submitted'

function PaidInterestForm() {
  const dismissKey = 'signal-studio-paid-interest-dismissed-v1'
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try { return localStorage.getItem(dismissKey) === '1' } catch { return false }
  })
  const [state, setState] = useState<FormState>('collapsed')
  const [email, setEmail] = useState('')
  const [useCase, setUseCase] = useState('')
  const [willingPay, setWillingPay] = useState('')
  const [workspaceSize, setWorkspaceSize] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deduped, setDeduped] = useState(false)

  if (dismissed) return null

  function dismiss() {
    try { localStorage.setItem(dismissKey, '1') } catch { /* ignore */ }
    setDismissed(true)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!email.trim() || !useCase.trim()) {
      setError('email and use case are both required')
      return
    }
    if (useCase.length > 140) {
      setError('use case must be ≤140 characters')
      return
    }
    setSubmitting(true)
    try {
      const body: Record<string, unknown> = {
        email: email.trim(),
        use_case: useCase.trim(),
      }
      if (willingPay.trim()) {
        const n = parseInt(willingPay, 10)
        if (Number.isFinite(n) && n >= 0) body.willing_pay = n
      }
      if (workspaceSize) body.workspace_size = workspaceSize
      const r = await fetch(`${API}/paid-interest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!r.ok) {
        setError(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail || d))
      } else {
        setDeduped(Boolean(d.deduped))
        setState('submitted')
      }
    } catch (err: any) {
      setError(err.message || 'submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (state === 'collapsed') {
    return (
      <div className="mt-12 mb-6 p-4 rounded-xl bg-blue-950/30 border border-blue-900/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bell size={16} className="text-blue-400" />
          <div>
            <div className="text-sm text-white font-medium">Want a paid version of SignalStudio?</div>
            <div className="text-xs text-gray-500 mt-0.5">
              We're not paid yet. Tell us what you'd use it for — we'll email you if/when a paid tier launches.
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setState('expanded')}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors"
          >
            Notify me
          </button>
          <button
            onClick={dismiss}
            aria-label="Dismiss"
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800/50 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      </div>
    )
  }

  if (state === 'submitted') {
    return (
      <div className="mt-12 mb-6 p-5 rounded-xl bg-emerald-950/30 border border-emerald-900/40 flex items-center gap-3">
        <CheckCircle size={18} className="text-emerald-400 flex-shrink-0" />
        <div className="flex-1">
          <div className="text-sm text-white font-medium">
            {deduped ? 'Already captured.' : 'Got it.'}
          </div>
          <div className="text-xs text-gray-400 mt-0.5">
            We'll email you at the launch. No automated follow-ups before then.
          </div>
        </div>
        <button onClick={dismiss} aria-label="Dismiss"
          className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800/50 transition-colors">
          <X size={14} />
        </button>
      </div>
    )
  }

  // expanded
  return (
    <form onSubmit={submit} className="mt-12 mb-6 p-5 rounded-xl bg-blue-950/30 border border-blue-900/40 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell size={16} className="text-blue-400" />
          <h3 className="text-sm font-medium text-white">Notify me when SignalStudio paid launches</h3>
        </div>
        <button type="button" onClick={() => setState('collapsed')} aria-label="Cancel"
          className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800/50 transition-colors">
          <X size={14} />
        </button>
      </div>
      <p className="text-xs text-gray-500 leading-relaxed">
        We're pre-launch. No date promised, no early-access discount promised.
        This just tells us there's demand — and lets us email you if it ships.
      </p>
      <div className="space-y-2">
        <label className="block text-xs text-gray-400">Email <span className="text-red-400">*</span></label>
        <input
          type="email"
          required
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div className="space-y-2">
        <label className="block text-xs text-gray-400">
          What would you use it for? <span className="text-red-400">*</span>
          <span className="text-gray-600 ml-2">({useCase.length}/140)</span>
        </label>
        <input
          type="text"
          required
          maxLength={140}
          value={useCase}
          onChange={e => setUseCase(e.target.value)}
          placeholder="e.g. weekly intelligence brief for my fund's research team"
          className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <label className="block text-xs text-gray-400">
            Would-pay $/mo <span className="text-gray-600">(optional)</span>
          </label>
          <input
            type="number"
            min="0"
            value={willingPay}
            onChange={e => setWillingPay(e.target.value)}
            placeholder="49"
            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div className="space-y-2">
          <label className="block text-xs text-gray-400">
            Team size <span className="text-gray-600">(optional)</span>
          </label>
          <select
            value={workspaceSize}
            onChange={e => setWorkspaceSize(e.target.value)}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="">—</option>
            <option value="solo">Solo</option>
            <option value="2-5">2-5</option>
            <option value="6-20">6-20</option>
            <option value="20+">20+</option>
          </select>
        </div>
      </div>
      {error && (
        <div className="p-2 rounded-lg bg-red-900/30 border border-red-700/50 text-red-200 text-xs">
          {error}
        </div>
      )}
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={() => setState('collapsed')}
          className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting || !email.trim() || !useCase.trim()}
          className="px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
        >
          {submitting ? 'Submitting…' : 'Notify me at launch'}
        </button>
      </div>
    </form>
  )
}


// ── Brain bridge page ─────────────────────────────────────────────────────
function BrainPage() {
  const [message, setMessage] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [traceId, setTraceId] = useState<string | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function ask() {
    if (!message.trim()) return
    setLoading(true); setAnswer(null); setError(null); setTraceId(null); setLatency(null)
    try {
      const r = await fetch(`${API}/brain/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })
      const d = await r.json()
      if (!r.ok) setError(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail || d))
      else { setAnswer(d.answer || '(no answer field returned)'); setTraceId(d.trace_id || null); setLatency(d.latency_ms ?? null) }
    } catch (e: any) { setError(e.message || 'request failed') }
    finally { setLoading(false) }
  }

  return (
    <div>
      <h1 className="text-3xl font-bold text-white mb-2">Brain</h1>
      <p className="text-gray-400 mb-6">
        Ask Rigby (the u-d-b Personal Assistant) anything. SignalStudio proxies your question through the fleet brain bridge.
      </p>
      <textarea value={message} onChange={e => setMessage(e.target.value)}
        placeholder="Ask anything — Rigby has u-d-b's full agent network behind her."
        className="w-full h-32 px-4 py-3 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 resize-none focus:border-blue-500 focus:outline-none" />
      <button onClick={ask} disabled={loading || !message.trim()}
        className="mt-3 px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg text-white font-medium transition">
        {loading ? 'Thinking...' : 'Ask Rigby'}
      </button>
      {error && <div className="mt-6 p-4 rounded-lg bg-red-900/30 border border-red-700/50 text-red-200 text-sm whitespace-pre-wrap"><div className="font-medium text-red-300 mb-1">Brain unreachable</div>{error}</div>}
      {answer && (
        <div className="mt-6">
          <div className="p-4 rounded-lg bg-gray-900 border border-gray-800 text-gray-100 whitespace-pre-wrap">{answer}</div>
          {(traceId || latency !== null) && (
            <div className="mt-2 text-xs text-gray-500 flex gap-4">
              {traceId && <span>trace: {traceId}</span>}
              {latency !== null && <span>latency: {latency}ms</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
