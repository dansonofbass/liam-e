"""The versioned API (``/api/v1/...``).

Single-user app served behind the Mistral Studio gateway, which authenticates callers — so this
group declares no additional per-route dependency. The declaration is still required: a subtree
that omits ``dependencies`` fails to import (fail-closed), so an anonymous group must say ``()``
explicitly.
"""

from fastapi import params

segment = "v1"

dependencies: tuple[params.Depends, ...] = ()
