"""Repositories package exporting data access repositories."""

from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.repositories.question import QuestionRepository

__all__ = ["KnowledgeRepository", "MaterialRepository", "QuestionRepository"]
