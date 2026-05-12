import { useState } from 'react'

import { useLoginApiAdminLoginPost } from '../../api/generated/printWeb'
import { Shell } from './Shell'

export function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
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
