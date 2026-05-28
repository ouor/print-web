import { useEffect, useMemo, useRef, useState } from 'react'

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

// Only DONE is terminal from the user's perspective. FAILED and REJECTED
// stay in the polling loop so an admin retry (or a manual approval that
// followed a delay) flows naturally back into 출력중 → 출력 완료 without
// the user ever knowing the print failed or was rejected.
const TERMINAL = new Set<JobStatus>([JobStatus.DONE])

// Collapse the backend status machine into the three user-facing phases.
// The admin-side detail (approval, rejection reason, printer failure) is
// deliberately not exposed — FAILED and REJECTED both surface as 대기중
// so the admin's existence stays invisible.
type UserPhase = 'waiting' | 'progress' | 'done'

function userPhase(s: JobStatus): UserPhase {
  if (s === JobStatus.PRINTING) return 'progress'
  if (s === JobStatus.DONE) return 'done'
  return 'waiting'
}

const PHASE_TITLE: Record<UserPhase, string> = {
  waiting: '대기중',
  progress: '출력중',
  done: '출력 완료',
}

const PHASE_TONE: Record<UserPhase, string> = {
  waiting: 'border-amber-300 bg-amber-50 text-amber-900',
  progress: 'border-blue-300 bg-blue-50 text-blue-900',
  done: 'border-emerald-300 bg-emerald-50 text-emerald-900',
}

function userSubtitle(s: JobStatus): string {
  if (s === JobStatus.PRINTING) return '출력 중입니다. 잠시만 기다려주세요.'
  if (s === JobStatus.DONE) return '출력물을 받아가세요.'
  // PENDING, APPROVED, FAILED, REJECTED — all share the same neutral copy
  // so the user can't tell the print failed or was rejected.
  return '순서를 기다리는 중입니다.'
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
          사진을 올리고 잠시 기다리면 인쇄됩니다.
        </p>
        <div className="mt-6">{children}</div>
      </main>
    </div>
  )
}

// Thresholds for the low-resolution warning. We expect images to print at
// 4x6 inches; 250 ppi (= 1500x1000 px on the rotated landscape image) is
// the line below which prints start looking soft to the average eye.
const LOW_RES_LONG_EDGE = 1500
const LOW_RES_SHORT_EDGE = 1000

type NormalizedImage = {
  file: File
  /** Width and height of the rotated landscape pixels; both 0 if the
   *  browser couldn't decode (e.g. HEIC outside Safari). */
  width: number
  height: number
}

// Normalize an upload so the backend always receives the image laid out
// in landscape (paper's long axis). EXIF orientation is baked into the
// pixels, and portrait sources are rotated 90° CW. Square images are
// passed through untouched — the print layer centers them with letterbox.
async function normalizeForPrint(file: File): Promise<NormalizedImage> {
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    // Browser can't decode (e.g. HEIC on a non-Safari browser). Hand the
    // original bytes to the backend; Pillow + pillow-heif will normalize
    // it server-side and the orientation guard will catch portrait inputs.
    return { file, width: 0, height: 0 }
  }

  const isPortrait = bitmap.height > bitmap.width
  const outW = isPortrait ? bitmap.height : bitmap.width
  const outH = isPortrait ? bitmap.width : bitmap.height

  const canvas = document.createElement('canvas')
  canvas.width = outW
  canvas.height = outH
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    bitmap.close()
    return { file, width: outW, height: outH }
  }

  if (isPortrait) {
    ctx.translate(outW, 0)
    ctx.rotate(Math.PI / 2)
    ctx.drawImage(bitmap, 0, 0)
  } else {
    ctx.drawImage(bitmap, 0, 0)
  }
  bitmap.close()

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', 0.92),
  )
  if (!blob) return { file, width: outW, height: outH }

  const baseName = file.name.replace(/\.[^.]+$/i, '') || 'photo'
  return {
    file: new File([blob], `${baseName}.jpg`, {
      type: 'image/jpeg',
      lastModified: Date.now(),
    }),
    width: outW,
    height: outH,
  }
}

function ImagePicker({
  file,
  disabled,
  onChange,
}: {
  file: File | null
  disabled: boolean
  onChange: (f: File | null) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [processing, setProcessing] = useState(false)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  const previewUrl = useMemo(() => {
    if (!file) return null
    return URL.createObjectURL(file)
  }, [file])
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  function openPicker() {
    if (disabled || processing) return
    inputRef.current?.click()
  }

  async function handleSelection(raw: File | null) {
    if (!raw) {
      setDims(null)
      onChange(null)
      return
    }
    setProcessing(true)
    try {
      const prepared = await normalizeForPrint(raw)
      setDims(
        prepared.width && prepared.height
          ? { w: prepared.width, h: prepared.height }
          : null,
      )
      onChange(prepared.file)
    } finally {
      setProcessing(false)
    }
  }

  const locked = disabled || processing
  const isLowRes =
    dims !== null &&
    (dims.w < LOW_RES_LONG_EDGE || dims.h < LOW_RES_SHORT_EDGE)

  return (
    <div className="mt-1">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        disabled={locked}
        onChange={(e) => {
          const raw = e.target.files?.[0] ?? null
          // Reset value so picking the same file again still re-runs.
          e.target.value = ''
          void handleSelection(raw)
        }}
        className="sr-only"
        aria-label="사진 선택"
      />
      <button
        type="button"
        onClick={openPicker}
        disabled={locked}
        aria-label={previewUrl ? '사진 변경' : '사진 선택'}
        className={
          'relative block w-full overflow-hidden rounded-xl text-left transition disabled:opacity-60 ' +
          (previewUrl
            ? 'border border-gray-300 bg-gray-100 hover:border-gray-400'
            : 'border-2 border-dashed border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100')
        }
      >
        {previewUrl ? (
          <img
            src={previewUrl}
            alt="선택한 사진"
            className="block max-h-80 w-full object-contain"
          />
        ) : (
          <div className="flex flex-col items-center justify-center px-4 py-16 text-gray-500">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-10 w-10"
              aria-hidden="true"
            >
              <rect x="3" y="5" width="18" height="14" rx="2" />
              <circle cx="12" cy="12" r="3" />
              <path d="M8 5l1.5-2h5L16 5" />
            </svg>
            <p className="mt-3 text-sm font-medium text-gray-700">
              사진을 선택하세요
            </p>
            <p className="mt-1 text-xs text-gray-500">탭하여 갤러리에서 선택</p>
          </div>
        )}
        {processing && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70 text-sm font-medium text-gray-700">
            사진 준비 중…
          </div>
        )}
      </button>
      {previewUrl && !processing && (
        <p className="mt-2 text-center text-xs text-gray-500">
          다시 탭하면 사진을 바꿀 수 있습니다.
        </p>
      )}
      {isLowRes && dims && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="mt-0.5 h-4 w-4 flex-shrink-0"
            aria-hidden="true"
          >
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          </svg>
          <div>
            <p className="font-medium">사진 해상도가 낮아요 ({dims.w}×{dims.h})</p>
            <p className="text-xs">인쇄 시 흐리게 보일 수 있어요. 그대로 진행하셔도 됩니다.</p>
          </div>
        </div>
      )}
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

        <div className="mt-4">
          <p className="text-sm font-medium text-gray-700">사진</p>
          <ImagePicker file={file} disabled={disabled} onChange={setFile} />
        </div>

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
  const phase = status ? userPhase(status) : null

  return (
    <Layout>
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        <p className="text-sm text-gray-500">요청자</p>
        <p className="text-lg font-medium text-gray-900">{name}</p>

        <div
          className={
            'mt-4 rounded-xl border px-4 py-3 ' +
            (phase ? PHASE_TONE[phase] : 'border-gray-200 bg-gray-50 text-gray-700')
          }
        >
          {query.isLoading && !phase && <p className="text-sm">상태 조회 중…</p>}
          {query.isError && (
            <p className="text-sm">상태를 가져오지 못했습니다. 잠시 후 다시 시도됩니다.</p>
          )}
          {phase && status && (
            <>
              <p className="text-base font-semibold">{PHASE_TITLE[phase]}</p>
              <p className="mt-0.5 text-sm">{userSubtitle(status)}</p>
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
