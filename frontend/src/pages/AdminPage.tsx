import { useMeApiAdminMeGet } from '../api/generated/printWeb'
import { Dashboard } from './admin/Dashboard'
import { LoginScreen } from './admin/LoginScreen'
import { Shell } from './admin/Shell'

export function AdminPage() {
  const me = useMeApiAdminMeGet({
    query: { staleTime: 30_000 },
  })

  if (me.isLoading) {
    return (
      <Shell>
        <p className="text-gray-500">확인 중…</p>
      </Shell>
    )
  }
  if (!me.data?.authenticated) {
    return <LoginScreen onLoggedIn={() => me.refetch()} />
  }
  return <Dashboard onLoggedOut={() => me.refetch()} />
}
