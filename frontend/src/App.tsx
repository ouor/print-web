import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AdminPage } from './pages/AdminPage'
import { UserPage } from './pages/UserPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<UserPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
