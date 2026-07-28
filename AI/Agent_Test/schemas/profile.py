"""이력서 파싱 결과(profile) 스키마 — AGENTS §2.1 (`_UserProfileRead`, 10필드).

`search_postings`·`analyze_gap`이 공유하는 중심 계약.
규칙(AGENTS §2): 없는 섹션 → `[]`, 값 없는 스칼라 → `null`(Optional=None).
로드베어링(실사용): skills, projects.techStack, experiences.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    level: Optional[str] = None


class Experience(BaseModel):
    id: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    employmentType: Optional[str] = None
    period: Optional[str] = None
    summary: Optional[str] = None


class Project(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    projectType: Optional[str] = None
    period: Optional[str] = None
    teamSize: Optional[int] = None
    role: Optional[str] = None
    summary: Optional[str] = None
    techStack: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class Education(BaseModel):
    id: Optional[str] = None
    school: Optional[str] = None
    major: Optional[str] = None
    degree: Optional[str] = None
    status: Optional[str] = None
    period: Optional[str] = None


class Certification(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    acquiredDate: Optional[str] = None


class Language(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    testName: Optional[str] = None
    score: Optional[str] = None
    testDate: Optional[str] = None
    proficiency: Optional[str] = None


class Bootcamp(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    organization: Optional[str] = None
    track: Optional[str] = None
    period: Optional[str] = None
    summary: Optional[str] = None


class Award(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None
    date: Optional[str] = None
    description: Optional[str] = None


class Evidence(BaseModel):
    evidenceId: Optional[str] = None
    source: Optional[str] = None
    text: Optional[str] = None


class UserProfile(BaseModel):
    """이력서 파싱 결과 = `_UserProfileRead` 10필드 (AGENTS §2.1)."""

    skills: list[Skill] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    bootcamp: list[Bootcamp] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    evidenceMap: list[Evidence] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
