"""Repositories package exporting data access repositories."""

from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository

__all__ = ["KnowledgeRepository", "MaterialRepository"]
