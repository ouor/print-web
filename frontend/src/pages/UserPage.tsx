import { useEffect, useMemo, useState } from 'react'

import {
  useFetchJobApiJobsJobIdGet,
  useSubmitJobApiJobsPost,
} from '../api/generated/printWeb'
import { JobStatus } from '../api/generated/model'

const STORAGE_KEY = 'print-web.user.job'

type StoredJob = {
  id: string
  name: string
}

function loadStored(): StoredJob | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as StoredJob
  } catch {
    return null
  }
}

function persistStored(value: StoredJob | null): void {
  if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  else localStorage.removeItem(STORAGE_KEY)
}

const TERMINAL = new Set<JobStatus>([
  JobStatus.DONE,
  JobStatus.FAILED,
  JobStatus.REJECTED,
])

const STATUS_LABEL: Record<JobStatus, { title: string; sub: string; tone: 'wait' | 'go' | 'ok' | 'bad' }> = {
  PENDING: { title: '검토 대기 중', sub: '관리자가 곧 확인합니다.', tone: 'wait' },
  APPROVED: { title: '승인됨', sub: '인쇄 순서를 기다리는 중입니다.', tone: 'go' },
  PRINTING: { title: '인쇄 중', sub: '잠시만 기다려주세요.', tone: 'go' },
  DONE: { title: '인쇄 완료', sub: '출력물을 받아가세요.', tone: 'ok' },
  FAILED: { title: '인쇄 실패', sub: '관리자에게 문의해주세요.', tone: 'bad' },
  REJECTED: { title: '요청 거절됨', sub: '관리자가 요청을 거절했습니다.', tone: 'bad' },
}

const TONE_CLASS: Record<'wait' | 'go' | 'ok' | 'bad', string> = {
  wait: 'border-amber-300 bg-amber-50 text-amber-900',
  go: 'border-blue-300 bg-blue-50 text-blue-900',
  ok: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  bad: 'border-rose-300 bg-rose-50 text-rose-900',
}

export function UserPage() {
  const [stored, setStored] = useState<StoredJob | null>(() => loadStored())

  if (stored) {
    return (
      <Tracker
        jobId={stored.id}
        name={stored.name}
        onReset={() => {
          persistStored(null)
          setStored(null)
        }}
      />
    )
  }

  return (
    <SubmitForm
      onSubmitted={(id, name) => {
        const next = { id, name }
        persistStored(next)
        setStored(next)
      }}
    />
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full bg-gray-50 px-4 py-8">
      <main className="mx-auto w-full max-w-md">
        <h1 className="text-center text-2xl font-semibold text-gray-900">
          사진 인쇄 요청
        </h1>
        <p className="mt-1 text-center text-sm text-gray-500">
          사진을 올리면 관리자 승인 후 인쇄됩니다.
        </p>
        <div className="mt-6">{children}</div>
      </main>
    </div>
  )
}

function SubmitForm({
  onSubmitted,
}: {
  onSubmitted: (id: string, name: string) => void
}) {
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const idemKey = useMemo(() => crypto.randomUUID(), [])

  const previewUrl = useMemo(() => {
    if (!file) return null
    return URL.createObjectURL(file)
  }, [file])
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const submit = useSubmitJobApiJobsPost({
    mutation: {
      onSuccess: (data) => {
        onSubmitted(data.id, name.trim())
      },
      onError: (err) => {
        const msg =
          (err as unknown as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '제출에 실패했습니다.'
        setError(typeof msg === 'string' ? msg : '제출에 실패했습니다.')
      },
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const trimmed = name.trim()
    if (!trimmed) {
      setError('이름을 입력해주세요.')
      return
    }
    if (!file) {
      setError('사진을 선택해주세요.')
      return
    }
    submit.mutate({
      data: {
        requester_name: trimmed,
        idempotency_key: idemKey,
        image: file,
      },
    })
  }

  const disabled = submit.isPending

  return (
    <Layout>
      <form
        className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200"
        onSubmit={handleSubmit}
      >
        <label className="block text-sm font-medium text-gray-700">
          이름
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={50}
            disabled={disabled}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-base outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            placeholder="홍길동"
            required
          />
        </label>

        <label className="mt-4 block text-sm font-medium text-gray-700">
          사진
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={disabled}
            className="mt-1 block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-gray-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-gray-700"
            required
          />
        </label>

        {previewUrl && (
          <div className="mt-3 overflow-hidden rounded-lg border border-gray-200">
            <img src={previewUrl} alt="" className="block max-h-72 w-full object-contain bg-gray-100" />
          </div>
        )}

        {error && (
          <p className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={disabled}
          className="mt-5 w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
        >
          {disabled ? '제출 중…' : '인쇄 요청하기'}
        </button>
      </form>
    </Layout>
  )
}

function Tracker({
  jobId,
  name,
  onReset,
}: {
  jobId: string
  name: string
  onReset: () => void
}) {
  const query = useFetchJobApiJobsJobIdGet(jobId, {
    query: {
      refetchInterval: (q) => {
        const s = q.state.data?.status
        if (s && TERMINAL.has(s)) return false
        return 2500
      },
      refetchIntervalInBackground: false,
    },
  })

  const status = query.data?.status
  const meta = status ? STATUS_LABEL[status] : null

  return (
    <Layout>
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        <p className="text-sm text-gray-500">요청자</p>
        <p className="text-lg font-medium text-gray-900">{name}</p>

        <div
          className={
            'mt-4 rounded-xl border px-4 py-3 ' +
            (meta ? TONE_CLASS[meta.tone] : 'border-gray-200 bg-gray-50 text-gray-700')
          }
        >
          {query.isLoading && !meta && <p className="text-sm">상태 조회 중…</p>}
          {query.isError && (
            <p className="text-sm">상태를 가져오지 못했습니다. 잠시 후 다시 시도됩니다.</p>
          )}
          {meta && (
            <>
              <p className="text-base font-semibold">{meta.title}</p>
              <p className="mt-0.5 text-sm">{meta.sub}</p>
            </>
          )}
        </div>

        {status && TERMINAL.has(status) && (
          <button
            type="button"
            onClick={onReset}
            className="mt-5 w-full rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-700"
          >
            새로 인쇄하기
          </button>
        )}
        {status && !TERMINAL.has(status) && (
          <button
            type="button"
            onClick={onReset}
            className="mt-5 w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            요청 취소하고 새로 시작
          </button>
        )}
      </div>
    </Layout>
  )
}
