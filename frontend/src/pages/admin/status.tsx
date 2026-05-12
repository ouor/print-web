import { useMemo } from 'react'

import { JobStatus } from '../../api/generated/model'

export const STATUS_BADGE: Record<JobStatus, string> = {
  PENDING: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-blue-100 text-blue-800',
  PRINTING: 'bg-blue-200 text-blue-900',
  DONE: 'bg-emerald-100 text-emerald-800',
  FAILED: 'bg-rose-100 text-rose-800',
  REJECTED: 'bg-gray-200 text-gray-700',
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  PENDING: '대기',
  APPROVED: '승인',
  PRINTING: '인쇄 중',
  DONE: '완료',
  FAILED: '실패',
  REJECTED: '거절',
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

export function RelativeTime({ ts }: { ts: string }) {
  const label = useMemo(() => formatRelative(ts), [ts])
  return <span className="text-xs text-gray-500 whitespace-nowrap">{label}</span>
}
