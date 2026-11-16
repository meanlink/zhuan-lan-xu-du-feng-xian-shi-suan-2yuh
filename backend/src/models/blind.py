from sqlalchemy import String, JSON, Double, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class BlindCase(Base):
    """A blind evaluation case: one fixed reader split, one selection, one unseal."""
    __tablename__ = 'blind_cases'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    blind_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    development_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    sealed_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    split: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='developing')
    chosen_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unseal_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locked_artifact: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    locked_threshold: Mapped[float | None] = mapped_column(Double, nullable=True)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    locked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    completed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
