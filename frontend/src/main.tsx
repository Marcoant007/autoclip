import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { App } from './App'
import './index.css'
import { Create, CreationReview } from './pages/Create'
import { Home } from './pages/Home'
import { Ingest } from './pages/Ingest'
import { JobProgress } from './pages/JobProgress'
import { Review } from './pages/Review'
import { Settings } from './pages/Settings'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Home /> },
      { path: 'clips', element: <Ingest /> },
      { path: 'create', element: <Create /> },
      { path: 'create/:creationId', element: <CreationReview /> },
      { path: 'jobs/:jobId', element: <JobProgress /> },
      { path: 'jobs/:jobId/clips', element: <Review /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
