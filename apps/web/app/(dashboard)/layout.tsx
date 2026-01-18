'use client'

import { useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { user, loading, logout } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login')
    }
  }, [user, loading, router])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse text-lg">Loading...</div>
      </div>
    )
  }

  if (!user) {
    return null
  }

  const navItems = [
    { href: '/dashboard', label: 'Overview' },
    { href: '/dashboard/repos', label: 'Repositories' },
    { href: '/dashboard/notion', label: 'Notion' },
  ]

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-14 items-center">
          <div className="mr-4 flex">
            <Link href="/dashboard" className="mr-6 flex items-center space-x-2">
              <span className="font-bold">FactGap</span>
            </Link>
            <nav className="flex items-center space-x-6 text-sm font-medium">
              {navItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`transition-colors hover:text-foreground/80 ${
                    pathname === item.href
                      ? 'text-foreground'
                      : 'text-foreground/60'
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex flex-1 items-center justify-end space-x-4">
            <span className="text-sm text-muted-foreground">
              {user.github_login}
            </span>
            <Button variant="ghost" size="sm" onClick={logout}>
              Logout
            </Button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="container py-6">{children}</main>
    </div>
  )
}
