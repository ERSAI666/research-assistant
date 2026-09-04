from pydantic import BaseModel, Field
from typing import List


class SubQuestion(BaseModel):
    question: str = Field(description="需要检索的具体子问题")


class SubQuestionList(BaseModel):
    sub_questions: List[SubQuestion] = Field(description="拆解后的3-4个子问题，覆盖核心维度")


class ResearchNote(BaseModel):
    key_points: List[str] = Field(description="提取的核心观点、关键数据")
    source_url: str = Field(default="", description="信息来源的网页链接")
    source_title: str = Field(default="", description="来源网页的标题")


class ResearchReport(BaseModel):
    core_conclusion: str = Field(description="200字以内核心结论")
    detailed_analysis: List[str] = Field(description="分点详细分析列表")
