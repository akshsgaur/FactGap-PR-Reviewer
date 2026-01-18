'use client'

import { useEffect, useState } from 'react'
import { useAuth } from '@/lib/auth'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'

interface NotionPage {
  id: string
  title: string
  url: string
  is_connected: boolean
}

interface ConnectedNotionPage {
  id: string
  notion_page_id: string
  notion_page_title: string | null
  is_active: boolean
  indexing_status: string
}

export default function NotionPage() {
  const { user, refreshUser } = useAuth()
  const [pages, setPages] = useState<NotionPage[]>([])
  const [connectedPages, setConnectedPages] = useState<ConnectedNotionPage[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [connectingNotion, setConnectingNotion] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPages = async () => {
    if (!user?.has_notion_connected) {
      setLoading(false)
      return
    }

    try {
      setError(null)
      const [pagesData, connectedData] = await Promise.all([
        api.listNotionPages(),
        api.listConnectedNotionPages(),
      ])
      setPages(pagesData)
      setConnectedPages(connectedData)
    } catch (err) {
      console.error('Failed to fetch Notion pages:', err)
      setError(err instanceof Error ? err.message : 'Failed to fetch Notion pages')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPages()
  }, [user?.has_notion_connected])

  // Check for connection status in URL params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('connected') === 'true') {
      refreshUser()
      // Clean up URL
      window.history.replaceState({}, '', '/dashboard/notion')
    }
    if (params.get('error')) {
      setError('Failed to connect Notion. Please try again.')
      window.history.replaceState({}, '', '/dashboard/notion')
    }
  }, [refreshUser])

  const handleConnectNotion = async () => {
    setConnectingNotion(true)
    try {
      const { url } = await api.getNotionAuthUrl()
      window.location.href = url
    } catch (err) {
      console.error('Failed to get Notion auth URL:', err)
      setError('Failed to start Notion connection')
      setConnectingNotion(false)
    }
  }

  const handleToggle = async (page: NotionPage) => {
    setActionLoading(page.id)
    try {
      if (page.is_connected) {
        await api.disableNotionPage(page.id)
      } else {
        await api.enableNotionPage(page.id, page.title)
      }
      await fetchPages()
    } catch (err) {
      console.error('Failed to toggle Notion page:', err)
      setError(err instanceof Error ? err.message : 'Failed to update Notion page')
    } finally {
      setActionLoading(null)
    }
  }

  const handleReindex = async (pageId: string) => {
    setActionLoading(pageId)
    try {
      await api.reindexNotionPage(pageId)
      await fetchPages()
    } catch (err) {
      console.error('Failed to reindex Notion page:', err)
      setError(err instanceof Error ? err.message : 'Failed to reindex Notion page')
    } finally {
      setActionLoading(null)
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'complete':
        return <Badge variant="success">Indexed</Badge>
      case 'indexing':
        return <Badge variant="warning">Indexing...</Badge>
      case 'error':
        return <Badge variant="destructive">Error</Badge>
      default:
        return <Badge variant="secondary">Pending</Badge>
    }
  }

  const getConnectedPage = (pageId: string): ConnectedNotionPage | undefined => {
    return connectedPages.find(p => p.notion_page_id === pageId)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-pulse text-lg">Loading Notion pages...</div>
      </div>
    )
  }

  if (!user?.has_notion_connected) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Notion Integration</h1>
          <p className="text-muted-foreground">
            Connect your Notion workspace to enable RAG over your documentation
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Connect Notion</CardTitle>
            <CardDescription>
              Allow FactGap to access your Notion pages for context during PR reviews
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-sm text-muted-foreground space-y-2">
              <p>By connecting Notion, the PR reviewer will be able to:</p>
              <ul className="list-inside list-disc space-y-1">
                <li>Reference your team's documentation in reviews</li>
                <li>Cite policies and guidelines when making recommendations</li>
                <li>Answer questions using your Notion knowledge base</li>
              </ul>
            </div>
            <Button
              onClick={handleConnectNotion}
              disabled={connectingNotion}
            >
              {connectingNotion ? 'Connecting...' : 'Connect Notion'}
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Notion Integration</h1>
        <p className="text-muted-foreground">
          Select Notion pages to include in your PR review context
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Available Pages</CardTitle>
          <CardDescription>
            Pages accessible via your Notion connection
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pages.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground">
              <p>No pages found.</p>
              <p className="text-sm mt-2">
                Make sure you've shared pages with the FactGap integration in Notion.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {pages.map((page) => {
                const connected = getConnectedPage(page.id)
                return (
                  <div
                    key={page.id}
                    className="flex items-center justify-between rounded-lg border p-4"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <h3 className="font-medium">{page.title}</h3>
                        {connected && getStatusBadge(connected.indexing_status)}
                      </div>
                      <a
                        href={page.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-muted-foreground hover:underline"
                      >
                        Open in Notion &rarr;
                      </a>
                    </div>
                    <div className="flex items-center gap-4">
                      {connected && connected.indexing_status === 'complete' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReindex(page.id)}
                          disabled={actionLoading === page.id}
                        >
                          Reindex
                        </Button>
                      )}
                      <Switch
                        checked={page.is_connected}
                        onCheckedChange={() => handleToggle(page)}
                        disabled={actionLoading === page.id}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {connectedPages.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Connected Pages</CardTitle>
            <CardDescription>
              These pages are included in your PR review context
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-muted-foreground">
              <p>Connected Notion pages will be used to:</p>
              <ul className="list-inside list-disc mt-2 space-y-1">
                <li>Provide context for PR analysis</li>
                <li>Answer @code-reviewer questions</li>
                <li>Cite guidelines and policies in reviews</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
