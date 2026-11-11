import React, { useState } from 'react'
import { RouterProvider } from 'react-router-dom'
import { Providers } from './app/providers'
import { makeRouter } from './app/router'
export function ManagementApp() {
  const [router] = useState(makeRouter)
  return (
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  )
}
