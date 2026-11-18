"""Browser-only provider connection management, behind the single-owner gateway."""

from fastapi import params

dependencies: tuple[params.Depends, ...] = ()
