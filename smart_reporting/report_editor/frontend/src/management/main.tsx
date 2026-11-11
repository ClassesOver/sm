import React from 'react'
import { createRoot } from 'react-dom/client'
import { ManagementApp } from './app'
import './styles/layout.css'

createRoot(document.getElementById('management-root')!).render(
  <ManagementApp />,
)
