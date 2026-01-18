'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export default function AuthCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { refreshUser } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = searchParams.get('token')
    const errorParam = searchParams.get('error')

    if (errorParam) {
      setError(errorParam)
      return
    }

    if (token) {
      api.setToken(token)
      refreshUser().then(() => {
        router.push('/dashboard')
      }).catch((err) => {
        console.error('Failed to refresh user:', err)
        setError('Failed to authenticate')
      })
    } else {
      setError('No authentication token received')
    }
  }, [searchParams, router, refreshUser])

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4">
        <div className="text-lg text-red-500">Authentication failed: {error}</div>
        <a href="/login" className="text-primary underline">
          Try again
        </a>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-2">
        <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full"></div>
        <div className="text-lg">Completing authentication...</div>
      </div>
    </div>
  )
}
