import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'

// Detect post-restore reload and force all queries to refetch.
// The _restored param is added by BackupPanel's reload logic.
const isPostRestore = new URL(window.location.href).searchParams.has('_restored')
if (isPostRestore) {
  const url = new URL(window.location.href)
  url.searchParams.delete('_restored')
  window.history.replaceState({}, '', url.toString())
}
import { queryClient } from './lib/queryClient'
import { router } from './router'
import { ThemeProvider } from './context/ThemeContext'
import { useUIStore } from './stores/uiStore'
import './styles.css'

// Monaco used to be configured here, which meant every visitor downloaded
// 3.8 MB of editor before the app rendered. It now loads on first use from
// components/k8s/MonacoEditor.tsx — still the locally bundled copy, never a
// CDN, because BNK clusters are routinely air-gapped.

// After a restore reload, nuke the entire query cache so no hook
// (even those with their own staleTime overrides) can serve pre-restore data.
if (isPostRestore) {
  queryClient.clear()
}

// Initialize theme from persisted state
const storedTheme = useUIStore.getState().theme
if (storedTheme === 'dark') {
  document.documentElement.classList.add('dark')
} else {
  document.documentElement.classList.remove('dark')
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider
          router={router}
          future={{
            v7_startTransition: true,
          }}
        />
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
