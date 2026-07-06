import { useRef, useState } from 'react'
import SpotlightCard from '../blocks/SpotlightCard'

export interface ForgeParams {
  resume: File | null
  useSample: boolean
  jobInput: string
  target: number
  maxIterations: number
}

interface Props {
  onSubmit: (params: ForgeParams) => void
  disabled?: boolean
}

export default function ForgeForm({ onSubmit, disabled }: Props) {
  const [resume, setResume] = useState<File | null>(null)
  const [useSample, setUseSample] = useState(false)
  const [jobInput, setJobInput] = useState('')
  const [target, setTarget] = useState(80)
  const [maxIterations, setMaxIterations] = useState(5)
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const acceptFile = (file: File | undefined) => {
    if (!file) return
    setResume(file)
    setUseSample(false)
  }

  const ready = (resume !== null || useSample) && jobInput.trim().length > 0

  return (
    <SpotlightCard
      className="mx-auto w-full max-w-3xl !border-zinc-800/80 !bg-zinc-900/60 !p-6 backdrop-blur-md sm:!p-8"
      spotlightColor="rgba(99, 102, 241, 0.18)"
    >
      <div className="grid gap-6 sm:grid-cols-2">
        {/* Resume upload */}
        <div>
          <label className="mb-2 block text-sm font-semibold text-zinc-300">Your resume</label>
          <div
            role="button"
            tabIndex={0}
            aria-label="Upload resume"
            onClick={() => fileInput.current?.click()}
            onKeyDown={e => e.key === 'Enter' && fileInput.current?.click()}
            onDragOver={e => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => {
              e.preventDefault()
              setDragging(false)
              acceptFile(e.dataTransfer.files[0])
            }}
            className={`flex h-40 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-4 text-center transition-colors ${
              dragging
                ? 'border-indigo-400 bg-indigo-500/10'
                : resume || useSample
                  ? 'border-emerald-500/50 bg-emerald-500/5'
                  : 'border-zinc-700 bg-zinc-900/40 hover:border-zinc-500'
            }`}
          >
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.tex,.txt,.md"
              className="hidden"
              onChange={e => acceptFile(e.target.files?.[0] ?? undefined)}
            />
            {resume ? (
              <>
                <span className="text-2xl">📄</span>
                <p className="mt-2 max-w-full truncate text-sm font-medium text-emerald-300">{resume.name}</p>
                <p className="mt-1 text-xs text-zinc-500">Click to replace</p>
              </>
            ) : useSample ? (
              <>
                <span className="text-2xl">🧪</span>
                <p className="mt-2 text-sm font-medium text-emerald-300">Using the bundled sample resume</p>
                <p className="mt-1 text-xs text-zinc-500">Click to upload your own instead</p>
              </>
            ) : (
              <>
                <span className="text-2xl">📎</span>
                <p className="mt-2 text-sm text-zinc-400">
                  Drop your resume here or <span className="text-indigo-400">browse</span>
                </p>
                <p className="mt-1 text-xs text-zinc-600">PDF · DOCX · TeX · TXT · MD</p>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              setUseSample(true)
              setResume(null)
            }}
            className="mt-2 text-xs text-zinc-500 underline-offset-2 hover:text-indigo-400 hover:underline"
          >
            No resume handy? Try the sample
          </button>
        </div>

        {/* Job description */}
        <div>
          <label className="mb-2 block text-sm font-semibold text-zinc-300">The job</label>
          <textarea
            value={jobInput}
            onChange={e => setJobInput(e.target.value)}
            placeholder={'Paste the job description here…\n\n…or drop in a posting URL (https://…)'}
            className="h-40 w-full resize-none rounded-2xl border border-zinc-700 bg-zinc-900/40 p-3 text-sm text-zinc-200 placeholder-zinc-600 outline-none transition-colors focus:border-indigo-500"
          />
          <p className="mt-2 text-xs text-zinc-600">
            Job boards that block bots (LinkedIn, Indeed…)? Paste the text — it always works.
          </p>
        </div>
      </div>

      {/* Options */}
      <div className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-4">
        <label className="flex items-center gap-3 text-sm text-zinc-400">
          Target score
          <input
            type="range"
            min={60}
            max={95}
            step={5}
            value={target}
            onChange={e => setTarget(Number(e.target.value))}
            className="w-32 accent-indigo-500"
          />
          <span className="w-8 font-mono text-indigo-300">{target}</span>
        </label>
        <label className="flex items-center gap-3 text-sm text-zinc-400">
          Max iterations
          <select
            value={maxIterations}
            onChange={e => setMaxIterations(Number(e.target.value))}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-200 outline-none focus:border-indigo-500"
          >
            {[1, 2, 3, 5, 8].map(n => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!ready || disabled}
          onClick={() => onSubmit({ resume, useSample, jobInput, target, maxIterations })}
          className="ml-auto rounded-xl bg-indigo-600 px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-600/25 transition-all hover:bg-indigo-500 hover:shadow-indigo-500/30 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        >
          Forge my resume ⚒️
        </button>
      </div>
    </SpotlightCard>
  )
}
