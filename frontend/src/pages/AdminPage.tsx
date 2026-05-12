import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import {
  getListJobsApiAdminJobsGetQueryKey,
  useApproveApiAdminJobsJobIdApprovePost,
  useListJobsApiAdminJobsGet,
  useLoginApiAdminLoginPost,
  useLogoutApiAdminLogoutPost,
  useMeApiAdminMeGet,
  useRejectApiAdminJobsJobIdRejectPost,
} from '../api/generated/printWeb'
import type { AdminJob } from '../api/generated/model'
import { JobStatus } from '../api/generated/model'

const REJECT_PRESETS = [
  '부적절한 이미지',
  '중복 요청',
  '행사 무관',
] as const

const STATUS_BADGE: Record<JobStatus, string> = {
  PENDING: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-blue-100 text-blue-800',
  PRINTING: 'bg-blue-200 text-blue-900',
  DONE: 'bg-emerald-100 text-emerald-800',
  FAILED: 'bg-rose-100 text-rose-800',
  REJECTED: 'bg-gray-200 text-gray-700',
}

const STATUS_LABEL: Record<JobStatus, string> = {
  PENDING: '대기',
  APPROVED: '승인',
  PRINTING: '인쇄 중',
  DONE: '완료',
  FAILED: '실패',
  REJECTED: '거절',
}

export function AdminPage() {
  const me = useMeApiAdminMeGet({
    query: { staleTime: 30_000 },
  })

  if (me.isLoading) {
    return <Shell><p className="text-gray-500">확인 중…</p></Shell>
  }
  if (!me.data?.authenticated) {
    return <LoginScreen onLoggedIn={() => me.refetch()} />
  }
  return <Dashboard onLoggedOut={() => me.refetch()} />
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <h1 className="text-lg font-semibold text-gray-900">print-web · 관리자</h1>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
    </div>
  )
}

function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const login = useLoginApiAdminLoginPost({
    mutation: {
      onSuccess: () => onLoggedIn(),
      onError: () => setError('비밀번호가 올바르지 않습니다.'),
    },
  })

  return (
    <Shell>
      <div className="mx-auto max-w-sm">
        <form
          className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200"
          onSubmit={(e) => {
            e.preventDefault()
            setError(null)
            login.mutate({ data: { password } })
          }}
        >
          <label className="block text-sm font-medium text-gray-700">
            관리자 비밀번호
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-base outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              required
            />
          </label>
          {error && (
            <p className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={login.isPending}
            className="mt-4 w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:bg-blue-300"
          >
            {login.isPending ? '확인 중…' : '로그인'}
          </button>
        </form>
      </div>
    </Shell>
  )
}

function Dashboard({ onLoggedOut }: { onLoggedOut: () => void }) {
  const queryClient = useQueryClient()
  const [visible, setVisible] = useState(() => !document.hidden)
  useEffect(() => {
    const handler = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [])

  const jobs = useListJobsApiAdminJobsGet(undefined, {
    query: {
      refetchInterval: visible ? 4000 : false,
      refetchIntervalInBackground: false,
    },
  })

  const logout = useLogoutApiAdminLogoutPost({
    mutation: {
      onSuccess: () => {
        queryClient.removeQueries({ queryKey: getListJobsApiAdminJobsGetQueryKey() })
        onLoggedOut()
      },
    },
  })

  const items = jobs.data?.items ?? []
  const pending = items.filter((j) => j.status === JobStatus.PENDING)
  const active = items.filter(
    (j) => j.status === JobStatus.APPROVED || j.status === JobStatus.PRINTING,
  )
  const recent = items.filter(
    (j) =>
      j.status === JobStatus.DONE ||
      j.status === JobStatus.FAILED ||
      j.status === JobStatus.REJECTED,
  )

  return (
    <div className="min-h-full bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <h1 className="text-lg font-semibold text-gray-900">print-web · 관리자</h1>
          <div className="flex items-center gap-3 text-sm text-gray-500">
            <span>대기 {pending.length} · 진행 {active.length}</span>
            <button
              type="button"
              onClick={() => logout.mutate()}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-gray-700 hover:bg-gray-100"
            >
              로그아웃
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-6 py-6 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            검토 대기 ({pending.length})
          </h2>
          {pending.length === 0 ? (
            <EmptyCard text="새로운 요청이 없습니다." />
          ) : (
            <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {pending.map((job) => (
                <PendingCard key={job.id} job={job} />
              ))}
            </ul>
          )}

          <h2 className="mt-8 mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            처리 중 ({active.length})
          </h2>
          {active.length === 0 ? (
            <EmptyCard text="진행 중인 작업이 없습니다." />
          ) : (
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {active.map((job) => (
                <CompactCard key={job.id} job={job} />
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            최근 처리 ({recent.length})
          </h2>
          {recent.length === 0 ? (
            <EmptyCard text="아직 처리된 작업이 없습니다." />
          ) : (
            <ul className="space-y-2">
              {recent.slice(0, 30).map((job) => (
                <HistoryRow key={job.id} job={job} />
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  )
}

function EmptyCard({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-300 bg-white p-6 text-center text-sm text-gray-500">
      {text}
    </div>
  )
}

function PendingCard({ job }: { job: AdminJob }) {
  const queryClient = useQueryClient()
  const [rejecting, setRejecting] = useState(false)

  const approve = useApproveApiAdminJobsJobIdApprovePost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getListJobsApiAdminJobsGetQueryKey(),
        })
      },
    },
  })

  return (
    <li className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-gray-200">
      <div className="bg-gray-100">
        {job.has_image ? (
          <img
            src={`/api/admin/jobs/${job.id}/thumb`}
            alt=""
            className="block h-48 w-full object-contain"
          />
        ) : (
          <div className="flex h-48 items-center justify-center text-sm text-gray-400">
            이미지 없음
          </div>
        )}
      </div>
      <div className="p-3">
        <div className="flex items-center justify-between">
          <p className="font-medium text-gray-900">{job.requester_name}</p>
          <RelativeTime ts={job.created_at} />
        </div>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={approve.isPending}
            onClick={() => approve.mutate({ jobId: job.id })}
            className="flex-1 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:bg-emerald-300"
          >
            승인
          </button>
          <button
            type="button"
            onClick={() => setRejecting(true)}
            className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            거절
          </button>
        </div>
      </div>
      {rejecting && (
        <RejectModal
          job={job}
          onClose={() => setRejecting(false)}
          onDone={() => {
            setRejecting(false)
            queryClient.invalidateQueries({
              queryKey: getListJobsApiAdminJobsGetQueryKey(),
            })
          }}
        />
      )}
    </li>
  )
}

function RejectModal({
  job,
  onClose,
  onDone,
}: {
  job: AdminJob
  onClose: () => void
  onDone: () => void
}) {
  const [selected, setSelected] = useState<string | null>(REJECT_PRESETS[0])
  const [custom, setCustom] = useState('')
  const reject = useRejectApiAdminJobsJobIdRejectPost({
    mutation: { onSuccess: () => onDone() },
  })

  const reason = selected === 'custom' ? custom.trim() : (selected ?? '')

  function submit() {
    if (!reason || reject.isPending) return
    reject.mutate({ jobId: job.id, data: { reason } })
  }

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-lg">
        <p className="text-sm text-gray-500">거절 — {job.requester_name}</p>
        <p className="mt-0.5 text-base font-semibold text-gray-900">사유 선택</p>
        <div className="mt-3 space-y-2">
          {REJECT_PRESETS.map((preset) => (
            <label key={preset} className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="radio"
                checked={selected === preset}
                onChange={() => setSelected(preset)}
              />
              {preset}
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="radio"
              checked={selected === 'custom'}
              onChange={() => setSelected('custom')}
            />
            직접 입력
          </label>
          <input
            type="text"
            value={custom}
            onChange={(e) => {
              setCustom(e.target.value)
              setSelected('custom')
            }}
            placeholder="사유를 적어주세요"
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            maxLength={200}
          />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
          >
            취소
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={reject.isPending || !reason}
            className="rounded-md bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:bg-rose-300"
          >
            {reject.isPending ? '처리 중…' : '거절'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CompactCard({ job }: { job: AdminJob }) {
  return (
    <li className="flex items-center gap-3 rounded-xl bg-white p-3 shadow-sm ring-1 ring-gray-200">
      {job.has_image ? (
        <img
          src={`/api/admin/jobs/${job.id}/thumb`}
          alt=""
          className="h-12 w-12 rounded-md object-cover"
        />
      ) : (
        <div className="h-12 w-12 rounded-md bg-gray-100" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-gray-900">{job.requester_name}</p>
        <RelativeTime ts={job.updated_at} />
      </div>
      <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_BADGE[job.status]}`}>
        {STATUS_LABEL[job.status]}
      </span>
    </li>
  )
}

function HistoryRow({ job }: { job: AdminJob }) {
  return (
    <li className="flex items-center gap-3 rounded-lg bg-white px-3 py-2 ring-1 ring-gray-200">
      <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_BADGE[job.status]}`}>
        {STATUS_LABEL[job.status]}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-gray-900">{job.requester_name}</p>
        {job.status === JobStatus.REJECTED && job.reject_reason && (
          <p className="truncate text-xs text-gray-500">{job.reject_reason}</p>
        )}
        {job.status === JobStatus.FAILED && job.status_message && (
          <p className="truncate text-xs text-rose-500">{job.status_message}</p>
        )}
      </div>
      <RelativeTime ts={job.updated_at} />
    </li>
  )
}

function RelativeTime({ ts }: { ts: string }) {
  const label = useMemo(() => formatRelative(ts), [ts])
  return <span className="text-xs text-gray-500 whitespace-nowrap">{label}</span>
}

function formatRelative(iso: string): string {
  // Backend sends naive UTC; treat as UTC explicitly.
  const t = new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()
  const diffSec = Math.round((Date.now() - t) / 1000)
  if (diffSec < 60) return '방금'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}시간 전`
  return `${Math.floor(diffSec / 86400)}일 전`
}
