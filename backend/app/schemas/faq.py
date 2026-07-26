from pydantic import BaseModel


class FAQResponse(BaseModel):
    id: str
    question: str
    answer: str
    display_order: int


class FAQsResponse(BaseModel):
    success: bool = True
    data: list[FAQResponse]
