"""Request bodies for the operator surface.

Separate from the response schemas because these are the two operations where a
missing field changes what an admin can do: a ban without a reason and an
adjudication without credentials are both irreversible from the user's side, so
neither can be "fill it in if you remember".
"""

from pydantic import BaseModel, ConfigDict, Field


class BanRequest(BaseModel):
    """Why an account is being deactivated.

    Required, and required to be non-blank.

    An admin ban does a lot — it cancels resting orders, releases reserved funds
    and revokes every session — and an unexplained one leaves the user unable to
    appeal and the next admin unable to tell a justified ban from a mistake. So
    this is not an optional note on an audit row; it is the field that makes the
    decision answerable, and it is shown to the user at sign-in.

    `min_length=3` rather than 1 because `"n/a"` and `"-"` are the same non-answer
    wearing a longer string.
    """

    # Stripped before the length is measured. Without this, `"   "` is three
    # characters, satisfies `min_length=3`, and becomes a ban whose stated reason
    # is invisible — which is the failure this field exists to prevent, arriving
    # through the back door. Trimming first also means the stored value has no
    # leading or trailing whitespace to render as a ragged line in the admin UI.
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Why the account is being deactivated. Shown to the user.",
    )
    note: str | None = Field(
        None,
        max_length=2000,
        description="Optional longer context: evidence, references, what happens next.",
    )


class UnbanRequest(BaseModel):
    """Why a ban was reversed.

    Optional, unlike `BanRequest.reason`. Reversing a ban is a restorative action
    rather than an accusation, and the common case is an appeal that succeeded —
    which the audit already shows by the unban itself.
    """

    note: str | None = Field(
        None, max_length=2000, description="Context for the reversal."
    )


class RejectMarketRequest(BaseModel):
    """Why a submission was declined.

    Required, for the same reason a ban's reason is.

    A rejected market is hidden from the catalogue and the author keeps read
    access to it — so this string is the only channel through which they learn
    anything. Without it the submission cannot be fixed, because nobody can tell
    whether the problem was the wording, the category, or the resolution
    criteria.

    Stripped before the length is measured, so `"  "` is caught rather than
    passing `min_length` as three characters of nothing.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Why the submission was declined. Shown to the author.",
    )
    note: str | None = Field(
        None,
        max_length=2000,
        description="Optional longer context, kept in the audit trail.",
    )