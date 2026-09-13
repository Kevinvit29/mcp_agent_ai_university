from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    language: str = "en"
    user_role: str = Field(default="student")
    requester_student_id: Optional[str] = None
    requester_advisor_id: Optional[str] = None
    requester_lecturer_id: Optional[str] = None
    session_id: Optional[str] = None
    # Optional pinned file context from the Knowledge Workspace. It makes “Ask”
    # answer from the exact uploaded file instead of trying to re-match the filename.
    document_id: Optional[int] = None
    document_scope: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = {}


class ChatResponse(BaseModel):
    success: bool = True
    ai_response: str
    answer: Optional[str] = None
    session_id: str
    selected_agent: Optional[str] = None
    selected_tool: Optional[str] = None
    tool_arguments: Dict[str, Any] = {}
    planner_warning: Optional[str] = None
    mcp_result: Dict[str, Any] = {}
    debug_trace: Dict[str, Any] = {}
    answer_source: Dict[str, Any] = {}
    history: List[ChatMessage] = []

class AnswerFeedbackRequest(BaseModel):
    """A voluntary answer-quality signal. It is reviewed before it can affect future routing."""
    session_id: Optional[str] = None
    user_role: str = Field(default="student")
    requester_student_id: Optional[str] = None
    requester_advisor_id: Optional[str] = None
    requester_lecturer_id: Optional[str] = None
    question: str = ""
    answer_excerpt: str = ""
    rating: str
    note: Optional[str] = None
    selected_tool: Optional[str] = None


class LearningReviewRequest(BaseModel):
    user_role: str = Field(default="admin")
    note: Optional[str] = None
