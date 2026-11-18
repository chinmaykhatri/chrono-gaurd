# ChronoGuard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build ChronoGuard — a freshness-aware reliability layer for Bifrost AI gateway with Tavily verification.

**Architecture:** Go plugin pair (cg-front/cg-back) inside Bifrost, Python FastAPI Verifier service, React Console dashboard, PostgreSQL + Redis data stores, Docker Compose orchestration.

**Tech Stack:** Go, Python 3.12, FastAPI, React 18, TypeScript, Vite, Tailwind, PostgreSQL 16, Redis 7, Docker Compose

---

## Phase 0: Infrastructure & Scaffolding

### Task 1: Repository Structure & Docker Compose
### Task 2: PostgreSQL Schema & Migrations (Alembic)
### Task 3: Verifier FastAPI Skeleton
### Task 4: Redis Integration & Clock Helper

## Phase 1: Verifier Core Pipeline

### Task 5: Claim Extraction Module
### Task 6: Volatility Classes & Fact Keys
### Task 7: Fact Ledger & Singleflight
### Task 8: Tavily Evidence Retrieval Client
### Task 9: Verdict Judge
### Task 10: Freshness Scoring
### Task 11: Triage & Budget Scheduler
### Task 12: Claim Manifest & best_before

## Phase 2: Bifrost Integration (Go Plugins)

### Task 13: cg-front Plugin (classifier, cache headers, decision engine)
### Task 14: cg-back Plugin (grounding injection)
### Task 15: Decision Engine (pure Go)

## Phase 3: Cache Loop

### Task 16: Revalidation (SWR, Blocking)
### Task 17: Eviction & Cascade Invalidation
### Task 18: Grounded Regeneration

## Phase 4: Console (React)

### Task 19: Console Shell (auth, layout, SSE)
### Task 20: Playground Page
### Task 21: Live Feed Page
### Task 22: Cache Explorer Page
### Task 23: Claim Inspector & Costs Pages

## Phase 5: Evaluation & Polish

### Task 24: Evaluation Lab & Dataset
### Task 25: Observability (metrics, traces, health)
### Task 26: Documentation & Demo Script

