"""Repositories package exporting data access repositories."""

from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.folder import FolderRepository
from app.repositories.grading import GradingRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.repositories.practice import PracticeRepository
from app.repositories.question import QuestionRepository
from app.repositories.user import UserRepository

__all__ = [
    "DiagnosisRepository",
    "FolderRepository",
    "GradingRepository",
    "KnowledgeRepository",
    "MaterialRepository",
    "PracticeRepository",
    "QuestionRepository",
    "UserRepository",
]
