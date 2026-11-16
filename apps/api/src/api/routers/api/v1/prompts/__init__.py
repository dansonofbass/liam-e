"""Owner-scoped prompt library; access is restricted by the deployment."""
from fastapi import params

dependencies: tuple[params.Depends, ...] = ()
