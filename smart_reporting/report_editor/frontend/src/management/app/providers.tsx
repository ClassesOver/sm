import React, { useState } from 'react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { managementTheme } from '../styles/tokens'
import { SessionProvider } from './session'
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
          mutations: { retry: false, gcTime: 0 },
        },
      }),
  )
  return (
    <ConfigProvider
      button={{ autoInsertSpace: false }}
      locale={zhCN}
      theme={managementTheme}
    >
      <QueryClientProvider client={client}>
        <SessionProvider>{children}</SessionProvider>
      </QueryClientProvider>
    </ConfigProvider>
  )
}
