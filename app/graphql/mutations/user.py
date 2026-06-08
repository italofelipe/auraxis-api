"""GraphQL mutations for user account state (#1471)."""

from __future__ import annotations

import graphene

from app.extensions.database import db
from app.graphql.auth import get_current_user_required
from app.graphql.types import MutationPayload
from app.utils.datetime_utils import utc_now_naive


class CompleteOnboardingPayload(MutationPayload):
    """Canonical payload for completeOnboarding mutation."""

    onboarding_completed_at = graphene.String(
        description="ISO 8601 timestamp when onboarding was completed."
    )


class CompleteOnboardingMutation(graphene.Mutation):
    """Mark the authenticated user's onboarding as completed (idempotent).

    REST parity: ``POST /user/onboarding/complete``.
    """

    Output = CompleteOnboardingPayload

    def mutate(self, info: graphene.ResolveInfo) -> CompleteOnboardingPayload:
        user = get_current_user_required()
        if user.onboarding_completed_at is None:
            user.onboarding_completed_at = utc_now_naive()
            db.session.commit()

        return CompleteOnboardingPayload(
            ok=True,
            message="Onboarding concluído",
            errors=[],
            onboarding_completed_at=user.onboarding_completed_at.isoformat(),
        )
