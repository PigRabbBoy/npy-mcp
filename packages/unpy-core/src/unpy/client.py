import hashlib
import json
import re
import uuid

from requests import Session, HTTPError
from requests.cookies import create_cookie
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from getpass import getpass

from .block import Block, BLOCK_TYPES
from .collection import (
    Collection,
    CollectionView,
    CollectionRowBlock,
    COLLECTION_VIEW_TYPES,
    TemplateBlock,
)
from .config import batch_max_ops
from .logger import logger
from .monitor import Monitor
from .operations import operation_update_last_edited, build_operation
from .settings import API_BASE_URL
from .space import Space
from .store import RecordStore, unwrap_record
from .user import User
from .utils import extract_id, now


def creval_get(crec):
    """Unwrap a comment record from the store (handles both flat and
    nested value.value shapes)."""
    if not isinstance(crec, dict):
        return None
    if "text" in crec or "parent_table" in crec:
        return crec  # already the flat comment value
    v = crec.get("value")
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    return v if isinstance(v, dict) else None


class _MissingPlaceholder:
    pass


Missing_placeholder = _MissingPlaceholder()


def _discussion_context(client, dval, recordmap):
    """Best-effort text snippet the discussion was started on."""
    pid = dval.get("parent_id")
    brec = (recordmap.get("block") or {}).get(pid) or {}
    bval = ((brec.get("value") or {}).get("value")) or brec.get("value") or brec
    props = bval.get("properties") or {} if isinstance(bval, dict) else {}
    title = props.get("title") or []
    parts = []
    for seg in title:
        if isinstance(seg, list) and seg:
            parts.append(str(seg[0]))
    return "".join(parts)


def create_session(client_specified_retry=None):
    """
    retry on 502
    """
    session = Session()
    if client_specified_retry:
        retry = client_specified_retry
    else:
        retry = Retry(
            total=10,
            backoff_factor=1,
            status_forcelist=(429, 502, 503, 504),
            # CAUTION: adding 'POST' to this list which is not technically idempotent
            allowed_methods=(
                "POST",
                "HEAD",
                "TRACE",
                "GET",
                "PUT",
                "OPTIONS",
                "DELETE",
            ),
        )
    # v2: size the connection pool to the fan-out worker count so threads
    # don't queue behind urllib3's default pool of 10 (or fight with
    # pool_block=True-style serialization)
    from .config import max_workers

    pool = max(10, max_workers() * 2)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    session.mount("https://", adapter)
    # Mimic browser headers to avoid bot detection / rate-limit differences
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://app.notion.com/",
        "Origin": "https://app.notion.com",
    })
    return session


class NotionClient(object):
    """
    This is the entry point to using the API. Create an instance of this class, passing it the value of the
    "token_v2" cookie from a logged-in browser session on Notion.so. Most of the methods on here are primarily
    for internal use -- the main one you'll likely want to use is `get_block`.
    """

    def __init__(
        self,
        token_v2=None,
        monitor=False,
        start_monitoring=False,
        enable_caching=False,
        cache_key=None,
        email=None,
        password=None,
        client_specified_retry=None,
    ):
        self.session = create_session(client_specified_retry)
        if token_v2:
            # Scope the session cookie to Notion hosts only. A cookie created
            # without a domain (cookiejar_from_dict) is attached to EVERY
            # request the session makes — external image sources, S3
            # presigned URLs, redirects — which leaks the session token.
            for domain in (".notion.com", ".notion.so"):
                self.session.cookies.set_cookie(
                    create_cookie(
                        "token_v2", token_v2, domain=domain, path="/", secure=True
                    )
                )
        else:
            self._set_token(email=email, password=password)

        if enable_caching:
            cache_key = cache_key or hashlib.sha256(token_v2.encode()).hexdigest()
            self._store = RecordStore(self, cache_key=cache_key)
        else:
            self._store = RecordStore(self)
        if monitor:
            self._monitor = Monitor(self)
            if start_monitoring:
                self.start_monitoring()
        else:
            self._monitor = None

        self._update_user_info()

    def start_monitoring(self):
        self._monitor.poll_async()
    
    def _fetch_space_data(self, records, space_id):
        """
        guest users have an empty `space` dict, so get the space_id from the `space_view` dict instead,
        and fetch the space data from the getPublicSpaceData endpoint.

        Note: This mutates the records dict
        """

        if not space_id:
            return

        space_data = self.post(
            "getPublicSpaceData", {"type": "space-ids", "spaceIds": [space_id]}
        ).json()

        records["space"] = {
            space["id"]: {"value": space} for space in space_data["results"]
        }


    def _set_token(self, email=None, password=None):
        if not email:
            email = input("Enter your Notion email address:\n")
        if not password:
            password = getpass("Enter your Notion password:\n")
        self.post("loginWithEmail", {"email": email, "password": password}).json()

    def _update_user_info(self):
        records = self.post("loadUserContent", {}).json()["recordMap"]
        user_id = list(records["notion_user"].keys())[0]

        # handle both old {"value": {...data}} and new
        # {"value": {"value": {...data}, "role": "..."}} nesting per record;
        # tolerate a missing user_root table or no space pointers (guests)
        space_id = None
        user_root_record = records.get("user_root", {}).get(user_id)
        user_root_value, _ = unwrap_record(user_root_record)
        space_view_pointers = (user_root_value or {}).get("space_view_pointers", [])
        if space_view_pointers:
            space_id = space_view_pointers[0].get("spaceId")
        self._fetch_space_data(records, space_id)

        self._store.store_recordmap(records)
        self.current_user = self.get_user(list(records["notion_user"].keys())[0])
        space_ids = list(records.get("space", {}).keys())
        self.current_space = self.get_space(space_ids[0]) if space_ids else None
        return records

    def get_email_uid(self):
        response = self.post("getSpaces", {}).json()
        return {
            response[uid]["notion_user"][uid]["value"]["email"]: uid
            for uid in response.keys()
        }

    def set_user_by_uid(self, user_id):
        self.session.headers.update({"x-notion-active-user-header": user_id})
        self._update_user_info()

    def set_user_by_email(self, email):
        email_uid_dict = self.get_email_uid()
        uid = email_uid_dict.get(email)
        if not uid:
            raise Exception(
                "Requested email address {email} not found; available addresses: {available}".format(
                    email=email, available=list(email_uid_dict)
                )
            )
        self.set_user_by_uid(uid)

    def get_top_level_pages(self):
        records = self._update_user_info()
        block_ids = list(records["block"].keys())
        # v2: one batched fetch for all top-level page ids (was sequential)
        if block_ids:
            try:
                self.refresh_records(block=block_ids)
            except Exception:
                pass
        return [self.get_block(bid) for bid in block_ids]

    def get_comments(self, block_id, include_resolved=True):
        """Return all discussions + comments attached to a block (page).

        Discussions live in the page's recordMap (loadPageChunk); each
        discussion record has parent_id = the commented block, and its
        `comments` list holds comment record ids resolved via
        syncRecordValues.

        Returns a list of dicts:
            {"id": <discussion id>,
             "context": <title-ish text the comment was started on>,
             "resolved": bool,
             "comments": [{"id", "author", "text", "created_time",
                           "last_edited_time", "alive"}, ...]}
        """
        from datetime import datetime

        block_id = extract_id(block_id)
        data = self.get_record_data("block", block_id, force_refresh=True)
        if not data:
            return []
        # Discussions ride along in the loadPageChunk recordmap of the block
        # itself (page or any block inside a page — the chunk covers the
        # enclosing page). No parent-walking needed.
        page_id = block_id
        try:
            resp = self.post(
                "loadPageChunk",
                {
                    "pageId": page_id,
                    "limit": 100,
                    "cursor": {"stack": []},
                    "chunkNumber": 0,
                    "verticalColumns": False,
                },
            ).json()
        except Exception:
            return []
        recordmap = resp.get("recordMap", {})
        discussions = []
        dval_map = {}
        fresh_comment_ids = {}
        all_comment_ids = set()
        for did, drec in (recordmap.get("discussion") or {}).items():
            dval = ((drec or {}).get("value") or {}).get("value") or drec.get(
                "value"
            ) or {}
            if not dval or dval.get("parent_id") != block_id:
                continue
            if dval.get("resolved") and not include_resolved:
                continue
            # the recordmap's comment list can be stale — always re-sync the
            # discussion record itself for the authoritative comments list
            fresh = self._store.get("discussion", did, force_refresh=True) or {}
            if isinstance(fresh, dict):
                fv = fresh.get("value")
                if isinstance(fv, dict) and "value" in fv:
                    fv = fv["value"]
                if isinstance(fv, dict):
                    dval = fv
            dval_map[did] = dval
            fresh_comment_ids[did] = list(dval.get("comments") or [])
            all_comment_ids.update(fresh_comment_ids[did])
        # v2: ONE batched syncRecordValues for every fresh comment id, then
        # resolve locally — was one POST per comment (sequentially)
        if all_comment_ids:
            try:
                self.refresh_records(comment=sorted(all_comment_ids))
            except Exception:
                pass
        for did, dval in dval_map.items():
            comments = []
            for cid in fresh_comment_ids.get(did) or []:
                with self._store._mutex:
                    crec = self._store._values["comment"].get(cid)
                creval = creval_get(crec)
                if not creval:
                    continue
                author = creval.get("created_by_id", "")
                text_parts = []
                for seg in creval.get("text") or []:
                    if not isinstance(seg, list) or not seg:
                        continue
                    if seg[0] == "‣":
                        # inline mention (user/page) — keep a readable token
                        text_parts.append("@…")
                    else:
                        text_parts.append(str(seg[0]))
                comments.append(
                    {
                        "id": cid,
                        "author": author,
                        "text": "".join(text_parts),
                        "created_time": datetime.utcfromtimestamp(
                            creval.get("created_time", 0) / 1000
                        ).isoformat()
                        if creval.get("created_time")
                        else None,
                        "last_edited_time": datetime.utcfromtimestamp(
                            creval.get("last_edited_time", 0) / 1000
                        ).isoformat()
                        if creval.get("last_edited_time")
                        else None,
                        "alive": creval.get("alive", True),
                    }
                )
            discussions.append(
                {
                    "id": dval.get("id", did),
                    "context": _discussion_context(self, dval, recordmap),
                    "resolved": dval.get("resolved", False),
                    "comments": comments,
                }
            )
        return discussions

    def add_comment(self, block_id, text, discussion_id=None, resolve=False):
        """Add a comment to a block (page).

        With no discussion_id a new discussion (comment thread) is started
        on the block (op shape = PageDiscussion.useSubmitNewDiscussion);
        with a discussion_id this is a reply inside that thread.

        Returns {"comment_id", "discussion_id"}.
        """
        import time as _time

        from .operations import build_operation

        block_id = extract_id(block_id)
        now_ms = int(_time.time() * 1000)
        comment_id = str(uuid.uuid4())
        space_id = self.current_space.id if self.current_space else ""
        user_id = self.current_user.id if self.current_user else ""
        ops = []
        if discussion_id is None:
            discussion_id = str(uuid.uuid4())
            # new thread: the web client *creates* the discussion with an
            # "update" op (partial args — NOT a full "set"), then appends it
            # to the block's discussions list
            ops.append(
                build_operation(
                    discussion_id,
                    [],
                    {
                        "type": "default",
                        "parent_id": block_id,
                        "parent_table": "block",
                        "resolved": False,
                        "space_id": space_id,
                    },
                    command="update",
                    table="discussion",
                )
            )
            ops.append(
                build_operation(
                    block_id,
                    ["discussions"],
                    {"id": discussion_id},
                    command="listAfter",
                    table="block",
                )
            )
        else:
            discussion_id = extract_id(discussion_id)
        ops.append(
            build_operation(
                comment_id,
                [],
                {
                    "id": comment_id,
                    "parent_id": discussion_id,
                    "parent_table": "discussion",
                    "alive": True,
                    "space_id": space_id,
                    "created_time": now_ms,
                    "last_edited_time": now_ms,
                    "version": 1,
                },
                command="set",
                table="comment",
            )
        )
        ops.append(
            build_operation(
                discussion_id,
                ["comments"],
                {"id": comment_id},
                command="listAfter",
                table="discussion",
            )
        )
        ops.append(
            build_operation(
                comment_id, ["text"], [[text]], command="set", table="comment"
            )
        )
        ops.append(
            build_operation(
                comment_id,
                [],
                {
                    "created_by_id": user_id,
                    "created_by_table": "notion_user",
                },
                command="update",
                table="comment",
            )
        )
        self.submit_transaction(ops, update_last_edited=False)
        return {"comment_id": comment_id, "discussion_id": discussion_id}

    def get_record_data(self, table, id, force_refresh=False, limit=100):
        return self._store.get(table, id, force_refresh=force_refresh, limit=limit)

    def get_block(self, url_or_id, force_refresh=False, limit=100):
        """
        Retrieve an instance of a subclass of Block that maps to the block/page identified by the URL or ID passed in.
        """
        block_id = extract_id(url_or_id)
        block = self.get_record_data("block", block_id, force_refresh=force_refresh, limit=limit)
        if not block:
            return None
        if block.get("parent_table") == "collection":
            if block.get("is_template"):
                block_class = TemplateBlock
            else:
                block_class = CollectionRowBlock
        else:
            block_class = BLOCK_TYPES.get(block.get("type", ""), Block)
        return block_class(self, block_id)

    def get_collection(self, collection_id, force_refresh=False):
        """
        Retrieve an instance of Collection that maps to the collection identified by the ID passed in.
        """
        coll = self.get_record_data(
            "collection", collection_id, force_refresh=force_refresh
        )
        return Collection(self, collection_id) if coll else None

    def get_user(self, user_id, force_refresh=False):
        """
        Retrieve an instance of User that maps to the notion_user identified by the ID passed in.
        """
        user = self.get_record_data("notion_user", user_id, force_refresh=force_refresh)
        return User(self, user_id) if user else None

    def get_space(self, space_id, force_refresh=False):
        """
        Retrieve an instance of Space that maps to the space identified by the ID passed in.
        """
        space = self.get_record_data("space", space_id, force_refresh=force_refresh)
        return Space(self, space_id) if space else None

    def get_collection_view(self, url_or_id, collection=None, force_refresh=False):
        """
        Retrieve an instance of a subclass of CollectionView that maps to the appropriate type.
        The `url_or_id` argument can either be the URL for a database page, or the ID of a collection_view (in which case
        you must also pass the collection)
        """
        # if it's a URL for a database page, try extracting the collection and view IDs
        if url_or_id.startswith("http"):
            match = re.search(r"([a-f0-9]{32})\?v=([a-f0-9]{32})", url_or_id)
            if not match:
                raise Exception("Invalid collection view URL")
            block_id, view_id = match.groups()
            collection = self.get_block(
                block_id, force_refresh=force_refresh
            ).collection
        else:
            view_id = url_or_id
            assert (
                collection is not None
            ), "If 'url_or_id' is an ID (not a URL), you must also pass the 'collection'"

        view = self.get_record_data(
            "collection_view", view_id, force_refresh=force_refresh
        )

        return (
            COLLECTION_VIEW_TYPES.get(view.get("type", ""), CollectionView)(
                self, view_id, collection=collection
            )
            if view
            else None
        )

    def refresh_records(self, **kwargs):
        """
        The keyword arguments map table names into lists of (or singular) record IDs to load for that table.
        Use `True` instead of a list to refresh all known records for that table.
        """
        self._store.call_get_record_values(**kwargs)

    def refresh_collection_rows(self, collection_id):
        row_ids = [
            row.id
            for row in self.get_collection(collection_id).get_rows(limit=-1)
        ]
        self._store.set_collection_rows(collection_id, row_ids)

    def post(self, endpoint, data):
        """
        All API requests on Notion.so are done as POSTs (except the websocket communications).
        Injects x-notion-active-user-header and x-notion-space-id to mimic browser.
        """
        url = urljoin(API_BASE_URL, endpoint)
        headers = {}
        current_user = getattr(self, "current_user", None)
        current_space = getattr(self, "current_space", None)
        if current_user:
            headers["x-notion-active-user-header"] = current_user.id
        if current_space:
            headers["x-notion-space-id"] = current_space.id
        response = self.session.post(url, json=data, headers=headers)
        if response.status_code == 400:
            # Log at debug level — loadPageChunk returns 400 for non-page blocks
            # (column, synced_block) which is expected and handled by fallback
            logger.debug(
                "Got 400 error attempting to POST to {}, with data: {}".format(
                    endpoint, json.dumps(data, indent=2)
                )
            )
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}
            # Surface the real cause: Notion's generic "message" hides the
            # specific validation error in "debugMessage" / "name" (e.g.
            # unsaved_transactions with the actual ValidationError text)
            parts = [
                error_data.get(key)
                for key in ("message", "name", "debugMessage")
                if error_data.get(key)
            ]
            raise HTTPError(
                " | ".join(parts)
                if parts
                else "There was an error (400) submitting the request."
            )
        response.raise_for_status()
        return response

    def submit_transaction(self, operations, update_last_edited=True):

        if not operations:
            return

        if isinstance(operations, dict):
            operations = [operations]

        if update_last_edited:
            updated_blocks = set(
                [op["id"] for op in operations if op["table"] == "block"]
            )
            operations += [
                operation_update_last_edited(self.current_user.id, block_id)
                for block_id in updated_blocks
            ]

        # if we're in a transaction, just add these operations to the list; otherwise, execute them right away
        if self.in_transaction():
            self._transaction_operations += operations
        else:
            # v2: enforce the batch cap on the FINAL (expanded) op list so
            # each HTTP request carries at most batch_max_ops operations
            cap = batch_max_ops()
            if cap and len(operations) > cap:
                from .config import legacy_mode
                ops = operations
                total = 0
                for i in range(0, len(ops), cap):
                    chunk = ops[i : i + cap]
                    data = self._build_save_transactions_payload(chunk)
                    self.post("saveTransactionsFanout", data)
                    self._store.run_local_operations(chunk)
                    total += len(chunk)
                return
            data = self._build_save_transactions_payload(operations)
            self.post("saveTransactionsFanout", data)
            self._store.run_local_operations(operations)

    def _build_save_transactions_payload(self, operations):
        """
        Convert legacy operation dicts ({id, table, path, command, args}) into
        the new `saveTransactionsFanout` format which uses `pointer` objects
        with {table, id, spaceId} and wraps operations in a transaction.
        """
        space_id = self.current_space.id if self.current_space else None
        new_ops = []
        for op in operations:
            new_op = {
                "pointer": {
                    "table": op["table"],
                    "id": op["id"],
                    "spaceId": space_id,
                },
                "path": op.get("path", []),
                "command": op["command"],
                "args": op["args"],
            }
            new_ops.append(new_op)
        return {
            "requestId": str(uuid.uuid4()),
            "transactions": [
                {
                    "id": str(uuid.uuid4()),
                    "spaceId": space_id,
                    "debug": {},
                    "operations": new_ops,
                }
            ],
        }

    def fetch_many_blocks(self, block_ids):
        """Fetch many blocks in parallel (v2 I/O fan-out).

        Uses a ThreadPoolExecutor (UNPY_MAX_WORKERS, machine-aware default)
        to resolve records concurrently. Thread-safety requires the v2
        RecordStore (read-locked); UNPY_LEGACY=1 serializes to one worker.
        Deduplicates ids and preserves input order in the result.

        Returns a list of Block (or None for unresolvable ids) in the same
        order as `block_ids`.
        """
        from concurrent.futures import ThreadPoolExecutor

        from .config import legacy_mode, max_workers

        # dedupe but keep first-seen order
        seen = {}
        for bid in block_ids:
            key = extract_id(bid)
            seen.setdefault(key, bid)
        unique_ids = list(seen.keys())
        if not unique_ids:
            return []

        workers = 1 if legacy_mode() else max_workers()
        if workers <= 1:
            results = [self.get_block(bid) for bid in unique_ids]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(self.get_block, unique_ids))

        by_id = {}
        for b in results:
            if b is not None:
                by_id[b.id] = b
        out = [by_id.get(extract_id(bid)) for bid in block_ids]
        return out

    def batched_transaction(self):
        """
        Context manager that buffers operations like as_atomic_transaction but
        flushes them in chunks of `batch_max_ops` (default 100) so writing N
        blocks costs ~N/100 HTTP round trips instead of N. Each chunk is
        submitted as its own transaction; a chunk that fails raises and stops
        the flush (earlier chunks are already committed). Yields a callback
        that reports committed-chunk progress.
        """
        from .config import batch_max_ops

        cap = batch_max_ops()
        if cap <= 0:
            return self.as_atomic_transaction()
        return _BatchedTransaction(self, cap)

    def flush_batched(self, iterator):
        """Submit operations from an iterable in chunks of batch_max_ops.

        Yields (first_index, op_count, committed_ops_total) after each chunk,
        counting DATA operations (the caller's own ops, before any
        update_last_edited expansion the submit path may append). Raises on
        the first failed chunk — later chunks are not attempted.
        """
        from .config import batch_max_ops

        cap = batch_max_ops()
        chunk, base, total = [], 0, 0
        for op in iterator:
            chunk.append(op)
            if len(chunk) >= cap:
                # submit a copy: the submit path extends the list it is
                # given (update_last_edited) and must not alias our cursor
                self.submit_transaction(list(chunk))
                total += len(chunk)
                yield base, len(chunk), total
                base += len(chunk)
                chunk = []
        if chunk:
            self.submit_transaction(list(chunk))
            total += len(chunk)
            yield base, len(chunk), total

    def query_collection(self, *args, **kwargs):
        return self._store.call_query_collection(*args, **kwargs)

    def as_atomic_transaction(self):
        """
        Returns a context manager that buffers up all calls to `submit_transaction` and sends them as one big transaction
        when the context manager exits.
        """
        return Transaction(client=self)

    def in_transaction(self):
        """
        Returns True if we're currently in a transaction, otherwise False.
        """
        return hasattr(self, "_transaction_operations")

    def search_pages_with_parent(self, parent_id, search="", limit=100):
        data = {
            "query": search,
            "parentId": parent_id,
            "limit": limit,
            "spaceId": self.current_space.id,
        }
        response = self.post("searchPagesWithParent", data).json()
        self._store.store_recordmap(response["recordMap"])
        return response["results"]

    def search_blocks(self, search, limit=25):
        return self.search(query=search, limit=limit)

    def search(
        self,
        query="",
        search_type="BlocksInSpace",
        limit=100,
        sort="relevance",
        source="quick_find",
        isDeletedOnly=False,
        excludeTemplates=False,
        isNavigableOnly=False,
        requireEditPermissions=False,
        ancestors=[],
        createdBy=[],
        editedBy=[],
        lastEditedTime={},
        createdTime={},
    ):
        data = {
            "type": search_type,
            "query": query,
            "spaceId": self.current_space.id,
            "limit": limit,
            "filters": {
                "isDeletedOnly": isDeletedOnly,
                "excludeTemplates": excludeTemplates,
                "isNavigableOnly": isNavigableOnly,
                "requireEditPermissions": requireEditPermissions,
                "ancestors": ancestors,
                "createdBy": createdBy,
                "editedBy": editedBy,
                "lastEditedTime": lastEditedTime,
                "createdTime": createdTime,
            },
            "sort": {"field": sort} if isinstance(sort, str) else sort,
            "source": source,
        }
        response = self.post("search", data).json()
        self._store.store_recordmap(response["recordMap"])
        result_ids = [result["id"] for result in response["results"]]
        # v2: one batched fetch for any results the recordMap didn't already
        # include (was one get_block round trip per result)
        from .store import Missing

        missing = []
        for rid in result_ids:
            with self._store._mutex:
                if self._store._values["block"].get(rid, Missing) is Missing:
                    missing.append(rid)
        if missing:
            try:
                self.refresh_records(block=missing)
            except Exception:
                pass
        return [self.get_block(rid) for rid in result_ids]

    def create_record(self, table, parent, **kwargs):

        # make up a new UUID; apparently we get to choose our own!
        record_id = str(uuid.uuid4())

        child_list_key = kwargs.get("child_list_key") or parent.child_list_key

        args = {
            "id": record_id,
            "version": 1,
            "alive": True,
            "created_by_id": self.current_user.id,
            "created_by_table": "notion_user",
            "created_time": now(),
            "parent_id": parent.id,
            "parent_table": parent._table,
            "space_id": self.current_space.id,
        }

        args.update(kwargs)

        with self.as_atomic_transaction():

            # create the new record
            self.submit_transaction(
                build_operation(
                    args=args, command="set", id=record_id, path=[], table=table
                )
            )

            # add the record to the content list of the parent, if needed
            if child_list_key:
                self.submit_transaction(
                    build_operation(
                        id=parent.id,
                        path=[child_list_key],
                        args={"id": record_id},
                        command="listAfter",
                        table=parent._table,
                    )
                )

        return record_id


class Transaction(object):

    is_dummy_nested_transaction = False

    def __init__(self, client):
        self.client = client

    def __enter__(self):

        if hasattr(self.client, "_transaction_operations"):
            # client is already in a transaction, so we'll just make this one a nullop and let the outer one handle it
            self.is_dummy_nested_transaction = True
            return

        self.client._transaction_operations = []
        self.client._pages_to_refresh = []
        self.client._blocks_to_refresh = []

    def __exit__(self, exc_type, exc_value, traceback):

        if self.is_dummy_nested_transaction:
            return

        operations = self.client._transaction_operations
        del self.client._transaction_operations

        # only actually submit the transaction if there was no exception
        if not exc_type:
            self.client.submit_transaction(operations)

        self.client._store.handle_post_transaction_refreshing()


class _BatchedTransaction(object):
    """Like Transaction, but flushes buffered ops in capped chunks on exit."""

    def __init__(self, client, cap):
        self.client = client
        self.cap = cap

    def __enter__(self):
        if hasattr(self.client, "_transaction_operations"):
            # nested inside an outer transaction — defer to it entirely
            self.is_dummy_nested_transaction = True
            return None
        self.client._transaction_operations = []
        self.client._pages_to_refresh = []
        self.client._blocks_to_refresh = []
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if getattr(self, "is_dummy_nested_transaction", False):
            return
        operations = self.client._transaction_operations
        del self.client._transaction_operations
        if exc_type:
            self.client._store.handle_post_transaction_refreshing()
            return
        # submit as ONE buffered flush; submit_transaction itself enforces the
        # batch cap on the expanded op list (splitting into capped requests)
        self.client.submit_transaction(operations)
        self.client._store.handle_post_transaction_refreshing()
