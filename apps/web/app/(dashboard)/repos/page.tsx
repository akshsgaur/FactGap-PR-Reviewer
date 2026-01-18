'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'

interface Repo {
  id: number
  full_name: string
  private: boolean
  description: string | null
  is_connected: boolean
}

interface ConnectedRepo {
  id: string
  github_repo_id: number
  repo_full_name: string
  is_active: boolean
  indexing_status: string
  last_indexed_at: string | null
}

export default function ReposPage() {
  const [repos, setRepos] = useState<Repo[]>([])
  const [connectedRepos, setConnectedRepos] = useState<ConnectedRepo[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchRepos = async () => {
    try {
      setError(null)
      const [reposData, connectedData] = await Promise.all([
        api.listRepos(),
        api.listConnectedRepos(),
      ])
      setRepos(reposData)
      setConnectedRepos(connectedData)
    } catch (err) {
      console.error('Failed to fetch repos:', err)
      setError(err instanceof Error ? err.message : 'Failed to fetch repositories')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRepos()
  }, [])

  const handleToggle = async (repo: Repo) => {
    setActionLoading(repo.id)
    try {
      if (repo.is_connected) {
        await api.disableRepo(repo.id)
      } else {
        await api.enableRepo(repo.id, repo.full_name)
      }
      await fetchRepos()
    } catch (err) {
      console.error('Failed to toggle repo:', err)
      setError(err instanceof Error ? err.message : 'Failed to update repository')
    } finally {
      setActionLoading(null)
    }
  }

  const handleReindex = async (repoId: number) => {
    setActionLoading(repoId)
    try {
      await api.reindexRepo(repoId)
      await fetchRepos()
    } catch (err) {
      console.error('Failed to reindex repo:', err)
      setError(err instanceof Error ? err.message : 'Failed to reindex repository')
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

  const getConnectedRepo = (repoId: number): ConnectedRepo | undefined => {
    return connectedRepos.find(r => r.github_repo_id === repoId)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-pulse text-lg">Loading repositories...</div>
      </div>
    )
  }

  if (error && repos.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Repositories</h1>
          <p className="text-muted-foreground">
            Select repositories to enable PR analysis
          </p>
        </div>
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-destructive mb-4">{error}</p>
            <p className="text-sm text-muted-foreground mb-4">
              Make sure you have installed the FactGap GitHub App on your account or organization.
            </p>
            <Button onClick={fetchRepos}>Try Again</Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Repositories</h1>
        <p className="text-muted-foreground">
          Select repositories to enable PR analysis. Connected repos will be indexed and analyzed automatically.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Available Repositories</CardTitle>
          <CardDescription>
            Repositories accessible via your GitHub App installation
          </CardDescription>
        </CardHeader>
        <CardContent>
          {repos.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground">
              <p>No repositories found.</p>
              <p className="text-sm mt-2">
                Install the FactGap GitHub App on repositories you want to analyze.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {repos.map((repo) => {
                const connected = getConnectedRepo(repo.id)
                return (
                  <div
                    key={repo.id}
                    className="flex items-center justify-between rounded-lg border p-4"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <h3 className="font-medium">{repo.full_name}</h3>
                        {repo.private && (
                          <Badge variant="outline">Private</Badge>
                        )}
                        {connected && getStatusBadge(connected.indexing_status)}
                      </div>
                      {repo.description && (
                        <p className="text-sm text-muted-foreground mt-1">
                          {repo.description}
                        </p>
                      )}
                      {connected?.last_indexed_at && (
                        <p className="text-xs text-muted-foreground mt-1">
                          Last indexed: {new Date(connected.last_indexed_at).toLocaleString()}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-4">
                      {connected && connected.indexing_status === 'complete' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReindex(repo.id)}
                          disabled={actionLoading === repo.id}
                        >
                          Reindex
                        </Button>
                      )}
                      <Switch
                        checked={repo.is_connected}
                        onCheckedChange={() => handleToggle(repo)}
                        disabled={actionLoading === repo.id}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {connectedRepos.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Connected Repositories</CardTitle>
            <CardDescription>
              These repositories are actively monitored for PRs
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-muted-foreground">
              <p>When a PR is opened or updated in these repositories:</p>
              <ul className="list-inside list-disc mt-2 space-y-1">
                <li>The PR content is automatically indexed</li>
                <li>An analysis comment is posted with cited evidence</li>
                <li>You can ask questions using @code-reviewer mentions</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
