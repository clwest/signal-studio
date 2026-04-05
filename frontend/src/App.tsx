import { useState, useEffect } from 'react'
import { Activity, Zap, TrendingUp, Shield, Briefcase, ChevronRight, ArrowLeft, Star, ExternalLink, CheckCircle, Clock, BarChart3 } from 'lucide-react'
import './App.css'

const API = 'http://localhost:8080/api'

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
  categories: Record<string, number>; avg_confidence: number
  evidence_cards_total: number; action_cards_total: number
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
  const [stats, setStats] = useState<Stats | null>(null)
  const [selectedSignal, setSelectedSignal] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch(`${API}/signals?category=${categoryFilter}`).then(r => r.json()),
      fetch(`${API}/stats`).then(r => r.json()),
    ]).then(([sigData, statsData]) => {
      setSignals(sigData.signals || [])
      setStats(statsData)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [categoryFilter])

  if (selectedSignal) {
    return (
      <div className="min-h-screen bg-gray-950 p-6">
        <SignalDetail signalId={selectedSignal} onBack={() => setSelectedSignal(null)} />
      </div>
    )
  }

  const categories = ['all', 'tech', 'business', 'crypto', 'career', 'security']

  return (
    <div className="min-h-screen bg-gray-950 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Activity className="text-blue-400" size={24} />
              SignalStudio
            </h1>
            <p className="text-gray-500 text-sm mt-1">Real-time opportunity intelligence</p>
          </div>
          {stats && (
            <div className="flex items-center gap-4 text-xs text-gray-500">
              <span className="flex items-center gap-1"><Activity size={12} className="text-green-400" /> {stats.active_signals} active</span>
              <span className="flex items-center gap-1"><Star size={12} className="text-blue-400" /> {stats.evidence_cards_total} evidence</span>
              <span className="flex items-center gap-1"><BarChart3 size={12} className="text-purple-400" /> {Math.round(stats.avg_confidence * 100)}% confidence</span>
            </div>
          )}
        </div>

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

        {loading ? (
          <div className="flex items-center justify-center h-64 text-gray-500">
            <Clock className="animate-spin mr-2" size={16} /> Loading signals...
          </div>
        ) : signals.length === 0 ? (
          <div className="text-center p-12 text-gray-600">No signals found. Run the seed script to populate demo data.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {signals.map(signal => (
              <SignalCard key={signal.id} signal={signal} onClick={() => setSelectedSignal(signal.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
