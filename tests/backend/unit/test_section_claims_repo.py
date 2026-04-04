from uuid import uuid4
from db.models.section_claims import SectionClaimRow
from db.repositories.section_claims import upsert_section_claims, load_section_claims, delete_section_claims


def test_section_claim_row_instantiates():
    row = SectionClaimRow(
        tenant_id=uuid4(),
        run_id=uuid4(),
        section_id="sec_1",
        claim_index=0,
        claim_text="AI is used in healthcare.",
    )
    assert row.claim_index == 0
    assert row.claim_text == "AI is used in healthcare."
