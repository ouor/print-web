import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  getListJobsApiAdminJobsGetQueryKey,
  useApproveApiAdminJobsJobIdApprovePost,
  useRetryApiAdminJobsJobIdRetryPost,
} from '../../api/generated/printWeb'
import type { AdminJob } from '../../api/generated/model'
import { JobStatus } from '../../api/generated/model'
import { RejectModal } from './RejectModal'
import { adminJobLabel, RelativeTime, STATUS_BADGE } from './status'

export function PendingCard({ job }: { job: AdminJob }) {
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

export function CompactCard({ job }: { job: AdminJob }) {
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
        {adminJobLabel(job)}
      </span>
    </li>
  )
}

export function HistoryRow({ job }: { job: AdminJob }) {
  const queryClient = useQueryClient()
  const retry = useRetryApiAdminJobsJobIdRetryPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getListJobsApiAdminJobsGetQueryKey(),
        })
      },
    },
  })

  const canRetry = job.status === JobStatus.FAILED && job.has_image

  return (
    <li className="flex items-center gap-3 rounded-lg bg-white px-3 py-2 ring-1 ring-gray-200">
      <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_BADGE[job.status]}`}>
        {adminJobLabel(job)}
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
      {canRetry && (
        <button
          type="button"
          disabled={retry.isPending}
          onClick={() => retry.mutate({ jobId: job.id })}
          className="rounded-md border border-blue-300 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {retry.isPending ? '재시도 중…' : '다시 인쇄'}
        </button>
      )}
      <RelativeTime ts={job.updated_at} />
    </li>
  )
}
