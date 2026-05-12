import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import {
  getListJobsApiAdminJobsGetQueryKey,
  useListJobsApiAdminJobsGet,
  useLogoutApiAdminLogoutPost,
} from '../../api/generated/printWeb'
import { JobStatus } from '../../api/generated/model'
import { CompactCard, HistoryRow, PendingCard } from './cards'

function EmptyCard({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-300 bg-white p-6 text-center text-sm text-gray-500">
      {text}
    </div>
  )
}

export function Dashboard({ onLoggedOut }: { onLoggedOut: () => void }) {
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
