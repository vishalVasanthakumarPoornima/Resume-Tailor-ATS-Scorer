export interface ScoreReport {
  score: number
  subscores: Record<string, number>
  max_subscores: Record<string, number>
  missing_keywords: string[]
  suggestions: string[]
}

export interface ForgeResultData {
  pdf_path: string
  tex_path: string
  report: ScoreReport
  iterations: number
  achieved_target: boolean
  notes: string[]
}

export interface JobStatus {
  id: string
  status: 'running' | 'done' | 'error'
  stage: string
  detail: string
  target: number
  iteration?: number
  last_score?: number
  result?: ForgeResultData
  job_title?: string
  job_company?: string | null
}

export interface Health {
  status: string
  backend?: string
  model?: string
  llm_error?: string
}

export async function createJob(form: FormData): Promise<string> {
  const res = await fetch('/api/jobs', { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${res.status})`)
  }
  const data = await res.json()
  return data.job_id
}

export async function getJob(id: string): Promise<JobStatus> {
  const res = await fetch(`/api/jobs/${id}`)
  if (!res.ok) throw new Error(`Status check failed (${res.status})`)
  return res.json()
}

export async function getHealth(): Promise<Health> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error('backend unreachable')
  return res.json()
}

export const pdfUrl = (id: string) => `/api/jobs/${id}/pdf`
export const texUrl = (id: string) => `/api/jobs/${id}/tex`
