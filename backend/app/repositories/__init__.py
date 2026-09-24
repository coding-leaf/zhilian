"""Repositories package exporting data access repositories."""

from app.repositories.grading import GradingRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.repositories.practice import PracticeRepository
from app.repositories.question import QuestionRepository

__all__ = [
    "GradingRepository",
    "KnowledgeRepository",
    "MaterialRepository",
    "PracticeRepository",
    "QuestionRepository",
]
