"""QMT snapshot publisher authentication helpers.

The Blob master token is never sent over the network by the QMT publisher.
When an explicit webhook secret is not configured, both trusted endpoints
derive the same independent request secret with HMAC-SHA256.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping


_DERIVATION_CONTEXT = b"quantcollection/qmt-webhook/v1"
_PLACEHOLDER_PREFIX = "replace_with_"


def resolve_qmt_webhook_secret(environ: Mapping[str, str] | None = None) -> str:
    """Resolve the shared webhook secret without exposing the Blob token.

    An explicit ``QMT_WEBHOOK_SECRET`` remains the preferred override.  For a
    Vercel project with a connected private Blob store, HMAC derivation avoids
    maintaining a second dashboard secret while keeping the Blob credential
    itself out of HTTP headers and payloads.
    """

    values = os.environ if environ is None else environ
    explicit = str(values.get("QMT_WEBHOOK_SECRET", "")).strip()
    if explicit and not explicit.lower().startswith(_PLACEHOLDER_PREFIX):
        return explicit

    blob_token = str(values.get("BLOB_READ_WRITE_TOKEN", "")).strip()
    if not blob_token:
        return ""
    return hmac.new(blob_token.encode("utf-8"), _DERIVATION_CONTEXT, hashlib.sha256).hexdigest()
