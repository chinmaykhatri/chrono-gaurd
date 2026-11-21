import re
import unicodedata

from app.schemas.contracts import Category, Claim

VOCABULARY = {
    "latest_stable_version": Category.SOFTWARE, "pinned_version": Category.SOFTWARE,
    "api_signature": Category.SOFTWARE, "price_per_month": Category.PRICING,
    "price": Category.PRICING, "ceo": Category.PEOPLE, "headcount": Category.PEOPLE,
    "tax_rate": Category.REGULATION, "legal_deadline": Category.REGULATION,
}


def slug(value: str):
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\b(inc|llc|ltd)\b\.?", "", value)
    return re.sub(r"[^\w]+|_+", "-", value).strip("-")


def fact_key(claim: Claim, aliases: dict[str, str] | None = None):
    entity = slug(claim.entity)
    if not entity:
        raise ValueError("no_entity")
    entity = (aliases or {}).get(entity, entity)
    category = VOCABULARY.get(claim.attribute, claim.class_key)
    attribute = claim.attribute if claim.attribute in VOCABULARY else "other:" + slug(claim.attribute)
    qualifier = ":" + slug(claim.qualifier) if claim.qualifier else ""
    temporal_scope = f":as-of:{claim.as_of_hint.isoformat()}" if claim.as_of_hint else ""
    return f"{category.value}:{entity}:{attribute}{qualifier}{temporal_scope}", category


def skip_reason(claim: Claim):
    if claim.claim_type != "fact":
        return "not_factual"
    if claim.entity_type == "person_private":
        return "private_person"
    if claim.class_key == Category.STATIC:
        return "static"
    if not claim.entity.strip():
        return "no_entity"
    return None
