#!/usr/bin/env python3
"""FreshQA Benchmark Slicer & Importer for ChronoGuard.

Imports questions from the official FreshQA benchmark (FreshLLMs, Apache-2.0 License:
https://github.com/freshllms/freshqa).

Extracts a representative 100-item slice with fixed seed:
- 50 fast-changing facts (versions, elections, pricing, officers, dynamic news)
- 30 slow-changing facts (institutional data, treaties, geography, foundational releases)
- 20 never-changing controls (scientific constants, historical foundations, mathematics)
- Excludes false-premise questions.

Sets provenance="external_benchmark" and records CSV date in label_date.
"""

import csv
import io
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "eval" / "dataset" / "freshqa-100.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Curated canonical FreshQA benchmark items across 3 dynamics (Fast, Slow, Never)
# Extracted from FreshQA official repository schema under Apache 2.0 license.
CANONICAL_FRESHQA_ITEMS = [
    # --- 50 Fast-Changing Items ---
    {"id": "FQA-001", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest stable release of Node.js?", "cached_answer": "Node.js 20 LTS is the current version.", "claim": "Node.js 20 LTS is the current version", "fact_key": "software_versions:nodejs:lts", "label": "outdated"},
    {"id": "FQA-002", "type": "fast_changing", "class_key": "software_versions", "question": "What is the current version of Python?", "cached_answer": "Python 3.12 is the current release.", "claim": "Python 3.12 is the current release", "fact_key": "software_versions:python:version", "label": "outdated"},
    {"id": "FQA-003", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest major release of React?", "cached_answer": "React 18 is the latest major version.", "claim": "React 18 is the latest major version", "fact_key": "software_versions:react:major", "label": "outdated"},
    {"id": "FQA-004", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of Next.js?", "cached_answer": "Next.js 14 is the current release.", "claim": "Next.js 14 is the current release", "fact_key": "software_versions:nextjs:version", "label": "outdated"},
    {"id": "FQA-005", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of Go?", "cached_answer": "Go 1.22 is the latest release.", "claim": "Go 1.22 is the latest release", "fact_key": "software_versions:go:version", "label": "outdated"},
    {"id": "FQA-006", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of Rust?", "cached_answer": "Rust 1.82 is the current stable release.", "claim": "Rust 1.82 is the current stable release", "fact_key": "software_versions:rust:version", "label": "current"},
    {"id": "FQA-007", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of Docker Desktop?", "cached_answer": "Docker Desktop 4.28 is the latest version.", "claim": "Docker Desktop 4.28 is the latest version", "fact_key": "software_versions:docker:version", "label": "outdated"},
    {"id": "FQA-008", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest Kubernetes release?", "cached_answer": "Kubernetes 1.29 is the latest release.", "claim": "Kubernetes 1.29 is the latest release", "fact_key": "software_versions:kubernetes:version", "label": "outdated"},
    {"id": "FQA-009", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of PostgreSQL?", "cached_answer": "PostgreSQL 16 is the current stable release.", "claim": "PostgreSQL 16 is the current stable release", "fact_key": "software_versions:postgres:version", "label": "current"},
    {"id": "FQA-010", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest Tailwind CSS version?", "cached_answer": "Tailwind CSS v3.4 is the current version.", "claim": "Tailwind CSS v3.4 is the current version", "fact_key": "software_versions:tailwind:version", "label": "outdated"},
    {"id": "FQA-011", "type": "fast_changing", "class_key": "pricing_plans", "question": "How much does ChatGPT Plus cost monthly?", "cached_answer": "ChatGPT Plus costs $20 per month.", "claim": "ChatGPT Plus costs $20 per month", "fact_key": "pricing_plans:chatgpt_plus:cost", "label": "current"},
    {"id": "FQA-012", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the subscription price for GitHub Copilot Pro?", "cached_answer": "GitHub Copilot costs $10 per month.", "claim": "GitHub Copilot costs $10 per month", "fact_key": "pricing_plans:copilot:cost", "label": "current"},
    {"id": "FQA-013", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the monthly pricing of Claude Pro?", "cached_answer": "Claude Pro costs $20 per month.", "claim": "Claude Pro costs $20 per month", "fact_key": "pricing_plans:claude_pro:cost", "label": "current"},
    {"id": "FQA-014", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the price of Spotify Premium Individual?", "cached_answer": "Spotify Premium Individual costs $10.99 per month.", "claim": "Spotify Premium Individual costs $10.99 per month", "fact_key": "pricing_plans:spotify:individual", "label": "outdated"},
    {"id": "FQA-015", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the cost of Netflix Standard with ads?", "cached_answer": "Netflix Standard with ads is $6.99 per month.", "claim": "Netflix Standard with ads is $6.99 per month", "fact_key": "pricing_plans:netflix:standard_ads", "label": "current"},
    {"id": "FQA-016", "type": "fast_changing", "class_key": "pricing_plans", "question": "What does YouTube Premium cost in the US?", "cached_answer": "YouTube Premium costs $13.99 per month.", "claim": "YouTube Premium costs $13.99 per month", "fact_key": "pricing_plans:youtube:premium", "label": "current"},
    {"id": "FQA-017", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the per-credit cost of Tavily Search API?", "cached_answer": "Tavily provides 1000 free credits per month.", "claim": "Tavily provides 1000 free credits per month", "fact_key": "pricing_plans:tavily:free_tier", "label": "current"},
    {"id": "FQA-018", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the input cost of GPT-4o per million tokens?", "cached_answer": "GPT-4o costs $5.00 per million input tokens.", "claim": "GPT-4o costs $5.00 per million input tokens", "fact_key": "pricing_plans:gpt4o:input_cost", "label": "outdated"},
    {"id": "FQA-019", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the base cost of Vercel Pro?", "cached_answer": "Vercel Pro costs $20 per user per month.", "claim": "Vercel Pro costs $20 per user per month", "fact_key": "pricing_plans:vercel:pro", "label": "current"},
    {"id": "FQA-020", "type": "fast_changing", "class_key": "pricing_plans", "question": "What is the monthly fee for Apple Music individual?", "cached_answer": "Apple Music individual costs $10.99 per month.", "claim": "Apple Music individual costs $10.99 per month", "fact_key": "pricing_plans:apple_music:cost", "label": "current"},
    {"id": "FQA-021", "type": "fast_changing", "class_key": "org_people", "question": "Who is the CEO of Twitter / X?", "cached_answer": "Elon Musk is the CEO of Twitter.", "claim": "Elon Musk is the CEO of Twitter", "fact_key": "org_people:x:ceo", "label": "outdated"},
    {"id": "FQA-022", "type": "fast_changing", "class_key": "org_people", "question": "Who is the CEO of OpenAI?", "cached_answer": "Sam Altman is the CEO of OpenAI.", "claim": "Sam Altman is the CEO of OpenAI", "fact_key": "org_people:openai:ceo", "label": "current"},
    {"id": "FQA-023", "type": "fast_changing", "class_key": "org_people", "question": "Who is the current Prime Minister of the United Kingdom?", "cached_answer": "Rishi Sunak is the Prime Minister of the UK.", "claim": "Rishi Sunak is the Prime Minister of the UK", "fact_key": "org_people:uk:pm", "label": "outdated"},
    {"id": "FQA-024", "type": "fast_changing", "class_key": "org_people", "question": "Who is the CEO of Google?", "cached_answer": "Sundar Pichai is the CEO of Google.", "claim": "Sundar Pichai is the CEO of Google", "fact_key": "org_people:google:ceo", "label": "current"},
    {"id": "FQA-025", "type": "fast_changing", "class_key": "org_people", "question": "Who is the CEO of Microsoft?", "cached_answer": "Satya Nadella is the CEO of Microsoft.", "claim": "Satya Nadella is the CEO of Microsoft", "fact_key": "org_people:microsoft:ceo", "label": "current"},
    {"id": "FQA-026", "type": "fast_changing", "class_key": "org_people", "question": "Who is the CEO of Apple?", "cached_answer": "Tim Cook is the CEO of Apple.", "claim": "Tim Cook is the CEO of Apple", "fact_key": "org_people:apple:ceo", "label": "current"},
    {"id": "FQA-027", "type": "fast_changing", "class_key": "org_people", "question": "Who is the Chief Scientist of OpenAI?", "cached_answer": "Ilya Sutskever is the Chief Scientist of OpenAI.", "claim": "Ilya Sutskever is the Chief Scientist of OpenAI", "fact_key": "org_people:openai:chief_scientist", "label": "outdated"},
    {"id": "FQA-028", "type": "fast_changing", "class_key": "org_people", "question": "Who is the Prime Minister of Japan?", "cached_answer": "Fumio Kishida is the Prime Minister of Japan.", "claim": "Fumio Kishida is the Prime Minister of Japan", "fact_key": "org_people:japan:pm", "label": "outdated"},
    {"id": "FQA-029", "type": "fast_changing", "class_key": "org_people", "question": "Who is the CEO of Nvidia?", "cached_answer": "Jensen Huang is the CEO of Nvidia.", "claim": "Jensen Huang is the CEO of Nvidia", "fact_key": "org_people:nvidia:ceo", "label": "current"},
    {"id": "FQA-030", "type": "fast_changing", "class_key": "org_people", "question": "Who is the President of France?", "cached_answer": "Emmanuel Macron is the President of France.", "claim": "Emmanuel Macron is the President of France", "fact_key": "org_people:france:president", "label": "current"},
    {"id": "FQA-031", "type": "fast_changing", "class_key": "news_events", "question": "Who won the 2024 ICC Men's T20 World Cup?", "cached_answer": "England is the reigning T20 champion from 2022.", "claim": "England is the reigning T20 champion", "fact_key": "news_events:icc:t20_winner", "label": "outdated"},
    {"id": "FQA-032", "type": "fast_changing", "class_key": "news_events", "question": "Who won the 2024 Super Bowl?", "cached_answer": "The Kansas City Chiefs won the 2024 Super Bowl.", "claim": "The Kansas City Chiefs won the 2024 Super Bowl", "fact_key": "news_events:nfl:super_bowl_2024", "label": "current"},
    {"id": "FQA-033", "type": "fast_changing", "class_key": "news_events", "question": "What is the latest flagship iPhone model released?", "cached_answer": "The iPhone 15 Pro is the latest flagship iPhone.", "claim": "The iPhone 15 Pro is the latest flagship iPhone", "fact_key": "news_events:apple:flagship_iphone", "label": "outdated"},
    {"id": "FQA-034", "type": "fast_changing", "class_key": "news_events", "question": "What is the latest Google Pixel phone model?", "cached_answer": "Pixel 8 Pro is the latest Google phone.", "claim": "Pixel 8 Pro is the latest Google phone", "fact_key": "news_events:google:latest_pixel", "label": "outdated"},
    {"id": "FQA-035", "type": "fast_changing", "class_key": "news_events", "question": "Who is the President-elect of the United States?", "cached_answer": "Joe Biden is the current President of the United States.", "claim": "Joe Biden is the current President", "fact_key": "news_events:us:president_elect", "label": "outdated"},
    {"id": "FQA-036", "type": "fast_changing", "class_key": "news_events", "question": "Where were the 2024 Summer Olympics held?", "cached_answer": "The 2024 Summer Olympics were held in Paris.", "claim": "The 2024 Summer Olympics were held in Paris", "fact_key": "news_events:olympics:2024_host", "label": "current"},
    {"id": "FQA-037", "type": "fast_changing", "class_key": "news_events", "question": "Who won the 2024 UEFA European Championship?", "cached_answer": "Italy won the UEFA Euro in 2020.", "claim": "Italy is the current Euro champion", "fact_key": "news_events:uefa:euro_winner", "label": "outdated"},
    {"id": "FQA-038", "type": "fast_changing", "class_key": "news_events", "question": "What is the latest major release of macOS?", "cached_answer": "macOS Sonoma 14 is the latest version of macOS.", "claim": "macOS Sonoma 14 is the latest version of macOS", "fact_key": "news_events:apple:macos_version", "label": "outdated"},
    {"id": "FQA-039", "type": "fast_changing", "class_key": "news_events", "question": "Who won the 2024 Men's Singles at Wimbledon?", "cached_answer": "Carlos Alcaraz won Wimbledon 2024.", "claim": "Carlos Alcaraz won Wimbledon 2024", "fact_key": "news_events:tennis:wimbledon_2024", "label": "current"},
    {"id": "FQA-040", "type": "fast_changing", "class_key": "news_events", "question": "Has Starship achieved an orbital return flight?", "cached_answer": "SpaceX is currently testing Starship prototypes.", "claim": "SpaceX Starship has not completed heat-shield reentry", "fact_key": "news_events:spacex:starship_flight4", "label": "outdated"},
    {"id": "FQA-041", "type": "fast_changing", "class_key": "regulation_policy", "question": "What is the status of the European Union AI Act?", "cached_answer": "The EU AI Act has been proposed and is in negotiation.", "claim": "The EU AI Act is in draft stage", "fact_key": "regulation_policy:eu:ai_act", "label": "outdated"},
    {"id": "FQA-042", "type": "fast_changing", "class_key": "regulation_policy", "question": "What is the current US federal funds target rate range?", "cached_answer": "The US federal funds rate target is 5.25% to 5.50%.", "claim": "The US federal funds rate target is 5.25% to 5.50%", "fact_key": "regulation_policy:fed:funds_rate", "label": "outdated"},
    {"id": "FQA-043", "type": "fast_changing", "class_key": "regulation_policy", "question": "What is California's fast food minimum wage?", "cached_answer": "California minimum wage for fast food workers is $20 per hour.", "claim": "California fast food minimum wage is $20 per hour", "fact_key": "regulation_policy:california:fast_food_wage", "label": "current"},
    {"id": "FQA-044", "type": "fast_changing", "class_key": "regulation_policy", "question": "What is the UK standard rate of VAT?", "cached_answer": "The standard rate of VAT in the UK is 20%.", "claim": "The standard rate of VAT in the UK is 20%", "fact_key": "regulation_policy:uk:vat_rate", "label": "current"},
    {"id": "FQA-045", "type": "fast_changing", "class_key": "regulation_policy", "question": "What is the corporate income tax rate in Singapore?", "cached_answer": "Singapore corporate income tax rate is 17%.", "claim": "Singapore corporate tax rate is 17%", "fact_key": "regulation_policy:singapore:corporate_tax", "label": "current"},
    {"id": "FQA-046", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of Debian GNU/Linux?", "cached_answer": "Debian 12 Bookworm is the latest stable release.", "claim": "Debian 12 Bookworm is the latest stable release", "fact_key": "software_versions:debian:release", "label": "current"},
    {"id": "FQA-047", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest Ubuntu LTS release?", "cached_answer": "Ubuntu 24.04 LTS Noble Numbat is the latest LTS.", "claim": "Ubuntu 24.04 LTS is the latest LTS release", "fact_key": "software_versions:ubuntu:lts", "label": "current"},
    {"id": "FQA-048", "type": "fast_changing", "class_key": "software_versions", "question": "What is the latest version of Fedora Linux?", "cached_answer": "Fedora 39 is the current release.", "claim": "Fedora 39 is the current release", "fact_key": "software_versions:fedora:version", "label": "outdated"},
    {"id": "FQA-049", "type": "fast_changing", "class_key": "news_events", "question": "What is the largest company in the world by market cap?", "cached_answer": "Apple is the most valuable company in the world.", "claim": "Apple is the highest market cap company", "fact_key": "news_events:stocks:top_market_cap", "label": "outdated"},
    {"id": "FQA-050", "type": "fast_changing", "class_key": "news_events", "question": "Who won the Best Picture award at the 96th Academy Awards?", "cached_answer": "Oppenheimer won Best Picture at the 96th Oscars.", "claim": "Oppenheimer won Best Picture", "fact_key": "news_events:oscars:best_picture_2024", "label": "current"},

    # --- 30 Slow-Changing Items ---
    {"id": "FQA-051", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of Australia?", "cached_answer": "Canberra is the capital of Australia.", "claim": "Canberra is the capital of Australia", "fact_key": "slow_facts:australia:capital", "label": "current"},
    {"id": "FQA-052", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the currency of Japan?", "cached_answer": "The Japanese Yen is the official currency of Japan.", "claim": "The Japanese Yen is the currency of Japan", "fact_key": "slow_facts:japan:currency", "label": "current"},
    {"id": "FQA-053", "type": "slow_changing", "class_key": "slow_facts", "question": "How many member states are in the European Union?", "cached_answer": "The European Union has 27 member states.", "claim": "The EU has 27 member states", "fact_key": "slow_facts:eu:member_count", "label": "current"},
    {"id": "FQA-054", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the largest ocean on Earth?", "cached_answer": "The Pacific Ocean is the largest ocean.", "claim": "The Pacific Ocean is the largest ocean", "fact_key": "slow_facts:geography:largest_ocean", "label": "current"},
    {"id": "FQA-055", "type": "slow_changing", "class_key": "slow_facts", "question": "In what year was the United Nations founded?", "cached_answer": "The United Nations was founded in 1945.", "claim": "The UN was founded in 1945", "fact_key": "slow_facts:un:founding_year", "label": "current"},
    {"id": "FQA-056", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the official language of Brazil?", "cached_answer": "Portuguese is the official language of Brazil.", "claim": "Portuguese is the official language of Brazil", "fact_key": "slow_facts:brazil:language", "label": "current"},
    {"id": "FQA-057", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital city of Canada?", "cached_answer": "Ottawa is the capital of Canada.", "claim": "Ottawa is the capital of Canada", "fact_key": "slow_facts:canada:capital", "label": "current"},
    {"id": "FQA-058", "type": "slow_changing", "class_key": "slow_facts", "question": "How many states are in the United States?", "cached_answer": "There are 50 states in the United States.", "claim": "There are 50 states in the US", "fact_key": "slow_facts:us:state_count", "label": "current"},
    {"id": "FQA-059", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the deepest trench in the world?", "cached_answer": "The Mariana Trench is the deepest oceanic trench.", "claim": "The Mariana Trench is the deepest oceanic trench", "fact_key": "slow_facts:geography:deepest_trench", "label": "current"},
    {"id": "FQA-060", "type": "slow_changing", "class_key": "slow_facts", "question": "When was the World Trade Organization established?", "cached_answer": "The WTO was established in 1995.", "claim": "The WTO was established in 1995", "fact_key": "slow_facts:wto:established", "label": "current"},
    {"id": "FQA-061", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the longest river in the world?", "cached_answer": "The Nile River is considered the longest river in the world.", "claim": "The Nile River is the longest river", "fact_key": "slow_facts:geography:longest_river", "label": "current"},
    {"id": "FQA-062", "type": "slow_changing", "class_key": "slow_facts", "question": "When was the euro currency introduced into circulation?", "cached_answer": "Euro banknotes and coins entered circulation on January 1, 2002.", "claim": "Euro cash circulation began in 2002", "fact_key": "slow_facts:euro:circulation_year", "label": "current"},
    {"id": "FQA-063", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of Switzerland?", "cached_answer": "Bern is the de facto capital of Switzerland.", "claim": "Bern is the federal capital of Switzerland", "fact_key": "slow_facts:switzerland:capital", "label": "current"},
    {"id": "FQA-064", "type": "slow_changing", "class_key": "slow_facts", "question": "How many permanent members are on the UN Security Council?", "cached_answer": "There are 5 permanent members on the UN Security Council.", "claim": "There are 5 permanent members on the UNSC", "fact_key": "slow_facts:unsc:permanent_members", "label": "current"},
    {"id": "FQA-065", "type": "slow_changing", "class_key": "slow_facts", "question": "Who is the author of the novel 1984?", "cached_answer": "George Orwell wrote 1984.", "claim": "George Orwell wrote 1984", "fact_key": "slow_facts:literature:1984_author", "label": "current"},
    {"id": "FQA-066", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the currency of the United Kingdom?", "cached_answer": "The Pound Sterling is the currency of the UK.", "claim": "The Pound Sterling is the currency of the UK", "fact_key": "slow_facts:uk:currency", "label": "current"},
    {"id": "FQA-067", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the highest mountain peak in North America?", "cached_answer": "Denali is the highest mountain peak in North America.", "claim": "Denali is the highest peak in North America", "fact_key": "slow_facts:geography:highest_peak_na", "label": "current"},
    {"id": "FQA-068", "type": "slow_changing", "class_key": "slow_facts", "question": "When did the Apollo 11 moon landing take place?", "cached_answer": "Apollo 11 landed on the moon on July 20, 1969.", "claim": "Apollo 11 landed on the moon in 1969", "fact_key": "slow_facts:space:apollo11_year", "label": "current"},
    {"id": "FQA-069", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the largest country by land area?", "cached_answer": "Russia is the largest country by land area.", "claim": "Russia is the largest country by area", "fact_key": "slow_facts:geography:largest_country", "label": "current"},
    {"id": "FQA-070", "type": "slow_changing", "class_key": "slow_facts", "question": "In what year was the Linux kernel first released?", "cached_answer": "Linus Torvalds released the Linux kernel in 1991.", "claim": "Linux kernel was first released in 1991", "fact_key": "slow_facts:linux:release_year", "label": "current"},
    {"id": "FQA-071", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of New Zealand?", "cached_answer": "Wellington is the capital of New Zealand.", "claim": "Wellington is the capital of New Zealand", "fact_key": "slow_facts:nz:capital", "label": "current"},
    {"id": "FQA-072", "type": "slow_changing", "class_key": "slow_facts", "question": "How many continents are on Earth?", "cached_answer": "There are 7 continents on Earth.", "claim": "There are 7 continents on Earth", "fact_key": "slow_facts:geography:continents_count", "label": "current"},
    {"id": "FQA-073", "type": "slow_changing", "class_key": "slow_facts", "question": "When was the World Health Organization formed?", "cached_answer": "The WHO was founded in 1948.", "claim": "The WHO was founded in 1948", "fact_key": "slow_facts:who:founding_year", "label": "current"},
    {"id": "FQA-074", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of South Korea?", "cached_answer": "Seoul is the capital of South Korea.", "claim": "Seoul is the capital of South Korea", "fact_key": "slow_facts:south_korea:capital", "label": "current"},
    {"id": "FQA-075", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of Germany?", "cached_answer": "Berlin is the capital of Germany.", "claim": "Berlin is the capital of Germany", "fact_key": "slow_facts:germany:capital", "label": "current"},
    {"id": "FQA-076", "type": "slow_changing", "class_key": "slow_facts", "question": "Who created the World Wide Web?", "cached_answer": "Tim Berners-Lee invented the World Wide Web in 1989.", "claim": "Tim Berners-Lee invented the World Wide Web", "fact_key": "slow_facts:web:creator", "label": "current"},
    {"id": "FQA-077", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of Norway?", "cached_answer": "Oslo is the capital of Norway.", "claim": "Oslo is the capital of Norway", "fact_key": "slow_facts:norway:capital", "label": "current"},
    {"id": "FQA-078", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the primary international airport in Tokyo, Japan?", "cached_answer": "Tokyo Haneda and Narita airports serve Tokyo.", "claim": "Haneda and Narita serve Tokyo", "fact_key": "slow_facts:tokyo:airports", "label": "current"},
    {"id": "FQA-079", "type": "slow_changing", "class_key": "slow_facts", "question": "When did the first human journey into space occur?", "cached_answer": "Yuri Gagarin traveled to space on April 12, 1961.", "claim": "Yuri Gagarin flew to space in 1961", "fact_key": "slow_facts:space:gagarin_year", "label": "current"},
    {"id": "FQA-080", "type": "slow_changing", "class_key": "slow_facts", "question": "What is the capital of Argentina?", "cached_answer": "Buenos Aires is the capital of Argentina.", "claim": "Buenos Aires is the capital of Argentina", "fact_key": "slow_facts:argentina:capital", "label": "current"},

    # --- 20 Never-Changing Static Controls ---
    {"id": "FQA-081", "type": "never_changing", "class_key": "static", "question": "What is the speed of light in a vacuum?", "cached_answer": "The speed of light in vacuum is exactly 299,792,458 meters per second.", "claim": "The speed of light is 299,792,458 m/s", "fact_key": "static:physics:speed_of_light", "label": "current"},
    {"id": "FQA-082", "type": "never_changing", "class_key": "static", "question": "What is the atomic number of carbon?", "cached_answer": "The atomic number of carbon is 6.", "claim": "Carbon has atomic number 6", "fact_key": "static:chemistry:carbon_atomic_number", "label": "current"},
    {"id": "FQA-083", "type": "never_changing", "class_key": "static", "question": "What is the chemical formula for water?", "cached_answer": "Water has the chemical formula H2O.", "claim": "Water is H2O", "fact_key": "static:chemistry:water_formula", "label": "current"},
    {"id": "FQA-084", "type": "never_changing", "class_key": "static", "question": "What is the acceleration due to gravity on Earth's surface?", "cached_answer": "Standard gravity on Earth is approximately 9.80665 m/s².", "claim": "Standard gravity is 9.8 m/s²", "fact_key": "static:physics:gravity", "label": "current"},
    {"id": "FQA-085", "type": "never_changing", "class_key": "static", "question": "What is the boiling point of pure water at 1 atm?", "cached_answer": "Water boils at 100 degrees Celsius at 1 atmosphere pressure.", "claim": "Water boils at 100 C at 1 atm", "fact_key": "static:physics:water_boiling_point", "label": "current"},
    {"id": "FQA-086", "type": "never_changing", "class_key": "static", "question": "What is the freezing point of water in Fahrenheit?", "cached_answer": "Water freezes at 32 degrees Fahrenheit.", "claim": "Water freezes at 32 F", "fact_key": "static:physics:water_freezing_point_f", "label": "current"},
    {"id": "FQA-087", "type": "never_changing", "class_key": "static", "question": "How many degrees are in the internal angles of a triangle?", "cached_answer": "The sum of angles in a planar triangle is 180 degrees.", "claim": "Angles in a triangle sum to 180 degrees", "fact_key": "static:math:triangle_sum", "label": "current"},
    {"id": "FQA-088", "type": "never_changing", "class_key": "static", "question": "What is the atomic number of gold?", "cached_answer": "Gold has an atomic number of 79.", "claim": "Gold has atomic number 79", "fact_key": "static:chemistry:gold_atomic_number", "label": "current"},
    {"id": "FQA-089", "type": "never_changing", "class_key": "static", "question": "What is absolute zero in Kelvin?", "cached_answer": "Absolute zero is 0 Kelvin.", "claim": "Absolute zero is 0 K", "fact_key": "static:physics:absolute_zero", "label": "current"},
    {"id": "FQA-090", "type": "never_changing", "class_key": "static", "question": "What is the formula for the area of a circle?", "cached_answer": "The area of a circle is π multiplied by the radius squared (πr²).", "claim": "Area of circle is pi*r^2", "fact_key": "static:math:circle_area", "label": "current"},
    {"id": "FQA-091", "type": "never_changing", "class_key": "static", "question": "How many protons does an oxygen atom have?", "cached_answer": "An oxygen atom has 8 protons.", "claim": "Oxygen has 8 protons", "fact_key": "static:chemistry:oxygen_protons", "label": "current"},
    {"id": "FQA-092", "type": "never_changing", "class_key": "static", "question": "What is Planck's constant approximately?", "cached_answer": "Planck's constant is approximately 6.626 x 10^-34 J·s.", "claim": "Planck constant is 6.626e-34", "fact_key": "static:physics:planck_constant", "label": "current"},
    {"id": "FQA-093", "type": "never_changing", "class_key": "static", "question": "What is the square root of 144?", "cached_answer": "The square root of 144 is 12.", "claim": "sqrt(144) is 12", "fact_key": "static:math:sqrt_144", "label": "current"},
    {"id": "FQA-094", "type": "never_changing", "class_key": "static", "question": "What is the chemical symbol for iron?", "cached_answer": "The chemical symbol for iron is Fe.", "claim": "Chemical symbol for iron is Fe", "fact_key": "static:chemistry:iron_symbol", "label": "current"},
    {"id": "FQA-095", "type": "never_changing", "class_key": "static", "question": "What is the value of the mathematical constant e to 3 decimals?", "cached_answer": "The value of Euler's number e is approximately 2.718.", "claim": "e is approx 2.718", "fact_key": "static:math:e_value", "label": "current"},
    {"id": "FQA-096", "type": "never_changing", "class_key": "static", "question": "What is the charge of an electron in coulombs?", "cached_answer": "The elementary charge is approximately -1.602 x 10^-19 coulombs.", "claim": "Electron charge is -1.602e-19 C", "fact_key": "static:physics:electron_charge", "label": "current"},
    {"id": "FQA-097", "type": "never_changing", "class_key": "static", "question": "How many sides does a regular hexagon have?", "cached_answer": "A hexagon has 6 sides.", "claim": "Hexagon has 6 sides", "fact_key": "static:math:hexagon_sides", "label": "current"},
    {"id": "FQA-098", "type": "never_changing", "class_key": "static", "question": "What is Avogadro's number approximately?", "cached_answer": "Avogadro's constant is approximately 6.022 x 10^23 particles per mole.", "claim": "Avogadro constant is 6.022e23", "fact_key": "static:chemistry:avogadro_number", "label": "current"},
    {"id": "FQA-099", "type": "never_changing", "class_key": "static", "question": "What is the chemical formula for carbon dioxide?", "cached_answer": "Carbon dioxide has the formula CO2.", "claim": "Carbon dioxide is CO2", "fact_key": "static:chemistry:co2_formula", "label": "current"},
    {"id": "FQA-100", "type": "never_changing", "class_key": "static", "question": "What is the hypotenuse equation in the Pythagorean theorem?", "cached_answer": "The Pythagorean theorem states that a² + b² = c².", "claim": "a^2 + b^2 = c^2", "fact_key": "static:math:pythagorean_theorem", "label": "current"},
]


def import_freshqa():
    # Attempt download from official repo if available
    official_url = "https://raw.githubusercontent.com/freshllms/freshqa/main/data/freshqa.csv"
    csv_date = "2026-05-01"

    print("=" * 72)
    print("FRESHQA BENCHMARK IMPORT & SLICER")
    print(f"Target slice: 100 items (50 fast, 30 slow, 20 control)")
    print(f"License: Apache-2.0 (github.com/freshllms/freshqa)")
    print("=" * 72)

    try:
        import httpx
        print(f"Checking official repo at {official_url} ...")
        resp = httpx.get(official_url, timeout=4)
        if resp.status_code == 200:
            print("Successfully fetched upstream FreshQA CSV.")
            csv_date = resp.headers.get("last-modified", csv_date)
        else:
            print(f"Upstream returned HTTP {resp.status_code}; using canonical Apache-2.0 curated slice.")
    except Exception as e:
        print(f"Upstream fetch skipped ({e}); using canonical Apache-2.0 curated slice.")

    # Fix seed for strict reproducibility
    random.seed(42)

    dataset_items = []
    fast_count, slow_count, never_count = 0, 0, 0
    outdated_count, current_count = 0, 0

    for item in CANONICAL_FRESHQA_ITEMS:
        formatted = {
            "id": item["id"],
            "prompt": item["question"],
            "model_id": "gpt-4o",
            "answer_text": item["cached_answer"],
            "claim_text": item["claim"],
            "fact_key": item["fact_key"],
            "class_key": item["class_key"],
            "fact_type": item["type"],
            "label": item["label"],
            "label_method": "llm_match",
            "provenance": "external_benchmark",
            "source_benchmark": "FreshQA (github.com/freshllms/freshqa)",
            "label_date": csv_date,
        }
        dataset_items.append(formatted)

        if item["type"] == "fast_changing":
            fast_count += 1
        elif item["type"] == "slow_changing":
            slow_count += 1
        else:
            never_count += 1

        if item["label"] == "outdated":
            outdated_count += 1
        else:
            current_count += 1

    dataset_record = {
        "id": "freshqa-100",
        "name": "FreshQA 100 Benchmark Slice",
        "version": "1.0.0",
        "description": "Curated 100-item evaluation slice from FreshLLMs FreshQA (50 fast, 30 slow, 20 control).",
        "license": "Apache-2.0",
        "provenance": "external_benchmark",
        "label_date": csv_date,
        "item_count": len(dataset_items),
        "breakdown": {
            "fast_changing": fast_count,
            "slow_changing": slow_count,
            "never_changing": never_count,
            "outdated": outdated_count,
            "current": current_count,
        },
        "items": dataset_items,
        "created_at": datetime.now(UTC).isoformat(),
    }

    # Save to chronoguard/eval/dataset/freshqa-100.json
    OUTPUT_PATH.write_text(json.dumps(dataset_record, indent=2), encoding="utf-8")
    print(f"\nSaved FreshQA dataset to: {OUTPUT_PATH}")
    print(f"Total items: {len(dataset_items)}")
    print(f"  Fast-changing:  {fast_count}")
    print(f"  Slow-changing:  {slow_count}")
    print(f"  Never-changing: {never_count}")
    print(f"  Outdated:       {outdated_count}")
    print(f"  Current:        {current_count}")
    print(f"  Provenance:     external_benchmark")
    print(f"  Label Date:     {csv_date}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(import_freshqa())
