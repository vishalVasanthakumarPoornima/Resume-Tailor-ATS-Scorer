import type { JobStatus } from '../lib/api'
import ShinyText from '../blocks/ShinyText'

const BASE_STAGES: { key: string[]; label: string; icon: string }[] = [
  { key: ['queued', 'ingest'], label: 'Parsing your resume', icon: '📄' },
  { key: ['job'], label: 'Analyzing the job posting', icon: '🔍' },
  { key: ['tailoring'], label: 'Tailoring & compiling LaTeX', icon: '⚒️' },
  { key: ['scoring'], label: 'Scoring against the ATS', icon: '🎯' },
]

const COVER_STAGE = { key: ['cover'], label: 'Writing your cover letter', icon: '✍️' }

export default function ProgressView({ job, withCover = false }: { job: JobStatus; withCover?: boolean }) {
  const STAGES = withCover ? [...BASE_STAGES, COVER_STAGE] : BASE_STAGES
  const found = STAGES.findIndex(s => s.key.includes(job.stage))
  const current = found === -1 ? STAGES.length : found

  return (
    <div className="mx-auto w-full max-w-md rounded-3xl border border-zinc-800/80 bg-zinc-900/60 p-8 backdrop-blur-md">
      <div className="mb-6 text-center">
        <ShinyText text="Forging your resume…" speed={2.5} className="text-lg font-semibold" />
      </div>
      <ol className="space-y-4">
        {STAGES.map((stage, i) => {
          const state = i < current ? 'done' : i === current ? 'active' : 'todo'
          return (
            <li key={stage.label} className="flex items-center gap-4">
              <span
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-sm transition-colors ${
                  state === 'done'
                    ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300'
                    : state === 'active'
                      ? 'animate-pulse border-indigo-500/60 bg-indigo-500/15'
                      : 'border-zinc-800 bg-zinc-900 text-zinc-600'
                }`}
              >
                {state === 'done' ? '✓' : stage.icon}
              </span>
              <span
                className={`text-sm ${
                  state === 'active' ? 'font-medium text-zinc-100' : state === 'done' ? 'text-zinc-400' : 'text-zinc-600'
                }`}
              >
                {stage.label}
              </span>
            </li>
          )
        })}
      </ol>
      <p className="mt-6 min-h-5 text-center text-xs text-zinc-500">{job.detail}</p>
      {job.last_score !== undefined && (
        <p className="mt-1 text-center text-xs text-zinc-500">
          best so far: <span className="font-mono text-indigo-300">{job.last_score}/100</span>
        </p>
      )}
      <p className="mt-4 text-center text-[11px] text-zinc-700">
        Usually about 10 seconds on a cloud model — a few minutes if you're running one locally.
      </p>
    </div>
  )
}
