from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class QuestionType(str, Enum):
    SINGLE = "single"
    MULTI = "multi"
    DATE = "date"


class QuizOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, description="Unique option identifier within question")
    label: str = Field(..., min_length=1, description="Option display label")


class QuizQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., pattern=r"^q\d{2}$", description="Question code, e.g. q02")
    order: int = Field(..., ge=1, description="Sequential display order")
    type: QuestionType = Field(..., description="Interaction type: single, multi, or date")
    title: str = Field(..., min_length=1, description="Question title text")
    required: bool = Field(default=True, description="Whether question is required")
    result_key: str = Field(..., min_length=1, description="Normalized profile / result attribute key")
    subtitle: Optional[str] = Field(default=None, description="Optional secondary helper text")
    min_select: Optional[int] = Field(default=None, ge=1, description="Minimum selections required for multi")
    max_select: Optional[int] = Field(default=None, ge=1, description="Maximum selections allowed for multi")
    options: Optional[List[QuizOption]] = Field(default=None, description="Selectable options for single/multi")


class QuizConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1, description="Version string, e.g. soulmate-quiz-v1")
    questions: List[QuizQuestion] = Field(..., description="Ordered list of questions")
