"""Seed database with realistic demo data for SignalStudio."""

import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import SignalCluster, EvidenceCard, SourceItem, ActionCard, init_db, get_engine

DEMO_CLUSTERS = [
    {
        "title": "AI Agent Frameworks Hitting Production — Enterprise Adoption Accelerating",
        "summary": "Multiple signals indicate enterprise teams are moving from AI agent POCs to production deployments. LangChain, CrewAI, and AutoGen seeing 3x GitHub stars growth. Fortune 500 companies reporting 40% cost reduction in customer service operations.",
        "category": "tech",
        "confidence_score": 0.89,
        "source_count": 12,
        "signal_strength": 0.92,
        "tags": ["ai-agents", "enterprise", "production", "langchain"],
        "evidence": [
            {"claim": "Enterprise AI agent adoption grew 340% in Q1 2026", "excerpt": "According to Gartner's latest survey, enterprise adoption of AI agent frameworks grew 340% year-over-year in Q1 2026, with LangChain and CrewAI leading deployment counts.", "source_title": "Gartner AI Agent Report Q1 2026", "domain": "gartner.com", "url": "https://gartner.com/ai-agents-2026", "confidence": 0.92, "type": "statistic"},
            {"claim": "Fortune 500 companies report 40% cost reduction using AI agents in customer service", "excerpt": "\"We replaced 60% of our tier-1 support with agent workflows and saw a 40% reduction in operational costs within 90 days,\" said the VP of Operations at a Fortune 100 retailer.", "source_title": "Forbes — AI Agents in Enterprise", "domain": "forbes.com", "url": "https://forbes.com/ai-agents-enterprise-2026", "confidence": 0.85, "type": "quote"},
            {"claim": "LangChain GitHub stars crossed 100K, up 3x from 2025", "excerpt": "The LangChain repository hit 100,000 GitHub stars in March 2026, tripling its star count from the same period in 2025.", "source_title": "GitHub Trending Report", "domain": "github.com", "url": "https://github.com/trending/python", "confidence": 0.95, "type": "statistic"},
        ],
        "sources": [
            {"title": "Gartner AI Agent Report Q1 2026", "url": "https://gartner.com/ai-agents-2026", "domain": "gartner.com", "spider": "techcrunch"},
            {"title": "Forbes — AI Agents in Enterprise", "url": "https://forbes.com/ai-agents-enterprise-2026", "domain": "forbes.com", "spider": "business_news"},
            {"title": "GitHub Trending Report", "url": "https://github.com/trending/python", "domain": "github.com", "spider": "github"},
            {"title": "HackerNews Discussion: AI Agents in Prod", "url": "https://news.ycombinator.com/item?id=39847", "domain": "news.ycombinator.com", "spider": "hackernews"},
        ],
        "action": {
            "title": "Evaluate AI Agent Framework for Internal Ops",
            "type": "build",
            "steps": [
                {"step": "Audit current manual workflows for agent automation candidates", "priority": "high"},
                {"step": "Run a 2-week POC with LangChain or CrewAI on top support ticket category", "priority": "high"},
                {"step": "Measure: tickets resolved, time-to-resolution, customer satisfaction delta", "priority": "medium"},
                {"step": "Build business case: projected cost savings at 40% reduction target", "priority": "medium"},
                {"step": "Present findings to leadership with 90-day rollout plan", "priority": "low"},
            ],
        },
    },
    {
        "title": "Remote-First Companies Outperforming Hybrid by 23% in Revenue Growth",
        "summary": "New data from multiple sources shows fully remote companies are growing faster than hybrid counterparts. Key factors: lower overhead, wider talent pools, and async-first culture enabling 24/7 operations.",
        "category": "business",
        "confidence_score": 0.78,
        "source_count": 8,
        "signal_strength": 0.81,
        "tags": ["remote-work", "revenue-growth", "hiring", "async"],
        "evidence": [
            {"claim": "Remote-first companies grew revenue 23% faster than hybrid in 2025", "excerpt": "A study of 2,400 companies found that fully remote organizations grew revenue 23% faster than their hybrid counterparts, with the gap widening in tech and professional services.", "source_title": "Owl Labs State of Remote Work 2026", "domain": "owllabs.com", "url": "https://owllabs.com/state-of-remote-work-2026", "confidence": 0.82, "type": "statistic"},
            {"claim": "Remote companies save $11,000 per employee annually on overhead", "excerpt": "The average remote-first company saves $11,000 per employee per year on office space, utilities, and related overhead costs.", "source_title": "Buffer Remote Work Report", "domain": "buffer.com", "url": "https://buffer.com/remote-work-2026", "confidence": 0.75, "type": "statistic"},
            {"claim": "Async-first teams complete 31% more projects per quarter", "excerpt": "Teams that adopted async-first communication completed 31% more projects per quarter compared to synchronous-heavy teams, according to Doist's productivity research.", "source_title": "Doist Async Work Study", "domain": "doist.com", "url": "https://doist.com/async-study-2026", "confidence": 0.71, "type": "statistic"},
        ],
        "sources": [
            {"title": "Owl Labs State of Remote Work 2026", "url": "https://owllabs.com/state-of-remote-work-2026", "domain": "owllabs.com", "spider": "business_news"},
            {"title": "Buffer Remote Work Report", "url": "https://buffer.com/remote-work-2026", "domain": "buffer.com", "spider": "reddit"},
            {"title": "Doist Async Work Study", "url": "https://doist.com/async-study-2026", "domain": "doist.com", "spider": "hackernews"},
        ],
        "action": {
            "title": "Pitch Remote-First Transition to Leadership",
            "type": "pitch",
            "steps": [
                {"step": "Calculate current office costs and project savings at $11K/employee", "priority": "high"},
                {"step": "Identify 3 competitors who went remote-first and their revenue trajectory", "priority": "medium"},
                {"step": "Draft async-first communication policy (Slack/Notion/Loom stack)", "priority": "medium"},
                {"step": "Propose 90-day pilot with one department", "priority": "high"},
            ],
        },
    },
    {
        "title": "DeFi Lending Protocols Seeing Record Inflows After Fed Rate Decision",
        "summary": "Decentralized lending platforms are experiencing unprecedented capital inflows following the Federal Reserve's latest rate announcement. Aave and Compound TVL up 45% in 72 hours.",
        "category": "crypto",
        "confidence_score": 0.85,
        "source_count": 15,
        "signal_strength": 0.88,
        "tags": ["defi", "lending", "fed-rates", "tvl", "aave"],
        "evidence": [
            {"claim": "Aave TVL increased 45% within 72 hours of Fed rate decision", "excerpt": "Total Value Locked in Aave surged from $12.3B to $17.8B in the 72 hours following the Fed's surprise 50bps cut, the fastest TVL growth since the 2024 bull run.", "source_title": "DeFiLlama Analytics", "domain": "defillama.com", "url": "https://defillama.com/protocol/aave", "confidence": 0.93, "type": "statistic"},
            {"claim": "Stablecoin yields on DeFi platforms now exceed traditional savings by 4x", "excerpt": "The average stablecoin lending yield on top DeFi protocols reached 8.2% APY, compared to 2.1% offered by major banks — a 4x premium that's driving institutional capital into DeFi.", "source_title": "CoinDesk DeFi Report", "domain": "coindesk.com", "url": "https://coindesk.com/defi-yields-2026", "confidence": 0.81, "type": "statistic"},
        ],
        "sources": [
            {"title": "DeFiLlama Analytics", "url": "https://defillama.com/protocol/aave", "domain": "defillama.com", "spider": "coingecko"},
            {"title": "CoinDesk DeFi Report", "url": "https://coindesk.com/defi-yields-2026", "domain": "coindesk.com", "spider": "financial"},
            {"title": "Etherscan Whale Tracker", "url": "https://etherscan.io/whales", "domain": "etherscan.io", "spider": "etherscan"},
        ],
        "action": {
            "title": "Analyze DeFi Yield Opportunity",
            "type": "invest",
            "steps": [
                {"step": "Review Aave/Compound risk parameters and audit history", "priority": "high"},
                {"step": "Calculate risk-adjusted yield vs traditional fixed income", "priority": "high"},
                {"step": "Set up monitoring for TVL drops > 10% as exit signal", "priority": "medium"},
                {"step": "Start with small allocation ($5K-10K) in USDC lending on Aave", "priority": "medium"},
            ],
        },
    },
    {
        "title": "Solo Founders Using AI Agents to Run 7-Figure Businesses",
        "summary": "Growing pattern of solo entrepreneurs using AI agent stacks to operate businesses that previously required 5-10 employees. Content creation, customer service, and operations fully automated.",
        "category": "business",
        "confidence_score": 0.73,
        "source_count": 6,
        "signal_strength": 0.76,
        "tags": ["solo-founder", "ai-agents", "automation", "one-person-business"],
        "evidence": [
            {"claim": "Solo founders with AI stacks are reaching $1M+ ARR without employees", "excerpt": "A growing cohort of solo founders are using AI agent stacks — ChatGPT for content, Claude for strategy, custom agents for customer service — to build and run businesses exceeding $1M in annual recurring revenue without hiring a single employee.", "source_title": "Indie Hackers — Solo AI Founders", "domain": "indiehackers.com", "url": "https://indiehackers.com/solo-ai-founders-2026", "confidence": 0.72, "type": "example"},
            {"claim": "AI reduces solo founder workweek from 80 to 25 hours while maintaining output", "excerpt": "\"I went from 80-hour weeks to 25-hour weeks. The AI handles content, email, scheduling, and first-pass customer support. I focus on product and strategy,\" reported a SaaS founder doing $2.1M ARR.", "source_title": "Twitter/X Thread — @solofounder", "domain": "x.com", "url": "https://x.com/solofounder/status/123456", "confidence": 0.65, "type": "quote"},
        ],
        "sources": [
            {"title": "Indie Hackers — Solo AI Founders", "url": "https://indiehackers.com/solo-ai-founders-2026", "domain": "indiehackers.com", "spider": "reddit"},
            {"title": "Twitter/X Thread", "url": "https://x.com/solofounder/status/123456", "domain": "x.com", "spider": "bluesky"},
        ],
        "action": {
            "title": "Build AI-First Solo Business Playbook",
            "type": "build",
            "steps": [
                {"step": "Map your current 80-hour workweek: categorize every task by automatable vs not", "priority": "high"},
                {"step": "Set up AI stack: content (Claude), support (Intercom+AI), scheduling (Calendly+Zapier)", "priority": "high"},
                {"step": "Automate content pipeline: research → draft → edit → publish (use Evidence Cards pattern)", "priority": "medium"},
                {"step": "Target: reduce to 25-hour week within 90 days while maintaining revenue", "priority": "medium"},
            ],
        },
    },
    {
        "title": "Cybersecurity Skills Gap Reaches Critical Levels — 3.5M Unfilled Positions",
        "summary": "The global cybersecurity workforce shortage has reached 3.5 million unfilled positions. Companies are turning to AI-powered security operations and upskilling programs as traditional hiring fails.",
        "category": "career",
        "confidence_score": 0.91,
        "source_count": 10,
        "signal_strength": 0.87,
        "tags": ["cybersecurity", "hiring", "skills-gap", "career-opportunity"],
        "evidence": [
            {"claim": "3.5 million cybersecurity positions remain unfilled globally in 2026", "excerpt": "ISC2's 2026 Cybersecurity Workforce Study reports 3.5 million unfilled cybersecurity positions worldwide, up from 3.4 million in 2025, with the gap widening fastest in cloud security and AI security.", "source_title": "ISC2 Workforce Study 2026", "domain": "isc2.org", "url": "https://isc2.org/workforce-study-2026", "confidence": 0.94, "type": "statistic"},
            {"claim": "Entry-level cybersecurity salaries jumped 18% YoY to average $95K", "excerpt": "The fierce competition for cybersecurity talent has pushed entry-level salaries up 18% year-over-year, with the average entry-level security analyst now earning $95,000 in the US.", "source_title": "CyberSeek Career Pathway Data", "domain": "cyberseek.org", "url": "https://cyberseek.org/pathway-2026", "confidence": 0.88, "type": "statistic"},
        ],
        "sources": [
            {"title": "ISC2 Workforce Study 2026", "url": "https://isc2.org/workforce-study-2026", "domain": "isc2.org", "spider": "securityweek"},
            {"title": "CyberSeek Career Pathway Data", "url": "https://cyberseek.org/pathway-2026", "domain": "cyberseek.org", "spider": "business_news"},
        ],
        "action": {
            "title": "Launch Cybersecurity Upskilling Program",
            "type": "hire",
            "steps": [
                {"step": "Identify 3-5 team members with adjacent skills (networking, DevOps, cloud) for security upskilling", "priority": "high"},
                {"step": "Enroll in CompTIA Security+ or AWS Security Specialty (fastest ROI certs)", "priority": "high"},
                {"step": "Set up internal CTF (Capture the Flag) practice environment", "priority": "medium"},
                {"step": "Partner with a bootcamp for pipeline of junior security analysts", "priority": "low"},
            ],
        },
    },
]


def seed_database(database_url: str = "sqlite:///./signalstudio.db"):
    """Seed the database with demo signal clusters."""
    engine = init_db(database_url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Clear existing data
    session.query(ActionCard).delete()
    session.query(EvidenceCard).delete()
    session.query(SourceItem).delete()
    session.query(SignalCluster).delete()
    session.commit()

    for i, cluster_data in enumerate(DEMO_CLUSTERS):
        cluster = SignalCluster(
            title=cluster_data["title"],
            summary=cluster_data["summary"],
            category=cluster_data["category"],
            confidence_score=cluster_data["confidence_score"],
            source_count=cluster_data["source_count"],
            signal_strength=cluster_data["signal_strength"],
            tags=cluster_data["tags"],
            created_at=datetime.utcnow() - timedelta(hours=i * 3),
        )
        session.add(cluster)
        session.flush()

        # Add evidence cards
        for j, ev in enumerate(cluster_data.get("evidence", [])):
            card = EvidenceCard(
                cluster_id=cluster.id,
                claim_text=ev["claim"],
                excerpt=ev["excerpt"],
                source_title=ev["source_title"],
                source_domain=ev["domain"],
                source_url=ev["url"],
                confidence_score=ev["confidence"],
                citation_label=f"[{j+1}]",
                claim_type=ev.get("type", "general"),
            )
            session.add(card)

        # Add source items
        for src in cluster_data.get("sources", []):
            item = SourceItem(
                cluster_id=cluster.id,
                title=src["title"],
                url=src["url"],
                domain=src["domain"],
                spider_name=src.get("spider", ""),
                relevance_score=0.7 + (i * 0.03),
            )
            session.add(item)

        # Add action card
        action = cluster_data.get("action", {})
        if action:
            ac = ActionCard(
                cluster_id=cluster.id,
                title=action["title"],
                steps=action["steps"],
                action_type=action.get("type", "investigate"),
            )
            session.add(ac)

    session.commit()
    print(f"Seeded {len(DEMO_CLUSTERS)} signal clusters with evidence cards, sources, and action cards.")
    session.close()


if __name__ == "__main__":
    seed_database()
