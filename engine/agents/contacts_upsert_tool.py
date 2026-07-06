"""Tool: upsert a person — vault People note always, Google People opt-in.

Purpose: land a contact card in the user's own vault first (local-first
invariant: the vault is the source of truth), then OPTIONALLY mirror it to
Google Contacts when the approved card explicitly asked for sync. The vault
write uses ``engine.vault.people_contact_writer`` — insert-only merge, user
content never dropped.
Pipeline position: registered in ``tool_registry`` for ``upsert_contact``.

Security invariants:
- Google sync is DENY BY DEFAULT: it happens only when the card the user
  approved carried ``sync_to_google=true``.
- With the kill switch engaged, the local vault write still succeeds and
  only the sync is refused by the gateway (fail closed on egress, never on
  the user's own data) — the result says so honestly.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.tool_registry import AgentTool, ToolResult
from engine.google.google_api_gateway import create_google_contact
from engine.google.google_auth_errors import GoogleError
from engine.google.google_session import GoogleSession
from engine.vault.people_contact_writer import upsert_person_note


class ContactsUpsertParams(BaseModel):
    """A person's details, exactly as approved on the card."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    sync_to_google: bool = False


def _narrow(params: BaseModel) -> ContactsUpsertParams:
    """Fail-closed narrowing: the registry pairs params to tools by
    construction, but a mismatch must refuse, never mis-execute."""
    if not isinstance(params, ContactsUpsertParams):
        raise ToolExecutionError(
            "ContactsUpsertParams", f"expected ContactsUpsertParams, got {type(params).__name__}"
        )
    return params


class ContactsUpsertTool(AgentTool):
    """Vault People note (always) + optional Google People mirror."""

    name = "contacts_upsert"
    card_type = CardType.UPSERT_CONTACT
    params_model = ContactsUpsertParams
    description = (
        "Save or enrich a person's contact card (name, phone, email, company) "
        "in the user's vault; optionally also create the contact in Google "
        "Contacts when sync_to_google is true."
    )

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        params = _narrow(params)
        lines = [f"Contact: {params.name}"]
        for label, value in (
            ("Phone", params.phone),
            ("Email", params.email),
            ("Company", params.company),
        ):
            if value:
                lines.append(f"{label}: {value}")
        lines.append(
            "Also sync to Google Contacts" if params.sync_to_google else "Vault only (no Google)"
        )
        return tuple(lines)

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        params = _narrow(params)
        # Local-first: the vault write happens regardless of Google's mood.
        note_path = upsert_person_note(
            self._vault_root,
            name=params.name,
            phone=params.phone,
            email=params.email,
            company=params.company,
        )
        detail: dict[str, object] = {"note_path": str(note_path), "synced_to_google": False}
        data_sent = ""  # local-only unless the card opted into sync
        summary = f"Contact saved to vault: {params.name}"
        if params.sync_to_google:
            try:
                created = await create_google_contact(
                    google_session,
                    name=params.name,
                    email=params.email,
                    phone=params.phone,
                    company=params.company,
                )
            except GoogleError as error:
                # Honest partial success: the vault write stands; the sync
                # failure is reported, never hidden and never faked.
                detail["google_sync_error"] = str(error)
                summary = f"Contact saved to vault: {params.name} (Google sync failed)"
            else:
                detail["synced_to_google"] = True
                detail["google_resource_name"] = created.resource_name
                data_sent = "contact name, phone, email, and company to Google People API"
                summary = f"Contact saved to vault and Google: {params.name}"
        return ToolResult(
            summary_line=summary, detail=detail, data_sent_off_machine=data_sent
        )
