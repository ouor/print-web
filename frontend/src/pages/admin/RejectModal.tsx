import { useState } from 'react'

import { useRejectApiAdminJobsJobIdRejectPost } from '../../api/generated/printWeb'
import type { AdminJob } from '../../api/generated/model'

const REJECT_PRESETS = ['부적절한 이미지', '중복 요청', '행사 무관'] as const

export function RejectModal({
  job,
  onClose,
  onDone,
}: {
  job: AdminJob
  onClose: () => void
  onDone: () => void
}) {
  const [selected, setSelected] = useState<string>(REJECT_PRESETS[0])
  const [custom, setCustom] = useState('')
  const reject = useRejectApiAdminJobsJobIdRejectPost({
    mutation: { onSuccess: () => onDone() },
  })

  const reason = selected === 'custom' ? custom.trim() : selected

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
