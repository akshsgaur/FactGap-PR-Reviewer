#!/usr/bin/env python3
"""
Full database reindexing script.

This script can index ALL connected repositories and Notion pages for ALL users,
or specific users/repos. Use with caution - this can be expensive!

Usage:
    # Index everything for all users
    python full_reindex.py --all

    # Index specific user
    python full_reindex.py --user-id <user_uuid>

    # Index specific repository
    python full_reindex.py --repo-id <repo_id>

    # Dry run (show what would be indexed)
    python full_reindex.py --all --dry-run

    # Force reindex (skip hash checks)
    python full_reindex.py --all --force
"""

import asyncio
import argparse
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.config import get_settings
from app.database import get_db, DatabaseManager
from app.services.indexing import get_indexing_service, IndexingService
from app.services.github_app import get_github_service, GitHubAppService
from app.services.notion_oauth import get_notion_service, NotionOAuthService


class FullReindexer:
    """Handles full database reindexing"""

    def __init__(self):
        self.settings = get_settings()
        self.db = get_db()
        self.indexing_service = get_indexing_service()
        self.github_service = get_github_service()
        self.notion_service = get_notion_service()

    async def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users with connected repositories"""
        try:
            # Get all users who have connected repos
            users = await self.db.client.table('connected_repos').select('user_id').execute()
            unique_user_ids = list(set(user['user_id'] for user in users.data))
            
            # Get full user details
            user_details = []
            for user_id in unique_user_ids:
                user = await self.db.client.auth.admin.get_user(user_id)
                if user.user:
                    user_details.append({
                        'id': user.user.id,
                        'email': user.user.email,
                        'github_app_installation_id': user.user.user_metadata.get('github_app_installation_id')
                    })
            
            return user_details
        except Exception as e:
            print(f"Error getting users: {e}")
            return []

    async def get_user_repos(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all connected repositories for a user"""
        try:
            repos = await self.db.get_connected_repos(user_id)
            return repos
        except Exception as e:
            print(f"Error getting repos for user {user_id}: {e}")
            return []

    async def get_user_notion_pages(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all connected Notion pages for a user"""
        try:
            pages = await self.db.get_connected_notion_pages(user_id)
            return pages
        except Exception as e:
            print(f"Error getting Notion pages for user {user_id}: {e}")
            return []

    async def index_repository(self, repo: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        """Index a single repository"""
        start_time = datetime.now()
        
        try:
            print(f"Indexing repository: {repo['repo_full_name']}")
            
            # Get GitHub installation ID
            user_repos = await self.db.get_connected_repos(repo['user_id'])
            user_repo = next((r for r in user_repos if r['id'] == repo['id']), None)
            
            if not user_repo:
                return {'error': 'Repository not found for user'}
            
            # Get installation ID from user metadata
            user = await self.db.client.auth.admin.get_user(repo['user_id'])
            installation_id = user.user.user_metadata.get('github_app_installation_id')
            
            if not installation_id:
                return {'error': 'GitHub App not installed for user'}
            
            # Index the repository
            result = await self.indexing_service.index_repository(
                repo_id=repo['id'],
                installation_id=installation_id,
                force_reindex=force
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': True,
                'repo_full_name': repo['repo_full_name'],
                'chunks_indexed': result.get('chunks_indexed', 0),
                'duration': duration,
                'skipped': result.get('skipped', 0)
            }
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return {
                'success': False,
                'repo_full_name': repo['repo_full_name'],
                'error': str(e),
                'duration': duration
            }

    async def index_notion_page(self, page: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        """Index a single Notion page"""
        start_time = datetime.now()
        
        try:
            print(f"Indexing Notion page: {page['title']}")
            
            # Index the page
            result = await self.indexing_service.index_notion_page(
                page_id=page['notion_page_id'],
                user_id=page['user_id'],
                force_reindex=force
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': True,
                'page_title': page['title'],
                'chunks_indexed': result.get('chunks_indexed', 0),
                'duration': duration,
                'skipped': result.get('skipped', 0)
            }
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return {
                'success': False,
                'page_title': page['title'],
                'error': str(e),
                'duration': duration
            }

    async def index_all(self, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """Index everything for all users"""
        print("🚀 Starting full database reindex...")
        
        if dry_run:
            print("🔍 DRY RUN MODE - No actual indexing will be performed")
        
        # Get all users
        users = await self.get_all_users()
        print(f"Found {len(users)} users with connected repositories")
        
        total_stats = {
            'users': 0,
            'repos': 0,
            'notion_pages': 0,
            'repo_chunks': 0,
            'notion_chunks': 0,
            'repo_skipped': 0,
            'notion_skipped': 0,
            'errors': 0,
            'duration': 0
        }
        
        start_time = datetime.now()
        
        for user in users:
            print(f"\n👤 Processing user: {user['email']} ({user['id']})")
            total_stats['users'] += 1
            
            # Get user's repositories
            repos = await self.get_user_repos(user['id'])
            print(f"  📁 Found {len(repos)} repositories")
            
            # Get user's Notion pages
            notion_pages = await self.get_user_notion_pages(user['id'])
            print(f"  📄 Found {len(notion_pages)} Notion pages")
            
            if dry_run:
                total_stats['repos'] += len(repos)
                total_stats['notion_pages'] += len(notion_pages)
                for repo in repos:
                    print(f"    📁 Would index: {repo['repo_full_name']}")
                for page in notion_pages:
                    print(f"    📄 Would index: {page['title']}")
                continue
            
            # Index repositories
            for repo in repos:
                if not repo['is_active']:
                    print(f"    ⏭️  Skipping inactive repo: {repo['repo_full_name']}")
                    continue
                
                result = await self.index_repository(repo, force=force)
                
                if result['success']:
                    total_stats['repos'] += 1
                    total_stats['repo_chunks'] += result.get('chunks_indexed', 0)
                    total_stats['repo_skipped'] += result.get('skipped', 0)
                    print(f"    ✅ {repo['repo_full_name']}: {result.get('chunks_indexed', 0)} chunks, {result.get('skipped', 0)} skipped")
                else:
                    total_stats['errors'] += 1
                    print(f"    ❌ {repo['repo_full_name']}: {result['error']}")
            
            # Index Notion pages
            for page in notion_pages:
                if not page['is_active']:
                    print(f"    ⏭️  Skipping inactive page: {page['title']}")
                    continue
                
                result = await self.index_notion_page(page, force=force)
                
                if result['success']:
                    total_stats['notion_pages'] += 1
                    total_stats['notion_chunks'] += result.get('chunks_indexed', 0)
                    total_stats['notion_skipped'] += result.get('skipped', 0)
                    print(f"    ✅ {page['title']}: {result.get('chunks_indexed', 0)} chunks, {result.get('skipped', 0)} skipped")
                else:
                    total_stats['errors'] += 1
                    print(f"    ❌ {page['title']}: {result['error']}")
        
        total_stats['duration'] = (datetime.now() - start_time).total_seconds()
        
        return total_stats

    async def index_user(self, user_id: str, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """Index everything for a specific user"""
        print(f"👤 Starting reindex for user: {user_id}")
        
        if dry_run:
            print("🔍 DRY RUN MODE - No actual indexing will be performed")
        
        # Get user details
        user = await self.db.client.auth.admin.get_user(user_id)
        if not user.user:
            return {'error': 'User not found'}
        
        print(f"User email: {user.user.email}")
        
        # Get user's repositories
        repos = await self.get_user_repos(user_id)
        print(f"Found {len(repos)} repositories")
        
        # Get user's Notion pages
        notion_pages = await self.get_user_notion_pages(user_id)
        print(f"Found {len(notion_pages)} Notion pages")
        
        if dry_run:
            stats = {
                'repos': len(repos),
                'notion_pages': len(notion_pages),
                'dry_run': True
            }
            for repo in repos:
                print(f"  📁 Would index: {repo['repo_full_name']}")
            for page in notion_pages:
                print(f"  📄 Would index: {page['title']}")
            return stats
        
        # Index everything
        stats = {
            'repos': 0,
            'notion_pages': 0,
            'repo_chunks': 0,
            'notion_chunks': 0,
            'repo_skipped': 0,
            'notion_skipped': 0,
            'errors': 0
        }
        
        start_time = datetime.now()
        
        # Index repositories
        for repo in repos:
            if not repo['is_active']:
                continue
            
            result = await self.index_repository(repo, force=force)
            
            if result['success']:
                stats['repos'] += 1
                stats['repo_chunks'] += result.get('chunks_indexed', 0)
                stats['repo_skipped'] += result.get('skipped', 0)
            else:
                stats['errors'] += 1
        
        # Index Notion pages
        for page in notion_pages:
            if not page['is_active']:
                continue
            
            result = await self.index_notion_page(page, force=force)
            
            if result['success']:
                stats['notion_pages'] += 1
                stats['notion_chunks'] += result.get('chunks_indexed', 0)
                stats['notion_skipped'] += result.get('skipped', 0)
            else:
                stats['errors'] += 1
        
        stats['duration'] = (datetime.now() - start_time).total_seconds()
        
        return stats


async def main():
    parser = argparse.ArgumentParser(description='Full database reindexing')
    parser.add_argument('--all', action='store_true', help='Index everything for all users')
    parser.add_argument('--user-id', help='Index everything for specific user ID')
    parser.add_argument('--repo-id', type=int, help='Index specific repository ID')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be indexed without doing it')
    parser.add_argument('--force', action='store_true', help='Force reindex (skip hash checks)')
    
    args = parser.parse_args()
    
    if not any([args.all, args.user_id, args.repo_id]):
        print("Error: Must specify one of --all, --user-id, or --repo-id")
        sys.exit(1)
    
    reindexer = FullReindexer()
    
    try:
        if args.all:
            stats = await reindexer.index_all(force=args.force, dry_run=args.dry_run)
        elif args.user_id:
            stats = await reindexer.index_user(args.user_id, force=args.force, dry_run=args.dry_run)
        elif args.repo_id:
            # Get repository details
            repos = await reindexer.db.client.table('connected_repos').select('*').eq('id', args.repo_id).execute()
            if not repos.data:
                print(f"Error: Repository {args.repo_id} not found")
                sys.exit(1)
            
            repo = repos.data[0]
            
            if args.dry_run:
                print(f"Would index repository: {repo['repo_full_name']}")
                stats = {'dry_run': True}
            else:
                result = await reindexer.index_repository(repo, force=args.force)
                stats = {
                    'repos': 1 if result['success'] else 0,
                    'repo_chunks': result.get('chunks_indexed', 0) if result['success'] else 0,
                    'repo_skipped': result.get('skipped', 0) if result['success'] else 0,
                    'errors': 0 if result['success'] else 1,
                    'duration': result.get('duration', 0)
                }
        
        # Print summary
        print("\n" + "="*60)
        print("📊 REINDEX SUMMARY")
        print("="*60)
        
        if args.dry_run:
            print(f"🔍 Dry run completed")
            if 'users' in stats:
                print(f"👤 Users: {stats['users']}")
            print(f"📁 Repositories: {stats['repos']}")
            print(f"📄 Notion pages: {stats['notion_pages']}")
        else:
            if 'users' in stats:
                print(f"👤 Users processed: {stats['users']}")
            print(f"📁 Repositories indexed: {stats['repos']}")
            print(f"📄 Notion pages indexed: {stats['notion_pages']}")
            print(f"🔧 Repo chunks: {stats['repo_chunks']}")
            print(f"📝 Notion chunks: {stats['notion_chunks']}")
            print(f"⏭️  Repo skipped: {stats['repo_skipped']}")
            print(f"⏭️  Notion skipped: {stats['notion_skipped']}")
            print(f"❌ Errors: {stats['errors']}")
            print(f"⏱️  Duration: {stats['duration']:.2f}s")
        
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n⚠️  Reindex interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during reindex: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
