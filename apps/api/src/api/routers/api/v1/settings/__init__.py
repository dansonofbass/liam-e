"""Owner-scoped UI settings; access is restricted by the deployment."""

from fastapi import params

dependencies: tuple[params.Depends, ...] = ()
