"""Personal task endpoints under /api/v1/tasks."""

from fastapi import params

segment = 'tasks'
dependencies: tuple[params.Depends, ...] = ()
