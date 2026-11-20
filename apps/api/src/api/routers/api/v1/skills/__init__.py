"""Skill catalog routes (inherits ``/api/v1`` anonymous single-owner access rule)."""

from fastapi import params

segment = "skills"

dependencies: tuple[params.Depends, ...] = ()
