import { useEffect, useRef, useState } from 'react'
import AnimatedContent from './blocks/AnimatedContent'
import Aurora from './blocks/Aurora'
import Particles from './blocks/Particles'
import ShinyText from './blocks/ShinyText'
import SplitText from './blocks/SplitText'
import ForgeForm, { type ForgeParams } from './components/ForgeForm'
import ProgressView from './components/ProgressView'
import ResultsView from './components/ResultsView'
import { createJob, getHealth, getJob, type Health, type JobStatus } from './lib/api'

type Phase = 'form' | 'running' | 'done' | 'error'

export default function App() {
  const [phase, setPhase] = useState<Phase>('form')
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState('')
  const [health, setHealth] = useState<Health | null>(null)
  const [withCover, setWithCover] = useState(false)
  const pollRef = useRef<number>()

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: 'offline' }))
  }, [])

  useEffect(() => () => window.clearInterval(pollRef.current), [])

  const submit = async (params: ForgeParams) => {
    setError('')
    setWithCover(params.coverLetter)
    const form = new FormData()
    form.set('job_input', params.jobInput)
    form.set('target', String(params.target))
    form.set('max_iterations', String(params.maxIterations))
    if (params.coverLetter) form.set('include_cover_letter', 'true')
    if (params.useSample) form.set('use_sample_resume', 'true')
    else if (params.resume) form.set('resume', params.resume)

    try {
      const id = await createJob(form)
      setPhase('running')
      pollRef.current = window.setInterval(async () => {
        try {
          const status = await getJob(id)
          setJob(status)
          if (status.status !== 'running') {
            window.clearInterval(pollRef.current)
            if (status.status === 'error') {
              setError(status.detail)
              setPhase('error')
            } else {
              setPhase('done')
            }
          }
        } catch {
          /* transient poll failure — keep trying */
        }
      }, 1200)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  const reset = () => {
    window.clearInterval(pollRef.current)
    setJob(null)
    setError('')
    setPhase('form')
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      {/* React Bits Aurora + Particles background */}
      <div className="pointer-events-none fixed inset-0 opacity-60">
        <Aurora colorStops={['#4f46e5', '#0ea5e9', '#8b5cf6']} amplitude={1.1} blend={0.55} speed={0.7} />
      </div>
      <div className="pointer-events-none fixed inset-0 opacity-40">
        <Particles
          particleColors={['#a5b4fc', '#67e8f9']}
          particleCount={140}
          particleSpread={11}
          speed={0.06}
          particleBaseSize={70}
          moveParticlesOnHover={false}
          alphaParticles
        />
      </div>

      <div className="relative z-10 mx-auto flex min-h-screen max-w-5xl flex-col px-4 py-6">
        {/* Header */}
        <header className="mb-14 flex items-center justify-between">
          <button onClick={reset} className="flex items-center gap-2 text-left">
            <span className="text-xl">⚒️</span>
            <ShinyText text="resume-forge" speed={4} className="text-lg font-bold tracking-tight" />
          </button>
          <div className="text-right text-xs text-zinc-600">
            {health === null ? (
              'connecting…'
            ) : health.status === 'ok' ? (
              <>
                <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-emerald-500 align-middle" />
                {health.backend} · <span className="font-mono">{health.model}</span>
              </>
            ) : (
              <>
                <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-rose-500 align-middle" />
                {health.llm_error ? 'LLM unavailable' : 'backend offline'}
              </>
            )}
          </div>
        </header>

        {/* Hero */}
        {phase === 'form' && (
          <section className="mb-12 text-center">
            <SplitText
              text="Tailor your resume to any job."
              tag="h1"
              className="text-4xl font-extrabold leading-tight text-zinc-50 sm:text-5xl"
              splitType="words"
              delay={60}
              duration={0.8}
              from={{ opacity: 0, y: 36 }}
              to={{ opacity: 1, y: 0 }}
            />
            <p className="mx-auto mt-5 max-w-xl text-zinc-400">
              Drop in your resume and a job posting. An AI model rewrites for the role —{' '}
              <span className="text-zinc-200">never inventing experience</span> — compiles a clean LaTeX PDF, and
              iterates until it beats the ATS score target.
            </p>
          </section>
        )}

        {/* Main */}
        <main className="flex flex-1 flex-col justify-start">
          {phase === 'form' && (
            <AnimatedContent distance={60} duration={0.9} delay={0.15}>
              <ForgeForm onSubmit={submit} />
            </AnimatedContent>
          )}
          {phase === 'running' && (
            <ProgressView
              job={job ?? ({ stage: 'queued', detail: 'Starting…' } as JobStatus)}
              withCover={withCover}
            />
          )}
          {phase === 'done' && job && <ResultsView job={job} onReset={reset} />}
          {phase === 'error' && (
            <div className="mx-auto w-full max-w-xl rounded-3xl border border-rose-500/30 bg-rose-500/5 p-8 text-center backdrop-blur-md">
              <p className="text-2xl">😵</p>
              <h2 className="mt-2 text-lg font-semibold text-rose-300">Something went wrong</h2>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">{error}</p>
              <button
                onClick={reset}
                className="mt-6 rounded-xl border border-zinc-700 px-6 py-2.5 text-sm text-zinc-300 transition-colors hover:border-zinc-500"
              >
                Try again
              </button>
            </div>
          )}
        </main>

        <footer className="mt-16 pb-2 text-center text-xs text-zinc-700">
          LaTeX + tectonic · deterministic ATS scorer · no fabrication, guaranteed by code
        </footer>
      </div>
    </div>
  )
}
