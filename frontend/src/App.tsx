import type { ReactNode } from 'react'
import { Navigate, Routes, Route, Link } from 'react-router-dom'
import Nav from './components/Nav'
import AlertsSidebar from './components/AlertsSidebar'
import Home from './pages/Home'
import MatchAnalysis from './pages/MatchAnalysis'
import NewAnalysis from './pages/NewAnalysis'
import ModelPerformance from './pages/ModelPerformance'
import Users from './pages/Users'
import Status from './pages/Status'
import SignIn, { AuthScreen } from './pages/SignIn'
import { StoreProvider, useStore } from './store'
import { useAuth } from './auth'
import { Spinner, btnGhost } from './components/ui'

/** Signed in: the app (its store polls the API). Otherwise: loading / sign-in, and no polling. */
export default function App() {
  const { state, retry } = useAuth()
  if (state.status === 'loading') {
    return <AuthScreen><span className="text-text-muted"><Spinner /></span></AuthScreen>
  }
  if (state.status === 'error') {
    return (
      <AuthScreen>
        <div className="text-xs text-red-400">{state.message}</div>
        <button className={btnGhost} onClick={retry}>Retry</button>
      </AuthScreen>
    )
  }
  if (state.status === 'signedOut') return <SignIn notice={state.notice} />
  return (
    // Keyed by user so a different account never sees the previous one's state.
    <StoreProvider key={state.user.id}>
      <Shell />
    </StoreProvider>
  )
}

function Shell() {
  const { sidebarOpen } = useStore()
  const { can } = useAuth()
  return (
    <div className="min-h-full">
      <Nav />
      <main className={`px-6 py-6 ${sidebarOpen ? 'pr-[444px]' : ''}`}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/games/:id" element={<MatchAnalysis />} />
          <Route path="/new" element={can('reviewer') ? <NewAnalysis /> : <Denied>Viewers can't start analyses.</Denied>} />
          <Route path="/test" element={<Navigate to="/new" replace />} />
          <Route path="/performance" element={<ModelPerformance />} />
          <Route path="/status" element={<Status />} />
          <Route path="/admin" element={<Navigate to="/admin/users" replace />} />
          <Route path="/admin/users" element={can('admin') ? <Users /> : <Denied>Admins only.</Denied>} />
        </Routes>
      </main>
      <AlertsSidebar />
    </div>
  )
}

function Denied({ children }: { children: ReactNode }) {
  return (
    <div className="text-sm text-text-muted">
      {children} <Link to="/" className="underline">Games</Link>
    </div>
  )
}
