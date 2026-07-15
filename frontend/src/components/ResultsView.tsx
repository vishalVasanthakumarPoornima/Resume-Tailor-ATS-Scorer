import { useState } from 'react'
import type { JobStatus } from '../lib/api'
import { coverLetterUrl, pdfUrl, reportUrl, texUrl } from '../lib/api'
import AnimatedContent from '../blocks/AnimatedContent'
import CountUp from '../blocks/CountUp'
import GradientText from '../blocks/GradientText'
import SpotlightCard from '../blocks/SpotlightCard'

const SUBSCORE_LABELS: Record<string, string> = {
  keywords: 'Keyword coverage',
  parseability: 'Parseability',
  sections: 'Standard sections',
  bullets: 'Bullet quality',
  contact: 'Contact info',
  length: 'Length',
}

export default function ResultsView({ job, onReset }: { job: JobStatus; onReset: () => void }) {
  const [showNotes, setShowNotes] = useState(false)
  const result = job.result!
  const { report } = result
  const hit = result.achieved_target
  const ring = hit ? 'text-emerald-400' : 'text-amber-400'

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <AnimatedContent distance={50} duration={0.7}>
      <SpotlightCard
        className="!border-zinc-800/80 !bg-zinc-900/60 !p-8 backdrop-blur-md"
        spotlightColor="rgba(52, 211, 153, 0.12)"
      >
        <div className="flex flex-col items-center gap-8 md:flex-row">
          {/* Score dial */}
          <div className="relative flex h-44 w-44 shrink-0 items-center justify-center">
            <svg viewBox="0 0 100 100" className="absolute inset-0 -rotate-90">
              <circle cx="50" cy="50" r="44" fill="none" stroke="currentColor" strokeWidth="7" className="text-zinc-800" />
              <circle
                cx="50"
                cy="50"
                r="44"
                fill="none"
                stroke="currentColor"
                strokeWidth="7"
                strokeLinecap="round"
                strokeDasharray={`${(report.score / 100) * 276.5} 276.5`}
                className={`${ring} transition-[stroke-dasharray] duration-1000`}
              />
            </svg>
            <div className="text-center">
              <div className={`text-5xl font-extrabold ${ring}`}>
                <CountUp to={report.score} duration={1.2} />
              </div>
              <div className="text-xs text-zinc-300">ATS score / 100</div>
            </div>
          </div>

          <div className="min-w-0 flex-1 text-center md:text-left">
            {hit ? (
              <GradientText
                colors={['#34d399', '#22d3ee', '#34d399']}
                animationSpeed={5}
                className="!mx-0 text-sm font-semibold uppercase tracking-wider"
              >
                Target reached
              </GradientText>
            ) : (
              <p className="text-sm font-semibold uppercase tracking-wider text-amber-400">
                Best effort — below target
              </p>
            )}
            <h2 className="mt-1 truncate text-2xl font-bold text-zinc-100">
              {job.job_title ?? 'Tailored resume'}
              {job.job_company ? <span className="text-zinc-400"> · {job.job_company}</span> : null}
            </h2>
            <p className="mt-1 text-sm text-zinc-300">
              {result.iterations} iteration{result.iterations === 1 ? '' : 's'} · target {job.target}
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-3 md:justify-start">
              <a
                href={pdfUrl(job.id)}
                download
                className="rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-600/25 transition-colors hover:bg-emerald-500"
              >
                Download PDF ↓
              </a>
              {result.cover_letter_pdf_path && (
                <a
                  href={coverLetterUrl(job.id)}
                  download
                  className="rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/25 transition-colors hover:bg-indigo-500"
                >
                  Cover letter ✍️
                </a>
              )}
              <a
                href={texUrl(job.id)}
                download
                className="rounded-xl border border-zinc-700 px-6 py-2.5 text-sm font-medium text-zinc-300 transition-colors hover:border-zinc-500"
              >
                .tex source
              </a>
              <a
                href={reportUrl(job.id)}
                download
                className="rounded-xl border border-zinc-700 px-6 py-2.5 text-sm font-medium text-zinc-300 transition-colors hover:border-zinc-500"
              >
                report.json
              </a>
              <button
                onClick={onReset}
                className="rounded-xl border border-zinc-800 px-6 py-2.5 text-sm text-zinc-300 transition-colors hover:border-zinc-600 hover:text-zinc-300"
              >
                Start over
              </button>
            </div>
          </div>
        </div>
      </SpotlightCard>
      </AnimatedContent>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Subscores */}
        <div className="rounded-3xl border border-zinc-800/80 bg-zinc-900/60 p-6 backdrop-blur-md">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">Score breakdown</h3>
          <div className="space-y-3">
            {Object.entries(report.subscores).map(([name, value]) => {
              const max = report.max_subscores[name] ?? 1
              const frac = value / max
              return (
                <div key={name}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-zinc-400">{SUBSCORE_LABELS[name] ?? name}</span>
                    <span className="font-mono text-zinc-300">
                      {value}/{max}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${
                        frac >= 0.8 ? 'bg-emerald-500' : frac >= 0.5 ? 'bg-amber-500' : 'bg-rose-500'
                      }`}
                      style={{ width: `${Math.max(frac * 100, 2)}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Gaps & suggestions */}
        <div className="rounded-3xl border border-zinc-800/80 bg-zinc-900/60 p-6 backdrop-blur-md">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">Remaining gaps</h3>
          {report.missing_keywords.length > 0 ? (
            <div className="mb-4 flex flex-wrap gap-2">
              {report.missing_keywords.slice(0, 12).map(kw => (
                <span key={kw} className="rounded-full border border-rose-500/30 bg-rose-500/10 px-3 py-1 text-xs text-rose-300">
                  {kw}
                </span>
              ))}
            </div>
          ) : (
            <p className="mb-4 text-sm text-emerald-400">Every JD keyword is covered ✓</p>
          )}
          <ul className="space-y-2">
            {report.suggestions.map(s => (
              <li key={s} className="flex gap-2 text-sm text-zinc-400">
                <span className="text-indigo-400">→</span>
                {s}
              </li>
            ))}
          </ul>
          {result.notes.length > 0 && (
            <div className="mt-4 border-t border-zinc-800 pt-3">
              <button onClick={() => setShowNotes(v => !v)} className="text-xs text-zinc-400 hover:text-zinc-400">
                {showNotes ? '▾' : '▸'} pipeline notes ({result.notes.length})
              </button>
              {showNotes && (
                <ul className="mt-2 space-y-1">
                  {result.notes.map(n => (
                    <li key={n} className="text-xs text-zinc-400">
                      {n}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
