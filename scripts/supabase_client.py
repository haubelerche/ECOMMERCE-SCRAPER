import os
from typing import Any, Dict, Optional

try:
    from supabase import create_client, Client
except Exception:
    # Defer import error until runtime if package missing — helpful for quick lint/syntax checks
    create_client = None
    Client = None


class SupabaseClient:
    """Minimal wrapper around supabase-py to insert/select rows.

    Requires SUPABASE_URL and SUPABASE_API_KEY set in environment.
    """

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize Supabase client.
        
        Args:
            url: Supabase URL (defaults to SUPABASE_URL env var)
            api_key: Supabase API key (defaults to SUPABASE_API_KEY env var)
        """
        supabase_url = url or os.getenv("SUPABASE_URL")
        supabase_api_key = api_key or os.getenv("SUPABASE_API_KEY")
        
        if not supabase_url or not supabase_api_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_API_KEY must be set in environment")
        if create_client is None:
            raise RuntimeError("supabase package is not installed. Add 'supabase' to requirements.txt and pip install -r requirements.txt")

        # avoid using forward type annotation here because the supabase Client symbol may not be present
        self.client = create_client(supabase_url, supabase_api_key)

    def insert(self, table: str, record: Dict[str, Any]) -> Any:
        """Insert a single record into a table. Returns inserted data or raises RuntimeError."""
        res = self.client.table(table).insert(record).execute()
        if getattr(res, "error", None):
            raise RuntimeError(res.error)
        return getattr(res, "data", None)

    def upsert(self, table: str, record: Dict[str, Any], on_conflict: Optional[str] = None) -> Any:
        """Upsert a record (insert or update on conflict). Returns upserted data or raises RuntimeError."""
        res = self.client.table(table).upsert(record, on_conflict=on_conflict).execute()
        if getattr(res, "error", None):
            raise RuntimeError(res.error)
        return getattr(res, "data", None)

    def select(self, table: str, columns: str = "*", match: Optional[Dict] = None) -> Any:
        q = self.client.table(table).select(columns)
        if match:
            q = q.match(match)
        res = q.execute()
        if getattr(res, "error", None):
            raise RuntimeError(res.error)
        return getattr(res, "data", None)
    
    def text_search(self, table: str, column: str, query: str, columns: str = "*", config: str = "english") -> Any:
        """Full-text search using PostgreSQL text search with ranking.
        
        Args:
            table: Table name to search in
            column: Column name to search (e.g., 'product_name')
            query: Search query text
            columns: Columns to return (default: "*")
            config: Text search configuration (default: "english")
        
        Returns:
            Matched rows ordered by relevance
        """
        q = self.client.table(table).select(columns)
        q = q.text_search(column, f"'{query}'", config=config)
        res = q.execute()
        if getattr(res, "error", None):
            raise RuntimeError(res.error)
        return getattr(res, "data", None)

    def rpc(self, function_name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Call a PostgreSQL function via Supabase RPC. Returns function result or raises RuntimeError."""
        res = self.client.rpc(function_name, params or {}).execute()
        if getattr(res, "error", None):
            raise RuntimeError(res.error)
        return getattr(res, "data", None)